"""One loaded vision-language model (llama.cpp b12602 + mtmd) that answers describe / ask / compare.

Runs inside the talk worker process. `Session(lib, model, mmproj, talk, gpu_layers)` loads the model, its context
and the image projector once; `answer(...)` is called any number of times; `close()` frees everything.

- Every answer starts from an empty KV memory (no earlier photo or question leaks into the next one).
- The prompt goes through the model's own chat template (llama_model_chat_template + llama_chat_apply_template),
  with mtmd's marker where each picture goes (compare: two markers, two bitmaps).
- Greedy sampling (temperature 0, as benchmarked), until end of generation, `max_tokens` or `cancelled()`.
  Cancelling only stops the answer; the model stays loaded.
- `n_ctx`, `n_ubatch`, flash attention, the KV cache type and (Qwen) the image token cap come from the catalog's
  `talk` settings (models.CATALOG).
- Out of memory: a model / context / projector load that returns NULL, or an evaluation that fails, raises
  `AllocFailed(need_mb)`. A failed load frees what it had allocated before raising; a failed answer frees its
  bitmaps and chunks and leaves the session usable. llama.cpp gives no reason code for a NULL load, so a corrupt
  file looks the same (files that don't exist raise FileNotFoundError first; the files are SHA-checked on install).

Progress and Stop (find 1.1 release fix): `progress(phase, frac)` (the talk worker's hook, vlm/worker._Watch) is
told each phase as it starts (frac None) and what really moved in it, and returning False stops the work, which
then raises `Cancelled`:
- "model": llama's own load fraction (llama_model_params.progress_callback; False aborts llama's load).
- "context": llama_init_from_model has no callback: a phase message only (its time is bounded by the worker).
- "vision": mtmd's load fraction (mtmd_context_params.progress_callback). Its warmup (after 1.0) made no eval
  calls in the probes; any "still computing" it sends there doesn't count (the engine's "vision" bound is fixed).
- "image": reading the photo (mtmd_helper_eval_chunks): the image encode on clip's graph through mtmd's cb_eval
  (every EVAL_EVERY nodes clip's scheduler stops at a node and calls back; False stops that split, every later
  split stops after one node, and the answer then ends as Cancelled; on Vulkan the prompt eval that follows still
  runs, as llama can't abort it there) and the prompt
  eval through llama's abort_callback (between graph nodes, CPU only: on Vulkan the prompt eval is not stoppable,
  and it is short). Both are frac None calls, never a fraction: "still computing", which the engine bounds.
- "answer": no calls; the tokens are the progress, and `cancelled()` is asked before each one.
The ctypes callbacks are kept on the session (llama and mtmd hold their addresses as long as the context lives).
"""
import codecs
import ctypes
import math
import os
import time

from . import llama_api as L

_KV = {"f16": L.GGML_TYPE_F16, "q8_0": L.GGML_TYPE_Q8_0, "q4_0": L.GGML_TYPE_Q4_0, "f32": L.GGML_TYPE_F32}
_MB = 1048576
EVAL_EVERY = 32         # clip's graph is split at every 32nd node so its encode can say "still computing" and stop
ASK_EVERY = 0.02        # seconds between two calls of the hook from llama's abort callback (it runs per graph node)


class Cancelled(Exception):
    """The job was stopped (Stop, a newer question, the engine) while loading or reading the photo."""


class AllocFailed(Exception):
    """Not enough memory to load or run the model. `need_mb`: about how much it needs (at least the two files,
    or the catalog's measured figure when the caller put it in the settings as `need_mb`)."""

    def __init__(self, need_mb, what="load the model"):
        self.need_mb = int(need_mb)
        super().__init__(f"not enough memory to {what} (needs about {self.need_mb} MB)")


class Session:
    def __init__(self, lib, model_path, mmproj_path, settings, gpu_layers, progress=None):
        self._lib, self._ll, self._mt = lib, lib.llama, lib.mtmd
        self._model = self._ctx = self._mctx = self._sampler = None
        self._hook, self._aborted, self._phase, self._nodes, self._asked = progress, False, "", 0, 0.0
        # kept alive for as long as llama / mtmd may call them (the context's whole life)
        self._cb_model = L.PROGRESS_CALLBACK(self._fraction("model"))
        self._cb_vision = L.PROGRESS_CALLBACK(self._fraction("vision"))
        self._cb_eval = L.EVAL_CALLBACK(self._on_eval)
        self._cb_abort = L.ABORT_CALLBACK(self._on_abort)
        for p in (model_path, mmproj_path):
            if not os.path.isfile(p):
                raise FileNotFoundError(p)
        files_mb = (os.path.getsize(model_path) + os.path.getsize(mmproj_path)) / _MB
        self.need_mb = int(settings.get("need_mb") or math.ceil(files_mb))
        fa = L.LLAMA_FLASH_ATTN_TYPE_ENABLED if settings.get("flash_attn") else L.LLAMA_FLASH_ATTN_TYPE_DISABLED
        ll, mt = self._ll, self._mt
        try:
            self._enter("model")
            ll.llama_backend_init()
            mp = ll.llama_model_default_params()
            mp.n_gpu_layers = int(gpu_layers)
            mp.progress_callback = ctypes.cast(self._cb_model, ctypes.c_void_p).value
            mp.progress_callback_user_data = None
            self._model = ll.llama_model_load_from_file(os.fsencode(model_path), mp) or None
            if self._model is None:
                raise Cancelled() if self._aborted else AllocFailed(self.need_mb)

            self._enter("context")
            cp = ll.llama_context_default_params()
            cp.n_ctx = int(settings["n_ctx"])
            cp.n_batch = cp.n_ctx                       # one decode call per text chunk; outputs: the last only
            cp.n_ubatch = int(settings["n_ubatch"])
            cp.flash_attn_type = fa
            cp.type_k = cp.type_v = _KV[settings.get("kv", "f16")]
            if settings.get("threads"):
                cp.n_threads = cp.n_threads_batch = int(settings["threads"])
            self._ctx = ll.llama_init_from_model(self._model, cp) or None
            if self._ctx is None:
                raise AllocFailed(self.need_mb)
            self._n_ctx = int(ll.llama_n_ctx(self._ctx))
            self._n_batch = cp.n_batch

            self._enter("vision")
            mcp = mt.mtmd_context_params_default()
            mcp.use_gpu = int(gpu_layers) != 0
            mcp.print_timings = False
            mcp.flash_attn_type = fa
            if settings.get("threads"):
                mcp.n_threads = int(settings["threads"])
            if settings.get("image_max_tokens"):
                mcp.image_max_tokens = int(settings["image_max_tokens"])
            mcp.progress_callback = ctypes.cast(self._cb_vision, ctypes.c_void_p).value
            mcp.progress_callback_user_data = None
            mcp.cb_eval = ctypes.cast(self._cb_eval, ctypes.c_void_p).value
            mcp.cb_eval_user_data = None
            self._mctx = mt.mtmd_init_from_file(os.fsencode(mmproj_path), self._model, mcp) or None
            if self._mctx is None:
                raise Cancelled() if self._aborted else AllocFailed(self.need_mb)

            self._sampler = ll.llama_sampler_chain_init(ll.llama_sampler_chain_default_params()) or None
            if self._sampler is None:
                raise AllocFailed(self.need_mb)
            ll.llama_sampler_chain_add(self._sampler, ll.llama_sampler_init_greedy())
            self._vocab = ll.llama_model_get_vocab(self._model)
            self._template = ll.llama_model_chat_template(self._model, None)     # bytes or None (then chatml)
            self._marker = mt.mtmd_default_marker()
        except BaseException:
            self.close()
            raise
        finally:
            self._hook = None                           # a job's hook lives only as long as that job

    # -- progress and Stop ----------------------------------------------------------------------------------------

    def _tell(self, phase, frac):
        """The hook; False (or an earlier False) means stop. A hook that fails never stops the work."""
        if self._aborted:
            return False
        if self._hook is None:
            return True
        try:
            go = bool(self._hook(phase, frac))
        except Exception:
            go = True
        except BaseException:                           # Ctrl+C / SystemExit inside llama's call: a stop, never
            go = False                                  # "not enough memory" (ctypes would swallow it as 0)
        if not go:
            self._aborted = True
        return go

    def _enter(self, phase):
        self._phase = phase
        if not self._tell(phase, None):
            raise Cancelled()

    def _fraction(self, phase):
        def cb(frac, _user):                            # llama / mtmd: true = go on loading
            try:
                return self._tell(phase, float(frac))
            except BaseException:                       # never a silent 0 (read as "not enough memory")
                self._aborted = True
                return False
        return cb

    def _on_eval(self, _tensor, ask, _user):
        """mtmd's (clip's) graph scheduler. ask: split here? (every EVAL_EVERY nodes, or at once after a Stop);
        then, once that node is computed: go on? It runs during the vision warmup and each image encode."""
        try:
            if ask:
                self._nodes += 1
                return self._aborted or self._nodes % EVAL_EVERY == 0
            return self._tell(self._phase, None)
        except Exception:
            return not ask
        except BaseException:
            self._aborted = True
            return bool(ask)                            # split here, then stop after the node

    def _on_abort(self, _data):
        """llama's abort callback (CPU backend, between graph nodes): true ends this llama_decode."""
        try:
            if self._aborted:
                return True
            now = time.monotonic()
            if now - self._asked < ASK_EVERY:
                return False
            self._asked = now
            return not self._tell(self._phase, None)
        except Exception:
            return False
        except BaseException:
            self._aborted = True
            return True

    # -- answering ------------------------------------------------------------------------------------------------

    def _format(self, content):
        """The user's turn through the model's chat template, ending where the assistant starts."""
        msg = (L.ChatMessage * 1)(L.ChatMessage(b"user", content))
        for tmpl in (self._template, b"chatml"):
            if tmpl is None:
                continue
            size = 2 * len(content) + 512
            while True:
                buf = ctypes.create_string_buffer(size)
                n = self._ll.llama_chat_apply_template(tmpl, msg, 1, True, buf, size)
                if n < 0:
                    break                               # a template llama.cpp doesn't know: try chatml
                if n < size:
                    return buf.raw[:n]
                size = n + 1
        raise RuntimeError("no chat template for this model")

    def _piece(self, tok):
        buf = ctypes.create_string_buffer(64)
        n = self._ll.llama_token_to_piece(self._vocab, tok, buf, 64, 0, False)
        if n < 0:
            buf = ctypes.create_string_buffer(-n)
            n = self._ll.llama_token_to_piece(self._vocab, tok, buf, -n, 0, False)
        return buf.raw[:max(n, 0)]

    def answer(self, images, prompt, max_tokens, on_token, cancelled, progress=None):
        """Answer `prompt` about `images` ([(rgb_bytes, w, h)], one or two), streaming text to `on_token`.
        progress: the job's hook (phases "image" then "answer"); a Stop while the photo is read raises Cancelled."""
        self._hook, self._aborted, self._nodes = progress, False, 0
        try:
            return self._answer(images, prompt, max_tokens, on_token, cancelled)
        finally:
            self._hook, self._aborted = None, False

    def _answer(self, images, prompt, max_tokens, on_token, cancelled):
        if self._ctx is None:
            raise RuntimeError("session closed")
        if not images:
            raise ValueError("no picture")
        for rgb, w, h in images:
            if w < 1 or h < 1 or len(rgb) != w * h * 3:
                raise ValueError("picture is not RGB of its size")
        text = prompt.encode("utf-8")
        if self._marker in text:
            raise ValueError("the prompt contains the picture marker")
        ll, mt = self._ll, self._mt
        self._enter("image")
        ll.llama_memory_clear(ll.llama_get_memory(self._ctx), True)
        formatted = self._format(b"".join(self._marker + b"\n" for _ in images) + text)
        bitmaps, chunks = [], None
        try:
            for rgb, w, h in images:
                b = mt.mtmd_bitmap_init(w, h, rgb) or None
                if b is None:
                    raise AllocFailed(self.need_mb, "read the picture")
                bitmaps.append(b)
            chunks = mt.mtmd_input_chunks_init() or None
            if chunks is None:
                raise AllocFailed(self.need_mb, "read the picture")
            inp = L.MtmdInputText(formatted, len(formatted), True, True)
            arr = (ctypes.c_void_p * len(bitmaps))(*bitmaps)
            ret = mt.mtmd_tokenize(self._mctx, chunks, ctypes.byref(inp), arr, len(bitmaps))
            if ret == 1:
                raise ValueError("pictures and markers don't match")
            if ret != 0:
                raise ValueError("the picture could not be prepared")
            n_prompt = int(mt.mtmd_helper_get_n_tokens(chunks))
            room = self._n_ctx - n_prompt
            if room < 1:
                raise ValueError("the pictures and question are too long for this model")
            max_tokens = min(int(max_tokens), room)
            n_past = L.llama_pos(0)
            ll.llama_set_abort_callback(self._ctx, self._cb_abort, None)
            try:
                ret = mt.mtmd_helper_eval_chunks(self._mctx, self._ctx, chunks, 0, 0, self._n_batch, True,
                                                 ctypes.byref(n_past))
            finally:
                ll.llama_set_abort_callback(self._ctx, L.ABORT_CALLBACK(), None)     # none while answering
            if ret != 0:
                raise Cancelled() if self._aborted else AllocFailed(self.need_mb, "read the picture")
        finally:
            if chunks is not None:
                mt.mtmd_input_chunks_free(chunks)
            for b in bitmaps:
                mt.mtmd_bitmap_free(b)
        self._enter("answer")
        return self._generate(max_tokens, on_token, cancelled)

    def _generate(self, max_tokens, on_token, cancelled):
        ll = self._ll
        utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
        out, tok_arr = [], (L.llama_token * 1)()
        for _ in range(max_tokens):
            if cancelled():
                break
            tok = ll.llama_sampler_sample(self._sampler, self._ctx, -1)
            if ll.llama_vocab_is_eog(self._vocab, tok):
                break
            s = utf8.decode(self._piece(tok))
            if s:
                out.append(s)
                on_token(s)
            tok_arr[0] = tok
            if ll.llama_decode(self._ctx, ll.llama_batch_get_one(tok_arr, 1)) != 0:
                raise AllocFailed(self.need_mb, "answer")
        tail = utf8.decode(b"", final=True)
        if tail:
            out.append(tail)
            on_token(tail)
        return "".join(out).strip()

    # -- teardown -------------------------------------------------------------------------------------------------

    def close(self):
        """Free the sampler, projector, context and model (each once; safe to call again)."""
        ll, mt = self._ll, self._mt
        if self._sampler is not None:
            s, self._sampler = self._sampler, None
            ll.llama_sampler_free(s)
        if self._mctx is not None:
            m, self._mctx = self._mctx, None
            mt.mtmd_free(m)
        if self._ctx is not None:
            c, self._ctx = self._ctx, None
            ll.llama_free(c)
        if self._model is not None:
            m, self._model = self._model, None
            ll.llama_model_free(m)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

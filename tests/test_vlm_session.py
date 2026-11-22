"""The loaded talk-about-a-photo session (vlm/session.py): a fake llama.cpp for the rules, one real-model test."""
import ctypes
import importlib
import importlib.util
import io
import os
import time

import pytest

from nobadfind.vlm import llama_api, prompts, session as vs

TALK = {"side": 512, "n_ctx": 1024, "n_ubatch": 256, "flash_attn": True, "kv": "q8_0"}
EOG = 0
MARKER = b"<__media__>"


class _Ns:
    pass


class FakeLib:
    """Records every call; handles are ints kept in `live` until freed. `reply` is the token script (EOG = 0)."""

    def __init__(self, reply=(5, 6, 7, EOG), load_fails=False, ctx_fails=False, mtmd_fails=False, eval_ret=0,
                 prompt_tokens=40, template=b"<|im_start|>", load_steps=0, mtmd_steps=0, eval_nodes=0):
        """load_steps / mtmd_steps: llama's / mtmd's progress callback is called that many times through its C
        pointer, and the load returns NULL as soon as it answers false (as llama.cpp does); eval_nodes: that many
        graph nodes in the image eval, each through mtmd's cb_eval (ask, and after a split node) and llama's
        abort_callback; a stop there makes the eval return 2 (aborted)."""
        self.reply, self.prompt_tokens, self.eval_ret = list(reply), prompt_tokens, eval_ret
        self.load_steps, self.mtmd_steps, self.eval_nodes = load_steps, mtmd_steps, eval_nodes
        self.progress_seen, self.abort_set = [], []
        self.live, self.calls, self.kv_at_eval, self.texts = set(), [], [], []
        self.kv, self._next, self._pos = 0, 100, 0
        self.model_params = self.ctx_params = self.mtmd_params = None
        self.llama, self.mtmd = _Ns(), _Ns()
        L, M = self.llama, self.mtmd

        def handle(kind):
            self._next += 1
            h = self._next
            self.live.add((kind, h))
            return h

        def free(kind):
            def f(h):
                self.calls.append(("free", kind))
                self.live.remove((kind, h))
            return f

        L.llama_backend_init = lambda: None
        L.llama_model_default_params = lambda: llama_api.ModelParams()
        L.llama_context_default_params = lambda: llama_api.ContextParams(n_ctx=512, n_batch=2048, n_ubatch=512)
        L.llama_sampler_chain_default_params = lambda: llama_api.SamplerChainParams()

        def through(ptr, user, steps, what):
            """Call a progress callback by its C address, as llama / mtmd do: False ends the load."""
            if not ptr or not steps:
                return True
            cb = llama_api.PROGRESS_CALLBACK(ptr)
            for i in range(steps + 1):
                go = cb(i / steps, user)
                self.progress_seen.append((what, i / steps, go))
                if not go:
                    return False
            return True

        def load_model(path, mp):
            self.model_params = mp
            if not through(mp.progress_callback, mp.progress_callback_user_data, self.load_steps, "model"):
                return None
            return None if load_fails else handle("model")
        L.llama_model_load_from_file = load_model
        L.llama_model_free = free("model")

        def init_ctx(model, cp):
            self.ctx_params = cp
            return None if ctx_fails else handle("ctx")
        L.llama_init_from_model = init_ctx
        L.llama_free = free("ctx")
        L.llama_n_ctx = lambda ctx: self.ctx_params.n_ctx
        L.llama_model_get_vocab = lambda model: 7
        L.llama_get_memory = lambda ctx: 9

        def clear(mem, data):
            self.calls.append(("clear",))
            self.kv = 0
        L.llama_memory_clear = clear
        L.llama_model_chat_template = lambda model, name: template

        def apply_template(tmpl, msgs, n, add_ass, buf, length):
            out = b"<|im_start|>user\n" + msgs[0].content + b"<|im_end|>\n<|im_start|>assistant\n"
            if buf is not None and length >= len(out):
                ctypes.memmove(buf, out, len(out))
            return len(out)
        L.llama_chat_apply_template = apply_template
        L.llama_sampler_chain_init = lambda p: handle("sampler")
        L.llama_sampler_init_greedy = lambda: 55
        L.llama_sampler_chain_add = lambda chain, s: self.calls.append(("greedy",))
        L.llama_sampler_free = free("sampler")

        def sample(smpl, ctx, idx):
            tok = self.reply[self._pos % len(self.reply)]
            self._pos += 1
            return tok
        L.llama_sampler_sample = sample
        L.llama_vocab_is_eog = lambda vocab, tok: tok == EOG

        def piece(vocab, tok, buf, size, lstrip, special):
            s = f" t{tok}".encode()
            ctypes.memmove(buf, s, len(s))
            return len(s)
        L.llama_token_to_piece = piece
        L.llama_batch_get_one = lambda toks, n: llama_api.Batch(n_tokens=n)

        def decode(ctx, batch):
            self.kv += batch.n_tokens
            return 0
        L.llama_decode = decode
        self.abort = None

        def set_abort(ctx, cb, data):
            self.abort = cb if cb else None             # a NULL ABORT_CALLBACK() is falsy
            self.abort_set.append(bool(cb))
        L.llama_set_abort_callback = set_abort

        M.mtmd_default_marker = lambda: MARKER
        M.mtmd_context_params_default = lambda: llama_api.MtmdContextParams()

        def mtmd_init(path, model, mp):
            self.mtmd_params = mp
            if not through(mp.progress_callback, mp.progress_callback_user_data, self.mtmd_steps, "vision"):
                return None
            return None if mtmd_fails else handle("mtmd")
        M.mtmd_init_from_file = mtmd_init
        M.mtmd_free = free("mtmd")
        M.mtmd_bitmap_init = lambda w, h, data: handle("bitmap")
        M.mtmd_bitmap_free = free("bitmap")
        M.mtmd_input_chunks_init = lambda: handle("chunks")
        M.mtmd_input_chunks_free = free("chunks")

        def tokenize(mctx, chunks, text, bitmaps, n):
            t = text._obj
            self.texts.append((t.text, n, t.add_special, t.parse_special))
            return 0 if t.text.count(MARKER) == n else 1
        M.mtmd_tokenize = tokenize
        M.mtmd_helper_get_n_tokens = lambda chunks: self.prompt_tokens

        def eval_chunks(mctx, ctx, chunks, n_past, seq, n_batch, logits_last, new_n_past):
            self.kv_at_eval.append(self.kv)
            ev = llama_api.EVAL_CALLBACK(self.mtmd_params.cb_eval) if self.mtmd_params.cb_eval else None
            for i in range(self.eval_nodes):
                if i < self.eval_nodes // 2:            # the image encode on clip's graph
                    if ev is not None and ev(i, True, None) and not ev(i, False, None):
                        return 2
                elif self.abort and self.abort(None):   # the prompt eval: llama's abort callback
                    return 2
            if self.eval_ret:
                return self.eval_ret
            self.kv += self.prompt_tokens
            new_n_past._obj.value = self.kv
            return 0
        M.mtmd_helper_eval_chunks = eval_chunks


IMG = (bytes(4 * 3 * 3), 4, 3)


@pytest.fixture
def files(tmp_path):
    m, p = tmp_path / "model.gguf", tmp_path / "mmproj.gguf"
    m.write_bytes(b"x" * 3 * 1048576)
    p.write_bytes(b"x" * 1048576)
    return str(m), str(p)


def _no(*_):
    return False


def test_answer_streams_tokens_and_stops_at_eog(files):
    lib = FakeLib(reply=(5, 6, 7, EOG, 9))
    s = vs.Session(lib, *files, TALK, 99)
    got = []
    assert s.answer([IMG], prompts.describe(), 200, got.append, _no) == "t5 t6 t7"
    assert got == [" t5", " t6", " t7"]
    # the catalog's talk settings and greedy sampling
    cp = lib.ctx_params
    assert (cp.n_ctx, cp.n_ubatch, cp.flash_attn_type) == (1024, 256, llama_api.LLAMA_FLASH_ATTN_TYPE_ENABLED)
    assert cp.type_k == cp.type_v == llama_api.GGML_TYPE_Q8_0
    assert lib.model_params.n_gpu_layers == 99 and lib.mtmd_params.use_gpu
    assert lib.mtmd_params.flash_attn_type == llama_api.LLAMA_FLASH_ATTN_TYPE_ENABLED
    assert ("greedy",) in lib.calls
    # the model's own chat template, the mtmd marker where the picture goes
    text, n, add_special, parse_special = lib.texts[0]
    assert text.startswith(b"<|im_start|>user\n" + MARKER) and b"Describe this photo" in text
    assert n == 1 and add_special and parse_special
    assert {k for k, _ in lib.live} == {"model", "ctx", "mtmd", "sampler"}     # bitmaps and chunks freed
    s.close()
    assert lib.live == set()
    s.close()                                                                   # twice is fine


def test_max_tokens_caps_the_answer(files):
    lib = FakeLib(reply=(5,))
    s = vs.Session(lib, *files, TALK, 0)
    assert s.answer([IMG], "hi", 4, _no, _no) == "t5 t5 t5 t5"
    assert not lib.mtmd_params.use_gpu and lib.model_params.n_gpu_layers == 0


def test_cancel_mid_stream_keeps_model(files):
    lib = FakeLib(reply=(5,))
    s = vs.Session(lib, *files, TALK, 99)
    got = []
    assert s.answer([IMG], "hi", 200, got.append, lambda: len(got) >= 3) == "t5 t5 t5"
    assert len(got) == 3
    assert not [c for c in lib.calls if c[0] == "free" and c[1] in ("model", "ctx", "mtmd", "sampler")]
    lib.reply = [6, EOG]
    lib._pos = 0
    assert s.answer([IMG], "again", 200, _no, _no) == "t6"
    s.close()


def test_cancel_before_any_token(files):
    lib = FakeLib(reply=(5,))
    s = vs.Session(lib, *files, TALK, 99)
    assert s.answer([IMG], "hi", 200, _no, lambda: True) == ""


# ---------- progress and Stop through llama's / mtmd's own callbacks (release fix) ----------
def test_load_progress_reaches_the_hook_through_llamas_and_mtmds_callbacks(files):
    lib = FakeLib(load_steps=4, mtmd_steps=2)
    seen = []
    s = vs.Session(lib, *files, TALK, 0, progress=lambda phase, frac: seen.append((phase, frac)) or True)
    assert seen == [("model", None), ("model", 0.0), ("model", 0.25), ("model", 0.5), ("model", 0.75),
                    ("model", 1.0), ("context", None), ("vision", None), ("vision", 0.0), ("vision", 0.5),
                    ("vision", 1.0)]
    assert lib.model_params.progress_callback and lib.mtmd_params.progress_callback and lib.mtmd_params.cb_eval
    s.close()


@pytest.mark.parametrize("where, at", [("model", 3), ("vision", 2)])
def test_stop_during_a_load_aborts_it_through_the_callback(files, where, at):
    """A Stop while llama (or mtmd) loads: the progress callback answers false, the load returns NULL, and that is
    Cancelled (not "not enough memory"), with everything freed."""
    lib = FakeLib(load_steps=10, mtmd_steps=10)
    n = [0]

    def hook(phase, frac):
        if phase == where and frac is not None:
            n[0] += 1
        return n[0] < at
    with pytest.raises(vs.Cancelled):
        vs.Session(lib, *files, TALK, 0, progress=hook)
    assert lib.progress_seen[-1] == (where, (at - 1) / 10, False)        # llama / mtmd saw the false: no more calls
    assert lib.live == set()


def test_stop_before_the_context_is_made_is_cancelled(files):
    lib = FakeLib(load_steps=2)
    with pytest.raises(vs.Cancelled):
        vs.Session(lib, *files, TALK, 0, progress=lambda phase, frac: phase != "context")
    assert lib.live == set() and lib.ctx_params is None


def test_the_photo_eval_says_still_computing_and_stops_through_the_eval_and_abort_callbacks(files, monkeypatch):
    monkeypatch.setattr(vs, "ASK_EVERY", 0.0)
    lib = FakeLib(reply=(5, 6, EOG), eval_nodes=4 * vs.EVAL_EVERY)
    s = vs.Session(lib, *files, TALK, 0)
    seen = []
    assert s.answer([IMG], "hi", 200, _no, _no, progress=lambda p, f: seen.append((p, f)) or True) == "t5 t6"
    calls = [p for p, f in seen]
    assert calls[0] == "image" and calls[-1] == "answer" and set(calls[1:-1]) == {"image"}
    assert all(f is None for p, f in seen)                               # never a fraction: "still computing"
    assert 2 <= len(seen) - 2 and lib.abort_set == [True, False]         # the abort callback: only for the eval
    for stop_after in (1, 2 * vs.EVAL_EVERY):                            # in the encode (cb_eval), the eval (abort)
        n = [0]

        def hook(p, f):
            n[0] += 1
            return n[0] <= stop_after
        lib.calls.clear()
        with pytest.raises(vs.Cancelled):
            s.answer([IMG], "hi", 200, _no, _no, progress=hook)
        assert not [c for c in lib.calls if c[0] == "free" and c[1] in ("model", "ctx", "mtmd")]   # model stays
        assert {k for k, _ in lib.live} == {"model", "ctx", "mtmd", "sampler"}                     # bitmaps freed
    assert s.answer([IMG], "again", 200, _no, _no) == "t5 t6"            # and it answers the next question
    s.close()


def test_a_failing_hook_never_stops_the_work(files):
    def boom(phase, frac):
        raise RuntimeError("x")
    lib = FakeLib(load_steps=3, mtmd_steps=3, eval_nodes=2 * vs.EVAL_EVERY)
    s = vs.Session(lib, *files, TALK, 0, progress=boom)
    assert s.answer([IMG], "hi", 200, _no, _no, progress=boom) == "t5 t6 t7"
    s.close()


@pytest.mark.parametrize("fail", ["load_fails", "ctx_fails", "mtmd_fails"])
def test_alloc_failure_reports_and_unloads(files, fail):
    lib = FakeLib(**{fail: True})
    with pytest.raises(vs.AllocFailed) as e:
        vs.Session(lib, *files, TALK, 99)
    assert e.value.need_mb >= 4                                   # at least the two files (3 MB + 1 MB)
    assert lib.live == set()                                      # no handle leaks


def test_a_missing_file_is_not_an_alloc_failure(files, tmp_path):
    lib = FakeLib()
    with pytest.raises(FileNotFoundError):
        vs.Session(lib, str(tmp_path / "nope.gguf"), files[1], TALK, 99)
    assert lib.live == set()


def test_out_of_memory_while_answering_keeps_the_session(files):
    lib = FakeLib(eval_ret=-3)
    s = vs.Session(lib, *files, TALK, 99)
    with pytest.raises(vs.AllocFailed):
        s.answer([IMG], "hi", 200, _no, _no)
    assert {k for k, _ in lib.live} == {"model", "ctx", "mtmd", "sampler"}     # bitmaps and chunks freed
    lib.eval_ret = 0
    assert s.answer([IMG], "hi", 200, _no, _no) == "t5 t6 t7"


def test_each_answer_starts_from_an_empty_context(files):
    lib = FakeLib()
    s = vs.Session(lib, *files, TALK, 99)
    for _ in range(3):
        s.answer([IMG], "hi", 200, _no, _no)
    assert lib.kv_at_eval == [0, 0, 0]
    assert lib.calls.count(("clear",)) == 3


def test_compare_gives_two_markers_and_two_bitmaps(files):
    lib = FakeLib()
    s = vs.Session(lib, *files, TALK, 99)
    s.answer([IMG, IMG], prompts.compare(None), 160, _no, _no)
    text, n, _, _ = lib.texts[0]
    assert n == 2 and text.count(MARKER) == 2


def test_bad_input_is_refused(files):
    lib = FakeLib()
    s = vs.Session(lib, *files, TALK, 99)
    with pytest.raises(ValueError):
        s.answer([], "hi", 10, _no, _no)
    with pytest.raises(ValueError):
        s.answer([(b"abc", 4, 3)], "hi", 10, _no, _no)            # not w*h*3 bytes
    with pytest.raises(ValueError):
        s.answer([IMG], "hi " + MARKER.decode(), 10, _no, _no)    # a marker typed in the question
    lib.prompt_tokens = 1024
    with pytest.raises(ValueError):
        s.answer([IMG], "hi", 10, _no, _no)                       # doesn't fit the context
    assert {k for k, _ in lib.live} == {"model", "ctx", "mtmd", "sampler"}
    s.close()
    with pytest.raises(RuntimeError):
        s.answer([IMG], "hi", 10, _no, _no)


def test_the_answer_is_capped_to_the_room_left_in_the_context(files):
    lib = FakeLib(reply=(5,), prompt_tokens=1020)
    s = vs.Session(lib, *files, TALK, 99)
    assert s.answer([IMG], "hi", 200, _no, _no).count("t5") == 4


def test_qwen_image_tokens_cap(files):
    lib = FakeLib()
    vs.Session(lib, *files, dict(TALK, image_max_tokens=160), 99)
    assert lib.mtmd_params.image_max_tokens == 160


def test_multibyte_pieces_are_joined(files):
    lib = FakeLib(reply=(1, 2, EOG))
    pieces = {1: "न".encode()[:2], 2: "न".encode()[2:] + b"!"}

    def piece(vocab, tok, buf, size, lstrip, special):
        ctypes.memmove(buf, pieces[tok], len(pieces[tok]))
        return len(pieces[tok])
    lib.llama.llama_token_to_piece = piece
    s = vs.Session(lib, *files, TALK, 99)
    got = []
    assert s.answer([IMG], "hi", 10, got.append, _no) == "न!"
    assert "".join(got) == "न!"


# --- the real model (dev only) ----------------------------------------------------------------------------------

RUNTIME = os.environ.get("NOBAD_FIND_LLAMA_DIR")
SMOL = os.environ.get("NOBAD_FIND_SMOLVLM2_DIR")


def _drawing(shape="circle", colour=(220, 20, 20)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 480), (255, 255, 255))
    d = ImageDraw.Draw(im)
    if shape == "circle":
        d.ellipse((170, 90, 470, 390), fill=colour)
    else:
        d.rectangle((170, 90, 470, 390), fill=colour)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _rss_peak_mb():
    import procinfo
    return procinfo._pmc().PeakPagefileUsage / 1048576          # peak private bytes of this process


@pytest.mark.skipif(not (RUNTIME and SMOL), reason="NOBAD_FIND_LLAMA_DIR / NOBAD_FIND_SMOLVLM2_DIR not set (dev only)")
@pytest.mark.skipif(importlib.util.find_spec("PIL") is None, reason="Pillow (dev dependency) not installed")
def test_real_smolvlm2_describes_a_drawing():
    importlib.import_module("onnxruntime")                     # must load before winrt (MSVCP140)
    from nobadfind import photo
    lib = llama_api.load(RUNTIME)
    gpu = 99 if os.path.isfile(os.path.join(RUNTIME, "ggml-vulkan.dll")) else 0
    model = os.path.join(SMOL, "SmolVLM2-500M-Video-Instruct-Q8_0.gguf")
    mmproj = os.path.join(SMOL, "mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf")
    t0 = time.perf_counter()
    s = vs.Session(lib, model, mmproj, TALK, gpu)
    load_s = time.perf_counter() - t0
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype, k32.GetModuleHandleW.argtypes = ctypes.c_void_p, [ctypes.c_wchar_p]
    assert not k32.GetModuleHandleW("ggml-rpc.dll")             # never loaded, even after a model + mmproj load
    try:
        red = photo.decode_rgb(_drawing(), TALK["side"])
        blue = photo.decode_rgb(_drawing("square", (20, 40, 220)), TALK["side"])
        assert red and blue
        t = time.perf_counter()
        got = []
        said = s.answer([red], prompts.describe(), prompts.max_tokens("describe"), got.append, _no)
        describe_s = time.perf_counter() - t
        assert "".join(got).strip() == said
        assert "red" in said.lower() or "circle" in said.lower(), said
        n = []
        cut = s.answer([red], prompts.describe(), 200, n.append, lambda: len(n) >= 3)   # cancel keeps the model
        assert len(n) == 3 and cut
        t = time.perf_counter()
        asked = s.answer([red], prompts.ask("What colour is the shape?"), prompts.max_tokens("ask"), _no, _no)
        ask_s = time.perf_counter() - t
        assert "red" in asked.lower(), asked
        t = time.perf_counter()
        compared = s.answer([red, blue], prompts.compare(None), prompts.max_tokens("compare"), _no, _no)
        compare_s = time.perf_counter() - t
        assert compared
        again = s.answer([red], prompts.describe(), prompts.max_tokens("describe"), _no, _no)
        assert again == said                                    # greedy and an empty context: the same answer
    finally:
        s.close()
    print(f"\n[{'vulkan' if gpu else 'cpu'}] load {load_s:.2f}s, peak private {_rss_peak_mb():.0f} MB"
          f"\n  describe {describe_s:.2f}s: {said!r}\n  ask {ask_s:.2f}s: {asked!r}"
          f"\n  compare {compare_s:.2f}s: {compared!r}")

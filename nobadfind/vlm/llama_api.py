"""A pinned ctypes binding to llama.cpp build b12602: llama.dll (text model) and mtmd.dll (images).

Pinned to ONE build. The structs below are passed and returned BY VALUE, so their layout must match the DLL exactly;
a different llama.cpp build can add, drop or reorder fields and then every value after the change is read from the
wrong place (or the call writes past the buffer). Moving to another build means re-checking every struct against
that build's headers with `tools/vlm_header_check.py` and changing `LLAMA_BUILD`.

Headers the layouts were copied from (tag b12602 of github.com/ggml-org/llama.cpp, SHA-256):
    include/llama.h           81de282d3c3a6e74f876c5954749efc9aabd3dd3fd3014479d5194cb4381298b
    tools/mtmd/mtmd.h         5118c638af74f5044c6f6a8e6fc88b475f36a636edfbbee5f258806677d76321
    tools/mtmd/mtmd-helper.h  9b52cd78efe09a2d05667e273d8ed11b749053b929d7cd1f4cbafb8312d0b9da
    ggml/include/ggml.h       bd114a12205b2039858da72e6fd43babd945ca09fb1ae6372051e1e5dfbae5c0  (enum ggml_type)
    ggml/include/ggml-backend.h 34464da4b46314c710cd634626578c6f2a6811431d41eddaf5e8aa77082fea2a (backend loading)

C types map as: enum -> c_int (MSVC enums are int), bool -> c_bool, size_t -> c_size_t, every pointer and function
pointer -> c_void_p. Use the *_default_params() functions and only change the fields you need.

`load(runtime_dir)` loads ggml.dll, llama.dll and mtmd.dll from that folder (in that order, the folder added to the
DLL search path for their dependencies), registers the folder's ggml backends (this build ships them as separate
DLLs, so without that step no device exists), and returns a `Lib` whose `.ggml`,
`.llama` and `.mtmd` have argtypes/restypes set for the functions used. One `Lib` per folder per process.

Backends are loaded ONE BY ONE with `ggml_backend_load` (security ruling, find 1.1), never
`ggml_backend_load_all_from_path` (which loads every ggml-*.dll it finds): only the pinned names in `BACKENDS`
(the ggml-cpu-* variants and ggml-vulkan.dll of llama_pins), so a DLL placed in the folder (ggml-rpc.dll, the
network backend, or anything else) is never loaded. Of the CPU variants only the one with the best
`ggml_backend_score` for this CPU is registered, as ggml's own loader does (each would add another CPU device).
"""
import ctypes
import os
import threading
import _ctypes
from ctypes import POINTER, c_bool, c_char_p, c_float, c_int, c_int8, c_int32, c_size_t, c_uint32, c_void_p

from .. import llama_pins

LLAMA_BUILD = "b12602"

# enum llama_split_mode (llama.h:201)
LLAMA_SPLIT_MODE_NONE, LLAMA_SPLIT_MODE_LAYER, LLAMA_SPLIT_MODE_ROW, LLAMA_SPLIT_MODE_TENSOR = 0, 1, 2, 3
# enum llama_flash_attn_type (llama.h:193)
LLAMA_FLASH_ATTN_TYPE_AUTO, LLAMA_FLASH_ATTN_TYPE_DISABLED, LLAMA_FLASH_ATTN_TYPE_ENABLED = -1, 0, 1
# enum ggml_type (ggml.h:219), the KV cache types we may choose
GGML_TYPE_F32, GGML_TYPE_F16, GGML_TYPE_Q4_0, GGML_TYPE_Q8_0 = 0, 1, 2, 8

llama_token = c_int32                                   # llama.h:69
llama_pos = c_int32                                     # llama.h:68
llama_seq_id = c_int32                                  # llama.h:70


class ModelParams(ctypes.Structure):
    """struct llama_model_params, llama.h:331-368 (b12602)."""
    _fields_ = [
        ("devices", c_void_p),                          # ggml_backend_dev_t *
        ("tensor_buft_overrides", c_void_p),            # const struct llama_model_tensor_buft_override *
        ("n_gpu_layers", c_int32),
        ("split_mode", c_int),                          # enum llama_split_mode
        ("load_mode", c_int),                           # enum llama_load_mode
        ("lazy_mode", c_int),                           # enum llama_lazy_mode
        ("main_gpu", c_int32),
        ("tensor_split", c_void_p),                     # const float *
        ("progress_callback", c_void_p),                # llama_progress_callback
        ("progress_callback_user_data", c_void_p),
        ("kv_overrides", c_void_p),                     # const struct llama_model_kv_override *
        ("vocab_only", c_bool),
        ("check_tensors", c_bool),
        ("use_extra_bufts", c_bool),
        ("no_host", c_bool),
        ("no_alloc", c_bool),
        ("load_mtp", c_bool),
    ]


class ContextParams(ctypes.Structure):
    """struct llama_context_params, llama.h:377-439 (b12602)."""
    _fields_ = [
        ("n_ctx", c_uint32),
        ("n_batch", c_uint32),
        ("n_ubatch", c_uint32),
        ("n_seq_max", c_uint32),
        ("n_rs_seq", c_uint32),
        ("n_outputs_max", c_uint32),
        ("n_outputs_max_per_seq", c_uint32),
        ("n_threads", c_int32),
        ("n_threads_batch", c_int32),
        ("ctx_type", c_int),                            # enum llama_context_type
        ("rope_scaling_type", c_int),                   # enum llama_rope_scaling_type
        ("pooling_type", c_int),                        # enum llama_pooling_type
        ("attention_type", c_int),                      # enum llama_attention_type
        ("flash_attn_type", c_int),                     # enum llama_flash_attn_type
        ("rope_freq_base", c_float),
        ("rope_freq_scale", c_float),
        ("yarn_ext_factor", c_float),
        ("yarn_attn_factor", c_float),
        ("yarn_beta_fast", c_float),
        ("yarn_beta_slow", c_float),
        ("yarn_orig_ctx", c_uint32),
        ("cb_eval", c_void_p),                          # ggml_backend_sched_eval_callback
        ("cb_eval_user_data", c_void_p),
        ("type_k", c_int),                              # enum ggml_type
        ("type_v", c_int),                              # enum ggml_type
        ("moe_cache_size", c_size_t),
        ("moe_cache_cpu_share", c_float),
        ("abort_callback", c_void_p),                   # ggml_abort_callback
        ("abort_callback_data", c_void_p),
        ("embeddings", c_bool),
        ("offload_kqv", c_bool),
        ("no_perf", c_bool),
        ("op_offload", c_bool),
        ("swa_full", c_bool),
        ("kv_unified", c_bool),
        ("samplers", c_void_p),                         # struct llama_sampler_seq_config *
        ("n_samplers", c_size_t),
        ("ctx_other", c_void_p),                        # struct llama_context *
    ]


class SamplerChainParams(ctypes.Structure):
    """struct llama_sampler_chain_params, llama.h:476-478 (b12602)."""
    _fields_ = [("no_perf", c_bool)]


class Batch(ctypes.Structure):
    """struct llama_batch, llama.h:275-284 (b12602)."""
    _fields_ = [
        ("n_tokens", c_int32),
        ("token", POINTER(llama_token)),
        ("embd", POINTER(c_float)),
        ("pos", POINTER(llama_pos)),
        ("n_seq_id", POINTER(c_int32)),
        ("seq_id", POINTER(POINTER(llama_seq_id))),
        ("logits", POINTER(c_int8)),
    ]


class MtmdContextParams(ctypes.Structure):
    """struct mtmd_context_params, mtmd.h:108-136 (b12602)."""
    _fields_ = [
        ("use_gpu", c_bool),
        ("device", c_void_p),                           # ggml_backend_dev_t
        ("print_timings", c_bool),
        ("n_threads", c_int),
        ("image_marker", c_char_p),                     # deprecated in the header, still in the layout
        ("media_marker", c_char_p),
        ("flash_attn_type", c_int),                     # enum llama_flash_attn_type
        ("warmup", c_bool),
        ("image_min_tokens", c_int),
        ("image_max_tokens", c_int),
        ("cb_eval", c_void_p),                          # ggml_backend_sched_eval_callback
        ("cb_eval_user_data", c_void_p),
        ("batch_max_tokens", c_int32),
        ("progress_callback", c_void_p),                # mtmd_progress_callback
        ("progress_callback_user_data", c_void_p),
    ]


class MtmdInputText(ctypes.Structure):
    """struct mtmd_input_text, mtmd.h:78-83 (b12602)."""
    _fields_ = [
        ("text", c_char_p),
        ("text_len", c_size_t),
        ("add_special", c_bool),
        ("parse_special", c_bool),
    ]


class ChatMessage(ctypes.Structure):
    """struct llama_chat_message, llama.h:481-484 (b12602)."""
    _fields_ = [("role", c_char_p), ("content", c_char_p)]


P = c_void_p                                            # opaque handles: model, context, vocab, sampler, ...
# typedef void (*ggml_log_callback)(enum ggml_log_level level, const char * text, void * user_data); ggml.h:2715
LOG_CALLBACK = ctypes.CFUNCTYPE(None, c_int, c_char_p, c_void_p)

# name: (restype, [argtypes])
GGML_FUNCS = {
    "ggml_backend_load": (c_void_p, [c_char_p]),                       # ggml-backend.h:272 (a ggml_backend_reg_t)
    "ggml_backend_dev_count": (c_size_t, []),                          # ggml-backend.h:258
}

LLAMA_FUNCS = {
    "llama_backend_init": (None, []),                                  # llama.h:500
    "llama_backend_free": (None, []),                                  # llama.h:503
    "llama_model_default_params": (ModelParams, []),                   # llama.h:493
    "llama_context_default_params": (ContextParams, []),               # llama.h:494
    "llama_sampler_chain_default_params": (SamplerChainParams, []),    # llama.h:495
    "llama_model_load_from_file": (P, [c_char_p, ModelParams]),        # llama.h:531
    "llama_model_free": (None, [P]),                                   # llama.h:553
    "llama_init_from_model": (P, [P, ContextParams]),                  # llama.h:555
    "llama_free": (None, [P]),                                         # llama.h:560
    "llama_n_ctx": (c_uint32, [P]),                                    # llama.h:576
    "llama_get_memory": (P, [P]),                                      # llama.h:584
    "llama_memory_clear": (None, [P, c_bool]),                         # llama.h:773
    "llama_model_get_vocab": (P, [P]),                                 # llama.h:587
    "llama_model_chat_template": (c_char_p, [P, c_char_p]),            # llama.h:657 (NULL name: the default)
    "llama_chat_apply_template": (c_int32, [c_char_p, POINTER(ChatMessage), c_size_t, c_bool, c_char_p, c_int32]),
    "llama_batch_get_one": (Batch, [POINTER(llama_token), c_int32]),   # llama.h:960 (deprecated, still exported)
    "llama_decode": (c_int32, [P, Batch]),                             # llama.h:1005 (deprecated, still exported)
    "llama_vocab_is_eog": (c_bool, [P, llama_token]),                  # llama.h:1263
    "llama_tokenize": (c_int32, [P, c_char_p, c_int32, POINTER(llama_token), c_int32, c_bool, c_bool]),  # :1305
    "llama_token_to_piece": (c_int32, [P, llama_token, c_char_p, c_int32, c_int32, c_bool]),            # :1319
    "llama_sampler_free": (None, [P]),                                 # llama.h:1475
    "llama_sampler_chain_init": (P, [SamplerChainParams]),             # llama.h:1480
    "llama_sampler_chain_add": (None, [P, P]),                         # llama.h:1483
    "llama_sampler_init_greedy": (P, []),                              # llama.h:1500
    "llama_sampler_sample": (llama_token, [P, P, c_int32]),            # llama.h:1666
    "llama_log_set": (None, [LOG_CALLBACK, P]),                        # llama.h:1692 (also sets ggml's logger)
}

MTMD_FUNCS = {
    "mtmd_default_marker": (c_char_p, []),                             # mtmd.h:138
    "mtmd_context_params_default": (MtmdContextParams, []),            # mtmd.h:140
    "mtmd_init_from_file": (P, [c_char_p, P, MtmdContextParams]),      # mtmd.h:144
    "mtmd_free": (None, [P]),                                          # mtmd.h:148
    "mtmd_support_vision": (c_bool, [P]),                              # mtmd.h:158
    "mtmd_bitmap_init": (P, [c_uint32, c_uint32, c_char_p]),           # mtmd.h:202 (nx, ny, RGB bytes)
    "mtmd_bitmap_free": (None, [P]),                                   # mtmd.h:210
    "mtmd_input_chunks_init": (P, []),                                 # mtmd.h:257
    "mtmd_input_chunks_size": (c_size_t, [P]),                         # mtmd.h:258
    "mtmd_input_chunks_free": (None, [P]),                             # mtmd.h:260
    "mtmd_helper_get_n_tokens": (c_size_t, [P]),                       # mtmd-helper.h:150
    "mtmd_tokenize": (c_int32, [P, P, POINTER(MtmdInputText), POINTER(c_void_p), c_size_t]),  # mtmd.h:336
    # mtmd-helper.h:166 (exported by mtmd.dll in b12602)
    "mtmd_helper_eval_chunks": (c_int32, [P, P, P, llama_pos, llama_seq_id, c_int32, c_bool, POINTER(llama_pos)]),
    "mtmd_log_set": (None, [LOG_CALLBACK, P]),                         # mtmd.h:392 (mtmd and clip)
    "mtmd_helper_log_set": (None, [LOG_CALLBACK, P]),                  # mtmd-helper.h:76 (the helper's own)
}

INCOMPLETE = "llama.cpp runtime incomplete"
NO_CPU = "llama.cpp runtime has no CPU backend"
DLLS = ("ggml.dll", "llama.dll", "mtmd.dll")             # load order
# the only backend DLLs ever loaded: the pinned CPU variants and Vulkan (never ggml-rpc.dll, never an unlisted name)
BACKENDS = tuple(sorted(n for n in {**llama_pins.CPU_DLLS, **llama_pins.VULKAN_DLLS}
                        if n.startswith("ggml-cpu-") or n == "ggml-vulkan.dll"))


class Lib:
    def __init__(self, runtime_dir, dll_dir, ggml, llama, mtmd):
        self.runtime_dir = runtime_dir
        self._dll_dir = dll_dir                             # keeps the folder on the DLL search path
        self.ggml = ggml
        self.llama = llama
        self.mtmd = mtmd


_loaded = {}
_lock = threading.Lock()


def _bind(dll, funcs, dll_name):
    for name, (restype, argtypes) in funcs.items():
        try:
            fn = getattr(dll, name)
        except AttributeError:
            raise RuntimeError(f"llama.cpp runtime is not build {LLAMA_BUILD}: {dll_name} has no {name}") from None
        fn.restype = restype
        fn.argtypes = argtypes


def _cpu_score(path):
    """ggml_backend_score() of one pinned CPU variant DLL: 0 when this CPU can't run it (ggml-cpu/ggml-cpu.cpp) or
    the DLL can't be loaded here (then it is skipped, not the whole runtime)."""
    try:
        dll = ctypes.CDLL(path)
    except OSError:
        return 0
    try:
        fn = getattr(dll, "ggml_backend_score", None)
        if fn is None:
            return 0
        fn.restype, fn.argtypes = c_int, []
        return int(fn())
    finally:
        _ctypes.FreeLibrary(dll._handle)


def _backend_paths(runtime_dir, score=_cpu_score):
    """The backend DLLs to load from `runtime_dir`: the best-scoring pinned CPU variant on disk, then ggml-vulkan.dll
    when it is on disk. Only names in BACKENDS are looked at."""
    present = [n for n in BACKENDS if os.path.isfile(os.path.join(runtime_dir, n))]
    best, best_score = None, 0
    for n in present:
        if n.startswith("ggml-cpu-"):
            s = score(os.path.join(runtime_dir, n))
            if s > best_score:
                best, best_score = n, s
    out = [best] if best else []
    out += [n for n in present if n == "ggml-vulkan.dll"]
    return [os.path.join(runtime_dir, n) for n in out]


@LOG_CALLBACK
def _no_log(_level, _text, _user):
    """Drops every llama.cpp / ggml / mtmd log line. Module-level, so it lives as long as the process."""


def silence_logs(lib):
    """No llama.cpp log output from now on (privacy: the prompt echo carries the user's question, and it must
    never reach a log, a captured stderr or a pipe transcript). Call once per process, right after load()."""
    lib.llama.llama_log_set(_no_log, None)
    lib.mtmd.mtmd_helper_log_set(_no_log, None)         # also calls mtmd_log_set
    lib.mtmd.mtmd_log_set(_no_log, None)


def load(runtime_dir, quiet=False):
    """Load (once per folder) the llama.cpp b12602 runtime in `runtime_dir`; returns a `Lib`. quiet: logging is
    switched off (silence_logs) before the backends are registered, so not even their device lines are printed."""
    runtime_dir = os.path.abspath(runtime_dir)
    key = os.path.normcase(runtime_dir)
    with _lock:
        if key in _loaded:
            return _loaded[key]
        missing = [n for n in DLLS if not os.path.isfile(os.path.join(runtime_dir, n))]
        if missing:
            raise RuntimeError(f"{INCOMPLETE}: {', '.join(missing)} missing in {runtime_dir}")
        dll_dir = os.add_dll_directory(runtime_dir) if hasattr(os, "add_dll_directory") else None
        try:
            try:
                ggml, llama, mtmd = (ctypes.CDLL(os.path.join(runtime_dir, n)) for n in DLLS)
            except OSError as e:
                raise RuntimeError(f"llama.cpp runtime could not be loaded: {e}") from e
            _bind(ggml, GGML_FUNCS, "ggml.dll")
            _bind(llama, LLAMA_FUNCS, "llama.dll")
            _bind(mtmd, MTMD_FUNCS, "mtmd.dll")
            if quiet:
                silence_logs(Lib(runtime_dir, None, ggml, llama, mtmd))
            paths = _backend_paths(runtime_dir)
            if not any(os.path.basename(p).startswith("ggml-cpu-") for p in paths):
                raise RuntimeError(f"{NO_CPU}: no pinned CPU variant runs on this processor")
            for path in paths:
                reg = ggml.ggml_backend_load(os.fsencode(path))
                if not reg and os.path.basename(path).startswith("ggml-cpu-"):
                    raise RuntimeError(f"{NO_CPU}: {os.path.basename(path)} did not register")
                # ggml-vulkan.dll: NULL when it has no device here (no Vulkan driver); the CPU still runs it
        except BaseException:
            if dll_dir is not None:
                dll_dir.close()
            raise
        lib = _loaded[key] = Lib(runtime_dir, dll_dir, ggml, llama, mtmd)
        return lib

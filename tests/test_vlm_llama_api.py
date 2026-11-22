import ctypes
import importlib.util
import os

import pytest

from nobadfind.vlm import llama_api

_spec = importlib.util.spec_from_file_location(
    "vlm_header_check", os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools", "vlm_header_check.py"))
header_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(header_check)

HEADERS = os.environ.get("NOBAD_FIND_LLAMA_HEADERS")
RUNTIME = os.environ.get("NOBAD_FIND_LLAMA_DIR")


@pytest.mark.skipif(not HEADERS, reason="NOBAD_FIND_LLAMA_HEADERS not set (dev only)")
def test_structs_match_b12602_headers():
    for cls, header, cname in header_check.STRUCTS:
        fields = header_check.parse_struct(os.path.join(HEADERS, header), cname)
        assert [f.name for f in fields] == [name for name, _ in cls._fields_], cname
        for f, (name, ctype) in zip(fields, cls._fields_):
            assert header_check.kind_of_c(f.ctype) == header_check.kind_of_ctypes(ctype), (cname, name, f.ctype)
        assert ctypes.sizeof(header_check.layout_from_header(fields)) == ctypes.sizeof(cls), cname
    assert header_check.check(HEADERS) == []


@pytest.mark.skipif(not HEADERS, reason="NOBAD_FIND_LLAMA_HEADERS not set (dev only)")
def test_log_functions_match_b12602_headers():
    assert header_check.check_funcs(HEADERS) == []
    assert {n for _h, n, _t in header_check.FUNCS} == {"llama_log_set", "mtmd_log_set", "mtmd_helper_log_set"}


def test_the_function_check_finds_a_wrong_binding(tmp_path, monkeypatch):
    (tmp_path / "llama.h").write_text("// x\nLLAMA_API void llama_log_set(ggml_log_callback cb, void * user_data);\n")
    (tmp_path / "mtmd.h").write_text("MTMD_API void mtmd_log_set(ggml_log_callback log_callback, void * user_data);")
    (tmp_path / "mtmd-helper.h").write_text("MTMD_API int mtmd_helper_log_set(ggml_log_callback cb);")
    assert header_check.parse_func(str(tmp_path / "llama.h"), "llama_log_set") == (
        "void", ["ggml_log_callback", "void *"], 2)
    problems = header_check.check_funcs(str(tmp_path))
    assert problems == ["mtmd_helper_log_set: 2 ctypes args != header 1 (line 1)"]


def test_silence_logs_sets_a_no_op_callback_on_all_three():
    calls = []

    class Ns:
        pass
    lib = Ns()
    lib.llama, lib.mtmd = Ns(), Ns()
    lib.llama.llama_log_set = lambda cb, ud: calls.append(("llama", cb, ud))
    lib.mtmd.mtmd_helper_log_set = lambda cb, ud: calls.append(("helper", cb, ud))
    lib.mtmd.mtmd_log_set = lambda cb, ud: calls.append(("mtmd", cb, ud))
    llama_api.silence_logs(lib)
    assert [(w, cb, ud) for w, cb, ud in calls] == [(w, llama_api._no_log, None) for w in ("llama", "helper", "mtmd")]
    llama_api._no_log(2, b"prompt with the user's question", None)      # callable, prints nothing


def test_load_refuses_a_runtime_without_both_dlls(tmp_path):
    assert llama_api.LLAMA_BUILD == "b12602"
    with pytest.raises(RuntimeError, match="llama.cpp runtime incomplete"):
        llama_api.load(str(tmp_path))
    (tmp_path / "llama.dll").write_bytes(b"")
    with pytest.raises(RuntimeError, match="llama.cpp runtime incomplete"):
        llama_api.load(str(tmp_path))


def test_only_pinned_backends_are_loaded_and_one_cpu_variant(tmp_path):
    """Security ruling: backends are loaded one by one (ggml_backend_load), only the pinned CPU variants and Vulkan;
    a DLL placed in the folder (ggml-rpc.dll, anything else) is never loaded. Of the CPU variants only the best one
    this CPU supports (ggml_backend_score), like ggml's own loader: several would each add a CPU device."""
    assert "ggml-rpc.dll" not in llama_api.BACKENDS and "ggml-vulkan.dll" in llama_api.BACKENDS
    assert all(n.startswith("ggml-cpu-") for n in llama_api.BACKENDS if n != "ggml-vulkan.dll")
    for n in ("ggml-cpu-x64.dll", "ggml-cpu-haswell.dll", "ggml-cpu-zen4.dll", "ggml-rpc.dll", "ggml-cpu-evil.dll",
              "ggml-foo.dll", "ggml-vulkan.dll"):
        (tmp_path / n).write_bytes(b"")
    scores = {"ggml-cpu-x64.dll": 1, "ggml-cpu-haswell.dll": 64, "ggml-cpu-zen4.dll": 0, "ggml-cpu-evil.dll": 999}
    asked = []

    def score(path):
        asked.append(os.path.basename(path))
        return scores[os.path.basename(path)]
    got = llama_api._backend_paths(str(tmp_path), score)
    assert [os.path.basename(p) for p in got] == ["ggml-cpu-haswell.dll", "ggml-vulkan.dll"]
    assert sorted(asked) == ["ggml-cpu-haswell.dll", "ggml-cpu-x64.dll", "ggml-cpu-zen4.dll"]   # never the evil one
    scores["ggml-cpu-haswell.dll"] = scores["ggml-cpu-x64.dll"] = 0
    assert [os.path.basename(p) for p in llama_api._backend_paths(str(tmp_path), score)] == ["ggml-vulkan.dll"]


def test_a_failed_bind_closes_the_dll_directory(tmp_path, monkeypatch):
    for n in llama_api.DLLS:
        (tmp_path / n).write_bytes(b"")
    closed = []

    class Handle:
        def close(self):
            closed.append(True)
    monkeypatch.setattr(llama_api.os, "add_dll_directory", lambda d: Handle(), raising=False)
    monkeypatch.setattr(llama_api.ctypes, "CDLL", lambda p: object())     # no functions: binding fails
    with pytest.raises(RuntimeError, match="is not build b12602"):
        llama_api.load(str(tmp_path))
    assert closed == [True] and os.path.normcase(str(tmp_path)) not in llama_api._loaded


def test_a_cpu_variant_that_will_not_load_scores_0_and_is_skipped(tmp_path):
    """T3-m1: a damaged or foreign CPU variant DLL is skipped (score 0), never an OSError out of load()."""
    bad = tmp_path / "ggml-cpu-haswell.dll"
    bad.write_bytes(b"not a DLL")
    assert llama_api._cpu_score(str(bad)) == 0
    (tmp_path / "ggml-cpu-x64.dll").write_bytes(b"")
    scores = {"ggml-cpu-x64.dll": 1}
    got = llama_api._backend_paths(str(tmp_path), lambda p: scores.get(os.path.basename(p))
                                   if os.path.basename(p) in scores else llama_api._cpu_score(p))
    assert [os.path.basename(p) for p in got] == ["ggml-cpu-x64.dll"]


class _FakeGgml:
    def __init__(self, regs):
        self.regs, self.loaded = regs, []

    def ggml_backend_load(self, path):
        name = os.path.basename(os.fsdecode(path))
        self.loaded.append(name)
        return self.regs.get(name)


def _fake_load(tmp_path, monkeypatch, ggml, backends):
    for n in llama_api.DLLS:
        (tmp_path / n).write_bytes(b"")
    libs = iter([ggml, object(), object()])
    monkeypatch.setattr(llama_api.ctypes, "CDLL", lambda p: next(libs))
    monkeypatch.setattr(llama_api, "_bind", lambda *a: None)
    monkeypatch.setattr(llama_api, "_backend_paths", lambda d: [os.path.join(d, n) for n in backends])


@pytest.mark.parametrize("backends, regs", [
    (["ggml-cpu-haswell.dll"], {}),                                      # the chosen CPU variant gives NULL
    (["ggml-cpu-haswell.dll", "ggml-vulkan.dll"], {"ggml-vulkan.dll": 1}),
    (["ggml-vulkan.dll"], {"ggml-vulkan.dll": 1}),                        # no CPU variant runs on this CPU
    ([], {}),
])
def test_no_cpu_backend_is_a_runtime_error_not_a_memory_note(tmp_path, monkeypatch, backends, regs):
    """T3-m2: when the CPU backend doesn't register, load() says so (RuntimeError) instead of carrying on to fail
    later as an allocation error ("Not enough memory")."""
    _fake_load(tmp_path, monkeypatch, _FakeGgml(regs), backends)
    with pytest.raises(RuntimeError, match=llama_api.NO_CPU):
        llama_api.load(str(tmp_path))
    assert os.path.normcase(str(tmp_path)) not in llama_api._loaded


def test_vulkan_without_a_device_is_fine_when_the_cpu_registers(tmp_path, monkeypatch):
    ggml = _FakeGgml({"ggml-cpu-haswell.dll": 1})                        # ggml-vulkan.dll: NULL (no driver)
    _fake_load(tmp_path, monkeypatch, ggml, ["ggml-cpu-haswell.dll", "ggml-vulkan.dll"])
    try:
        lib = llama_api.load(str(tmp_path))
        assert lib.ggml is ggml and ggml.loaded == ["ggml-cpu-haswell.dll", "ggml-vulkan.dll"]
    finally:
        llama_api._loaded.pop(os.path.normcase(str(tmp_path)), None)


def _values(struct):
    return {name: getattr(struct, name) for name, _ in struct._fields_}


@pytest.mark.skipif(not RUNTIME, reason="NOBAD_FIND_LLAMA_DIR not set (needs a real llama.cpp b12602 runtime)")
def test_real_runtime_smoke():
    lib = llama_api.load(RUNTIME)
    assert isinstance(lib.llama, ctypes.CDLL) and isinstance(lib.mtmd, ctypes.CDLL)
    assert llama_api.load(RUNTIME) is lib                   # loaded once per folder
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype, k32.GetModuleHandleW.argtypes = ctypes.c_void_p, [ctypes.c_wchar_p]
    assert not k32.GetModuleHandleW("ggml-rpc.dll")         # never loaded, even when it is in the folder
    assert lib.ggml.ggml_backend_dev_count() >= 1
    if not os.path.isfile(os.path.join(RUNTIME, "ggml-vulkan.dll")):
        assert lib.ggml.ggml_backend_dev_count() == 1       # one CPU device: the best variant only
    lib.llama.llama_backend_init()

    # Every field's default, from b12602's own source (llama-model.cpp:3596, llama-context.cpp:4400,
    # llama.cpp:78, mtmd.cpp:592): a field read from the wrong offset shows up here.
    mp = lib.llama.llama_model_default_params()
    assert isinstance(mp, llama_api.ModelParams)
    assert _values(mp) == {
        "devices": None, "tensor_buft_overrides": None, "n_gpu_layers": -1,
        "split_mode": llama_api.LLAMA_SPLIT_MODE_LAYER, "load_mode": -1, "lazy_mode": 1, "main_gpu": 0,
        "tensor_split": None, "progress_callback": None, "progress_callback_user_data": None, "kv_overrides": None,
        "vocab_only": False, "check_tensors": False, "use_extra_bufts": True, "no_host": False, "no_alloc": False,
        "load_mtp": False}
    mp.n_gpu_layers = 7
    assert mp.n_gpu_layers == 7 and mp.split_mode == llama_api.LLAMA_SPLIT_MODE_LAYER

    cp = lib.llama.llama_context_default_params()
    assert isinstance(cp, llama_api.ContextParams)
    assert _values(cp) == {
        "n_ctx": 512, "n_batch": 2048, "n_ubatch": 512, "n_seq_max": 1, "n_rs_seq": 0, "n_outputs_max": 0,
        "n_outputs_max_per_seq": 1, "n_threads": 4, "n_threads_batch": 4, "ctx_type": 0,
        "rope_scaling_type": -1, "pooling_type": -1, "attention_type": -1,
        "flash_attn_type": llama_api.LLAMA_FLASH_ATTN_TYPE_AUTO, "rope_freq_base": 0.0, "rope_freq_scale": 0.0,
        "yarn_ext_factor": -1.0, "yarn_attn_factor": -1.0, "yarn_beta_fast": -1.0, "yarn_beta_slow": -1.0,
        "yarn_orig_ctx": 0, "cb_eval": None, "cb_eval_user_data": None,
        "type_k": llama_api.GGML_TYPE_F16, "type_v": llama_api.GGML_TYPE_F16, "moe_cache_size": 0,
        "moe_cache_cpu_share": 0.0, "abort_callback": None, "abort_callback_data": None, "embeddings": False,
        "offload_kqv": True, "no_perf": True, "op_offload": True, "swa_full": True, "kv_unified": False,
        "samplers": None, "n_samplers": 0, "ctx_other": None}

    sp = lib.llama.llama_sampler_chain_default_params()
    assert sp.no_perf is True
    chain = lib.llama.llama_sampler_chain_init(sp)
    assert chain
    lib.llama.llama_sampler_chain_add(chain, lib.llama.llama_sampler_init_greedy())
    lib.llama.llama_sampler_free(chain)

    xp = lib.mtmd.mtmd_context_params_default()
    assert isinstance(xp, llama_api.MtmdContextParams)
    assert lib.mtmd.mtmd_default_marker() == b"<__media__>"
    assert _values(xp) == {
        "use_gpu": True, "device": None, "print_timings": True, "n_threads": 4, "image_marker": None,
        "media_marker": b"<__media__>", "flash_attn_type": llama_api.LLAMA_FLASH_ATTN_TYPE_AUTO, "warmup": True,
        "image_min_tokens": -1, "image_max_tokens": -1, "cb_eval": None, "cb_eval_user_data": None,
        "batch_max_tokens": 1024, "progress_callback": None, "progress_callback_user_data": None}

    bmp = lib.mtmd.mtmd_bitmap_init(2, 2, bytes(12))
    assert bmp
    lib.mtmd.mtmd_bitmap_free(bmp)
    chunks = lib.mtmd.mtmd_input_chunks_init()
    assert chunks
    lib.mtmd.mtmd_input_chunks_free(chunks)

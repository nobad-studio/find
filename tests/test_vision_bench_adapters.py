"""tools/vision_bench/adapters.py: fixed prompts, safe decoding, pinned files, and a llama.cpp command with no server."""
import json
import os
import re

import pytest

from tools.vision_bench import adapters
from tools.vision_bench.adapters import (ADAPTERS, DecodeError, NotSupported, decode, llama_argv, parse_llama_ms,
                                         prompt_for)

MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "vision_bench",
                      "models.json")


def test_prompt_templates_fixed():
    assert prompt_for("detect", None, "florence2-base-ft") == "<OD>"
    assert prompt_for("ocr", None, "florence2-base-ft") == "<OCR>"
    assert prompt_for("caption", None, "florence2-base-ft") == "<MORE_DETAILED_CAPTION>"
    assert prompt_for("detect", None, "qwen3vl-2b-q4") == "List every object you can see in this photo, comma-separated."
    assert prompt_for("ocr", None, "qwen3vl-2b-q4") == "Write out all the text in this photo exactly as written."
    assert prompt_for("caption", None, "smolvlm2-500m") == "Describe this photo in detail."
    assert prompt_for("ask", "How many people?", "qwen3vl-2b-q4") == "How many people? Answer briefly."
    assert prompt_for("compare", "Same place?", "qwen3vl-2b-q4") == (
        "The first image and the second image are two photos. Same place? Answer briefly.")


def test_florence_refuses_ask_and_compare():
    for task in ("ask", "compare"):
        with pytest.raises(NotSupported):
            prompt_for(task, "Q?", "florence2-base-ft")


def test_every_candidate_has_an_adapter():
    with open(MODELS, encoding="utf-8") as f:
        models = json.load(f)["models"]
    assert set(ADAPTERS) == {"florence2-base-ft", "smolvlm2-500m", "qwen3vl-2b-q4", "wevisone-vl-2b"}
    assert set(ADAPTERS) <= set(models)


def test_decode_refuses_corrupt_and_empty(tmp_path):
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    junk = tmp_path / "junk.jpg"
    junk.write_bytes(os.urandom(1024))
    for p in (empty, junk):
        with pytest.raises(DecodeError):
            decode(str(p), 768)


def test_decode_refuses_too_many_pixels(tmp_path, monkeypatch):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGB", (400, 300)).save(p)
    monkeypatch.setattr(adapters, "MAX_PIXELS", 100_000)
    with pytest.raises(DecodeError):
        decode(str(p), 768)


def test_decode_refuses_big_file(tmp_path, monkeypatch):
    from PIL import Image
    p = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(p)
    monkeypatch.setattr(adapters, "MAX_BYTES", 10)
    with pytest.raises(DecodeError):
        decode(str(p), 768)


def test_decode_fits_max_side(tmp_path):
    from PIL import Image
    p = tmp_path / "wide.png"
    Image.new("RGB", (2000, 1000)).save(p)
    im = decode(str(p), 768)
    assert im.mode == "RGB" and max(im.size) == 768


def test_models_json_complete():
    with open(MODELS, encoding="utf-8") as f:
        data = json.load(f)
    for cid, m in data["models"].items():
        assert m["repo"] and re.fullmatch(r"[0-9a-f]{40}", m["rev"]), cid
        assert m["licence"] in ("MIT", "Apache-2.0"), cid
        assert m["files"], cid
        for name, (size, sha) in m["files"].items():
            assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha), (cid, name)
    for dev, b in data["llama"].items():
        assert b["url"].startswith("https://github.com/ggml-org/llama.cpp/releases/download/"), dev
        assert b["size"] > 0 and re.fullmatch(r"[0-9a-f]{64}", b["sha256"]), dev


def test_llama_cmdline_has_no_server_or_port():
    argv = llama_argv("C:/t/llama-cpu", "C:/m/model.gguf", "C:/m/mmproj.gguf", ["C:/tmp/a.png", "C:/tmp/b.png"],
                      "Describe.", gpu=False)
    assert os.path.basename(argv[0]) == "llama-mtmd-cli.exe"
    for flag in ("-m", "--mmproj", "-p", "--temp"):
        assert flag in argv
    assert argv.count("--image") == 2
    assert argv[argv.index("-ngl") + 1] == "0"
    joined = " ".join(argv).lower()
    for bad in ("server", "--port", "--host", "http"):
        assert bad not in joined
    assert llama_argv("C:/t/llama-vulkan", "m", "p", ["a"], "x", gpu=True)[
        llama_argv("C:/t/llama-vulkan", "m", "p", ["a"], "x", gpu=True).index("-ngl") + 1] == "99"


def test_parse_llama_ms():
    err = ("image slice encoded in 812 ms\nimage decoded (batch 1/1) in 40 ms\n"
           "llama_perf_context_print:        load time =    1500.10 ms\n"
           "llama_perf_context_print:       total time =    2300.50 ms /    90 tokens\n")
    assert parse_llama_ms(err) == pytest.approx(2300.5 - 1500.1)   # total already includes load + image work
    assert parse_llama_ms("nothing here") is None


class _R:
    def __init__(self, err, code=0, out=b"an answer"):
        self.returncode, self.stdout, self.stderr = code, out, err.encode()


def _llama(tmp_path, monkeypatch, err, device):
    from PIL import Image
    img = tmp_path / "p.png"
    Image.new("RGB", (64, 64)).save(img)
    monkeypatch.setenv("VBENCH_TMP", str(tmp_path / "tmp"))
    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **k: _R(err))
    a = adapters.Qwen3VL2B(tools_dir=str(tmp_path))
    a.load(str(tmp_path), device)
    return a, str(img)


USING_VK = ("0.00.103.296 I llama_prepare_model_devices: using device Vulkan0 (Intel(R) Iris(R) Xe Graphics) "
            "(unknown id) - 7380 MiB free\n")


def test_gpu_build_that_ran_on_cpu_is_not_available(tmp_path, monkeypatch):
    # b12602's CPU-only build also prints "offloaded 33/33 layers to GPU": only "using device <GPU>" proves a GPU
    for err in ("load_tensors: offloaded 33/33 layers to GPU\n", "no device line at all\n"):
        a, img = _llama(tmp_path, monkeypatch, err, "vulkan")
        with pytest.raises(adapters.GpuNotUsed):
            a.run("caption", img, None, None)
        a.close()
    a, img = _llama(tmp_path, monkeypatch, USING_VK, "vulkan")
    assert a.run("caption", img, None, None) == "an answer"
    a.close()


def test_llama_runs_verbose_for_its_timing_and_device_lines():
    assert "-v" in llama_argv("C:/t/llama-cpu", "m", "p", ["a"], "x", gpu=False)


def test_llama_temp_files_live_under_vbench_tmp_and_are_removed(tmp_path, monkeypatch):
    a, img = _llama(tmp_path, monkeypatch, "", "cpu")
    a.run("caption", img, None, None)
    assert os.path.commonpath([a.tmp, str(tmp_path / "tmp")]) == str(tmp_path / "tmp")
    a.close()
    assert not os.path.exists(a.tmp)


def test_florence_uses_fp16_graphs_on_gpu():
    f = adapters.Florence2()
    assert all(n.endswith("_int8.onnx") for n in f.graphs("cpu"))
    assert all(n.endswith("_fp16.onnx") for n in f.graphs("directml")) and f.graphs("cuda") == f.graphs("directml")
    with open(MODELS, encoding="utf-8") as fh:
        files = json.load(fh)["models"]["florence2-base-ft"]["files"]
    for dev in ("cpu", "directml"):
        for n in f.graphs(dev):
            assert "onnx/" + n in files


def test_merge_cache_keeps_encoder_cache_when_graph_returns_an_empty_one():
    import numpy as np
    full = np.ones((1, 12, 587, 64), np.float32)
    past = {"past_key_values.0.encoder.key": full, "past_key_values.0.decoder.key": np.ones((1, 12, 1, 64))}
    new = {"past_key_values.0.encoder.key": np.zeros((0, 12, 1, 64)), "past_key_values.0.decoder.key": np.ones((1, 12, 2, 64))}
    out = adapters.merge_cache(past, new)
    assert out["past_key_values.0.encoder.key"] is full
    assert out["past_key_values.0.decoder.key"].shape == (1, 12, 2, 64)
    assert adapters.merge_cache(None, new) is new


def test_variants_change_only_the_flags_they_name():
    base = llama_argv("C:/t/llama-vulkan", "m", "p", ["a"], "x", gpu=True)
    v = adapters.VARIANTS["fast"]
    argv = llama_argv("C:/t/llama-vulkan", "m", "p", ["a"], "x", gpu=True, variant=v, task="ask")
    assert argv[argv.index("-n") + 1] == str(v["max_tokens"]["ask"])
    assert argv[argv.index("--image-max-tokens") + 1] == str(v["image_max_tokens"])
    assert "--image-max-tokens" not in base and base[base.index("-n") + 1] == "256"
    for flag in v.get("flags", []):
        assert flag in argv
    assert "-v" in argv and "--port" not in argv


def test_every_variant_is_known_and_well_formed():
    assert "base" in adapters.VARIANTS
    for name, v in adapters.VARIANTS.items():
        assert set(v) <= {"max_side", "max_tokens", "image_max_tokens", "flags", "about"}, name
        assert all(t in ("detect", "ocr", "caption", "ask", "compare") for t in v.get("max_tokens", {})), name

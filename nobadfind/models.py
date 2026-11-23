"""The model catalog and tiers (spec 2026-11-18 §4): which model does each feature, what it needs from the PC.

Every downloadable model is pinned to one revision, and every file to its size and SHA-256 (embed._fetch_verified
checks both before a file is used). Only permissive licences. Sizes are the download; ram_mb and the speed notes
were measured on the reference PC (i5-12500H, 16 threads, 15.7 GB; docs/measurements.md, 2026-11-19 0.8.0).

Tiers (the spec's table):
  light     < 8 GB RAM or <= 4 cores           all-MiniLM-L6-v2, no photo meaning, Windows OCR
  balanced  8-16 GB and 4+ cores               multilingual-e5-small, SigLIP base, Windows OCR
  best      16 GB+ and 8+ cores, or DirectML   multilingual-e5-base, SigLIP 2 base, Windows OCR
            with 4 GB+ of video memory
"""
import json
import math
import os

from .const import DATA_DIR, MODEL_FILES, MODEL_REV
from . import llama_pins
from .photo import PHOTO_FILES, PHOTO_REV

TIERS = ("light", "balanced", "best")
HF = "https://huggingface.co/"

_E5_SMALL_REV = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
_E5_BASE_REV = "1ec9243030a27d1a115d5c340572074c125b58b2"
_SIGLIP2_REV = "ba1f3b0843f24bc5417d38e19c37b287d719b2f4"


def _runtime(rid, name, zipinfo, dlls, improves):
    zname, zurl, size, sha = zipinfo
    return {"id": rid, "feature": "runtime", "name": name, "tier": "light", "licence": "MIT",
            "source": "https://github.com/ggml-org/llama.cpp/releases/tag/" + llama_pins.TAG, "rev": llama_pins.TAG,
            "url": zurl, "files": {"zip": (zname, size, sha)}, "files_in_zip": dict(dlls),
            "dir": os.path.join("runtime", rid), "languages": [], "improves": improves, "ram_mb": 0,
            "speed_note": "", "builtin": False}


CATALOG = [
    {"id": "minilm-l6-v2", "min_score": 0.25, "spread": 0.29, "name_spread": 0.29, "name_strong": 0.33, "feature": "text", "name": "all-MiniLM-L6-v2", "tier": "light", "licence": "Apache-2.0",
     "source": HF + "sentence-transformers/all-MiniLM-L6-v2", "rev": MODEL_REV, "files": dict(MODEL_FILES),
     "repo": "sentence-transformers/all-MiniLM-L6-v2",
     "dir": "model", "dim": 384, "query_prefix": "", "passage_prefix": "", "pooling": "mean", "languages": ["en"],
     "improves": "Finds files by what they mean, in English", "quality": {"english": 0.847, "hindi": 0.497}, "ram_mb": 40,
     "speed_note": "about 33 pieces of text a second while indexing; a question in about 6 ms", "builtin": False},
    {"id": "multilingual-e5-small", "min_score": 0.8, "spread": 0.04, "name_spread": 0.04, "name_strong": 0.88, "feature": "text", "name": "multilingual-e5-small", "tier": "balanced",
     "licence": "MIT", "source": HF + "intfloat/multilingual-e5-small (ONNX: Xenova/multilingual-e5-small)",
     "rev": _E5_SMALL_REV, "repo": "Xenova/multilingual-e5-small",
     "files": {"model.onnx": ("onnx/model_quantized.onnx", 118308185,
                              "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"),
               "tokenizer.json": ("tokenizer.json", 17082730,
                                  "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39")},
     "dim": 384, "query_prefix": "query: ", "passage_prefix": "passage: ", "pooling": "mean",
     "languages": ["en", "hi", "multilingual (about 100 languages)"],
     "improves": "Meaning search in Hindi, mixed Hindi and English, and about 100 other languages",
     "quality": {"english": 0.785, "hindi": 0.823}, "ram_mb": 385, "speed_note": "about 30-70 pieces of text a second while indexing; a question in about 10 ms", "builtin": False},
    {"id": "multilingual-e5-base", "min_score": 0.77, "spread": 0.04, "name_spread": 0.04, "name_strong": 0.85, "feature": "text", "name": "multilingual-e5-base", "tier": "best",
     "licence": "MIT", "source": HF + "intfloat/multilingual-e5-base (ONNX: Xenova/multilingual-e5-base)",
     "rev": _E5_BASE_REV, "repo": "Xenova/multilingual-e5-base",
     "files": {"model.onnx": ("onnx/model_quantized.onnx", 278647662,
                              "df7a9a29309e3ad491e1783adf8baee710262cc06079c7cbab63c630277fac94"),
               "tokenizer.json": ("tokenizer.json", 17082660,
                                  "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626")},
     "dim": 768, "query_prefix": "query: ", "passage_prefix": "passage: ", "pooling": "mean",
     "languages": ["en", "hi", "multilingual (about 100 languages)"],
     "improves": "Many languages with better English than e5 small (Hindi about the same)",
     "quality": {"english": 0.824, "hindi": 0.808}, "ram_mb": 544, "speed_note": "about 8-24 pieces of text a second while indexing; a question in about 20 ms", "builtin": False},
    {"id": "gte-small", "min_score": 0.8, "spread": 0.1, "name_spread": 0.1, "name_strong": 0.88, "feature": "text", "name": "GTE small (English)", "tier": "light", "licence": "MIT",
     "source": HF + "thenlper/gte-small" + " (ONNX: Xenova/gte-small)", "rev": "5927d1727bb12db490052a1b33265ad78058de08", "repo": "Xenova/gte-small",
     "files": {"model.onnx": ("onnx/model_quantized.onnx", 34014426, "18dec105109b6004369799ca4761fb8fb413c64172c02147bcfac186b5c5f6cb"),
               "tokenizer.json": ("tokenizer.json", 711661, "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0")},
     "dim": 384, "query_prefix": "", "passage_prefix": "", "pooling": "mean",
     "languages": ["en"], "improves": "Better English meaning search than all-MiniLM, and faster", "quality": {"english": 0.873, "hindi": 0.546}, "ram_mb": 56, "speed_note": "about 54 pieces of text a second while indexing; a question in about 7 ms", "builtin": False},
    {"id": "bge-base-en-v1.5", "min_score": 0.47, "spread": 0.16, "name_spread": 0.16, "name_strong": 0.55, "feature": "text", "name": "BGE base (English) v1.5", "tier": "best", "licence": "MIT",
     "source": HF + "BAAI/bge-base-en-v1.5" + " (ONNX: Xenova/bge-base-en-v1.5)", "rev": "4d6cd88e18e51a5e020c2c305726d76ada9c03cf", "repo": "Xenova/bge-base-en-v1.5",
     "files": {"model.onnx": ("onnx/model_quantized.onnx", 110083337, "c9729cc84cbd0e9fecc759505d2be65916c9fe05222d7ea26c65fcb3382af38d"),
               "tokenizer.json": ("tokenizer.json", 711396, "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66")},
     "dim": 768, "query_prefix": "Represent this sentence for searching relevant passages: ", "passage_prefix": "", "pooling": "cls",
     "languages": ["en"], "improves": "A bigger English model (no better than GTE small on our test set, slower)", "quality": {"english": 0.864, "hindi": 0.567}, "ram_mb": 125, "speed_note": "about 16 pieces of text a second while indexing; a question in about 25 ms", "builtin": False},
    {"id": "siglip-base", "feature": "photo", "name": "SigLIP base", "short": "SigLIP", "tier": "balanced", "licence": "Apache-2.0",
     "source": HF + "google/siglip-base-patch16-224 (ONNX: Xenova/siglip-base-patch16-224)", "rev": PHOTO_REV,
     "repo": "Xenova/siglip-base-patch16-224", "files": dict(PHOTO_FILES), "dir": "photo-model", "dim": 768, "style": "siglip",
     "languages": ["en"], "improves": "Finds photos by what's in them (English questions)", "ram_mb": 156,
     "speed_note": "about 3 photos a second (1 per 0.3 s per thread group); a question in about 60 ms", "builtin": False},
    {"id": "siglip2-base", "feature": "photo", "name": "SigLIP 2 base", "short": "SigLIP 2", "tier": "best", "licence": "Apache-2.0",
     "source": HF + "google/siglip2-base-patch16-224 (ONNX: onnx-community/siglip2-base-patch16-224-ONNX)",
     "rev": _SIGLIP2_REV, "repo": "onnx-community/siglip2-base-patch16-224-ONNX",
     # vision in fp16 (2026-11-22): the 8-bit vision file blurred the photo vectors (held-out nDCG@10 -0.18 against
     # SigLIP base); fp16 vision + 8-bit text +0.035 (measurements.md). fp16 loads with basic graph optimization
     # (photo.open_session). "vectors": 2 makes vectors from the old file be made again (vector_tag).
     "files": {"vision.onnx": ("onnx/vision_model_fp16.onnx", 186039516,
                               "a1959f7bd3993a607e48839f6d01e25b876fe76afda301b028b78eef68aabd95"),
               "text.onnx": ("onnx/text_model_quantized.onnx", 283438275,
                             "3a0603d3a00c05a80a6ded4743c16aaac7b1e62cdcc7e362e7ce418659b96400"),
               "tokenizer.json": ("tokenizer.json", 34363039,
                                  "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322")},
     "dim": 768, "style": "siglip2", "vectors": 2, "languages": ["en", "hi", "multilingual"],
     "improves": "Finds photos with questions in many languages, Hindi included", "ram_mb": 370,
     "speed_note": "about 3 photos a second on 4 threads (SigLIP base about 4); a question in about 90-125 ms",
     "builtin": False},
    # talk about a photo (find 1.1): a small vision-language model run by llama.cpp (the runtimes below). Not part of
    # the search tiers: it is offered when the user first asks to talk about a photo. Files, revisions, sizes and
    # SHA-256s are tools/vision_bench/models.json. Measured through the real talk worker on the reference PC
    # (docs/measurements.md, 2026-11-22 1.1.0): ram_mb = the most system memory the worker held (peak private or
    # working set, the bigger, over the CPU and the Vulkan runs: on shared-memory graphics the "video" memory is
    # system RAM too); vram_mb = its peak graphics memory on Vulkan (talk_need_mb picks between them).
    # timing, per runtime and governor level (talk_timing): the talk worker runs in the worker group under the
    # level's CPU hard cap (Gentle 35 %, Very light 15 % and efficiency mode), so each level was measured with that
    # cap in force (tools/measure_talk.py; measurements.md 2026-11-22 "release fix: progress, Stop, priority"; CPU
    # rows are two runs, the worker at normal memory / I/O priority while a job runs). load_s = what loading adds to the first question (cold first word minus a warm describe's, the
    # median over the runs), answer_s = (fastest, slowest) finished answer once loaded (Ask, Compare, warm Describe,
    # over all runs); the UI's "about N s" comes only from these.
    {"id": "smolvlm2-500m", "feature": "talk", "name": "SmolVLM2 500M", "tier": "balanced", "licence": "Apache-2.0",
     "source": HF + "ggml-org/SmolVLM2-500M-Video-Instruct-GGUF", "rev": "ccd7aae53bcb1997355c2f094959e72b3642ce17",
     "repo": "ggml-org/SmolVLM2-500M-Video-Instruct-GGUF",
     "files": {"model.gguf": ("SmolVLM2-500M-Video-Instruct-Q8_0.gguf", 436808704,
                              "6f67b8036b2469fcd71728702720c6b51aebd759b78137a8120733b4d66438bc"),
               "mmproj.gguf": ("mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf", 108785184,
                               "921dc7e259f308e5b027111fa185efcbf33db13f6e35749ddf7f5cdb60ef520b")},
     "talk": {"side": 512, "n_ctx": 1024, "n_ubatch": 256, "flash_attn": True, "kv": "q8_0"},
     "languages": ["en"], "improves": "Answers questions about a photo, on this PC",
     "ram_mb": 1031, "vram_mb": 665,
     "timing": {"cpu": {"full": {"load_s": 2, "answer_s": (3, 9)}, "gentle": {"load_s": 1, "answer_s": (3, 10)},
                        "light": {"load_s": 3, "answer_s": (5, 16)}},
                "vulkan": {"full": {"load_s": 2, "answer_s": (1, 4)}, "gentle": {"load_s": 1, "answer_s": (1, 4)},
                           "light": {"load_s": 1, "answer_s": (1, 4)}}},
     "speed_note": "an answer in about 1-4 s on the reference PC's graphics (Iris Xe), 3-10 s on its processor "
                   "(5-16 s while NOBAD Find runs very light)",
     "builtin": False},
    {"id": "qwen3vl-2b", "feature": "talk", "name": "Qwen3-VL 2B", "tier": "best", "licence": "Apache-2.0",
     "source": HF + "Qwen/Qwen3-VL-2B-Instruct-GGUF", "rev": "52d6c8ffea26cc873ac5ad116f8631268d7eb503",
     "repo": "Qwen/Qwen3-VL-2B-Instruct-GGUF",
     "files": {"model.gguf": ("Qwen3VL-2B-Instruct-Q4_K_M.gguf", 1107409952,
                              "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"),
               "mmproj.gguf": ("mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", 445053216,
                               "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82")},
     "talk": {"side": 512, "image_max_tokens": 160, "n_ctx": 1024, "n_ubatch": 256, "flash_attn": True, "kv": "q8_0"},
     "languages": ["en", "multilingual"], "improves": "Deeper answers about a photo, on this PC",
     "ram_mb": 2483, "vram_mb": 2062,
     "timing": {"cpu": {"full": {"load_s": 3, "answer_s": (5, 29)}, "gentle": {"load_s": 2, "answer_s": (4, 18)},
                        "light": {"load_s": 3, "answer_s": (8, 46)}},
                "vulkan": {"full": {"load_s": 3, "answer_s": (1, 11)}, "gentle": {"load_s": 1, "answer_s": (1, 11)},
                           "light": {"load_s": 2, "answer_s": (1, 11)}}},
     "speed_note": "an answer in about 1-11 s on the reference PC's graphics (Iris Xe), 4-29 s on its processor "
                   "(8-46 s while NOBAD Find runs very light); the first question also loads it (about 1-3 s "
                   "measured with its files already read once)",
     "builtin": False},
    # the llama.cpp release the talk models run on (release zip, pinned; files_in_zip = the DLLs kept from it, name:
    # (size, SHA-256); never ggml-rpc.dll, never an .exe). Unpacked to runtime/<id> by the download.
    _runtime("llama-cpu", "llama.cpp runtime (CPU)", llama_pins.CPU_ZIP, llama_pins.CPU_DLLS,
             "Runs the talk models on the processor"),
    _runtime("llama-vulkan", "llama.cpp runtime (graphics card)", llama_pins.VULKAN_ZIP, llama_pins.VULKAN_DLLS,
             "Runs the talk models on the graphics card (Vulkan)"),
    {"id": "windows-ocr", "feature": "ocr", "name": "Windows OCR", "tier": "light", "licence": "Windows",
     "source": "Windows (Windows.Media.Ocr)", "rev": "", "files": {}, "languages": ["the Windows language packs"],
     "improves": "Reads words in photos, screenshots and scans", "ram_mb": 0, "speed_note": "built into Windows",
     "builtin": True},
]
_BY_ID = {m["id"]: m for m in CATALOG}
# the features the search tiers, auto_configure and the models page work with; "talk" and "runtime" entries are
# fetched on use (talk about a photo), never by a tier
SEARCH_FEATURES = ("text", "photo", "ocr")
# what each tier uses per feature ("" = off), by language focus (english: the best English model the PC can run;
# multilingual: multilingual-e5; hindi: the model that scored best on the Hindi set). Measured: measurements.md.
FOCUSES = ("english", "multilingual", "hindi")
TEXT_CHOICE = {"english": {"light": "gte-small", "balanced": "gte-small", "best": "gte-small"},
               "multilingual": {"light": "minilm-l6-v2", "balanced": "multilingual-e5-small",
                                "best": "multilingual-e5-base"},
               "hindi": {"light": "minilm-l6-v2", "balanced": "multilingual-e5-small", "best": "multilingual-e5-small"}}
PHOTO_CHOICE = {"light": "", "balanced": "siglip-base", "best": "siglip2-base"}
# English search quality, measured (tools/eval_text.py, pipeline nDCG@10): gte-small 0.873 beats every bigger
# English model on our set, so it's the English choice at every tier; bge-base stays for who wants a bigger model.
# Hindi: multilingual-e5-small 0.823 beats e5-base 0.808, bge-m3 0.802 and the Hindi-specific candidates.
TIER_CHOICE = {t: {"text": TEXT_CHOICE["multilingual"][t], "photo": PHOTO_CHOICE[t], "ocr": "windows-ocr"}
               for t in ("light", "balanced", "best")}
DEFAULT_TEXT, DEFAULT_PHOTO = "minilm-l6-v2", "siglip-base"
# what a tier asks of the PC (spec table); 16 GB and 8 GB PCs report a little less than that
NEEDS = {"light": (0.0, 1), "balanced": (7.5, 4), "best": (15.0, 8)}


def get(mid):
    return _BY_ID.get(mid)


# ---------- variants and their measured needs (spec 2026-11-22 hardware intelligence §5.1) ----------
# A variant is one way to run a model: its files (None = the model's own files above), the backends it runs on with
# what it was measured to need there (ram_mb, vram_mb, and items_s, or first_word_s for talk; "source" names the
# docs/measurements.md section), its ONNX session options and the variants whose vectors are interchangeable with
# it (equivalent_to). These per-backend needs are the earlier single measurements, not a profile: what a reference
# profile measured is MEASURED below, and only that may be used to suggest a model for a PC.
BACKENDS = ("cpu", "directml", "cuda", "vulkan")
_REPIN = "2026-11-22: SigLIP 2 \"best\" tier re-pinned (4 threads, quiet PC, process private memory)"
_TEXT_SRC = "2026-11-19 (0.8.0 engine): text models (one process, passages/s while indexing on 8 threads)"
_TALK_SRC = ("2026-11-22 (1.1.0): talk about a photo through the real worker (memory: peak private or working set, "
             "the bigger; graphics: shared) and release fix (first_word_s: slowest warm first word at Gentle)")
# passages a second while indexing, English set (measurements.md 2026-11-19 0.8.0, the text-models table)
_TEXT_ITEMS_S = {"minilm-l6-v2": 32.9, "gte-small": 54.3, "multilingual-e5-small": 30.2,
                 "multilingual-e5-base": 8.3, "bge-base-en-v1.5": 16.3}
_VARIANTS = {
    "siglip-base": [
        {"id": "8bit", "files": None, "session": {}, "equivalent_to": [],
         "backends": {"cpu": {"ram_mb": 148, "vram_mb": 0, "items_s": 4.0, "source": _REPIN}}}],
    # fp16 and fp32 vision gave the same vectors on 50 photos (cosine 1.00000, measurements.md _REPIN); the spec's
    # 200-input equivalence check is still to be run before the fp32 variant ships.
    "siglip2-base": [
        {"id": "fp16-vision", "files": None, "session": {"basic_opt": True, "no_arena": True},
         "equivalent_to": ["fp32-vision"],
         "backends": {"cpu": {"ram_mb": 207, "vram_mb": 0, "items_s": 2.9, "source": _REPIN}}},
        # not downloadable yet: its file (onnx/vision_model.onnx at the model's revision) has no pinned size and
        # SHA-256 in this catalog, so embed._fetch_verified can't fetch it
        {"id": "fp32-vision", "files": {"vision.onnx": ("onnx/vision_model.onnx", None, None)}, "pinned": False,
         "session": {"no_arena": True}, "equivalent_to": ["fp16-vision"],
         "backends": {"cpu": {"ram_mb": 370, "vram_mb": 0, "items_s": 4.6, "source": _REPIN}}}],
    "smolvlm2-500m": [
        {"id": "q8_0", "files": None, "session": {}, "equivalent_to": [],
         "backends": {"cpu": {"ram_mb": 610, "vram_mb": 0, "first_word_s": 9.25, "source": _TALK_SRC},
                      "vulkan": {"ram_mb": 1031, "vram_mb": 665, "first_word_s": 2.58, "source": _TALK_SRC}}}],
    "qwen3vl-2b": [
        {"id": "q4_k_m", "files": None, "session": {}, "equivalent_to": [],
         "backends": {"cpu": {"ram_mb": 2373, "vram_mb": 0, "first_word_s": 9.65, "source": _TALK_SRC},
                      "vulkan": {"ram_mb": 2483, "vram_mb": 2062, "first_word_s": 3.26, "source": _TALK_SRC}}}],
}


def variants(mid):
    """The model's variants (a copy). A text model has one, from its measured row. KeyError for an unknown id."""
    m = _BY_ID[mid]
    if m["feature"] == "text":
        vs = [{"id": "default", "files": None, "session": {}, "equivalent_to": [],
               "backends": {"cpu": {"ram_mb": m["ram_mb"], "vram_mb": 0, "items_s": _TEXT_ITEMS_S[mid],
                                    "source": _TEXT_SRC}}}]
    else:
        vs = _VARIANTS.get(mid, [])
    out = []
    for v in vs:
        v = dict(v, backends={b: dict(n) for b, n in v["backends"].items()}, equivalent_to=list(v["equivalent_to"]),
                 session=dict(v["session"]))
        v["tag"] = vector_tag(mid)
        out.append(v)
    return out


# What tools/bench_profiles.py measured on the reference PC (i5-12500H, 16 threads, 15.7 GB, Iris Xe: no
# dedicated graphics memory) emulating each reference profile at Gentle: (model, variant, backend, profile) -> row.
# docs/measurements.md "2026-11-23: reference-profile benchmark (mid measured)" lists every run. A combination missing here was
# NOT measured: it is never suggested. "floor" is each floor dimension's verdict: pass | fail | not measured.
# ram_mb = the worker's whole-process peak private bytes; ws_mb its peak working set. On Vulkan (Iris Xe: shared
# memory) shared_mb is the graphics memory it held, which is system RAM: never capacity of its own, and
# ram_upper_bound_mb = private + shared is only the upper bound for the RAM budget (the two may overlap).
# Measured 2026-11-23 on mid only (8 threads by job affinity, Gentle): the low and high runs were stopped by memory
# pressure on the PC and are not measured; degradation needs them, so it is "not measured" everywhere.
_BENCH = "measurements.md 2026-11-23: reference-profile benchmark (mid)"
_NOT_DEGR = {"degradation": "not measured"}
MEASURED = {
    ("siglip2-base", "fp16-vision", "cpu", "mid"): {
        "workload": "photo_search", "items_s": 1.416, "query_ms": 196.5, "query_p50_ms": 179.6, "ram_mb": 598,
        "ws_mb": 621, "vram_mb": 0, "shared_mb": 0, "first_vector_s": 5.4, "photos": 500, "searches": 50,
        "crashes": 0, "kills": 0, "visual_ndcg10": 0.812, "visual_recall10": 0.866,
        "floor": dict(_NOT_DEGR, usefulness="pass", reliability="pass", responsiveness="pass", memory="pass",
                      availability="pass"), "source": _BENCH},
    ("smolvlm2-500m", "q8_0", "cpu", "mid"): {
        "workload": "photo_talk", "items_s": None, "query_ms": None, "first_word_s": 13.53, "cold_first_word_s": 7.94,
        "load_s": 0.38, "ram_mb": 535, "ws_mb": 628, "vram_mb": 0, "shared_mb": 0, "ram_upper_bound_mb": 628,
        "runs": 10, "crashes": 0, "hang_kills": 0, "kills": 0, "checks_passed": 3,
        "floor": dict(_NOT_DEGR, usefulness="pass", reliability="pass", responsiveness="pass", memory="pass",
                      availability="pass"), "source": _BENCH},
    ("smolvlm2-500m", "q8_0", "vulkan", "mid"): {
        "workload": "photo_talk", "items_s": None, "query_ms": None, "first_word_s": 5.77, "cold_first_word_s": 5.14,
        "load_s": 1.27, "ram_mb": 1033, "ws_mb": 786, "vram_mb": 0, "shared_mb": 663, "ram_upper_bound_mb": 1696,
        "runs": 10, "crashes": 0, "hang_kills": 0, "kills": 0, "checks_passed": 3,
        "floor": dict(_NOT_DEGR, usefulness="pass", reliability="pass", responsiveness="pass", memory="pass",
                      availability="pass"), "source": _BENCH},
    ("qwen3vl-2b", "q4_k_m", "cpu", "mid"): {
        "workload": "photo_talk", "items_s": None, "query_ms": None, "first_word_s": 17.62, "cold_first_word_s": 12.74,
        "load_s": 3.87, "ram_mb": 1743, "ws_mb": 2410, "vram_mb": 0, "shared_mb": 0, "ram_upper_bound_mb": 2410,
        "runs": 10, "crashes": 0, "hang_kills": 0, "kills": 0, "checks_passed": 3,
        "floor": dict(_NOT_DEGR, usefulness="pass", reliability="pass", responsiveness="fail", memory="pass",
                      availability="pass"), "source": _BENCH},
    ("qwen3vl-2b", "q4_k_m", "vulkan", "mid"): {
        "workload": "photo_talk", "items_s": None, "query_ms": None, "first_word_s": 12.08, "cold_first_word_s": 12.08,
        "load_s": 6.21, "ram_mb": 2491, "ws_mb": 2247, "vram_mb": 0, "shared_mb": 2058, "ram_upper_bound_mb": 4549,
        "runs": 10, "crashes": 0, "hang_kills": 0, "kills": 0, "checks_passed": 3,
        "floor": dict(_NOT_DEGR, usefulness="pass", reliability="pass", responsiveness="pass", memory="pass",
                      availability="pass"), "source": _BENCH},
}


def measured(mid, variant, backend, profile):
    """The benchmark's row for this model, variant, backend and reference profile (a copy), or None when it was not
    measured: {"workload", "items_s", "query_ms", "ram_mb", "vram_mb", ["first_word_s", "load_s"], "floor",
    "source", ...}."""
    row = MEASURED.get((mid, variant, backend, profile))
    return None if row is None else json.loads(json.dumps(row))


def vector_tag(mid):
    """What photo vectors are stored under (meta pvec_model): the model id, plus "#<n>" once the catalog changed a
    file that alters the vectors. A different tag means the photos are looked at again, beside the old vectors
    (indexer._load_photo): their rows and tag stay until the new set covers every photo and the two swap in one
    transaction. Meanwhile the old ones answer with the model's text half, which is only right while the re-pins
    since they were made changed vision files alone: a re-pin that changes the text side too sets
    "text_changed_at": <its "vectors" number> (old_vectors_askable), and older vectors are then kept but not asked."""
    m = get(mid) or {}
    return f"{mid}#{m['vectors']}" if m.get("vectors") else mid


def _tag_number(tag):
    try:
        return int(tag.split("#", 1)[1]) if "#" in tag else 0
    except ValueError:
        return 0


def old_vectors_askable(old_tag, mid):
    """True when photo vectors stored under old_tag can answer during a rebuild to mid's vectors: their model is a
    photo model on this PC, and (same model) no re-pin between them changed its text half, i.e. not
    old #n < text_changed_at <= mid's "vectors"."""
    old = old_tag.split("#", 1)[0]
    spec = get(old) or {}
    if spec.get("feature") != "photo" or not ready(old):
        return False
    if old != mid:
        return True
    at = spec.get("text_changed_at")
    return not (at and _tag_number(old_tag) < at <= (spec.get("vectors") or 0))


def ids(feature=None):
    return [m["id"] for m in CATALOG if feature is None or m["feature"] == feature]


def model_dir(mid, data_dir=DATA_DIR):
    m = _BY_ID[mid]
    return os.path.join(data_dir, m.get("dir") or os.path.join("models", mid))


def ready(mid, data_dir=DATA_DIR):
    """Every file of the model on disk at its exact size (the SHA-256 was checked when it was downloaded)."""
    m = get(mid)
    if m is None:
        return False
    if m["builtin"]:
        return True
    d = model_dir(mid, data_dir)
    if m["feature"] == "runtime":               # the zip is not kept: its kept DLLs are what has to be there
        return all(os.path.isfile(os.path.join(d, n)) and os.path.getsize(os.path.join(d, n)) == size
                   for n, (size, _sha) in m["files_in_zip"].items())
    return all(os.path.isfile(os.path.join(d, n)) and os.path.getsize(os.path.join(d, n)) == size
               for n, (_p, size, _sha) in m["files"].items())


def missing_mb(mid, data_dir=DATA_DIR):
    """MB still to download for this model: only the files not on disk at their exact size (a re-pinned file, e.g.
    SigLIP 2's vision in 2026-11-22, is 177 MB to fetch, not the model's 481 MB). 0 when ready or built in."""
    m = get(mid)
    if m is None or m["builtin"]:
        return 0
    d = model_dir(mid, data_dir)
    if m["feature"] == "runtime":
        return 0 if ready(mid, data_dir) else round(size_mb(m))
    left = sum(size for name, (_p, size, _s) in m["files"].items()
               if not (os.path.isfile(os.path.join(d, name)) and os.path.getsize(os.path.join(d, name)) == size))
    return round(left / 1048576)


def size_mb(m):
    return round(sum(size for _p, size, _s in (m["files"] or {}).values()) / 1048576) if not m["builtin"] else 0


def talk_models():
    """The talk-about-a-photo models, SmolVLM2 first."""
    return [m for m in CATALOG if m["feature"] == "talk"]


def runtime_for(device, data_dir=DATA_DIR):
    """The llama.cpp runtime id to use: llama-vulkan for "vulkan" when it is on disk, else llama-cpu."""
    return "llama-vulkan" if device == "vulkan" and ready("llama-vulkan", data_dir) else "llama-cpu"


def talk_runtime(pc, data_dir=DATA_DIR):
    """The runtime talk about a photo uses on this PC: the one on disk (llama-vulkan first), else the one to
    download: llama-vulkan when Windows lists a graphics adapter (hardware.scan "gpu"), else llama-cpu."""
    rid = runtime_for("vulkan", data_dir)
    if ready(rid, data_dir):
        return rid
    return "llama-vulkan" if pc.get("gpu") else "llama-cpu"


TALK_LEVELS = ("full", "gentle", "light")     # the governor's levels talk runs at (paused refuses it)
LEVEL_NAMES = {"gentle": "Gentle", "light": "Very light"}       # as the UI's level chip says them
# a level whose typical answer (the middle of its measured range) takes at least this many times Full's gets the
# "Slower now" note: on the processor at Very light (SmolVLM2 1.4x, Qwen 1.5x); never on Vulkan or at Gentle,
# where the cap measured no slower (the 4 llama threads fit under 35 % of 16 threads; the graphics do the work)
SLOW_FACTOR = 1.4


def _talk_level(level):
    level = str(level or "full").lower()
    return level if level in TALK_LEVELS else ("light" if level == "paused" else "full")


def talk_timing(m, runtime, level="full"):
    """(load_s, (fastest, slowest answer_s)) measured for this talk model on this runtime at this governor level
    (the worker group's CPU cap and efficiency mode); (0, (0, 0)) if not measured."""
    by_level = (m.get("timing") or {}).get("vulkan" if runtime == "llama-vulkan" else "cpu") or {}
    t = by_level.get(_talk_level(level)) or {}
    lo, hi = t.get("answer_s") or (0, 0)
    return int(t.get("load_s") or 0), (int(lo), int(hi))


def talk_slow_note(m, runtime, level):
    """"Slower now: NOBAD Find is in Very light mode." when a typical answer at this level (the middle of its
    measured range) was measured at least SLOW_FACTOR times as long as at Full on this runtime, else ""."""
    level = _talk_level(level)
    if level == "full":
        return ""
    _load, (lo, hi) = talk_timing(m, runtime, level)
    _fl, (flo, fhi) = talk_timing(m, runtime, "full")
    if flo + fhi and lo + hi >= SLOW_FACTOR * (flo + fhi):
        return f"Slower now: NOBAD Find is in {LEVEL_NAMES[level]} mode."
    return ""


def talk_need_mb(m, runtime):
    """The talk model's measured memory need for this runtime: ram_mb on the processor, max(ram_mb, vram_mb) on
    Vulkan (measured: on shared-memory graphics such as Iris Xe, Qwen3-VL on Vulkan committed more system RAM than
    its graphics memory; DXGI can't tell shared from dedicated reliably, and the need only raises the worker
    group's memory limit and sizes the out-of-memory note, so the bigger figure is used on every graphics card)."""
    ram, vram = int(m.get("ram_mb") or 0), int(m.get("vram_mb") or 0)
    return max(ram, vram) if runtime == "llama-vulkan" else ram


def recommend(pc):
    """light | balanced | best for this PC (the spec's table)."""
    ram, cores = float(pc.get("ram_gb") or 0), int(pc.get("cores") or 1)
    if ram < NEEDS["balanced"][0] or cores <= 4:
        return "light"
    if (ram >= NEEDS["best"][0] and cores >= NEEDS["best"][1]) or (pc.get("directml") and pc.get("vram_gb", 0) >= 4):
        return "best"
    return "balanced"


def capable(m, pc, vectors=0):
    """(True, "") or (False, a sentence saying why this PC shouldn't run it). vectors: how many meaning vectors the
    index would hold with it (float16, dim numbers each), so the disk check counts them too."""
    if m["builtin"]:
        return True, ""
    ram, cores = float(pc.get("ram_gb") or 0), int(pc.get("cores") or 1)
    need_ram, need_cores = NEEDS[m["tier"]]
    gpu = bool(pc.get("directml")) and pc.get("vram_gb", 0) >= 4
    free = float(pc.get("disk_free_gb") or 0)
    need_gb = size_mb(m) / 1024 + vectors * 2 * m.get("dim", 0) / 1073741824
    if free and free < need_gb + 1:
        return False, (f"Needs {need_gb:.1f} GB on the disk (the model and its vectors) plus 1 GB to spare; "
                       f"{free:.1f} GB is free")
    if m["feature"] == "talk":
        return _talk_capable(m, pc, ram, cores)
    if m["tier"] == "best" and not gpu and (ram < need_ram or cores < need_cores):
        return False, "Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)"
    if m["tier"] == "balanced" and (ram < need_ram or cores < need_cores):
        return False, "Needs 8 GB of memory and 4 cores"
    return True, ""


def _talk_capable(m, pc, ram, cores):
    """A talk model never runs on DirectML (llama.cpp: the processor or Vulkan), so it has its own check: the tier's
    memory and cores for the processor, or a graphics card with its own memory for the model's measured graphics
    need (vram_mb; shared-memory graphics such as Iris Xe use system memory, so the processor's check applies)."""
    need_ram, need_cores = NEEDS[m["tier"]]
    if ram >= need_ram and cores >= need_cores:
        return True, ""
    vram_mb = int(m.get("vram_mb") or 0)
    if pc.get("gpu") and vram_mb and float(pc.get("vram_gb") or 0) * 1024 >= vram_mb:
        return True, ""
    gb = math.ceil(vram_mb / 102.4) / 10
    return False, (f"Needs {round(need_ram + 0.5):.0f} GB of memory and {need_cores} cores, or a graphics card "
                   f"with {gb:.1f} GB of its own memory")


def selected(settings, feature):
    """The model the settings ask for ("" = the feature is off)."""
    if feature == "text":
        return (settings.get("text_model") or DEFAULT_TEXT) if settings.get("semantic") else ""
    if feature == "photo":
        return (settings.get("photo_model") or DEFAULT_PHOTO) if settings.get("photo_meaning") else ""
    return "windows-ocr" if settings.get("ocr") else ""


def tier_choice(tier, focus="multilingual"):
    """{"text", "photo", "ocr"} model ids for a tier and language focus ("" = off)."""
    return {"text": TEXT_CHOICE.get(focus, TEXT_CHOICE["multilingual"])[tier], "photo": PHOTO_CHOICE[tier],
            "ocr": "windows-ocr"}


def tier_current(settings, focus=None):
    now = {f: selected(settings, f) for f in ("text", "photo")}
    for f in ([focus] if focus else []) + list(FOCUSES):
        for tier in TIERS:
            want = tier_choice(tier, f)
            if now == {"text": want["text"], "photo": want["photo"]}:
                return tier
    return "custom"


def focus_from_languages(tags):
    """english | multilingual | hindi from Windows' display and keyboard languages (BCP-47 tags)."""
    tags = [t.lower() for t in tags if t]
    if any(t.split("-")[0] == "hi" for t in tags):
        return "hindi"
    if any(t.split("-")[0] != "en" for t in tags):
        return "multilingual"
    return "english"


def url(m, path):
    return f"{HF}{m['repo']}/resolve/{m['rev']}/{path}"

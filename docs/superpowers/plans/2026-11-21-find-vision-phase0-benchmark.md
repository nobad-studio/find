# Vision Phase 0: benchmark harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dev-only tool that measures every candidate vision model on this PC (speed, load time, RAM/VRAM,
answer quality) on CPU / DirectML / CUDA, so the maintainer can pick 1.0's defaults and the L2 runtime from real
numbers.

**Architecture:** `tools/vision_bench/` (never shipped, never imported by `nobadfind`). A pure scorer and evalset
loader (unit-tested), a probe of what this PC can run, and a runner that starts **one subprocess per
(candidate, device)** so each one's RAM is its own and a crash or hang only kills that run. Two backends:
ONNX Runtime in Python (Florence-2), and llama.cpp's `llama-mtmd-cli` release binary over stdio (GGUF VLMs; no
server, no port, no Ollama). Output: `summary.md` + `results.json`; the maintainer copies the table into
`docs/measurements.md`.

**Tech Stack:** Python 3.11, onnxruntime / onnxruntime-directml / onnxruntime-gpu (each in its own dev venv),
llama.cpp release binaries (CPU, Vulkan, CUDA builds), huggingface_hub for pinned downloads, Pillow (bench only).

**Spec:** `docs/superpowers/specs/2026-11-21-find-visual-intelligence-design.md` (Phase 0, §1, §2, budgets).

## Global Constraints

- Dev only: nothing under `tools/vision_bench/` is imported by `nobadfind/` or packaged (`packaging/nobadfind.spec`
  unchanged). Its extra deps live in `tools/vision_bench/requirements.txt`, not `requirements*.txt`.
- No Ollama. No llama.cpp server mode, no listening port: `llama-mtmd-cli` over stdin/stdout only.
- 2B is the ceiling: no 4B candidate. Candidates: Florence-2-base-ft (MIT), WeVisOne-VL-2B (Apache-2.0),
  SmolVLM2-500M-Video-Instruct (Apache-2.0), Qwen3-VL-2B-Instruct Q4_K_M + mmproj Q8_0 (Apache-2.0), one Hindi
  OCR candidate (permissive licence, chosen in Task 6).
- Every download: pinned revision / release tag, exact size + SHA-256 recorded in `tools/vision_bench/models.json`,
  verified before use. Downloads go to `--models-dir` (outside the repo), only when run with `--download`.
- The maintainer's photos never enter the repo: the evalset is a local folder given by `--set`; only
  `tools/vision_bench/evalset.example.json` (no photos) is committed.
- Per-run limits: timeout 120 s per photo, 600 s per model load; a run is killed by PID after that.
- Measurements honest: a device that wasn't really used (provider missing, fell back to CPU) is reported as
  "not available", never as that device.
- `python -m pytest -q tests` and `python -m pyflakes nobadfind tests tools/vision_bench` clean before each commit.

## Review Focus

- A photo that can't be decoded (corrupt, 0 bytes, 20000x20000 px) → that item is scored `error: decode`, the run
  continues (Task 4 test).
- A model process that crashes or runs out of memory → recorded as `crash` with its exit code, the next
  candidate runs (Task 5 test).
- GPU asked for but not present (no DirectML/CUDA provider, no CUDA build) → `not available`, never measured as
  CPU under a GPU label (Task 3 test).
- Hindi / mixed-script expected text → scorer compares NFC-normalized, case-folded, whitespace-collapsed text
  (Task 1 test).
- A run that hangs (no output) → killed at the timeout, recorded `timeout` (Task 5 test).

---

### Task 1: Scorer

**Files:**
- Create: `tools/vision_bench/__init__.py` (empty), `tools/vision_bench/score.py`
- Test: `tests/test_vision_bench_score.py`

**Interfaces:**
- Produces: `normalize(text: str) -> str`;
  `score_item(item: dict, answer: str) -> float` (0.0-1.0) for item kinds `objects`, `text`, `count`, `yesno`,
  `describe`; `aggregate(scores: list[tuple[str, float]]) -> dict[str, float]` (mean per kind + `"all"`).

- [ ] **Step 1: Write the failing tests**

```python
from tools.vision_bench.score import normalize, score_item, aggregate

def test_normalize_hindi_and_case():
    assert normalize("  नमस्ते  World ") == normalize("नमस्ते world")

def test_text_item_is_substring_after_normalize():
    assert score_item({"kind": "text", "expect": "EXIT 12"}, "The sign says: exit  12.") == 1.0
    assert score_item({"kind": "text", "expect": "EXIT 12"}, "No text") == 0.0

def test_objects_item_is_fraction_of_expected_found():
    item = {"kind": "objects", "expect": ["dog", "car"]}
    assert score_item(item, "a dog next to a bicycle") == 0.5

def test_objects_synonyms():
    item = {"kind": "objects", "expect": [["car", "vehicle"]]}
    assert score_item(item, "a red vehicle") == 1.0

def test_count_item_reads_first_number_or_word():
    assert score_item({"kind": "count", "expect": 2}, "There are two boys.") == 1.0
    assert score_item({"kind": "count", "expect": 2}, "3 boys") == 0.0

def test_yesno_item():
    assert score_item({"kind": "yesno", "expect": True}, "Yes, same place.") == 1.0
    assert score_item({"kind": "yesno", "expect": True}, "No.") == 0.0

def test_describe_item_is_keyword_hit_rate():
    item = {"kind": "describe", "expect": ["beach", "sunset", "two people"]}
    assert abs(score_item(item, "Two people on a beach.") - 2 / 3) < 1e-9

def test_aggregate():
    assert aggregate([("text", 1.0), ("text", 0.0), ("count", 1.0)]) == {"text": 0.5, "count": 1.0, "all": 2 / 3}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest -q tests/test_vision_bench_score.py`
Expected: FAIL, `ModuleNotFoundError: tools.vision_bench`

- [ ] **Step 3: Implement `score.py`**

`normalize`: `unicodedata.normalize("NFC")`, `casefold()`, punctuation except Devanagari marks → space, collapse
whitespace. Number words one–twenty for `count`. `yesno`: first of `yes|no` in the normalized answer.
An `expect` entry that is a list is a synonym group (any match counts).

- [ ] **Step 4: Run to verify they pass** — same command, Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/vision_bench/__init__.py tools/vision_bench/score.py tests/test_vision_bench_score.py
git commit -m "vision bench: answer scorer (objects, text, count, yes/no, describe; Hindi-safe)"
```

### Task 2: Evalset format and loader

**Files:**
- Create: `tools/vision_bench/evalset.py`, `tools/vision_bench/evalset.example.json`
- Test: `tests/test_vision_bench_evalset.py`

**Interfaces:**
- Consumes: item kinds from Task 1.
- Produces: `load_set(path: str) -> list[dict]`; each item `{"id": str, "image": abs path, "image2": abs path |
  None, "task": "detect"|"ocr"|"caption"|"ask"|"compare", "question": str|None, "kind": ..., "expect": ...}`.
  Raises `ValueError` naming the item id on any bad item.

File format (`set.json` in the maintainer's folder, images beside it, paths relative to it):

```json
{"version": 1, "items": [
  {"id": "sign-01", "image": "sign-01.jpg", "task": "ocr", "kind": "text", "expect": "EXIT 12"},
  {"id": "boys-01", "image": "boys-01.jpg", "task": "ask", "question": "How many people are in this photo?",
   "kind": "count", "expect": 2},
  {"id": "same-01", "image": "a.jpg", "image2": "b.jpg", "task": "compare",
   "question": "Were these two photos taken at the same place?", "kind": "yesno", "expect": true}]}
```

- [ ] **Step 1: Write failing tests**: `test_loads_and_resolves_paths` (tmp folder, two images, paths absolute and
  existing); `test_missing_image_names_item` (`ValueError` containing `"sign-01"`); `test_compare_needs_image2`;
  `test_path_outside_set_folder_refused` (`"image": "..\\x.jpg"` → `ValueError`); `test_unknown_kind_refused`;
  `test_example_file_is_valid_shape` (loads `evalset.example.json` with image checks off:
  `load_set(path, check_files=False)`).
- [ ] **Step 2: Run** `python -m pytest -q tests/test_vision_bench_evalset.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `load_set(path: str, check_files: bool = True) -> list[dict]`. Example file: 50 item
  stubs covering the spec's mix (15 detect/objects, 10 ocr English, 5 ocr Hindi, 10 ask count/question, 5 caption
  describe, 5 compare), image names only.
- [ ] **Step 4: Run** → 6 passed.
- [ ] **Step 5: Commit** `vision bench: evalset format, loader and a 50-item example`.

### Task 3: What this PC can run (probe)

**Files:**
- Create: `tools/vision_bench/probe.py`
- Test: `tests/test_vision_bench_probe.py`

**Interfaces:**
- Consumes: `nobadfind.hardware.scan()` (existing: RAM, cores, AVX2, GPU name/vendor/VRAM).
- Produces: `devices(hw: dict, ort_providers: list[str], llama_builds: dict[str, str]) -> list[dict]`, each
  `{"device": "cpu"|"directml"|"cuda"|"vulkan", "backend": "ort"|"llama", "available": bool, "why": str}`.
  `probe() -> dict` = `{"hardware": scan(), "devices": devices(...)}` using the real providers and the llama
  builds found in `--tools-dir`.

- [ ] **Step 1: Failing tests** (pure `devices`, fake inputs):
  `test_cpu_always_available`; `test_cuda_needs_nvidia_and_provider` (NVIDIA GPU but providers lack
  `CUDAExecutionProvider` → `available False`, `why` mentions the provider); `test_directml_needs_provider`;
  `test_vulkan_needs_llama_vulkan_build`; `test_no_gpu_means_no_gpu_devices_available`.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_vision_bench_probe.py` → FAIL.
- [ ] **Step 3: Implement.** Vendor from the DXGI vendor id (`0x10DE` NVIDIA, `0x1002` AMD, `0x8086` Intel).
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit** `vision bench: device probe (CPU, DirectML, CUDA, Vulkan), honest about what's missing`.

### Task 4: Candidate adapters

**Files:**
- Create: `tools/vision_bench/adapters.py`, `tools/vision_bench/models.json`, `tools/vision_bench/requirements.txt`
- Test: `tests/test_vision_bench_adapters.py`

**Interfaces:**
- Produces: `class Adapter` with `load(models_dir: str, device: str) -> None`,
  `run(task: str, image: str, image2: str | None, question: str | None) -> str`, `close() -> None`;
  `ADAPTERS: dict[str, type[Adapter]]` keyed by candidate id: `florence2-base-ft`, `smolvlm2-500m`,
  `qwen3vl-2b-q4`, `wevisone-vl-2b`, `hindi-ocr`.
  `prompt_for(task: str, question: str | None, candidate: str) -> str` (fixed templates; Florence uses its task
  tokens `<OD>`, `<OCR>`, `<MORE_DETAILED_CAPTION>`; `ask`/`compare` with Florence → `NotSupported`).
  `decode(path: str, max_side: int) -> "PIL.Image"`: refuses > 50 MB files and > 40 MP images (`DecodeError`).
  `models.json`: per candidate `repo`, `rev`, `files: {name: [size, sha256]}`, `licence`; llama.cpp builds per
  device: release tag, zip name, size, sha256.

- [ ] **Step 1: Failing tests** (no models needed):
  `test_prompt_templates_fixed` (exact strings for each task); `test_florence_refuses_ask`;
  `test_decode_refuses_huge_and_corrupt` (tmp 0-byte file and a 1 KB file of random bytes → `DecodeError`);
  `test_models_json_complete` (every candidate has repo, rev, licence in {MIT, Apache-2.0}, every file a size>0 and
  64-hex sha256); `test_llama_cmdline_has_no_server_or_port` (built argv for `qwen3vl-2b-q4` contains
  `llama-mtmd-cli`, `-m`, `--mmproj`, `--image`, and none of `server`, `--port`, `--host`).
- [ ] **Step 2: Run** `python -m pytest -q tests/test_vision_bench_adapters.py` → FAIL.
- [ ] **Step 3: Implement.** Florence: ORT sessions from `onnx-community/Florence-2-base-ft` (int8 variants when
  present), `tokenizers` for text, providers chosen per device. GGUF candidates: `llama-mtmd-cli` from
  `--tools-dir/<build>/` via `subprocess.run(argv, input=None, capture_output=True, timeout=120)`, `-ngl 99` for
  GPU builds, `-ngl 0` for CPU, temperature 0. Fill `models.json` by resolving each repo's current revision once
  (`huggingface_hub.HfApi().model_info(repo).sha`) and recording sizes + SHA-256s; Hindi OCR: pick the smallest
  permissive ONNX OCR with Devanagari recognition (record the choice and its licence in the file).
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit** `vision bench: adapters (Florence-2 on ONNX Runtime; GGUF VLMs via llama-mtmd-cli, no server)`.

### Task 5: Runner (one process per candidate × device)

**Files:**
- Create: `tools/vision_bench/run.py`, `tools/vision_bench/__main__.py`
- Test: `tests/test_vision_bench_run.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: CLI `python -m tools.vision_bench --set <folder> --models-dir <dir> --tools-dir <dir> [--download]
  [--only ID,...] [--devices cpu,directml,...] --out <dir>`.
  `run_one(candidate: str, device: str, items: list[dict], ...) -> dict` (in a child process) returning
  `{"candidate", "device", "status": "ok"|"crash"|"timeout"|"not available"|"error", "load_s", "ms_per_item"
  (median), "peak_private_mb", "peak_vram_mb" | None, "scores": aggregate(...), "items": [{id, status, answer, score,
  ms}]}`. Parent: `supervise(cmd: list[str], timeout_s: float) -> tuple[int | None, str]` (exit code or None on
  timeout; kills by PID).

- [ ] **Step 1: Failing tests** with a fake child (`tests/` helper script that sleeps, exits 3, or prints JSON):
  `test_supervise_timeout_kills` (sleeping child, timeout 1 s → `(None, ...)`, child PID gone);
  `test_crash_recorded_and_next_runs` (two fake candidates, first exits 3 → results `["crash", "ok"]`);
  `test_decode_error_item_does_not_stop_run` (one bad image among three → item statuses `["ok", "error: decode",
  "ok"]`); `test_unavailable_device_not_run` (probe says cuda unavailable → status `"not available"`, no child
  started).
- [ ] **Step 2: Run** `python -m pytest -q tests/test_vision_bench_run.py` → FAIL.
- [ ] **Step 3: Implement.** Peak private MB like `tools/eval_text.py` (`GetProcessMemoryInfo`), sampled every
  0.5 s from the parent over the child and its children (the llama process). VRAM: PDH
  `\GPU Process Memory(pid_*)\Dedicated Usage` for those PIDs, `None` if the counter is missing. `--download`
  fetches only the files in `models.json`, checking size + SHA-256, and refuses on mismatch.
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit** `vision bench: runner, one supervised process per candidate and device`.

### Task 6: Report, docs and the real run

**Files:**
- Create: `tools/vision_bench/report.py`, `tools/vision_bench/README.md`
- Modify: `docs/measurements.md` (new section, after the run), `ROADMAP.md` (status table row "Vision Phase 0")
- Test: `tests/test_vision_bench_report.py`

**Interfaces:**
- Consumes: `run_one` results (Task 5).
- Produces: `summary(results: list[dict], probe: dict) -> str` (markdown): PC line (CPU, cores, RAM, GPU, VRAM),
  then one table per layer: L1 (Florence-2, WeVisOne) on detect/ocr/caption; Hindi OCR; L2 (SmolVLM2, Qwen3-VL-2B,
  WeVisOne) on ask/compare/describe. Columns: candidate, device, status, load s, ms per photo, peak RAM MB, peak
  VRAM MB, score per kind, overall; plus "deep pass over 10,000 photos ≈ N h" = ms_per_item × 10,000.

- [ ] **Step 1: Failing tests**: `test_summary_has_pc_line_and_tables`; `test_not_available_rows_show_why`;
  `test_deep_pass_hours` (ms 6000 → "16.7 h").
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → 3 passed.
- [ ] **Step 5: README**: setup (one venv per ORT build: `onnxruntime`, `onnxruntime-directml`,
  `onnxruntime-gpu`; llama.cpp zips per `models.json`), how to build the 50-photo set from the example, the
  command, what each column means. Note total download (~5 GB) and that it's all outside the repo.
- [ ] **Step 6: Commit** `vision bench: report and README`.
- [ ] **Step 7: Real run (needs the maintainer):** ask for consent to download (~5 GB to a folder they choose) and
  for their 50-photo set. Run with the PC otherwise idle, window closed. Paste `summary.md` into
  `docs/measurements.md` under "2026-11-xx: Vision Phase 0", update the ROADMAP row, commit
  `measurements: vision Phase 0 on <PC>`.
- [ ] **Step 8: Gate:** show the maintainer the tables and the spec's per-PC table with the numbers filled in;
  they pick the defaults per PC class, the L2 runtime (ONNX Runtime vs llama.cpp) and whether WeVisOne replaces
  anything. Record their picks in the spec's "Maintainer decisions".

---

## After Phase 0: the remaining plans (written when their inputs are known)

All land as PRs into `find-1.0`, released together as **1.0.0**. Each gets its own plan file, written after the
previous one is merged, against the Phase 0 decisions:

1. `…-vision-l1.md`: VISION job + vision worker exe, Florence-2 + Hindi OCR catalog entries (on-demand
   download), tables `vcaps`/`vobjs`/`vtext`, text indexing, new-first queue, search + object filters, minimum
   safety, Indexing-page rows, AGENTS.md OCR exception.
2. `…-vision-talk.md`: L2 runtime in the vision worker, `vision_*` contract methods + transcripts, detail sheet
   Describe / Ask / Compare (Flutter), streaming, idle unload.
3. `…-vision-pc-analyzer.md`: runtime/model choice per PC, GPU packs from PyPI (+ SYSTEM-INTEGRATION.md), 20 s
   estimate, suggested-settings screen, "How hard" choice, per-layer switches.
4. `…-vision-scheduler.md`: rhythm (+ AGENTS.md exception, Settings reset), heavy-work rules, VRAM checks, crash →
   smaller model, warnings.
5. `…-vision-learn.md`: questions + labels + prototypes, people opt-in (`vision_people`), Privacy & data rows.
6. `…-vision-deep-pass.md`: L3, "Keep getting smarter", estimate on turn-on.
7. Release 1.0.0 via `docs/ai/playbooks/release-find.md`, after a size check (install ≤ 153 MB + 25 MB) and a
   background-weight check with `tools/measure.py` (closed window ≤ 60 MB).

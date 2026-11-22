# Vision benchmark (dev only, never shipped)

Measures each candidate vision model on this PC so the maintainer can pick NOBAD Find 1.0's defaults from real
numbers (spec: `docs/superpowers/specs/2026-11-21-find-visual-intelligence-design.md`, Phase 0).

| Candidate | Layer | Runs with | Download |
|---|---|---|---|
| `florence2-base-ft` (MIT) | L1: objects, text, captions | ONNX Runtime (int8) | 277 MB |
| `smolvlm2-500m` (Apache-2.0) | L2: talk | llama.cpp `llama-mtmd-cli` (Q8_0) | 545 MB |
| `qwen3vl-2b-q4` (Apache-2.0) | L2: talk | llama.cpp (Q4_K_M + Q8_0 projector) | 1,552 MB |
| `wevisone-vl-2b` (Apache-2.0) | L1/L2 challenger | llama.cpp (Q4_K_M + Q8_0 projector) | 1,729 MB |
| llama.cpp b12602 CPU / Vulkan | runtime | | 25 / 39 MB |
| llama.cpp b12602 CUDA 12.4 + runtime | runtime (NVIDIA only) | | 358 + 391 MB |

Every file is pinned in `models.json` (repo revision, size, SHA-256) and checked before use. Nothing is downloaded
without `--download`, and then only what the chosen candidates and devices need. No Ollama, no llama.cpp server,
no port: llama.cpp runs as a command-line program, one photo per run, stdin closed.

## Setup

```
python -m venv %USERPROFILE%\vbench-cpu
%USERPROFILE%\vbench-cpu\Scripts\pip install -r tools\vision_bench\requirements.txt
```

For DirectML, a second venv with `onnxruntime-directml` instead of `onnxruntime` (same minor version); for CUDA,
one with `onnxruntime-gpu`. Each venv only ever sees one ONNX Runtime build.

## The photo set (your photos never go into the repo)

1. Make a folder outside the repo, e.g. `D:\vbench-set`.
2. Copy `evalset.example.json` there as `set.json`. Put 50 of your photos in it (names as in the file, or your own).
3. Write the real expected answer for each one: objects you can see (`["dog", ["car", "vehicle"]]`, an inner list
   = any of those words), the text on a sign (English or Hindi), how many people, yes/no for a compare pair,
   keywords a good description must mention.

## Run (window closed, PC otherwise idle)

```
python -m tools.vision_bench --set D:\vbench-set --models-dir D:\vbench-models --tools-dir D:\vbench-tools ^
    --out D:\vbench-out --download
```

`--only qwen3vl-2b-q4,smolvlm2-500m` to run some candidates, `--devices cpu,vulkan` to choose devices,
`--tasks ocr,ask` to choose tasks. Every (candidate, device) runs in its own process; a crash, an out-of-memory
or a hang (10 min to load, 2 min a photo) is recorded and the next one runs.

## The report (`summary.md`, also `results.json` with every answer)

- **status**: ok, crash (exit code), timeout, or not available (with why: no NVIDIA card, no DirectML build, ...).
  A device that wasn't really used is never reported as used.
- **load s**: the model loading once. **ms per photo**: median compute time per photo, without loading.
- **peak RAM MB / peak GPU MB**: the most private memory (and dedicated + shared GPU memory) of the run's
  processes; integrated GPUs such as Intel Iris Xe only use shared memory.
- **errors**: photos that couldn't be decoded or answered (not scored).
- **score per kind / overall**: 0-1 against your expected answers (`score.py`: case, spacing, punctuation and
  Unicode forms don't matter; objects and keywords as whole words).
- **10,000 photos**: ms per photo x 10,000, roughly what a deep pass would cost in idle time.

Not measured here: Hindi OCR (PaddleOCR Devanagari, pinned in `models.json`); its detect + read pipeline is built
and measured with the L1 layer.

# NOBAD Find: Hardware Intelligence and the Adaptive Resource Governor (design only)

Status: **design, not implemented.** Maintainer request 2026-11-22. No code, no change to the `find-governor-v2`
branch (PR #16), no default-model migration. It builds on PR #16 and lands after it.

## 1. Intent

Find should be **hardware-adaptive, not resource-hungry**. A PC with a strong NVIDIA card should benefit from it.
A low-end laptop should stay smooth. Neither should be judged by a single number such as total VRAM.

Two ideas are kept apart on purpose:

| | Profile | Governor |
|---|---|---|
| Answers | What can this PC do, and what does the user want? | What can it safely run **right now**? |
| Changes when | the hardware changes, or the user changes the goal | every tick (2 s), with hysteresis |
| Decides | the model variants, backends and maximum batch/concurrency allowed | the level (FULL..PAUSED), the effective limits, load or release |
| Never | reacts to a passing load | rewrites the profile |

So a Performance PC whose GPU memory is briefly taken by a game runs like an Efficiency PC only for as long as the
game holds it. Its profile doesn't change.

Principle kept from the photo work: **understanding stays separate from retrieval.** SigLIP finds, OCR reads,
MiniLM relates, query intelligence interprets, and Qwen verifies only when asked. The governor schedules all of
them and makes none of them automatic.

## 2. What already exists (reuse, don't duplicate)

| Piece | Where | What it does now |
|---|---|---|
| Installed facts | `hardware.scan()` (main) | RAM, physical cores, AVX2, best GPU by VRAM (DXGI), DirectML present, disk free, SSD |
| GPU memory budget | PR #16 `hardware.adapter_memory()`, `gpu_memory_free()` | dedicated/shared budget per adapter; an integrated GPU judged on shared memory |
| Live sensors | PR #16 `winapi`: commit, disk, battery saver, thermal, `GpuMemorySampler` | fail to None = unknown, never "bad" |
| Levels and rules | `governor.Brain` (main) + PR #16 rules with `_Latch` hysteresis | FULL/GENTLE/LIGHT/PAUSED; step up one level after 30 s |
| Per-operation limits | PR #16 `governor.op_limits()` | `effective = min(user, cpu, memory, governor[, gpu])` for walk, readers, photo, vision; `OP_MB`, `VISION_GPU_MB = 1024` |
| Live capability | PR #16 `capability.assess(sample, hardware, measured)` | per model: installed check, RAM need + margin (256 MB + 25%) vs free − 1.5 GB, commit, battery, CPU load, measured speed; device gpu/cpu |
| Installed capability | `models.capable()`, `models.recommend()` (main) | tier by RAM/cores; "best" also with DirectML and ≥ 4 GB VRAM |
| Memory safety | `jobs` WORKERS cap `max(1024, min(4096, RAM/4))` MB; `watchdog` 1500 MB/worker, 3000 MB/job | hard limits under everything here |
| Lazy models | `embed.Lazy` (release after 180 s idle) | models load on use |

What's missing is what this spec adds:
1. A **profile** (capability class + user goal), separate from the live level.
2. **Model variants** with measured requirements, and selection among equivalent variants.
3. **Usable** GPU memory with a reserve, not free or total memory.
4. **Batch size** as a governed quantity.
5. A **backend fallback chain**.
6. **Qwen eligibility rules.**
7. **Acceptance criteria.**

## 3. Hardware facts (extend `hardware.scan`, still once per run, cached)

Added to what `scan()` and PR #16's `adapter_memory()` give:
- **GPU:** vendor (from the DXGI VendorId: 0x10DE NVIDIA, 0x1002 AMD, 0x8086 Intel), model name, dedicated MB,
  shared MB, integrated flag.
- **Backends available** (installed, not live): `cpu` (always), `directml` (the ONNX Runtime provider is
  present), `cuda` (only when the NVIDIA GPU pack is installed and its runtime loads), `vulkan` (llama.cpp
  build present; for VLMs only).
- **CPU:** physical cores, threads, AVX2 (present), AVX-512 VNNI (unknown on Windows; stays False).
- **Memory and disk:** installed RAM, SSD or not, free space on the data drive.

Every probe still fails safe: an unknown backend is "not available", never assumed.

## 4. Profiles

### 4.1 Classes (from hardware facts only)

| Class | Rule (first match) | Example |
|---|---|---|
| **Performance** | NVIDIA with ≥ 8 GB dedicated and the CUDA pack, or any discrete GPU with ≥ 8 GB dedicated and DirectML; and RAM ≥ 16 GB; and SSD | RTX 4070 desktop, 32 GB |
| **Balanced** | discrete GPU with ≥ 4 GB dedicated, or RAM ≥ 16 GB with ≥ 8 physical cores | GTX 1650 laptop; 16 GB / 8-core with an iGPU |
| **Efficiency** | integrated GPU, or RAM 8-16 GB | Iris Xe, 16 GB, 8 cores: the reference PC is Balanced by RAM/cores but treated as Efficiency for GPU work (shared memory) |
| **Compatibility** | RAM < 8 GB, or ≤ 4 physical cores, or no SSD | older laptops |

The class is split into two axes, because one PC can be strong on one and weak on the other:
- `cpu_class` (from RAM, cores, SSD);
- `gpu_class` (from the GPU, its memory and backends).

For example, the reference PC is `cpu_class` Balanced and `gpu_class` Efficiency. CPU work (readers, the text
model) follows `cpu_class`; GPU work (photo embedding on GPU, VLM) follows `gpu_class`.

### 4.2 User goal (one setting, three values)

New setting `performance_goal`: `quiet` | `balanced` (default) | `fast`. It sits beside the existing `power`
setting, which it replaces later (`boost` → `fast`); until then both are read.
- `quiet`: prefer the variant with the lowest memory, smaller batches, never the GPU for background work.
- `balanced`: the best accuracy the class supports, the lighter of equivalent variants.
- `fast`: the faster of equivalent variants and larger batches, within the same safety limits.

The profile is the pair (class, goal). It changes only on a hardware change (detected at start, or a GPU pack
installed/removed) or on the user's setting. It is shown in Settings > Performance with its reasons.

## 5. Model variants and their requirements

### 5.1 Catalog extension

A catalog model (`models.CATALOG`) keeps its id, and gains `variants`, each with:
- `id` (e.g. `siglip2-base/fp16-vision`), the files (path, size, SHA-256) or a reference to the model's shared
  files;
- `backends` it runs on (`cpu`, `directml`, `cuda`, `vulkan`);
- **measured requirements per backend**: `ram_mb`, `vram_mb`, `items_s` (from a row in measurements.md, then
  from this PC's in-app benchmark: PR #16's `measured`);
- `session`: loading options (e.g. `basic_opt`, `no_arena`) instead of hard-coding them;
- `equivalent_to`: other variants whose vectors are interchangeable.

**Equivalence is measured, never assumed:** cosine ≥ 0.999 on the reference drawings
(`tests/test_siglip2_real.py`) and on 50 photos. Equivalent variants share one vector tag, so switching between
them **does not rebuild the index**. Non-equivalent variants (e.g. SigLIP 2's old 8-bit vision at 0.88-0.92) are
different vector tags and need the full quality evaluation before they ship.

Measured example (2026-11-22, reference PC, CPU, 4 threads):

| Variant | RAM | photos/s | equivalent |
|---|---|---|---|
| `siglip2-base/fp16-vision` (no arena) | 207 MB | 2.9 | with fp32 (cosine 1.00000) |
| `siglip2-base/fp32-vision` (no arena) | 370 MB | 4.6 | with fp16 |
| `siglip-base` (8-bit) | 117-148 MB | 4.0 | its own tag |

### 5.2 Selection (extends PR #16 `capability.assess`)

For a feature (photo, text, vision) whose **model** the user or tier chose:
1. Take that model's variants whose backend is available and whose installed requirement fits the class.
2. Of those, keep the ones that fit the **live budget** now (step 6.1).
3. Among **equivalent** variants, pick by goal:
   - `quiet`: least RAM, then least VRAM.
   - `balanced`: the lighter one, unless the faster one is more than 1.5× as fast and fits with 2× margin.
   - `fast`: highest `items_s` that fits.
4. If none fits now, the feature waits ("Not now: ...", as PR #16 already says). It never falls back to a
   non-equivalent variant on its own: that would mix vectors.

`assess` returns, per feature, `{"model", "variant", "backend", "batch", "why"}` in addition to PR #16's
`can_run` / `why` / `device`. The governor applies it; the pools read it like they read `op_limits` now.

Choosing the higher precision is **not** a goal in itself: fp16 and fp32 SigLIP 2 vision give the same vectors,
so the choice is purely about memory against speed.

## 6. Live resources

### 6.1 Usable memory (RAM and GPU), not free or total

- **RAM:** `usable_ram = free_ram − LOW_FREE_MB` (1.5 GB kept for Windows, as now).
- **GPU, discrete:** `usable_vram = free_dedicated − reserve`, with
  `reserve = max(512 MB, 15% of the dedicated budget)`. The reserve covers desktop composition, other apps,
  allocator fragmentation and the load-time spike.
- **GPU, integrated:** its "VRAM" is shared system memory, so a GPU allocation is also a RAM allocation. Its
  need is checked **once against the RAM budget** (never added to it a second time). `usable_shared` is capped by
  `usable_ram`.
- **Load spike:** a variant's `vram_mb` / `ram_mb` is its measured **peak**, including loading, never its
  steady state.
- Counters are kept separate in the UI and logs: process private RAM, GPU dedicated, GPU shared. They are never
  summed (they overlap on an integrated GPU).

### 6.2 Batch size and concurrency

`op_limits` gains a `batch` per operation. It is computed so that `batch × per_item_mb + model_mb ≤ usable` for
the backend in use:
- Batch sizes come from a small per-variant list (e.g. photo: 1, 4, 8, 16, 32). The largest that fits is used,
  capped by the goal (`quiet`: ≤ 4).
- On memory pressure the batch **halves at once**. It grows **one step at a time**, only after the budget allows
  it for `STEP_UP_AFTER` (30 s), the same rule as the levels.
- Concurrency stays PR #16's `effective = min(user, cpu, memory, governor[, gpu])`, and is still at most one
  vision stream per GPU.

### 6.3 Pressure, pause and resume

Reuses PR #16's rules and `_Latch` timings; adds only what variants need:
- **GPU memory pressure** (`usable_vram < need` for ON_FOR):
  1. Batch steps down.
  2. If even batch 1 doesn't fit: the GPU work moves to the next backend in the chain (step 7) if that backend's
     variant is equivalent; otherwise it pauses.
- **Resume:** after the clear condition holds OFF_FOR **and** RULE_HOLD, the work returns to the profile's
  preferred backend and batch, one step at a time.
- **A model is loaded only after `assess` says it fits now.** If loading itself fails (out of memory, driver),
  that variant/backend is marked unavailable for this run, the next one in the chain is tried once, and the
  reason is shown.

## 7. Backend fallback chain

| Model kind | Chain | Condition to move on |
|---|---|---|
| ONNX embedders (SigLIP, MiniLM) | `cuda` → `directml` → `cpu` | backend not available, load fails, or doesn't fit now |
| VLM (llama.cpp: SmolVLM2, Qwen) | `cuda` → `vulkan` → `cpu` | same |
| OCR | Windows OCR (CPU); a model OCR only if installed | - |

Rules:
- A backend is used for an index only if its vectors are **equivalent** to that index's tag (measured per
  backend pair, like variants). Otherwise the index stays on its backend, and the work waits rather than mixing.
- Each move is logged, and shown once in the activity list ("Photos: the graphics card is busy, using the
  processor").

## 8. Qwen (and any VLM)

- **Never automatic.** Plenty of VRAM makes Qwen *allowed*, never *used*.
- **Used only** when the user explicitly asks about one photo (talk, describe, deeper analysis), or later for a
  shortlist re-rank, and only for query types whose benefit was shown on a fresh held-out set (none today: the
  caption test failed).
- **Never during background indexing,** in any profile.
- **Before it loads:** `assess` must allow it now (its measured peak, reserve included); SmolVLM2 and other
  vision models unload first (one large vision model resident, as already decided).
- It unloads after the answer or after `embed.Lazy`'s idle time, whichever comes first.

## 9. Transparency

Settings > Performance shows:
- **"This PC":** the class per axis with its reasons, and the goal.
- **"Right now":** PR #16's tiles, plus the chosen variant/backend/batch per feature and what limited it.

The Index page shows "Running at once now" (PR #16) plus the batch. Every automatic change has a one-line reason
in plain words.

## 10. Integration plan with PR #16

1. **PR #16 lands first** (it is a draft; nothing here changes it).
2. **PR A, hardware facts + profile:**
   - `hardware.scan()` gets vendor and backends.
   - New `profile.py` (pure: facts + goal → class per axis, preferences).
   - `performance_goal` setting (`const.DEFAULTS`, `settings.coerce`, schema, a Settings row).
   - No behaviour change beyond showing the profile.
3. **PR B, variants:**
   - Catalog `variants` / `equivalent_to` / `session` with measured rows.
   - `models.vector_tag` per equivalence group.
   - `photo.open_session` reads `session` options instead of detecting the failure.
   - Equivalence tests.
4. **PR C, selection + batching:**
   - `capability.assess` returns variant/backend/batch.
   - `op_limits` gains `batch`.
   - Pools read them; GPU pressure → batch down → backend chain.
5. **PR D, benchmarks:**
   - The in-app "Test my PC" fills `measured` per variant and backend.
   - Profile-specific benchmark tables in measurements.md.

Each PR goes behind its own switch where it changes behaviour, keeps the mixed-file regression and the photo
evaluation unchanged for the same model, and is reviewed on its own.

## 11. Acceptance criteria (measured, not "detection works")

| # | Criterion | How it's checked |
|---|---|---|
| A1 | Profile is stable under load: a 10-minute synthetic GPU-memory hog (or fake samples) never changes the profile | test with fake samples + one real run |
| A2 | Governor reacts to GPU pressure within 3 ticks (≤ 6 s) and is back at the profile's preference within `OFF_FOR + RULE_HOLD + STEP_UP_AFTER` + 2 ticks after the pressure ends | Brain tests (pure, time from `Sample.t`) |
| A3 | Nothing is scheduled on a GPU when `usable_vram` (with the reserve) is below the variant's measured peak | capability table tests incl. a 12 GB card with 2 GB free → not on GPU |
| A4 | Integrated GPU: a variant's need is counted once against RAM; a 16 GB iGPU PC with 3 GB free is still refused a 4 GB model (PR #16's example holds) | capability tests |
| A5 | Worker peak private memory ≤ the variant's declared `ram_mb` × 1.25 + 256 MB over a 500-photo run; zero watchdog kills | benchmark run, job accounting |
| A6 | Equivalent variants: cosine ≥ 0.999 on the reference drawings and 50 photos; switching between them rebuilds nothing | tests (real-model test skips in CI) |
| A7 | Backend fallback: a simulated load failure moves to the next backend in one attempt, logs it, never writes vectors under a non-equivalent tag | unit tests with fake sessions |
| A8 | Batch: halves at once under pressure, grows one step per `STEP_UP_AFTER`, never exceeds the goal's cap | Brain/op_limits tests |
| A9 | Qwen: zero VLM loads during indexing in every profile; loads only on an explicit request and only if `assess` allows it | tests + benchmark log grep |
| A10 | Throughput by profile (reference PC, quiet): SigLIP 2 at FULL ≥ 4 photos/s with `fast` (fp32), ≤ 250 MB worker RAM with `quiet`/`balanced` (fp16) | profile benchmark table |
| A11 | No regression: `tools/eval_search.py` mixed-file results identical; `tools/eval_photo_search.py` nDCG@10 unchanged for the same model and tag | the two tools, before/after |
| A12 | Profile benchmark published: SigLIP base, SigLIP 2 fp16, SigLIP 2 fp32 × FULL / GENTLE / LIGHT: photos/s, RAM, GPU memory, time to first results | measurements.md table |

## 12. Not in this spec

- Making SigLIP 2 the default (separate decision, after A10/A12).
- A CUDA pack's packaging (the visual spec's GPU packs section).
- New models (Experiment A adds candidates after this foundation, each with its variant rows).
- A rewrite of the indexer or the governor: everything extends `Brain`, `op_limits` and `assess`.

## 13. Open questions for the maintainer

1. `performance_goal` names (`quiet` / `balanced` / `fast`)? And should it replace `power` (`boost`) now or later?
2. The GPU reserve `max(512 MB, 15%)`: a starting value to measure (A2/A3), or should it be a setting?
3. Should Performance require an SSD, or only weigh it for the walk (`cpu_class`)?

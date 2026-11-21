# NOBAD Find: Hardware Intelligence and the Adaptive Resource Governor (design only)

Status: **design, not implemented; architecture approved by the maintainer 2026-11-22 (section 13).** Maintainer request 2026-11-22. No code, no change to the `find-governor-v2`
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

### 4.1 Classes: one per axis (from hardware facts only)

A PC is classed on **four separate axes** (maintainer, 2026-11-22: "SSD should influence storage-related
scheduling, not the overall class"). Each axis is Performance, Balanced, Efficiency or Compatibility, and each
kind of work follows only the axes it depends on.

| Axis | Decided by | Drives |
|---|---|---|
| `gpu_class` | GPU vendor, dedicated/shared memory, backends (CUDA pack, DirectML) | photo embedding and VLM on the GPU, GPU batch sizes |
| `cpu_class` | physical cores, AVX2, architecture | readers, CPU embedding, CPU threads |
| `storage_class` | SSD/HDD (and, once measured, random-read latency) | walk threads, names batches, reader parallelism on that disk |
| `memory_class` | installed RAM (live free memory is the governor's job, not the class's) | how many models may stay resident, worker memory caps |

| Class (GPU axis) | Rule (first match) | Example |
|---|---|---|
| **Performance** | discrete GPU with ≥ 8 GB dedicated and CUDA (pack installed) or DirectML | RTX 4070 |
| **Balanced** | discrete GPU with ≥ 4 GB dedicated and a GPU backend | GTX 1650 laptop |
| **Efficiency** | integrated GPU with a GPU backend (shared memory) | Intel Iris Xe |
| **Compatibility** | no usable GPU backend | CPU only |

CPU, storage and memory axes use the same four names, with the thresholds in `profile.py` (pure, tested):
- CPU: ≥ 8 physical cores with AVX2 = Performance; 6-7 = Balanced; 4-5 = Efficiency; fewer = Compatibility.
- Storage: SSD = Performance; HDD = Efficiency.
- Memory: ≥ 32 GB = Performance; 16-31 = Balanced; 8-15 = Efficiency; less = Compatibility.

Examples:
- **Strong NVIDIA + 32 GB + fast CPU + HDD:** GPU, CPU and memory are Performance; storage is Efficiency.
  GPU inference runs at Performance; only the walk and readers on the HDD are paced.
- **The reference PC** (Iris Xe, 16 GB, 8 cores, SSD): GPU Efficiency, CPU Performance, storage Performance,
  memory Balanced.

### 4.2 User goal (one setting, three values)

New canonical setting `performance_goal`: `quiet` | `balanced` (default) | `fast` (maintainer approved
2026-11-22).

| Goal | Intent | What it changes |
|---|---|---|
| `quiet` | least contention, heat, fan noise and background impact | lightest equivalent variant; batch ≤ 4; no GPU for background work; the governor's step-up waits twice as long; it steps down earlier on others' CPU (≥ 60% instead of 85%), on disk busy (≥ 70% or ≥ 30 ms a transfer), and on thermal pressure (passive limit < 95%) where those sensors exist (PR #16) |
| `balanced` | throughput and responsiveness together | the lighter of equivalent variants unless the faster is > 1.5× faster with 2× margin; PR #16 thresholds as they are |
| `fast` | most throughput within safe limits | the fastest equivalent variant that fits; largest batch that fits; today's `boost` behaviour (all threads while you use the PC); never past the safety limits (reserve, watchdog, job caps, pause rules) |

`quiet` is not "fewer workers": it lowers what Find asks for **and** makes the governor more sensitive to
everything that makes a PC feel busy (CPU, GPU, disk, heat).

**Migration from `power`** (no user preference is lost):
- At the first start with the new setting, `performance_goal` is taken from `power`: `balanced` → `balanced`,
  `boost` → `fast`, and the migration is recorded (meta `goal_migrated`), so it runs once.
- After that, `performance_goal` is the only setting that decides. A compatibility layer keeps reading and writing
  `power` for older UIs and transcripts: `fast` ↔ `boost`, anything else ↔ `balanced`.
- `power` is removed only in a later release, after the UI and contract no longer use it.

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

**Equivalence is measured on representative inputs, never assumed.** Two variants (or two backends) are equivalent
only if **every** item in the equivalence set has cosine ≥ 0.999 and the mean is ≥ 0.9995. The set has 200 photos
across the photo test set's categories: people, scenes, objects, text-heavy, screenshots, black and white, scans,
small and very large images, and odd aspect ratios. The three reference drawings (`tests/test_siglip2_real.py`)
are added on top. A single sample or a few easy pictures are not enough: the colour test passed even for the
broken 8-bit file.

**The index stores its compatibility identity.** Each vector table records (in `meta`) the
**embedding identity** of the vectors it holds: model id, equivalence group, and the variant and backend that
made them, e.g. `pvec_model = "siglip2-base#2"`, `pvec_made_by = "fp16-vision/cpu"`.
- A switch of variant or backend **reuses the vectors only if the new one is in the same equivalence group.**
  Otherwise the photos are looked at again, beside the old vectors, the way a text-model switch already works
  (`vecs_next`).
- Vectors with two identities are never searched together.

Non-equivalent variants (e.g. SigLIP 2's old 8-bit vision, cosine 0.88-0.92) are different identities, and need
the full quality evaluation on a fresh held-out set before they ship.

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
- **GPU, discrete** (maintainer approved as the initial policy, 2026-11-22):

  ```
  R             = max(512 MB, 0.15 × V_free)
  V_usable      = max(0, V_free − R)
  ```

  Example: 3,072 MB free → R = 512 MB → 2,560 MB usable, so a variant whose measured peak is 2,700 MB is **not**
  scheduled on that GPU. The reserve covers desktop composition, other apps, allocator fragmentation and what
  appears between the check and the load.
- **The reserve is a starting policy, not a guarantee:**
  - `LIMITS["GPU_RESERVE_MIN_MB"]` (512) and `LIMITS["GPU_RESERVE_SHARE"]` (0.15) are internal and configurable.
  - Every GPU allocation failure is recorded per adapter (driver and model in the log; the counts in meta).
  - After a failure on an adapter, that adapter's minimum reserve is raised by the size that failed, up to 2 GB,
    and kept. It drops back one step after 7 days without failures.
  - The recorded failures feed the next revision of the defaults.
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
- **A model is loaded only after `assess` says it fits now, and a passed check is not a promise.** Another app can
  take memory between the check and the load, so:
  1. **Final check:** the worker re-reads free memory for that device immediately before allocating, and
     refuses if `need > usable` at that moment.
  2. **Allocation failure** (ONNX Runtime or llama.cpp out of memory, or a driver error) is caught inside the
     worker. The worker never crashes on it: it releases what it allocated, reports `alloc_failed` with the size
     and device, and stays alive.
  3. **The engine's reaction**, in order:
     - record it (6.1, the reserve learns);
     - retry the same variant once at half the batch;
     - then the next **equivalent** backend;
     - then pause that work (6.4).
  4. A failure during inference (not loading) follows the same path, from step 2.

### 6.4 When no compatible backend fits

Exactly this order, and nothing else:
1. Reduce the batch size step by step, down to 1.
2. Try the next backend in the chain **whose vectors are equivalent** to the index's identity.
3. If none fits: **pause that work**, show the reason once ("Photos paused: not enough graphics or system memory
   right now"), and leave the rest of Find running.
4. **Resume** when the governor's recovery conditions hold (`OFF_FOR` + `RULE_HOLD`, then one step at a time):
   - first on the preferred backend at batch 1;
   - then growing.

Never silently switch to a backend or variant that makes **incompatible** vectors. A switch like that is only
ever the user's explicit choice, and it starts a visible re-index (5.1).

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

## 8b. User control and reset to safe defaults (maintainer, 2026-11-22)

**Everything automatic can be set by the user,** and one action returns to the safe defaults.

| Setting (Settings > Performance) | Values | Default |
|---|---|---|
| Goal | quiet / balanced / fast | balanced (migrated from `power`) |
| Graphics card for background work | auto / on / off | auto |
| Backend per feature (photos, text, talk) | auto / CUDA / DirectML / Vulkan / processor (only what's available) | auto |
| Variant per model (e.g. SigLIP 2 "lighter" fp16 / "faster" fp32) | auto / each equivalent variant | auto |
| Most at once (existing `workers`) and largest batch | auto / a number | auto |
| Profile override per axis (GPU / CPU / storage / memory) | auto / a class | auto |
| Advanced: GPU reserve minimum (MB) | 512-4096 | 512 (raised per adapter by learned failures) |

Rules:
1. **A user choice narrows or redirects; it never removes a safety limit.**
   - Always kept: the RAM kept for Windows, the GPU reserve floor (512 MB), the WORKERS memory cap, the watchdog
     limits, pause on call/battery/presentation (their own settings), and never mixing vector identities.
   - A forced choice that doesn't fit right now **waits and says why**: "Photos on the graphics card: waiting,
     2.1 GB free and they need 2.7 GB". It isn't silently replaced.
2. **A choice that changes vector identity** (a non-equivalent variant or backend, or another model) asks first:
   it shows the re-index time estimate, then re-indexes beside the old vectors.
3. **"Reset to safe defaults"**, one button on the Performance page:
   - It **resets:** the goal to balanced; every override to auto; the advanced reserve to 512 MB; and the learned
     per-adapter reserves.
   - It **keeps:** the index, the chosen models (choosing models is Settings > Models, with its own "Use the
     recommended models"), privacy settings, folders, and the learned per-app game levels (those have their own
     "Reset" in Settings already).
   - It asks once, then applies at once: the governor re-decides on the next tick.
4. **Every value** is in `const.DEFAULTS`, `settings.coerce`, the contract schema and a Settings row, like every
   setting (AGENTS.md).
5. Each override shows, beside it, what "auto" would pick right now and why, so a user can see what they're
   overriding.

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
   - `performance_goal` setting (`const.DEFAULTS`, `settings.coerce`, schema, a Settings row), the one-time
     `power` migration with its compatibility layer, and "Reset to safe defaults" (8b).
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
   - Per-feature backend/variant/batch overrides (8b), the final allocation check and the learned reserve (6.1, 6.3).
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
| A13 | Reserve rule: 3,072 MB free → 512 MB reserve → 2,560 MB usable; a 2,700 MB peak is refused; 10,000 MB free → 1,500 MB reserve | capability table tests |
| A14 | Allocation failure between check and load (fake session raising out-of-memory): the worker survives, the engine records it, retries at half batch, then an equivalent backend, then pauses; the adapter's reserve rises by the failed size (≤ 2 GB) | unit tests with fake sessions |
| A15 | Index identity: a switch to an equivalent variant/backend keeps the vectors; to a non-equivalent one re-indexes beside the old vectors; a search never mixes identities | tests (like test_vector_rebuild.py) |
| A16 | Equivalence uses the 200-input representative set: every cosine ≥ 0.999 and mean ≥ 0.9995; the old SigLIP 2 8-bit vision is rejected | real-model test (skips in CI) |
| A17 | Storage is its own axis: strong GPU + HDD → GPU Performance, storage Efficiency; GPU batch/backend unchanged by the HDD, walk/readers paced | profile tests |
| A18 | `power` migration: `boost` → `fast`, `balanced` → `balanced`, once; older UIs reading/writing `power` keep working | settings tests + contract transcript |
| A19 | User overrides never cross a safety limit; a forced choice that doesn't fit waits with its reason; "Reset to safe defaults" restores the listed values and keeps the listed ones | tests + one UI walkthrough |
| A20 | `quiet` reacts to more than workers: with fake samples, others' CPU 65%, disk 35 ms or passive limit 93% steps `quiet` down while `balanced` doesn't | Brain tests |

## 12. Not in this spec

- Making SigLIP 2 the default (separate decision, after A10/A12).
- A CUDA pack's packaging (the visual spec's GPU packs section).
- New models (Experiment A adds candidates after this foundation, each with its variant rows).
- A rewrite of the indexer or the governor: everything extends `Brain`, `op_limits` and `assess`.

## 13. Maintainer decisions (2026-11-22; architecture approved)

1. **Goal names `quiet` / `balanced` / `fast`: approved.** `performance_goal` is canonical; `power` is migrated
   once (`boost` → `fast`) and kept readable/writable through a compatibility layer until it can be deprecated.
   `quiet` covers CPU, GPU, disk and heat, not only workers (4.2).
2. **GPU reserve `R = max(512 MB, 0.15 × V_free)`, `V_usable = max(0, V_free − R)`: approved as the initial
   policy.** It is configurable internally (and as an advanced setting), allocation failures are collected, and
   requirements include loading peaks (6.1).
3. **Performance does not require an SSD.** Storage is its own axis and only paces storage work (4.1).

Refinements adopted:
- a final allocation check and survivable allocation failure (6.3);
- index-aware switching with the embedding identity stored with the index, and equivalence on a 200-input
  representative set (5.1);
- a defined order when no backend fits (6.4);
- hardware capability kept separate from live pressure (1);
- everything user-settable with "Reset to safe defaults" (8b).

Review note: this document is on the local branch `find-visual-design` and has not been pushed, which is why
the GitHub connector couldn't read it. Pushing (or opening a draft PR) needs the maintainer's go-ahead.

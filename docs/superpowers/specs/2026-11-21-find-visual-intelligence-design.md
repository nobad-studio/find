# NOBAD Find: visual intelligence engine (see, read, talk about photos; adapts to any PC)

Date: 2026-11-21. Status: design, awaiting the maintainer's approval. Repo: `nobad-studio/find` (current 0.9.6).

## Intent

Make Find understand photos the way a person does, on whatever PC it runs on. The maintainer's words: "a super
smarter version, adaptable on any PC". Today Find finds photos by what's in them (SigLIP vectors, `photo.py`) and
by the words in them (Windows OCR, `ocr.py`). This adds:

- **Seeing:** objects, where they are, a caption, and the text in each region, for every photo.
- **Talking:** describe a photo, answer a question about it ("what's written on this sign?"), compare two photos.
- **Adapting:** a PC analyzer picks models and runtime (CUDA on NVIDIA, DirectML on other GPUs, CPU otherwise),
  learns when the user actually uses the PC, works hard when they're away and backs off before they notice.
- **Learning from the user:** after indexing, Google Photos-style questions ("Are these all of *Bruno*?"),
  confirmed answers kept and used to get better.
- **New first:** a photo that just arrived (folder notifications, or the turbo change journal) is analysed before
  the backlog.

Several small models share the work instead of one big vision model doing everything. Weights are kept small
(quantized) and loaded only while they work.

## Goals

1. Multi-model stack in layers, each cheaper than the next and run on more photos (Design §1).
2. PC analyzer + model and runtime selection, with an honest time estimate for any choice (§2).
3. Adaptive scheduler on top of the existing governor: learned usage pattern, instant back-off, crash and lag
   control, warnings before heavy work (§3).
4. Talk about a photo in the photo detail sheet: describe, ask, compare two (§4).
5. Feedback questions and labels that improve search (§5).
6. Opt-in "keep getting smarter" deep pass (§6).

## Non-goals

- 4B models or bigger. Maintainer: "dont use 4b model thats too much". 2B is the ceiling, and only quantized.
- Training or fine-tuning model weights on the PC. "Getting better" means stored labels and per-label example
  vectors (§5), not gradient training.
- Cloud anything. Every model runs locally; the only network use is the model/runtime downloads the user agrees
  to (house rule: each outbound connection has a setting and an entry in SYSTEM-INTEGRATION.md).
- Video understanding (SmolVLM2 can, but out of scope).
- Person grouping on by default. It exists only behind the opt-in `vision_people` setting (decisions below).

## Anti-goals (fails even if it "works")

- A game stutters, a call lags or the PC feels slow because Find loaded a vision model.
- A download, or hours of GPU work, starts without the user saying yes.
- A model's guess is shown as fact. Talk answers and auto labels are labelled as the model's reading.
- Questions back to the user feel like nagging.
- The engine's closed-window memory grows: models load, work and unload.
- A model crash takes the engine or the UI with it.

## Size, weight and control budgets (maintainer, 2026-11-21: "dont make it too big … super transparency and
custom by user pref … not overweight even in bg")

- **App size:** installed Find is 153 MB today (0.9.6). 1.0 adds at most **25 MB** to the install; every model and
  GPU pack is an on-demand download (Release section), never in the installer.
- **Background weight:** with the window closed and no vision work queued, the engine stays at the existing
  target (<= 60 MB, CPU ~ 0 %; ROADMAP). Vision work in the background follows the governor's caps (GENTLE 35 %
  CPU, LIGHT 15 %) and never runs at LIGHT/PAUSED; heavy work only under §3's rules. Defaults are conservative:
  L1 on idle only, deep pass off, talk on demand.
- **Every part is the user's choice:** each layer (L1 see/read, Hindi OCR, talk, deep pass, people, usage
  pattern, GPU use) has its own switch; one "How hard may Find work in the background" choice (Light / Balanced
  / Max, default Balanced) sets the caps; each can be limited to "only when plugged in" / "only when I'm away".
- **Transparency:** the Indexing page shows, per layer: on/off and why, the model and its size, queue length and
  ETA, what it's doing right now, and its live CPU / GPU / RAM; Settings -> Models shows every downloaded item
  and Remove. No vision work happens that isn't listed there.

- **Window closed, work continues (maintainer, 2026-11-21):** when the user opted into background work, vision
  work keeps running in the engine's worker processes after the window closes, and the system tray icon (engine-
  owned, `tray.py`) shows it: a tooltip with what's running ("Understanding photos: 1,240 left"), and menu items
  Pause vision work / Resume / Open Find. Opted out: closing the window stops vision work (queue kept).
- **No data leaves the PC:** the only outbound connections are the consented downloads (pinned, hashed); models
  run fully offline, never call home, and no photo, caption, answer or label is ever sent anywhere. The vision
  worker has no network code; a test asserts the vision modules import no network library.
- **Everything stays encrypted:** captions, objects, text, descriptions, labels, prototypes and the usage pattern
  live only in the SQLCipher index (DPAPI key), never in plain files, logs or temp files (talk answers are not
  logged; the decoder passes pixels to the model in memory).
- **Better meaning search:** captions, region text and descriptions are embedded with the active text model into
  the same vectors as other text, so meaning search ("someone celebrating a birthday") finds photos by what's in
  them as well as by SigLIP's look.

## Constraints

- Windows 10/11 x64. Python engine (`NobadFind.exe`, PyInstaller one-folder) + Flutter UI (`nobad_find.exe`)
  over the pipe contract (`contract/`). Normal-user rights (the turbo helper is the only elevated part and is not
  touched here).
- Models: permissive licence, pinned revision, every file size + SHA-256 checked, downloaded only with consent
  (same path as `embed.download_model` / `photo.download_model`, catalog in `models.py`).
  Checked 2026-11-21 on Hugging Face: Florence-2-base-ft MIT; Qwen3-VL-2B-Instruct, WeVisOne-VL-2B (Tencent),
  SmolVLM2-500M Apache-2.0.
- Photos are untrusted: decoded only by Windows' image decoders, size-limited, in low-priority worker processes
  inside the WORKERS job object (`jobs.py`), as `photo.py` and `ocr.py` do now.
- Model output is untrusted text: stored and shown, never executed, never used as a path or command.
- No listening TCP port. Any model runtime talks to the engine over pipes/stdio, not localhost HTTP.
- GPU runtimes are big (CUDA libraries are hundreds of MB): not in the installer, downloaded as an optional
  "GPU pack" with consent, pinned and hashed like models.
- Index stays in the existing encrypted SQLite store (`store.py`); new tables only, migrations like the others.
- Existing test suite stays green; pyflakes clean; contract transcripts updated for every new method.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Light index for every photo (SigLIP + Florence-2), talking model only when the user asks | Cheapest; search can't use the talking model's deeper understanding |
| B | Talking model writes a detailed description of every photo in the background | Best search for complex questions; hours to days of compute, too heavy as a default |
| **C (picked)** | A by default, plus B as an opt-in deep pass that runs newest-first, only when the user is away / plugged in | Light on any PC, and gets smarter for users who opt in |

Picked: C. The maintainer handed over the how ("u pick best and optimized and smarter"); C is the only option
that stays light on a weak PC and still has a path to the best results.

## Design

### 1. The layers

| Layer | Model (default) | Runs on | When | Output (new tables) |
|---|---|---|---|---|
| L0 see-by-meaning | SigLIP base / SigLIP 2 (exists) | every photo | indexing (as now) | `pvecs` (exists) |
| L1 detect + read | Florence-2-base-ft, 0.23B, ONNX int8 | every photo | idle / gentle levels | `vcaps` caption, `vobjs` label+box+score, `vtext` text+box |
| L2 talk | per PC (§2): SmolVLM2-500M or Qwen3-VL-2B Q4 | one or two photos | user asks | not stored, except a describe answer the user keeps |
| L3 deep pass | the L2 model | opt-in, all photos newest first | user away / plugged in | `vdesc` long description |

- L1 tasks per photo: detailed caption, object detection, OCR with regions. Florence-2's OCR runs alongside
  Windows OCR; the builder benchmarks them and keeps the better one per language. Hindi / Devanagari is read by
  the added ONNX OCR model (Windows OCR has no hi-IN; Florence-2 reads English).
- Captions, object labels, region text and deep-pass descriptions are indexed as text: FTS (`text` table) and the
  text-meaning vectors (`vecs`), linked to the photo. So "red car near a gate" matches on words and meaning, and
  SigLIP still ranks by look. Ranking merges the signals as search does now (builder tunes weights against a
  labelled photo set, kept in `tests/`).
- Search can filter by detected objects ("photos with 2 people", "screenshots with a QR code") via `vobjs`.
- Each row stores the model id + revision that made it; a model change re-queues only what that model made.

### 2. PC analyzer and model selection

Extends `hardware.py` (already reads RAM, cores, AVX2/AVX-512, GPU via DXGI incl. VRAM) and `models.py` tiers.

- Measured once per run and when the hardware changes: GPU vendor, dedicated VRAM, driver; RAM; cores;
  battery vs plugged in; free disk on the data drive.
- Runtime choice:

| PC | L1 (Florence-2) | L2/L3 (talk) |
|---|---|---|
| NVIDIA, 4 GB+ VRAM, GPU pack installed | ONNX Runtime CUDA | Qwen3-VL-2B Q4 on GPU |
| Other GPU (AMD/Intel), 4 GB+ VRAM or 16 GB shared | ONNX Runtime DirectML (Find's existing GPU path) | Qwen3-VL-2B Q4 on GPU |
| No useful GPU, 16 GB+ RAM, 8+ cores | CPU | Qwen3-VL-2B Q4 on CPU (slow; on demand only, no deep pass by default) |
| Smaller PC | CPU | SmolVLM2-500M |
| < 8 GB RAM or <= 4 cores | CPU, L1 off by default (can be turned on) | SmolVLM2-500M on demand |

- Candidate sizes: Qwen3-VL-2B Q4_K_M 1.1 GB + vision projector Q8 0.45 GB (official `Qwen/Qwen3-VL-2B-Instruct-GGUF`);
  an ONNX export also exists (`onnx-community/Qwen3-VL-2B-Instruct-ONNX`). WeVisOne-VL-2B is benchmarked against
  Florence-2 for L1 localisation and against Qwen3-VL-2B for L2; it ships only if it wins.
- **Runtime for L2 is decided by the Phase 0 benchmark**, between (a) ONNX Runtime (already a dependency, one
  stack, DirectML/CUDA providers) and (b) llama.cpp (GGUF, mature 4-bit kernels, CUDA/Vulkan/CPU builds) loaded
  in a worker process through bindings or stdio, never its HTTP server. Criteria in Phase 0.
- **User picks a heavier model:** allowed (2B ceiling). Before it applies, Find runs a ~20 s test on the user's own
  photos and shows the real numbers: "Qwen3-VL-2B on this PC: about 6 s a photo; the deep pass over 12,400
  photos would take about 21 hours of idle time; uses about 2.1 GB while working". Then it opens
  **Settings → Models** with suggested settings filled in (e.g. "deep pass only when plugged in", "GPU on",
  "L1 at night only"), which the user applies or edits. Nothing heavy starts until they press Apply.
- Settings → Models "Your PC" shows the chosen stack, why it was chosen, and the measured speed of each model.

### 3. Adaptive scheduler (extends `governor.py`, stays rule-based and explainable)

- **Usage pattern:** the governor already samples every 2 s. A new `rhythm` keeps, per weekday × hour, how often
  the user was active and how busy the PC was (rolling weeks, a few KB, local, visible and resettable in
  Settings, off switch; maintainer-approved exception, decisions below). It predicts "likely away for the next hour".
- **Work classes:** L0/L1 are *light* (run at gentle/full as now); L1 on GPU, model loads and L3 are *heavy*.
  Heavy work starts only when: level is FULL, the user has been idle for a while (existing IDLE_AFTER) or the
  rhythm predicts away, no fullscreen app or game is running, plugged in (unless the user allowed battery), and
  enough free RAM/VRAM is measured for that model plus a margin.
- **Instant back-off:** input, a fullscreen app or a game, a lag sign (existing record_lag) → the heavy worker
  stops after the current photo (max a few seconds), unloads the model, and the per-app memory learns, as today.
- **Idle unload:** a talk model unloads after 2 min without a question; the L1 model when its queue is empty.
- **Crash and hang control:** each model runs in its own worker process in the WORKERS job with a memory cap.
  A per-photo timeout (watchdog.py) kills a stuck worker. A crash or out-of-memory marks the photo (`err`),
  retries once, then drops that layer to the next smaller model; two crashes in a day turn the layer off and the
  Indexing page says why. A photo that crashes a model twice is skipped for good (poison-file rule).
- **Warnings:** a toast/dialog before any download, before the first heavy run, and when an estimate is over an
  hour. The Indexing page shows each layer's queue, ETA, current model, and Find's live CPU/GPU/RAM, as now.

### 4. Talk about a photo (UI: photo detail sheet; engine: new pipe methods)

- Detail sheet gets: **Describe**, a question box ("Ask about this photo"), and **Compare with…** (pick a second
  photo from results).
- Answers stream in. Fixed prompt templates + the user's question; images resized to the model's input in the
  decoder worker. A first question loads the model (the sheet shows "Loading Qwen3-VL-2B… ~4 s").
- If a question is better served by stored data (e.g. "what's written here?" and `vtext` exists), the stored text
  is shown at once and the model is asked only if the user wants more.
- Answers are labelled "Find's reading of this photo" and can be copied; a describe answer can be kept (goes to
  `vdesc`, so search uses it).
- Contract: `vision_state`, `vision_ask {file_id, question}`, `vision_describe {file_id}`,
  `vision_compare {a, b, question?}`, `vision_cancel`; event `vision` (progress, tokens, state). Schemas and
  transcripts in `contract/`, like the other methods.

### 5. Questions back to the user, and labels

- After an L1 pass, the engine groups photos by SigLIP vectors + object labels and proposes a few questions:
  "Are these all *dog*?" (with a rename box: "Bruno"), "Is this a *receipt*?", "Same place?".
- Shown as a dismissible card on Home and in a "Help Find learn" page: Yes / No / Rename / Not now. At most a
  few per day; an off switch; never a popup.
- Stored in `vlabels (file_id, label, source user|auto, verdict yes|no, at)` and `vprotos (label, vector, n)`:
  a confirmed label is searchable text on its photos and its example vector (mean of confirmed SigLIP vectors)
  tags new similar photos as *suggested* (lower weight, shown as "suggested"); a No suppresses that label for
  that photo and lowers it for similar ones. All visible and deletable in Settings → Privacy & data, and wiped
  with the index.

### 6. New first, and the deep pass

- One priority queue for L1/L3: (1) photos the user is looking at right now, (2) new or changed photos (from
  `watcher.py`, or turbo's journal changes when turbo is on), (3) newest by date taken / mtime, (4) the rest.
- **Keep getting smarter** (setting, off by default): enables L3 and lets L1 use the GPU at heavy-work times.
  Turning it on shows the §2 estimate first.

## Release: everything ships together as NOBAD Find 1.0.0

Maintainer decision 2026-11-21: all phases below land as separate PRs into a `find-1.0` integration branch and reach
users together in one release, **1.0.0**. No intermediate public release carries part of the vision engine.

**Download only what is needed, when it is needed.** The installer carries code only (plus the small CPU
runtimes). Each model or GPU pack is fetched the first time a feature that needs it is turned on or used, after the
user's consent for that item, and never in advance:
- Florence-2: when photo understanding (L1) is first turned on.
- The Hindi OCR model: only when Hindi is among the user's languages and text reading is on.
- The talk model for this PC: the first time the user presses Describe / Ask / Compare.
- A GPU pack: only on a PC with that GPU, when the PC analyzer recommends it and the user accepts.
- A heavier model: only after the user picks it and accepts the estimate (§2).
Settings -> Models lists every item with its size, whether it's downloaded, and Remove.

**No Ollama.** Find never uses or depends on Ollama (maintainer). The L2 runtime is ONNX Runtime or llama.cpp's
library, run inside Find's own worker process, as decided by Phase 0.

## Phases (each its own PR into `find-1.0`, tests first, CI green)

0. **Benchmark** (`tools/vision_bench.py`, no product code): Florence-2 ONNX int8 vs WeVisOne-VL-2B (L1);
   SmolVLM2-500M vs Qwen3-VL-2B Q4 vs WeVisOne-VL-2B (L2), each on CPU / DirectML / CUDA where possible, ONNX
   Runtime vs llama.cpp. Measures: ms per photo, load time, peak RAM/VRAM, answer quality on a fixed 50-photo set
   with expected answers (objects, sign text incl. Hindi, counts, compare). Results in `docs/measurements.md`.
   Gate: the maintainer picks the defaults from the table.
1. L1 layer + tables + text indexing + new-first queue + search integration.
2. Talk (L2) + detail sheet UI + contract.
3. PC analyzer runtime choice + GPU pack + estimate + suggested settings screen.
4. Adaptive scheduler (rhythm, heavy-work rules, crash control).
5. Feedback questions and labels.
6. Deep pass (L3).

## Calls made by the designer (the maintainer can override)

- **GPU runtimes:** the installer keeps the CPU-only `onnxruntime` it ships today (DirectML is not active on the
  reference PC; ROADMAP). Both GPU builds (`onnxruntime-directml`, `onnxruntime-gpu` + CUDA libraries) go into
  optional downloaded **GPU packs**, one per vendor, each a separate runtime folder used only by the vision
  worker exe. Existing text/photo models are unaffected unless a later measurement says otherwise.
- **Each phase is safe on its own** (even though all ship together in 1.0): Phase 1 already carries the minimum safety: vision work in its own worker
  process, a per-photo timeout, a memory cap, the poison-file rule, and it runs only at the governor's GENTLE/FULL
  levels and stops at LIGHT/PAUSED. Phase 4 adds the smarter parts (rhythm, VRAM checks, crash → smaller model).
- **Memory:** vision workers get their own job object (`VISION`, nested in OUTER, kill-on-close) instead of sharing
  the WORKERS limit. Its cap is set per model from the measured need + margin, and a model starts only when that
  much RAM is actually free. While the user talks to a photo, the watchdog may release the idle indexing models
  (they reload on use, `embed.Lazy`); the talk model always unloads first when Find's total passes `JOB_MB`.
- **llama.cpp CPU build** (only if Phase 0 picks llama.cpp): bundled in the installer, a pinned upstream release
  with its SHA-256 recorded in the build script, like other bundled binaries. GPU builds stay in the packs.

## Maintainer decisions (2026-11-21)

- **Model OCR allowed** (relaxes the AGENTS.md "Windows OCR only, no OCR model downloads" rule for this feature):
  Florence-2's OCR reads English text with regions; a small permissive-licence ONNX OCR model is added for Hindi /
  Devanagari (picked in Phase 0). Both are catalog entries, downloaded only with consent. Windows OCR stays for
  the languages it reads well. AGENTS.md is updated in the PR that adds them.
- **Usage pattern allowed** (a narrow exception to the 2026-11-17 "no usage history" rule): per weekday x hour
  counts of "user active / PC busy" only, no apps, windows or single-event times; inside the encrypted index;
  shown in Settings with Reset and an off switch. AGENTS.md records the exception.
- **People: opt-in.** A separate setting (`vision_people`, off by default) allows person groups and person
  labels. Off: grouping and questions skip clusters whose object labels say "person", and no person label is
  proposed or auto-applied. Everything stays on the PC, is listed in Settings -> Privacy & data and deletable.
- **NVIDIA GPU pack from PyPI:** NVIDIA's own published wheels (onnxruntime-gpu, nvidia-cudnn etc.) at pinned
  versions, each file size + SHA-256 checked through `embed._fetch_verified`; NOBAD redistributes nothing. The
  DirectML pack comes from PyPI the same way. New outbound host (files.pythonhosted.org) gets its setting and its
  SYSTEM-INTEGRATION.md entry.

## Phase 0 results and the upgrades they led to (maintainer, 2026-11-21)

Measured on the reference PC (`docs/measurements.md`, "Vision Phase 0" sections). The maintainer approved the
following; they override earlier sections where they differ.

**Models (every candidate stays in the catalog as a choice; nothing is removed):**
- **Background understanding (L1 captions/objects, and the deep pass): SmolVLM2-500M** on every PC that may run
  it (Iris Xe Vulkan: 2.3 s a photo, 6.5 h per 10,000; overall 0.72; 7/7 questions, 6/6 descriptions).
- **Talking:** SmolVLM2-500M answers first; **Qwen3-VL-2B Q4** (overall 0.91, exact English/German text, all
  objects and comparisons) is offered as **deeper analysis** when the capability assessment says loading it is
  safe right now (see escalation below), with its tuned settings from the Phase 0 speed-up runs.
- **Text:** Windows OCR for the languages it has; PaddleOCR Devanagari (ONNX) for Hindi. **No vision model's
  reading of Hindi text is ever shown as fact** (Qwen3-VL-2B invented fluent Hindi that isn't on the sign).
- Florence-2 and WeVisOne-VL-2B stay as user choices; Florence's place is decided by the like-for-like runs
  (same resolution, CPU vs CPU, DirectML vs Vulkan, detection scored apart from description).
- Note: `onnxruntime-directml` stops at 1.24.4 while the CPU build is 1.27.0; the DirectML GPU pack pins its own.
- One model process stays loaded while it works (never one load per photo, which only the benchmark does), and
  **only one large vision model is ever resident**; one inference stream on a constrained (shared-memory) GPU.

**Capability assessment (replaces "tiers by installed RAM" for vision):** `capability.assess` from live values:
free physical RAM, commit pressure, free/budget GPU memory, measured speed per model on this PC, current CPU/GPU
load, battery and battery saver. A model is allowed only if its measured need + margin fits now. Example that
must hold: a 16 GB PC with 3 GB free never starts Qwen. Shown live in Settings -> Models "Your PC".

**Intelligent model escalation:** a question SmolVLM2 answers well is answered at once; a harder one ("what is
the relationship between the people, what does this scene say?"), or the user's "Deeper analysis", offers Qwen
with its live cost ("about 5 s, 4 GB while answering"). If allowed: SmolVLM2 unloads, Qwen loads, answers,
unloads. If not allowed, the reason is shown ("only 3 GB free; close something or try later").

**In-app benchmark ("Test my PC", Settings -> Models):** the Phase 0 harness, trimmed: a few of the user's own
photos (chosen by the user, never uploaded), each available model on each available device, about a minute;
results stored in the encrypted index and fed to the capability assessment and the time estimates.

**Governor inputs added:** commit pressure, disk latency/busy, battery saver, thermal pressure (where a reliable
cheap source exists), GPU memory budget, "heavy creative app in front" (editable list; treated like a game in
Light). Each with hysteresis and a minimum time in state.

**Concurrency:** per-operation limits recomputed every governor tick, effective = min(user, CPU, memory,
governor), for names walk, text readers, photo decode/embed, and vision (max 1 stream on a constrained GPU);
one logical SQLite writer with batched transactions.

**Vision pipeline (new code only; the working indexer is not rewritten):** bounded queues with backpressure
(decode -> embed -> OCR -> semantic -> persistence), never the whole PC in RAM; a per-photo job ledger in the
encrypted index (discovered, embedded, OCR done, understood, indexed; failures with attempt count and backoff, a
permanently unreadable file is not retried forever), so a crash never redoes finished work.

**Workers:** one program (no extra executables: install-size budget); each worker process has a role, an id, its
creation time, current job, loaded model, memory, last heartbeat and last exit code, tracked by the engine and
shown on the Indexing page's Processes list; job objects stay the final cleanup. Exit: stop new work, stop
discovery, cancel at a safe boundary, flush, unload models, wait a bounded grace period, then terminate.

**Notifications:** an in-app notification list (bell with unread count) and local Windows toasts (no push
service, nothing over the network) for: a worker crashed / was restarted, a model fell back or was released for
memory, an internal error, suggestions (a better model fits now, turbo needs its OK, an update), long pauses.
Deduplicated and rate-limited, quiet during games and calls, no file names unless the user allows it, history
capped and kept inside the encrypted index. (Built separately on `find-notifications`.)

## Hybrid photo search (maintainer, 2026-11-21: "use hybrid retrieval, not just vector similarity")

Today `search.py` fuses names, full text, text meaning and SigLIP photo look with reciprocal rank fusion and
hand-set weights (1.3 / 1.0 / 0.8 / 1.0), tuned on a synthetic file corpus. Photo search adds channels:

| Channel | Source |
|---|---|
| V look | SigLIP (exists) |
| C caption meaning | SmolVLM2 caption, as full text and as text vectors |
| O objects and attributes | SmolVLM2 objects ("person", "laptop", "dark") |
| R actions and relationships | SmolVLM2 "who does what" ("person using laptop") |
| T text in the photo | Windows OCR (exists) + PaddleOCR Devanagari |
| M metadata | date, size, folder, type: a ranking signal as well as a filter |

- **Calibrated, not raw:** each channel's raw score is mapped on judged data to the log-odds that the photo is
  relevant. **A missing channel adds 0 (neutral):** a photo with no text or not yet understood is never pushed down.
- **Learned weights:** a small regularized logistic model on the judged searches, checked on searches held out
  from fitting; weights may depend on what the query asks for (objects, actions, text, dates).
- **Light query expansion:** related phrasings via the text meaning model and concepts from the user's own
  captions; no language model per search. The original query stays first; expansions only add candidates, and
  everything is re-ranked against the original.
- **Facts in one pass:** one structured SmolVLM2 prompt (caption, objects, people/pet count, actions, scene, text
  present), stored once per photo; benchmarked against the separate questions before it replaces them.
- **People's feelings and expressions** ("looking frustrated") sit behind `vision_people` (off by default);
  objects, actions and scenes are on for everyone.
- **Gate:** it ships only if it beats both today's RRF and SigLIP alone (baseline 2026-11-21: 0.755 and 0.864
  nDCG@10, `docs/measurements.md`; today's fusion is worse than its own photo channel) on recall@10 and nDCG@10 on the photo search test set: 60
  searches x about 300 openly licensed Wikimedia Commons photos graded 0/1/2 from what is visible
  (`C:\Users\aassw\vbench\search\`, outside the repo; licences in `photos\sources.json`).

## Still open

- Florence-2's place: like-for-like it is slower and weaker than SmolVLM2 (768 px CPU: 9.1 s vs 5.6 s a photo;
  objects 0.49 vs 0.76, descriptions 0.62 vs 0.92, text 0.11 vs 0.69), and the published fp16 GPU graphs don't
  run on DirectML. It stays a catalog choice with no default role.
- Qwen's tuned settings: "fastest" (512 px, fewer image tokens, flash attention, 8-bit KV cache) for scene and
  relationship questions, 4.9 s, objects/counts/comparisons kept; "short answers" (7.0 s) for text questions. Its
  GPU memory reading (5.8 GB shared) is measured again before it's relied on.

## Left to the builder

- Exact thresholds (VRAM margin, idle times, timeouts), table column details, ranking weights (tuned on the test
  set), prompt wording, the grouping method for questions, and the GPU pack's packaging.

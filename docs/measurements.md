# NOBAD Find: measurements

Numbers decide (ROADMAP §3). Every performance claim points at a row here. Newest first. Working set = RAM in use
now; private = committed memory only this process can use (`Get-Process` `WorkingSet64` / `PrivateMemorySize64`,
summed over the process tree).

## 2026-11-23: photo admission policy D on by default (rollback flag)

Policy D from Experiment A (below) is now the default in `nobadfind/search.py` (`photo_admission`, `_keywordish`,
`_admit_photos`): on a keyword-style search (one content word, no picture words) a photo found only by its look
must score at least `PHOTO_SURE` (0.85) of the best photo; weaker ones stay only when a name, text or meaning
channel found them too. Visual descriptions are unchanged. Rollback to the earlier behaviour:
`NOBAD_FIND_PHOTO_ADMIT=off`, or the `admit_all` search variant in the eval tools (`admit_query` forces D on).
B's and C's measurement variants (`admit_conf:<t>`, `admit_evidence`) were not ported.

Re-run on the fresh set's **training split only** (53 searches; a copy of `%USERPROFILE%\vbench\search2` with the
held-out searches removed, so they never ran), SigLIP base, OCR on, `--variants ";admit_all"`, scored with
the Experiment A scoring script (`admission_report.py --split train`, kept outside the repo with the set):

| Policy | nDCG@10 | R@10 | keyword: grade-0 photos in top 10 | keyword: weak results | negatives: results in top 10 | named docs | OCR-only docs |
|---|---|---|---|---|---|---|---|
| A (`admit_all`, rollback) | 0.714 | 0.788 | 6.7 | 56.3 | 10.0 | 5/5 | 4/5 |
| **D (default)** | 0.714 | 0.788 | **0.7** | **0.3** | 7.0 | 5/5 | 4/5 |

- Same numbers as Experiment A's training run for A and D. Rankings changed on 4 of 53 searches, all one word:
  the keyword searches "lease", "passport", "tax" and the negative "a kangaroo". No described search changed (0 of 47).
  Negatives: results claimed sure 0.3 -> 0.3.
- Held-out: not run again. Its one scoring (Experiment A) stands.
- Mixed-file regression (`tools/eval_search.py`, MiniLM + SigLIP base), flag off vs on, two runs each: keywords
  1.0 / 1.0 and photo 1.0 / 1.0 (recall@1 / recall@5) in every run; recall unchanged everywhere. Some lines change
  between two runs of the same setting: the best guess on "what did i save today" (keywords guesses 33 vs 32,
  once) and the meaning MRR on "job application letter" and "plane ticket" (0.495 vs 0.529). D can't touch these
  searches (no content word, or two or more), so this is run-to-run noise in the eval, not D.
- The eval now uses the set's display names (`manifest.json`) and writes each variant's weak/sure counts and
  ranked photos to its JSON (ported from Experiment A). Sets without a manifest are unchanged.

## 2026-11-22: Experiment A, photo admission policies on the fresh set (SigLIP base, the default)

Fresh set (`%USERPROFILE%\vbench\search2`): 319 new Wikimedia Commons photos (15 duplicates of the old set
removed), 110 new searches (people, relations, mood, attributes, scenes, English/German/Hindi text, screenshots,
Hindi and Hinglish twins, very wide/tall images, 6 document keywords, 6 negatives), graded by 10 agents against
every search. Split fixed before grading: 53 training / 57 held-out (Hindi/Hinglish twins on their English
search's side). 20 document photos: 10 with true descriptive file names (filename evidence), 10 neutral; the
eval keeps those display names (`manifest.json`). Decision rule written before the results
(`results/admission-rule.md`): choose on training, score held-out once.

Training (47 described searches, 3 keyword, 3 negative):

| Policy | nDCG@10 | R@10 | keyword: grade-0 photos in top 10 | keyword: weak results | named docs | OCR-only docs |
|---|---|---|---|---|---|---|
| A today | 0.714 | 0.788 | 6.7 | 56.3 | 5/5 | 4/5 |
| B score >= 0.03 | 0.714 | 0.788 | 6.7 | 12.7 | 5/5 | 4/5 |
| B score >= 0.04 | 0.708 | 0.774 (-0.014, not eligible) | 4.7 | 6.0 | 5/5 | 4/5 |
| B score >= 0.05 | 0.699 | 0.768 | 2.7 | 2.3 | 5/5 | 4/5 |
| C evidence-aware, every search | **0.506** | 0.511 | 0.7 | 0.3 | 5/5 | 4/5 |
| **D query-aware** (C for keyword-style searches only) | 0.714 | 0.788 | **0.7** | **0.3** | 5/5 | 4/5 |

- **Chosen by the rule: D.** Applied to every search, C costs most of v2's gain (0.714 -> 0.506): global
  admission floors hurt, as expected.
- **Held-out, scored once (51 described, 3 keyword, 3 negative):** D vs A on described searches identical
  (0 of 51 changed); keyword grade-0 photos in the top 10: 5.0 -> 1.0; weak results on keyword searches:
  55.3 -> 0; negatives: results in top 10 10 -> 7, claimed sure 0 -> 0; named documents 3/3 -> 3/3;
  neutral-named documents 3/3 -> 2/3. The one lost is a handwritten receipt Windows OCR can't read: it ranked
  only as "the picture may show it", the look-only match D filters on keyword searches.
- `_keywordish`: one content word and no picture words. Search variants `admit_conf:<t>`, `admit_evidence`,
  `admit_query`; off by default (measurement only) until the maintainer decides.

Fresh-set baseline (all 110 searches, nothing tuned on it): SigLIP base v1 0.686 / 0.739, **v2 0.727 / 0.813**
(nDCG@10 / recall@10), SigLIP alone 0.752 / 0.812; SigLIP 2 (fp16 vision) v2 **0.767 / 0.890**, v1 0.764 / 0.846,
alone 0.804 / 0.892. This independently confirms v2 over v1 and SigLIP 2 over SigLIP base.

## 2026-11-23: reference-profile benchmark (mid measured)

`tools/bench_profiles.py` (dev only). It measures each model, variant and runtime against every dimension of the
floor (the plan's floors table), on the reference PC (i5-12500H, 16 threads, 15.7 GB, Iris Xe with no dedicated
graphics memory: its "video" memory is system RAM).
- **Emulation of `mid`:** 8 threads (CPUs 0-7) set by the job object's affinity. Every process in each run was
  checked to be on CPUs 0-7.
- **Level:** Gentle, for an 8-thread PC: the worker group's CPU hard cap is 35 % of 8 threads (job CPU rate 17.5 %
  of this PC's 16). The photo worker gets 4 threads (`governor.op_limits` at Gentle) and idle priority.
- **Memory cap:** Find's worker cap for 16 GB, 4,096 MB. The talk worker gets the model's measured need on top, as
  in the app.
- **Code measured:** the app's own: `photo.embed_photo` / `photo.open_session`, which loads the fp16 vision with
  basic optimization and the arena off; ONNX Runtime logs the first, failed attempt. Talk goes through
  `vlm.worker.Talker` via `tools/measure_talk.py`'s runner.
- **Free memory:** before each run, at least 2.5 GB free and no full-screen game. Free memory was 4.3-4.5 GB
  before the runs (other programs were open). During the Qwen runs it fell to 1.6-1.7 GB.
- **Cold loads:** every cold load found the model files already in Windows' file cache. A first load after a
  restart was not measured.

**What was measured, and what wasn't:**
- Only `mid` was measured (5 runs, 14.7 min of PC time).
- The `low` and `high` runs were stopped because the PC ran low on memory, and nothing was recorded for them.
  Every low and high cell is **not measured**.
- **Graceful degradation** needs the run on the next smaller profile, so it is **not measured** everywhere.
- **Not on the PC, so not run:** SigLIP 2 fp32 vision (its file isn't pinned in the catalog yet) and SigLIP base.
- **Discrete GPU:** no rows, and no estimates published (this PC has none).

### photo_search

- **Indexing:** 500 photos (the first 500 of the 556-photo set's folder).
- **Searches:** 50 searches (the first 50 non-negative questions), warm: the question encoded as the app does
  (`encode_question`, uncached), then scored against the 500 vectors.
- **Usefulness:** not measured by this benchmark. It comes from the recorded evaluation (`eval_photo_search`,
  2026-11-22 "SigLIP 2 base vs SigLIP base, side by side", result files `pm-s2-tq-v16.json` and
  `pm-siglip-base.json`): Find's pipeline on the searches whose channels include V (look) or C (caption), weighted
  by their counts (56 + 28). Nothing was tuned.
- **Memory:** worker peak = the whole process's peak private bytes. That is more than the vision-only 207 MB in
  the re-pin section, which was the vision session's own memory.

| profile | model, variant | photos/s (Gentle) | first vector | worker peak private / working set | search p50 / p95 | crashes / watchdog kills | usefulness V+C nDCG@10 / recall@10 | Usefulness | Reliability | Responsiveness | Memory (≤ 1,638 MB) | Availability | Degradation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mid | SigLIP 2 base, fp16 vision + 8-bit text | 1.42 (500/500) | 5.4 s | 598 / 621 MB | 180 / 197 ms | 0 / 0 | 0.812 / 0.866 (V 0.821 / 0.877, C 0.794 / 0.844) | pass | pass | pass | pass | pass (CPU) | not measured |
| mid | SigLIP 2 base, fp32 vision | not measured | not measured | not measured | not measured | not measured | same vectors as fp16 on 50 photos (re-pin section) | not measured | not measured | not measured | not measured | not measured | not measured |
| mid | SigLIP base (8-bit) | not measured (side by side: 556 photos in 151 s, CPU, not at a profile, while a Qwen job ran) | not measured | not measured | not measured | not measured | 0.776 / 0.856 (V 0.778 / 0.860, C 0.771 / 0.849; side by side, 2026-11-22) | pass (2026-11-22) | not measured | not measured | not measured | not measured | not measured |
| low, high | every photo model | not measured | | | | | | | | | | | |

The search-time figure is the question encoder plus a plain dot over 500 vectors, not the whole `search.search`;
the search process peaked at 632 MB private (the engine side, not the worker). 368 s for the run.

### photo_talk

10 jobs on one fresh worker: Describe, Ask, Compare on the `tools/vision_bench` photos, plus the three checks of
`tests/test_vlm_session.py`'s real-model test (a red circle described as red or a circle, "What colour is the
shape?" answered red, a compare that answers). The first job is the cold load.
- **First word:** p95 by nearest rank (with 10 jobs, the slowest).
- **Load:** model + context + vision part, in the cold job.
- **Memory:** private, working set and shared graphics memory are listed separately. The shared memory is never
  counted as graphics capacity. Private + shared is listed only as an upper bound for the RAM budget on this
  integrated GPU; the two may overlap.
- **Floor memory:** the biggest single figure, against 25 % of 16 GB = 4,096 MB. Qwen on Vulkan passes by that
  figure (2,491 MB), but its upper bound (4,549 MB) is over the budget. If private and shared don't overlap, it
  would fail.

| profile | model, runtime | runs done | first word p95 | cold first word | load | private / working set / shared graphics | private + shared (upper bound) | crashes / hang kills / watchdog kills | checks | Usefulness | Reliability | Responsiveness (≤ 15 s, ≤ 30 s) | Memory (≤ 4,096 MB) | Availability | Degradation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mid | SmolVLM2 500M, llama-cpu | 10/10 | 13.5 s | 7.9 s | 0.4 s | 535 / 628 / 0 MB | 535 MB | 0 / 0 / 0 | 3/3 | pass | pass | pass | pass | pass | not measured |
| mid | SmolVLM2 500M, llama-vulkan | 10/10 | 5.8 s | 5.1 s | 1.3 s | 1,033 / 786 / 663 MB | 1,696 MB | 0 / 0 / 0 | 3/3 | pass | pass | pass | pass | pass (CPU path passed) | not measured |
| mid | Qwen3-VL 2B, llama-cpu | 10/10 | **17.6 s** | 12.7 s | 3.9 s | 1,743 / 2,410 / 0 MB | 1,743 MB | 0 / 0 / 0 | 3/3 | pass | pass | **fail** (first word) | pass | pass | not measured |
| mid | Qwen3-VL 2B, llama-vulkan | 10/10 | 12.1 s | 12.1 s | 6.2 s | 2,491 / 2,247 / 2,058 MB | 4,549 MB (over 4,096 if they don't overlap) | 0 / 0 / 0 | 3/3 | pass | pass | pass | pass (biggest figure) | pass (CPU path passed) | not measured |
| low, high | every talk model and runtime | not measured | | | | | | | | | | | | | |

**Runs, in order:**
- SmolVLM2 on the CPU: first words 7.94, 9.38, 13.33, 6.74, 6.75, 7.03, 13.4, 6.86, 6.72, 13.53 s.
- SmolVLM2 on Vulkan: 5.14, 3.25, 5.77, 2.41, 2.36, 2.72, 5.64, 2.92, 2.85, 4.6 s.
- Qwen on the CPU: 12.74, 8.17, 17.45, 8.6, 7.88, 8.35, 15.51, 8.96, 8.76, 17.62 s.
- Qwen on Vulkan: 12.08, 4.54, 8.21, 4.95, 5.31, 4.6, 6.87, 5.66, 5.65, 9.49 s.

**What the slow ones were and how long each run took:**
- The Compares were the slowest first words.
- Every run read the sign as "EXIT".
- Run times: 99 / 47 / 189 / 180 s.

**Catalog:** `models.MEASURED` holds these 5 rows only. `models.measured()` returns None for everything else
("not measured": never suggested).

### text

No text model files were on the PC, so the text workload was not benchmarked per profile. Its only figures are the
earlier ones: 2026-11-19 (0.8.0 engine), the text-models table (passages/s on 8 threads, at no particular level,
and RAM of one process). `models.variants` carries them, labelled with that source.

## 2026-11-23 (1.1.1): the index totals on a big index (`Store.stats`)

A user's index, read-only on the maintainer's PC: SQLCipher, 10.8 GB plus a 417 MB WAL; 950,903 files, 6.3 M
chunks, 763 k meaning vectors. One `Store.stats` (six COUNTs) took 10.1 s; four at once (the Index page asked
`status_full` again every 3 s, plus the `status_full` event) took 63.6-73.9 s each and held all four of the
pipe's request threads, so searches timed out. Since 1.1.1 the count runs in the background, one at a time.

| date | files | chunks | meaning vectors | one count | vecs | files with text | nvecs | chunks | pvecs | files | four at once |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-23 | 950,903 | 6.3 M | 763 k | 10.1 s | 6.2 s | 1.8 s | 0.9 s | 0.8 s | 0.3 s | 0.1 s | 63.6-73.9 s each |

## 2026-11-22 (1.1.0): talk about a photo, release fix: progress, Stop, priority

The hang deadline now counts only real progress, phase by phase (`vlm.worker.PHASES`), Stop reaches a load and
the photo eval through llama.cpp's callbacks, and the worker has normal memory / I/O priority while a job runs
(`winapi.worker_activity`; CPU priority, the worker group and the CPU cap unchanged). Measured with
`tools/measure_talk.py` through the real `Talker` and worker, the same way as the section under this one (own worker
group, the level's CPU cap checked, EcoQoS at Very light, the memory allowance), with the real `check_deadline`
running every 0.25 s (it never fired). Same PC, photos and jobs; runtime folders as unpacked by the zips. The PC
was idle (the maintainer's game had ended), 7.4-8.4 GB free, except the "low RAM" rows: a memory hog (a child of
the script, given back below a 1,536 MB floor) left 3.8-3.9 GB free before the run. The runs were back to back,
so every "cold" load found the model files already in Windows' file cache: a first load after a restart was not
measured. Times are first word / finished answer, s; "load" is the cold job's model + context + vision part;
"free" is before the run / lowest during it; "slowest phase gaps" lists any phase with 0.5 s or more without
progress as the Talker counts it (the "image" figures are the 1 s rate of "still computing" messages).

| model, runtime, level (run) | load | Describe (cold) | Ask | Compare | Describe (warm) | peak private | graphics | free | slowest phase gaps (s) |
|---|---|---|---|---|---|---|---|---|---|
| SmolVLM2 500M, CPU, Full (1) | 0.84 | 5.9 / 6.29 | 4.07 / 4.11 | 8.26 / 8.61 | 3.9 / 4.08 | 533 MB | - | 7,924 / 7,321 MB | prepare 0.6, image 1.2 |
| SmolVLM2 500M, CPU, Full (2) | 0.21 | 5.1 / 5.54 | 3.91 / 3.94 | 7.95 / 8.35 | 3.94 / 4.09 | 534 MB | - | 8,382 / 7,633 MB | image 1.1 |
| SmolVLM2 500M, CPU, Gentle (1) | 0.22 | 5.93 / 6.63 | 4.72 / 4.76 | 9.25 / 9.7 | 4.13 / 4.26 | 533 MB | - | 7,898 / 6,034 MB | image 1.2 |
| SmolVLM2 500M, CPU, Gentle (2) | 0.21 | 4.91 / 5.36 | 3.7 / 3.73 | 7.41 / 7.84 | 4.6 / 4.75 | 533 MB | - | 8,215 / 7,541 MB | image 1.1 |
| SmolVLM2 500M, CPU, Very light (1) | 0.24 | 7.72 / 8.79 | 7.83 / 8.11 | 14.41 / 15.05 | 6.4 / 6.52 | 533 MB | - | 7,790 / 6,188 MB | image 1.4 |
| SmolVLM2 500M, CPU, Very light (2) | 0.19 | 9.63 / 10.28 | 6.21 / 6.25 | 11.56 / 12.42 | 5.56 / 5.93 | 534 MB | - | 8,363 / 7,502 MB | image 2.2 |
| SmolVLM2 500M, Vulkan, Full | 0.54 | 3.11 / 3.53 | 1.38 / 1.42 | 2.57 / 3.11 | 1.33 / 1.51 | 1,029 MB | 663 MB shared | 7,446 / 6,559 MB | prepare 0.8, image 1.0 |
| SmolVLM2 500M, Vulkan, Gentle | 0.35 | 2.41 / 2.85 | 1.34 / 1.39 | 2.58 / 3.05 | 1.36 / 1.54 | 1,029 MB | 663 MB shared | 7,517 / 6,654 MB | start 0.5, image 1.0 |
| SmolVLM2 500M, Vulkan, Very light | 0.4 | 2.3 / 2.75 | 1.37 / 1.41 | 2.59 / 3.06 | 1.35 / 1.52 | 1,029 MB | 663 MB shared | 7,616 / 6,689 MB | image 1.0 |
| Qwen3-VL 2B, CPU, Full (1) | 2.45 | 8.42 / 12.31 | 5.43 / 5.48 | 9.67 / 17.76 | 5.19 / 8.12 | 1,736 MB | - | 7,661 / 5,144 MB | model 0.9, image 1.1 |
| Qwen3-VL 2B, CPU, Full (2) | 2.46 | 11.39 / 17.5 | 7.62 / 7.66 | 15.34 / 28.19 | 8.77 / 13.07 | 1,736 MB | - | 8,175 / 5,715 MB | start 0.7, model 0.5, image 1.2 |
| Qwen3-VL 2B, CPU, Full, low RAM (1) | 1.81 | 11.82 / 17.87 | 8.44 / 8.54 | 15.29 / 28.18 | 8.45 / 12.8 | 1,736 MB | - | 3,845 / 1,554 MB | start 0.7, image 1.3 |
| Qwen3-VL 2B, CPU, Gentle (1) | 1.23 | 7.01 / 10.42 | 5.53 / 5.61 | 9.65 / 17.43 | 5.31 / 8.24 | 1,736 MB | - | 7,633 / 5,032 MB | image 1.1 |
| Qwen3-VL 2B, CPU, Gentle (2) | 1.18 | 7.15 / 10.55 | 4.46 / 4.5 | 8.82 / 16.03 | 4.62 / 7.19 | 1,736 MB | - | 8,181 / 5,855 MB | start 0.7, image 1.1 |
| Qwen3-VL 2B, CPU, Gentle, low RAM (1) | 1.3 | 7.36 / 10.56 | 4.73 / 4.77 | 15.52 / 28.8 | 9.17 / 13.82 | 1,735 MB | - | 3,841 / 1,585 MB | image 1.3 |
| Qwen3-VL 2B, CPU, Gentle, low RAM (2) | 1.91 | 12.27 / 18.71 | 8.68 / 8.73 | 9.66 / 16.59 | 4.99 / 7.52 | 1,736 MB | - | 3,830 / 1,525 MB | start 0.8, image 1.2 |
| Qwen3-VL 2B, CPU, Gentle, low RAM (3) | 1.5 | 7.22 / 10.57 | 4.85 / 4.89 | 8.71 / 18.72 | 7.93 / 11.86 | 1,736 MB | - | 3,892 / 1,568 MB | image 1.3 |
| Qwen3-VL 2B, CPU, Very light (1) | 1.74 | 10.73 / 16.61 | 8.77 / 8.83 | 15.62 / 27.96 | 8.24 / 12.31 | 1,736 MB | - | 7,621 / 5,201 MB | image 1.3 |
| Qwen3-VL 2B, CPU, Very light (2) | 2.28 | 16.91 / 26.9 | 13.73 / 14.05 | 25.11 / 45.91 | 14.33 / 18.45 | 1,736 MB | - | 8,200 / 5,736 MB | start 0.7, model 0.5, image 1.4 |
| Qwen3-VL 2B, Vulkan, Full | 1.5 | 4.59 / 8.19 | 1.84 / 1.88 | 3.24 / 10.5 | 1.83 / 4.77 | 2,478 MB | 2,058 MB shared | 8,319 / 6,062 MB | image 2.3 |
| Qwen3-VL 2B, Vulkan, Gentle | 1.1 | 3.29 / 6.8 | 1.81 / 1.86 | 3.26 / 10.61 | 1.84 / 4.81 | 2,477 MB | 2,058 MB shared | 8,296 / 6,051 MB | image 1.6 |
| Qwen3-VL 2B, Vulkan, Very light | 1.55 | 4.14 / 7.62 | 1.75 / 1.8 | 3.18 / 10.38 | 1.86 / 4.81 | 2,478 MB | 2,074 MB shared | 8,353 / 6,057 MB | image 1.6 |

- **The 127 s case did not come back.** Qwen on the CPU with 3.8-3.9 GB free (3 runs at Gentle, 1 at Full,
  free memory down to 1,525-1,585 MB during the run) loaded in 1.3-1.9 s and gave its first word in 7.2-12.3 s;
  the longest time without progress in any phase was 1.3 s. Whether that is the normal memory / I/O priority or
  the warm file cache can't be told apart from these runs (the stalled run in the section under this one had the
  files cached too, but the PC was in use).
- **Longest without progress, per phase, over all 21 runs** (the bounds in `vlm.worker.PHASES` are next to them):
  start 0.75 s, prepare 0.83 s, photo 0.36 s, model 0.88 s, context 0.06 s, vision 0.25 s, image 2.3 s (Vulkan,
  whose prompt eval sends no "still computing"), answer 0.35 s; the longest photo eval in all was 25 s (Qwen, CPU,
  Very light, Compare). Bounds: 60 s for each step, 600 s cap on the photo eval, 120 s between two tokens.
- **Stop, from `Talker.cancel` to the worker's "cancelled"** (every run with `--stops`; min-max over runs):

  | phase stopped | SmolVLM2 CPU | SmolVLM2 Vulkan | Qwen CPU | Qwen Vulkan |
  |---|---|---|---|---|
  | model (llama's load) | (load done in 0.3 s: landed in vision) 0.011-0.084 | (landed in context / vision) 0.083-0.088 | 0.088-0.132 | 0.179-0.193 |
  | vision part (mtmd's load) | 0.047-0.075 | 0.062-0.089 | 0.160-0.312 | 0.218-0.253 |
  | reading the photo | 0.007-0.462 | 0.056-0.079 | 0.026-1.466 | 0.605-1.085 |
  | answering | 0.003-0.194 | 0.010-0.020 | 0.002-0.043 | 0.001-0.041 |
  | engine stop during the load (pause, memory, runtime swap), to the process's exit | 0.091-0.124 | 0.186-0.234 | 0.172-0.297 | 0.309-0.331 |

  The engine's stop never had to terminate the worker (exit code 0 every time). Reading the photo on Vulkan takes
  up to about 1 s to stop: the prompt eval there can't be aborted and runs to its end. A load stopped in "model"
  or "vision" leaves nothing loaded; one stopped while reading the photo keeps the model. Not stoppable at all:
  prepare, photo, context (each well under 1 s here).
- **Low memory.**
  - What the app says (`api.talk_assess`, the free-RAM fallback until PR #16) with the hog leaving 2,841 MB free:
    deeper "Not now: only 2.8 GB free, Qwen3-VL needs about 2.4 GB plus margin", quick allowed; with the PC
    itself at 233 MB free (a game running, no hog): both "Not now" (0.2 GB). At 3.8 GB both were allowed.
  - A load that runs out under the worker group's limit (`--alloc-limit-mb`, the limit set low and not raised):
    Qwen at 700 MB: llama's model load returned NULL and the job ended with the plain "Not enough memory right
    now (needs about 2.4 GB). Close something or try again later." in 0.8 s; the same worker then answered with
    the limit back up. SmolVLM2 at 300 MB: the model loaded, then ggml's `GGML_ASSERT(ctx->mem_buffer != NULL)`
    in the vision part's load ended the worker process (llama.cpp aborts; Python can't catch it): the job showed
    "The picture model stopped unexpectedly. Try again.", and the next question started a fresh worker and
    answered. In the app the group's limit is raised by the model's measured need before the load, so this needs
    Windows itself to run out of commit.
  - Nothing else was killed. Processes older than a minute that had ended by the end of a run: Windows' own
    short-lived ones (svchost.exe, WmiPrvSE.exe, audiodg.exe, backgroundTaskHost.exe) and, in 4 runs, a worker of
    the installed NOBAD Find (`--multiprocessing-fork`, which it releases when idle). The installed Find's main
    process ran through all the runs. The measuring script only ends its own worker group and hog.
- **Catalog** (`models.CATALOG` `timing`, from these runs only, low-RAM rows left out, as before: `load_s` the
  median of cold minus warm first word, `answer_s` fastest-slowest finished Ask / Compare / warm Describe):
  SmolVLM2 CPU Full 2 / 3-9, Gentle 1 / 3-10, Very light 3 / 5-16; Vulkan 2 / 1-4, 1 / 1-4, 1 / 1-4. Qwen CPU
  Full 3 / 5-29, Gentle 2 / 4-18, Very light 3 / 8-46; Vulkan 3 / 1-11, 1 / 1-11, 2 / 1-11. Very light on the CPU
  is still the only "Slower now" (Qwen 1.59x, SmolVLM2 1.75x). Run 2 of Qwen CPU at Full and at Very light was
  much slower than run 1 (a busier moment on the PC); every run is in the range. Memory unchanged within a few
  MB (Qwen's Vulkan graphics memory once 2,074 MB against the catalog's 2,062; its need is the 2,483 MB of system
  memory either way).
- Overhead of the callbacks (A/B against the previous `session.py`, SmolVLM2 first word, median of 3): CPU 3.91 /
  3.90 s new against 4.02 / 3.92 s old, Vulkan 1.33 / 1.33 s against 1.28 / 1.33 s: within the noise.

## 2026-11-22 (1.1.0): talk about a photo under the real limits (Full, Gentle, Very light)

The talk worker runs in Find's worker group, so it gets the governor's CPU hard cap on that group (Full none,
Gentle 35 %, Very light 15 % of all 16 threads, `governor.CPU_CAP`), efficiency mode (EcoQoS) at Very light
(`governor._eco_workers`), and its own idle CPU / low memory / very low I/O priority (`winapi.worker_priority`).
The rows below were measured with all of that in force (the row under this one was not: no cap, no EcoQoS).
Script: `tools/measure_talk.py` (dev only): the real `vlm.worker.Talker` and its spawned worker, inside this run's
own worker group (`jobs.setup`, never a running Find's), the level's cap set on the group and checked
(`Job.cpu_cap`), EcoQoS on the worker at Very light (checked inside the group, like the governor), the group's
memory limit raised by the model's need (`jobs.set_talk_allowance`). Only the talk worker was in the group; in
the app, indexing workers would share the cap. Same PC, settings, photos and jobs as the row under this one;
runtime folders with only the pinned DLLs (I2). Times are first word / finished answer, in seconds; "longest wait"
is the longest gap between two pieces of progress in the run (the app ends a worker after `vlm.worker.LOAD_S` /
`ANSWER_S`, 120 s, without any). The reference PC was in normal use (NOBAD Find and other programs running,
3.6-5.4 GB free), so the processor rows were run two to four times; every run is listed.

| model, runtime, level (run) | Describe (cold) | Ask | Compare | Describe (warm) | longest wait | peak private | graphics |
|---|---|---|---|---|---|---|---|
| SmolVLM2 500M, CPU, Full (1) | 7.4 / 7.8 | 3.7 / 3.7 | 6.8 / 7.1 | 3.6 / 3.7 | 6.7 s | 533 MB | - |
| SmolVLM2 500M, CPU, Full (2) | 5.8 / 6.2 | 3.3 / 3.4 | 10.0 / 10.4 | 3.6 / 3.7 | 10.0 s | 533 MB | - |
| SmolVLM2 500M, CPU, Gentle (1) | 4.6 / 5.0 | 3.9 / 3.9 | 7.3 / 7.7 | 3.8 / 3.9 | 7.2 s | 533 MB | - |
| SmolVLM2 500M, CPU, Gentle (2) | 5.8 / 6.2 | 3.8 / 3.9 | 9.9 / 10.3 | 4.1 / 4.2 | 9.9 s | 533 MB | - |
| SmolVLM2 500M, CPU, Very light (1) | 9.1 / 9.8 | 8.9 / 8.9 | 12.6 / 14.2 | 7.7 / 7.9 | 12.5 s | 533 MB | - |
| SmolVLM2 500M, CPU, Very light (2) | 6.7 / 7.3 | 8.9 / 8.9 | 13.0 / 14.1 | 5.8 / 5.9 | 12.7 s | 533 MB | - |
| SmolVLM2 500M, Vulkan, Full | 2.1 / 2.5 | 1.3 / 1.3 | 2.4 / 2.9 | 1.3 / 1.4 | 2.4 s | 1,032 MB | 665 MB shared |
| SmolVLM2 500M, Vulkan, Gentle | 2.1 / 2.5 | 1.3 / 1.3 | 2.4 / 2.9 | 1.3 / 1.4 | 2.4 s | 1,031 MB | 665 MB shared |
| SmolVLM2 500M, Vulkan, Very light | 2.2 / 2.6 | 1.3 / 1.3 | 2.4 / 2.9 | 1.3 / 1.4 | 2.4 s | 1,031 MB | 665 MB shared |
| Qwen3-VL 2B, CPU, Full (1) | 20.1 / 26.3 | 5.4 / 5.5 | 14.5 / 21.6 | 7.3 / 10.5 | 14.4 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Full (2) | 17.2 / 20.5 | 5.1 / 5.1 | 12.0 / 20.0 | 7.0 / 9.5 | 11.9 s | 1,735 MB | - |
| Qwen3-VL 2B, CPU, Full (3) | 16.3 / 19.5 | 4.4 / 4.5 | 8.7 / 15.7 | 4.7 / 7.3 | 10.6 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Gentle (1) | 17.9 / 23.2 | 4.5 / 4.6 | 9.1 / 16.3 | 4.8 / 7.3 | 11.3 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Gentle (2) | 146.6 / 149.9 | 4.7 / 4.7 | 8.5 / 16.0 | 4.8 / 7.2 | 127.2 s | 1,735 MB | - |
| Qwen3-VL 2B, CPU, Gentle (3) | 50.3 / 56.6 | 6.6 / 6.7 | 12.9 / 25.5 | 7.8 / 11.5 | 38.6 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Gentle (4) | 6.4 / 9.7 | 7.3 / 7.4 | 15.9 / 28.9 | 8.7 / 13.9 | 15.8 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Very light (1) | 20.9 / 29.5 | 7.7 / 7.8 | 18.1 / 30.6 | 10.2 / 14.4 | 17.8 s | 1,736 MB | - |
| Qwen3-VL 2B, CPU, Very light (2) | 20.1 / 25.3 | 7.4 / 7.4 | 16.9 / 31.6 | 10.8 / 14.9 | 16.8 s | 1,735 MB | - |
| Qwen3-VL 2B, Vulkan, Full | 14.6 / 18.0 | 1.7 / 1.7 | 3.2 / 11.5 | 1.8 / 4.9 | 11.2 s | 2,482 MB | 2,062 MB shared |
| Qwen3-VL 2B, Vulkan, Gentle | 13.0 / 16.2 | 1.7 / 1.7 | 3.1 / 10.2 | 1.8 / 4.8 | 11.0 s | 2,482 MB | 2,062 MB shared |
| Qwen3-VL 2B, Vulkan, Very light | 13.1 / 16.5 | 1.7 / 1.7 | 3.1 / 10.3 | 1.8 / 4.8 | 11.2 s | 2,482 MB | 2,062 MB shared |

- **Very light slows the processor runtime, nothing else does.** 15 % of 16 threads is about 2.4 threads for
  llama.cpp's 4, plus efficiency cores: SmolVLM2's Ask took 8.9 s instead of 3.3-3.9 s, Qwen's Compare about 31 s
  instead of 16-22 s. Gentle (35 %, about 5.6 threads) leaves room for the 4 threads and measured the same as
  Full within this PC's noise. On Vulkan the graphics do the work and no level changed the times.
- **No answer was ended or slow enough to be.** Every job finished; the longest gap in an answer was 17.8 s
  (Qwen, CPU, Very light, a Compare's first word). The one long wait was a cold load: Qwen on the CPU at Gentle,
  run 2, took 146.6 s to its first word with 127.2 s without progress, over `LOAD_S` (in the app the worker
  would have been ended as "stopped responding"); run 3, 50 s. Both came while this PC's free memory was low
  (run 3 started at 3.6 GB free); runs 1 and 4 at Gentle, every Full and every Very light run loaded in 6-21 s.
  It looks like reading the 1.1 GB model at very low I/O and memory priority while memory is short, not the CPU
  cap (the same cap at Very light never did it), but that wasn't proven: an open question, see below.
- **Catalog** (`models.CATALOG` `timing[runtime][level]`, `models.talk_timing`): `load_s` = the median over the
  runs of (cold first word - warm Describe's first word); `answer_s` = (fastest, slowest) finished Ask, Compare or
  warm Describe over all runs. SmolVLM2 CPU: Full 3 / 3-11, Gentle 1 / 3-11, Very light 1 / 5-15; Vulkan 1 / 1-3
  at every level. Qwen CPU: Full 12 / 4-22, Gentle 28 / 4-29, Very light 10 / 7-32; Vulkan: Full 13 / 1-12,
  Gentle and Very light 11 / 1-11. `vision_state` sends the figures for the level now and the runtime this PC
  would use; the UI's "Loading … about N s" and the Deeper line's "about N-M s" are these.
- **"Slower now"**: `vision_state`'s `slow_note` ("Slower now: NOBAD Find is in Very light mode.") when the
  middle of a level's answer range is at least 1.4 times Full's (`models.SLOW_FACTOR`): the processor at Very
  light (SmolVLM2 1.43x, Qwen 1.5x), never Gentle or Vulkan. The UI shows it on the Deeper line and under a
  running answer.
- Memory and answers as in the row under this one (SmolVLM2 533 / 1,031-1,032 MB, Qwen 1,735-1,736 / 2,482 MB; the
  sign read as "EXIT" in every run).
- Runtime on disk (I2, `llama_pins.py`): only the DLLs Find loads are pinned and unpacked: CPU 19 DLLs,
  30,034,944 bytes (29 MB); Vulkan 20 DLLs, 74,901,504 bytes (71 MB). The 9 dropped (llama-server-impl,
  llama-cli-impl, llama-common and the other tools' DLLs) were 21.8 MB per runtime; the PE import tables (pefile)
  of the kept DLLs name nothing outside the kept set, and the real-runtime tests pass on folders with only these.
  The downloads (the zips, 24 / 37 MB) are unchanged.
- Open: whether a cold load can stall past `LOAD_S` for a reason Find controls (worker I/O priority while memory
  is short); a discrete graphics card; a PC with less memory.

## 2026-11-22 (1.1.0): talk about a photo through the real worker

Describe, Ask and Compare through `vlm.worker.Talker` and its spawned talk worker process (not the llama.cpp
CLI), on the reference PC (i5-12500H, 16 threads, 15.7 GB, Intel Iris Xe with 128 MB of its own memory: the
graphics share system RAM), llama.cpp b12602, the catalog's talk settings (512 px side, n_ctx 1024, n_ubatch 256,
flash attention, q8_0 KV; Qwen `image_max_tokens` 160), greedy. NOBAD Find itself was running beside it
(about 1 GB); 4.8-5.3 GB was free before each run. One fresh worker per row; its jobs in order: **Describe**
dog-01.jpg (cold: starts the worker, loads the model, answers), **Ask** "What's written here?" on sign-01.jpg,
**Compare** dog-01.jpg with dog-02.jpg, **Describe** cat-01.jpg (warm), photos from the Wikimedia Commons set of
`tools/vision_bench`. Times are seconds from the question to its first word / to the finished answer. Peak
private = the worker's peak committed memory (PeakPagefileUsage); working set sampled every 0.25 s; graphics =
the PDH counters `\GPU Process Memory(pid_*)\Dedicated Usage` + `Shared Usage`, peak.

| model, runtime | Describe (cold) | Ask | Compare | Describe (warm) | peak private | peak working set | graphics |
|---|---|---|---|---|---|---|---|
| SmolVLM2 500M, CPU | 6.5 / 6.9 | 3.3 / 3.3 | 6.8 / 7.2 | 3.8 / 3.9 | 535 MB | 610 MB | - |
| SmolVLM2 500M, Vulkan | 2.4 / 2.8 | 1.2 / 1.3 | 2.4 / 2.9 | 1.3 / 1.4 | 1,031 MB | 784 MB | 665 MB shared |
| Qwen3-VL 2B, CPU | 16.7 / 20.0 | 6.9 / 7.0 | 9.7 / 19.6 | 4.6 / 7.2 | 1,736 MB | 2,373 MB | - |
| Qwen3-VL 2B, Vulkan | 14.9 / 18.5 | 1.7 / 1.7 | 3.2 / 12.0 | 1.8 / 5.1 | 2,483 MB | 2,250 MB | 2,062 MB shared |

- Answers: both models read the sign as "EXIT". SmolVLM2's describe and compare are short and plain ("There is a
  cat walking on the snow."; it called both dog-park signs "a sign with a dog on it"); Qwen's are long and
  specific (it named the park on the sign, slightly misspelled, the flag and the silos).
- Loading: Qwen's first word comes 13-15 s after the first question (start + load + the first picture), 2-5 s after
  later ones; SmolVLM2's 2.4 s (Vulkan) / 6.5 s (CPU) and then 1-4 s. (These runs had no CPU cap; the UI's
  "Loading … about N s" now comes from the catalog's per-level figures in the section above, sent by
  `vision_state` as `load_s`.)
- Memory: on Vulkan with shared-memory graphics the worker commits MORE system RAM than its graphics memory (Qwen
  2,483 vs 2,062 MB), so the need passed to the worker on Vulkan is `max(ram_mb, vram_mb)` (`models.talk_need_mb`,
  on every graphics card: shared and dedicated memory can't be told apart reliably). Catalog, from these rows: `ram_mb` = the biggest
  system-memory figure of the model's CPU and Vulkan runs (SmolVLM2 1,031, Qwen 2,483; was 942 / 2,411 from the
  CLI at `-c 4096`), `vram_mb` = its graphics memory on Vulkan (665 / 2,062; was 658 / 2,060). Qwen on Vulkan
  fits the worker group's commit limit (base 4,019 MB + the need) with room to spare.
- Not measured: a discrete graphics card (dedicated memory), and a PC with less memory.

## 2026-11-22: review fixes to photo ranking v2

Found in review; fixed in `nobadfind/query.py` (intent) and `nobadfind/search.py` (tests in `tests/test_photo.py`).

1. **"photos", "list all photos", "show me pictures" list every image again.** v2 had asked SigLIP the word
   "photos". Collection intent now lives in query interpretation: `query.parse` sets `q.collection` (pictures
   asked for as such: listed with the filters, not ranked) and `q.visual` (a clean description for the photo
   model, "" when there is nothing to describe). "screenshot" counts as description ("show screenshots" is
   screenshot retrieval); "photo/picture/image/pic" don't.
2. **SigLIP gets the raw text (`q.visual`) only when it is a plain description:** nothing in it was read as a date, place,
   folder, `dirs`, `here`, size, sort, extensions or Hinglish. The photo model is English-only, and those words go
   to filters. Otherwise it gets the meaning words, as v1.
3. **Loose meaning is dropped only for a photo's OCR text, never its name,** and only when a photo model is there
   (without one, OCR is all there is).
4. **Known, not changed:** with no floors, a keyword search ("lease") also lists up to 100 weak photos after the
   sure results. Maintainer decision 2026-11-22: don't restore global floors; measure admission policies A
   (current), B (minimum visual confidence for standalone visual matches), C (evidence-aware: a weak visual
   match only with a filename, OCR or metadata signal) on a fresh held-out set (nDCG@10, recall@10,
   precision@10, weak results after sure ones, keyword-only false positives, no-answer false positives,
   filename-only and OCR-only regressions). C is the favoured candidate.
5. **Download size:** the photo-model notice gives only what is still to download (`models.missing_mb`): an
   existing SigLIP 2 user is asked for an update of 177 MB, not 481 MB.

Re-measured after the fixes (final code): the 556-photo / 155-search set is unchanged search by search (0 of 146 searches changed; training 0.731, held-out 0.712 nDCG@10); the mixed-file benchmark is identical with v2 on and rolled back (keywords 1.0, photo 1.0, meaning MRR 0.495, all 0.951; no question changed). An intermediate run had shown meaning 0.533 vs 0.495; it did not hold on the final code.

## 2026-11-22: SigLIP 2 "best" tier re-pinned: fp16 vision + 8-bit text (maintainer decision)

Catalog `siglip2-base`: vision `onnx/vision_model_fp16.onnx` (186,039,516 bytes, SHA-256 a1959f7b…aabd95,
rev ba1f3b08), text unchanged (8-bit), `"vectors": 2` so photo vectors from the old 8-bit vision are made again
(`models.vector_tag` -> meta `pvec_model` "siglip2-base#2"); SigLIP base users keep their vectors. Download
393 -> 481 MB. Default and balanced tier stay on SigLIP base.

Resources on the reference PC, quiet (no other job), 4 threads, private memory of the process:

| | vision RAM after 20 photos | photos/s | question (text) RAM | question p50 |
|---|---|---|---|---|
| SigLIP base (8-bit) | 148 MB (117 MB, arena off) | 4.0 | 149-156 MB | 94-99 ms |
| SigLIP 2, fp16 vision, default session | **1,275 MB** | 3.4 | - | - |
| **SigLIP 2, fp16 vision, basic opt + arena off (shipped)** | **207 MB** | **2.9** | 368-372 MB | 89-124 ms |
| SigLIP 2, fp32 vision (not shipped), arena off | 370 MB | 4.6 | - | - |

- fp16 and fp32 vision give the same vectors (cosine 1.00000 on 50 photos), so the held-out gain (+0.035
  nDCG@10) holds for either; fp16 is shipped as the lighter one (background indexing), fp32 is the faster option
  for a hardware-adaptive profile later.
- `photo.open_session`: tries the full optimizer, and only on its `GetIndexFromName` failure reopens with basic
  optimization and the memory arena off (the arena grew to 1.3 GB with basic optimization, measured).
- `tests/test_siglip2_real.py` (runs with `NOBAD_FIND_SIGLIP2_DIR`): the pinned files' vectors for three drawn
  pictures must be within cosine 0.995 of stored fp32 references. The old 8-bit vision fails it (0.92 / 0.88 /
  0.92); fp16 passes (1.000).
- SigLIP 2's question encoder holds 368 MB (its 256k-word vocabulary); arena off doesn't change that.

## 2026-11-22: caption enrichment, pre-registered held-out test (`tools/heldout_photo_rank.py`): FAILED

Rules and candidates committed before grading (143b077). SigLIP base features; captions from SmolVLM2-500M and
Qwen3-VL-2B (Qwen with `-c 1024 -ub 256` for the new photos) on all 556 photos. 101 training searches,
45 held-out, 4 held-out negatives.

| | train CV nDCG@10 | **held-out nDCG@10** | held-out recall@10 |
|---|---|---|---|
| SigLIP alone | - | 0.723 | 0.815 |
| H0 calibrated SigLIP + b/w rule | 0.756 | 0.716 | 0.807 |
| H1 + SmolVLM2 captions | 0.757 | 0.703 | 0.769 |
| **H2 + Qwen captions (chosen by training CV)** | **0.773** | **0.733** | 0.794 |
| H3 query-dependent weights | 0.668 | 0.704 | 0.804 |

- **H2 vs SigLIP alone, held-out: +0.010 (CI -0.037 to +0.058), 21 better / 19 worse: not supported.**
- Category regression: similar scenes -0.059 (CI -0.113 to -0.004). Text +0.124 and mood +0.080 (CIs cross 0).
- Negatives: H2 more confident on searches with no answer (top-3 calibrated probability 0.321 vs H0 0.175).
- **Decision (maintainer rules): captions stay out of the default ranking.**
- H3 is far below H0 even in training CV (0.668 vs 0.756). Cause found: the Newton solver in
  `nobadfind/hybrid.py` diverged on the sparse `words` channel (89 % zeros, 12 distinct values; one weight swung
  between 81 and -391). That killed the channel in H1 and H2 (and in the 2026-11-21 step-1 fits) and wrecked one
  H3 fold (0.359). Fixed 2026-11-22 with a backtracking line search (`tests/test_hybrid.py`). The table above
  is the pre-registered run, with the broken solver.
- Qwen peak shared GPU memory read 7,347 MB over this 252-photo run (2,060 MB in the 10-photo test with the
  same flags); cause not established yet (growth over the run, or the counter including another process).

**Diagnostic re-run with a converging solver (by a reviewer; NOT pre-registered):**

| | train CV nDCG@10 | held-out nDCG@10 |
|---|---|---|
| H0 | 0.756 | 0.716 |
| H1 | 0.750 | 0.711 |
| H2 | 0.786 | 0.749 |
| H3 | 0.773 | 0.707 |

- H2 vs SigLIP alone, held-out: +0.026 (CI -0.015 to +0.073). Still fails the CI rule, so the decision stands
  (captions stay out). The pre-registered run understated the effect.
- The held-out searches have now been used twice; a new test of captions or H3 needs fresh held-out searches.

**Review notes (2026-11-22):**
- H0 is not "SigLIP + b/w rule" only: it also has the OCR channels on searches asking for text.
- The negatives rule compared absolute probabilities across candidates, with a base rate on a different label
  scale. So "H2 more confident on negatives" is weak evidence: H2's negatives/real ratio is 0.58, H0's 0.61.
- Category CIs rest on 3-8 searches each, with no multiple-comparison correction (the "similar scenes"
  regression is n=5).

## 2026-11-22: SigLIP 2 base vs SigLIP base, side by side (separate indexes; nothing replaced)

Same 556 photos / 155 searches, each model in its own throwaway index (`eval_photo_search --photo-model
siglip2-base [--photo-dir DIR]`). Same 224 px squeeze, same question templates. Reference PC, CPU, measured
while a Qwen caption job ran on the GPU (absolute times inflated for every row).

| SigLIP 2 files (onnx-community rev ba1f3b08) | train nDCG@10 vs base | **held-out nDCG@10 vs base** | embed 556 photos |
|---|---|---|---|
| **pinned today**: 8-bit text + 8-bit vision | **-0.133** (CI -0.177..-0.090) | **-0.179** (CI -0.248..-0.114) | 148 s |
| fp16 text + fp16 vision | +0.032 (+0.009..+0.057) | +0.025 (-0.001..+0.053) | 218 s; search 449 ms p50 (fp16 text slow on CPU) |
| **8-bit text + fp16 vision** | **+0.038** (+0.020..+0.057) | **+0.035 (+0.005..+0.066)** | 242 s |
| SigLIP base (default) | 0.756 | 0.723 | 151 s |

- **The pinned SigLIP 2 is broken by its 8-bit vision model:** zero-shot margins (4 photos, cat/dog/laptop/bird)
  8-bit+8-bit 0.040, fp16 text only 0.045, **fp16 vision 0.065**, both fp16 0.071, SigLIP base 0.063.
  The "best" tier (`PHOTO_CHOICE["best"] = "siglip2-base"`) therefore gives WORSE photo search than the default
  today. *Superseded: the best tier was re-pinned to fp16 vision + 8-bit text the same day (see "SigLIP 2 'best'
  tier re-pinned" above).*
- fp16 exports load only with `GraphOptimizationLevel.ORT_ENABLE_BASIC` (ONNX Runtime 1.27's full optimizer
  fails in `GetIndexFromName`); inputs and outputs stay float32.
- **8-bit text + fp16 vision passes every held-out rule:** SigLIP alone +0.035 (CI above 0); in Find's v2
  pipeline 0.712 -> 0.742 (+0.030, CI +0.001..+0.060); recall@10 +0.028 (CI -0.004..+0.065; a reviewer
  recomputed +0.026, CI -0.006..+0.063, over 44 searches: the discrepancy is not resolved yet; recall averages
  cover fewer searches than nDCG, because searches with only grade-1 photos have no recall). Held-out per
  category: text +0.099 (CI +0.050..+0.155), screenshots +0.100, mood +0.078, people +0.015, relationships
  +0.008, attributes -0.005, scenes -0.010, ambiguous -0.033 (n=3, CI -0.243..+0.150): no regression by the
  rule. Negatives: top-1 similarity gap real-vs-negative 0.059 (base 0.058): not more confident.
- Chosen by the training searches too (0.794 vs 0.788 for fp16+fp16), so the held-out set didn't pick it.
- Cost: vision file 177 MB (SigLIP base 99 MB), text 270 MB (111 MB); embedding about 1.6x slower.

## 2026-11-22: photo set expanded to 556 photos / 155 searches; v2 checked on held-out searches

The set (`%USERPROFILE%\vbench\search`):
- **Searches:** 95 new ones (people and actions, relationships, mood, English/German/Hindi text, screenshots,
  attributes, similar scenes, ambiguous, 8 negatives).
- **Photos:** 251 new photos from Wikimedia Commons; 556 usable after 4 were left out (two historical nudes,
  left out as a conservative call; one duplicate; one flagged unusable).
- **Grading:** 15 grading agents, each photo graded against every search.
- **Split:** fixed before any grading (`split.json`, seed 20261122). Held-out = half of each category of the new
  searches (49); the original 60 searches can't be a test (v2 was designed on them), so they are training.
- 35 non-negative searches have fewer than 3 clearly relevant photos; they still count (grade 1 scores in nDCG)
  but are noisier.

**Bug found and fixed (v2 only):** when every word reads as a file kind ("a screenshot of program code" ->
kinds code + image, no words left), photos were never asked and all images were listed newest first. In v2,
SigLIP's own question decides. Found on training searches q114/q116.

nDCG@10 (negatives excluded; questions as typed through `search.search`):

| | all 146 | training 101 | **held-out 45** |
|---|---|---|---|
| v1 (rollback) | 0.628 | 0.642 | 0.596 |
| **v2 (default, with the fix)** | **0.724** | **0.731** | **0.712** |
| SigLIP alone | 0.745 | 0.756 | 0.723 |

(Review note 2026-11-22: the "all 146" column actually averages 147 searches: it includes the negative q155,
which has grade-1 photos. Over the true 146: SigLIP alone 0.746, v2 0.725.)

- **v2 gains +0.116 over v1 on held-out searches it never saw.**
- Mixed-file regression (`eval_search`), v2 vs rollback: identical (keywords 1.0/1.0, photo 1.0/1.0, meaning
  MRR 0.495, all 0.951); no question changed rank.
- Search time measured while a caption job ran on the same PC: v1 125 / v2 127 ms p50. Not comparable with
  the quiet-PC 2.8 / 3.8 ms; re-measure idle.

## 2026-11-22: Qwen3-VL-2B memory (llama.cpp flags only, 10 photos, Iris Xe Vulkan)

On top of Qwen's "fastest" settings; same two caption questions; RAM = peak private, GPU = peak shared (separate
counters that overlap on an integrated GPU; never added).

| Flags | peak RAM | peak GPU | compute a photo | answers same as A |
|---|---|---|---|---|
| A: as in the 308-photo run (`-c 4096`, ubatch 512) | 3,056 MB | 2,532 MB | 5.7 s | - |
| **B: `-c 1024 -ub 256`** | **2,411 MB (-21 %)** | **2,060 MB (-19 %)** | 5.5 s | **10/10 captions, 10/10 objects** |
| C: B + `-lm none` (no memory map) | 2,415 MB | 2,053 MB | 5.0 s | 10/10 |
| D: B + `--no-mmproj-offload` (vision encoder on CPU) | 2,378 MB | 1,588 MB | 8.3 s | 6/10 captions |
| E: B + `--no-host` | 3,820 MB | 1,835 MB | 4.9 s | 10/10 |

- **B is free:** about a fifth less of both, identical answers, same speed. Qwen's talk settings should carry it.
- D trades 0.5 GB of GPU memory for 50 % more time and different answers: only for a GPU short of memory.
- E moves memory from the GPU to process RAM (worse overall on a shared-memory GPU).

## 2026-11-22: memory and speed of photo ranking v2, and leaner caption runs

**v2 adds no model and no memory.** What a photo search uses, measured on the reference PC:
- SigLIP text encoder (`text.onnx`, 111 MB file): **+148 MB private** when loaded, +156 MB after 60 questions;
  96 ms a new question (p50), cached after. It sits in `embed.Lazy` (released when idle). ONNX Runtime's
  `enable_cpu_mem_arena=False` / `enable_mem_pattern=False` saved nothing (+151 / +149 MB) and were slower
  (113 / 203 ms): not used.
- Photo vectors: float16, 768 values = 1.5 KB a photo (10,000 photos ~15 MB); scored in blocks, and a 64-number
  first pass from 20,000 photos up, so the whole matrix is never converted at once.
- Search time (`eval_photo_search --variants`, questions cached as while typing): today p50 2.8 ms (max 4.7),
  **v2 p50 3.8 ms** (max 120 ms, one search). Today's speed came from its floors: a median of **6** photos
  returned per search, v2 returns the full 60.

**Captions with less memory (SmolVLM2, 20 photos, llama.cpp flags only):** `-c 1024 -fa on -ctk q8_0 -ctv q8_0
-ub 256` instead of `-c 4096`: peak private RAM 1,138 -> **942 MB (-17 %)**, GPU shared 848 -> **658 MB (-22 %)**,
same speed (2.92 s a photo); 14 of 20 answers identical, the other 6 differ in small details (8-bit cache). Use
for background captions if captions ship.

## 2026-11-22: hybrid photo search, step 2: Qwen3-VL-2B captions vs SmolVLM2-500M, like for like

Same 308 photos, same two questions (one-sentence caption, 48 tokens; object list, 40 tokens; repeat penalty
1.3), same 60 searches, same channels and 5-fold cross-validation over searches (`tools/fit_hybrid.py --facts F
--report`). Iris Xe Vulkan, llama.cpp b12602. Qwen with its Phase 0 "fastest" settings (512 px, <= 160 image
tokens, flash attention, 8-bit KV cache). Memory sampled every 0.5 s by the vision bench's probes; process RAM
(private) and GPU memory (shared, as Windows counts it on the Iris Xe) are separate counters: on an integrated
GPU the shared pool is system memory too, so the two overlap and must not be added.

| Captions from | compute a photo p50 / p90 | 10,000 photos | peak private RAM | peak GPU (shared) |
|---|---|---|---|---|
| SmolVLM2-500M Q8_0 | 3.0 / 3.5 s | ~8.4 h | 1,138 MB | 848 MB |
| Qwen3-VL-2B Q4_K_M | 5.1 / 6.6 s | ~14 h | 3,056 MB | 2,532 MB |

(Wall time 5.4 / 11.0 s: llama-mtmd-cli reloads the model per question; the product keeps it loaded.)

nDCG@10 / recall@10 by kind of search (searches better/worse than SigLIP alone):

| Kind of search (n) | SigLIP alone | v2 | + SmolVLM2 captions | + Qwen captions |
|---|---|---|---|---|
| people and actions (17) | 0.746 / 0.832 | 0.755 | 0.806 / 0.862 (11/5) | **0.839 / 0.891 (14/3)** |
| relationships (14) | 0.771 / 0.851 | 0.781 | 0.827 / 0.895 (9/4) | **0.853 / 0.917 (12/2)** |
| ambiguous / mood (4) | 0.648 / 0.807 | 0.648 | 0.658 / 0.782 (2/2) | **0.758 / 0.829 (3/1)** |
| objects (39) | 0.876 / 0.908 | 0.870 | 0.874 / 0.897 (13/14) | 0.887 / 0.909 (16/14) |
| text-heavy (8) | **0.875 / 0.902** | 0.737 | 0.819 / 0.885 (1/5) | 0.803 / 0.910 (1/4) |
| screenshots and documents (3) | **0.815 / 0.850** | 0.482 | 0.795 / 0.833 (1/2) | 0.720 / 0.917 (0/1) |
| Hindi signs (1) | 0.752 / 0.667 | 0.626 | 0.659 / 1.0 | 0.728 / 1.0 |
| black and white (1) | 0.907 / 0.900 | 0.907 | 1.0 / 1.0 (saturation rule) | 1.0 / 1.0 (saturation rule) |
| **all (60)** | 0.864 / 0.913 | 0.840 | 0.871 / 0.906 (25/22) | **0.884 / 0.926 (28/19)** |

- **Against SigLIP alone (the baseline and fallback), neither passes:** SmolVLM2 +0.007 nDCG@10 (95 % CI -0.016
  to +0.029), Qwen +0.020 (CI -0.006 to +0.046). Against v2, Qwen +0.044 (CI +0.007 to +0.091), but v2 is the
  live mixed-file pipeline; SigLIP alone is the fair bar for a photos-only ranking.
- **Where captions help is consistent across both models, more with Qwen:** people and actions +0.093,
  relationships +0.082, mood +0.110 nDCG@10 over SigLIP alone ("a woman smiling" +0.29, "feeling lonely" +0.25,
  "people dancing" +0.25).
- **Where they hurt, also consistent:** text-heavy -0.07, screenshots -0.10 ("a screenshot ..." -0.28, "a sign
  with writing on it" -0.24). SigLIP alone stays best for writing; a one-sentence caption says less about it.
- Hindi: no model's reading of Hindi is used in any channel (captions only describe; the OCR channel is Windows
  OCR). PaddleOCR Devanagari is not in this run yet. Qwen also invents text and people (an empty bench: "a red
  sign that reads 'This seat is closed'", objects "bench, person, animal"; the sign says "Help Save Lives").
- One search per kind for Hindi and black and white: too few to conclude anything about those two.

## 2026-11-21: photo ranking v2 (fix the existing ranking first; flag `NOBAD_FIND_PHOTO_V2=1`, off by default)

*Superseded: v2 is on by default since 2026-11-22 (maintainer); rollback `NOBAD_FIND_PHOTO_V2=0`. See the
556-photo section and the review fixes above.*

Same 308 photos / 60 searches (`tools/eval_photo_search.py --variants`, one index build, each change measured
alone). Diagnosis of today's 0.755 against SigLIP alone 0.864 (nDCG@10):

| Change (alone) | nDCG@10 | recall@10 |
|---|---|---|
| today | 0.755 | 0.780 |
| no photo score floors | **0.815** | **0.871** |
| SigLIP reads the whole description | 0.767 | 0.795 |
| no "sure first" reorder / no best guess | 0.752 / 0.755 | 0.780 / 0.780 |
| photo list alone in the fusion (measurement only) | 0.754 | 0.773 |

- **Floors were the main damage.** SigLIP similarities run 0.02-0.08 for right photos; `PHOTO_MIN` 0.04 and
  the relative floors dropped true matches (two of four coffee cups at 0.030/0.033).
- **Loose OCR meaning was the rest:** of the "text has a loosely related meaning" results in the top 10, 38 of
  44 were wrong (garbled stadium-advert text matching gardens, boats, calm lakes).
- The query parser drops kind words before SigLIP sees them ("a screenshot of a phone" -> "phone") and reads
  "a handwritten note" as text documents only (no photo can match: the one empty search). Not changed: open item.

**v2** = no photo floors (low photos kept in SigLIP's order, shown as less sure after the sure results) + SigLIP
asked the whole description when it has no date/place/folder words + a photo's OCR text counts as a meaning
match only when at least "related" (0.38, the existing label threshold; exact words still count).

| Ranking | nDCG@10 | recall@10 | worse than SigLIP alone |
|---|---|---|---|
| today | 0.755 | 0.780 | 43 searches |
| **v2** | **0.840** | **0.895** | 6 |
| SigLIP alone (baseline and fallback) | 0.864 | 0.913 | - |

- v2 vs today, paired per search: **+0.086 nDCG@10 (bootstrap 95 % CI +0.056 to +0.119), 41 better, 4 worse.**
- v2 vs SigLIP alone: -0.024 (CI -0.064 to 0.000); the empty "handwritten note" search alone is -0.017.
- Mixed-file regression check (`tools/eval_search.py`, documents + look-alike names + photos), v2 off / on:
  keywords recall@1 1.0 / 1.0, photo 1.0 / 1.0, meaning MRR 0.495 / 0.495, all 0.951 / 0.951: no change.
  (An earlier run's meaning 0.529 was run-to-run variation: the corpus is regenerated with fresh dates.)

## 2026-11-21: hybrid photo search, step 1: calibrated channels with SmolVLM2-500M captions

`python tools/fit_hybrid.py <set>`, same 308 photos and 60 searches. Captions and object lists from SmolVLM2-500M
Q8_0 on Iris Xe Vulkan (two short questions, 48/40 tokens, repeat penalty 1.3): **3.0 s compute a photo** (5.4 s
wall with llama-mtmd-cli reloading the model each run), 308/308 without errors. Channels calibrated per channel
(Platt, log-odds over the base rate, missing = 0) and weighted by logistic regression; 5-fold cross-validation
over SEARCHES (weights never see the searches they're scored on).

| Ranking | nDCG@10 | recall@10 |
|---|---|---|
| Find today | 0.755 | 0.780 |
| SigLIP alone | 0.864 | 0.913 |
| SigLIP + caption + objects + words | 0.868 | 0.902 |
| + black-and-white rule + text channels for searches asking for writing | **0.874** | 0.908 |
| + every channel weighted apart for searches asking for writing | 0.871 | 0.906 |

- **Not a real gain yet:** paired per search against SigLIP alone, nDCG@10 +0.007 (bootstrap 95 % CI -0.016 to
  +0.029; 25 searches better, 22 worse), recall@10 -0.007. **Gate not passed; not wired into search.**
- Captions help people and actions: "someone reading a book" +0.19, "people dancing" +0.19, "someone sitting
  alone" +0.18, "a woman smiling" +0.15; by kind: actions 0.77 -> 0.83, mood 0.65 -> 0.68.
- They hurt screens and text: "a screenshot ..." -0.26, "a restaurant menu" -0.22, frustrated laptop -0.19.
  SigLIP base already reads signs well; Windows OCR found text in only 37 of 308 photos, so the OCR channels got
  ~0 weight.
- Black and white: mean HSV saturation < 30 marks every black-and-white/sepia photo graded relevant (a rule, not
  learned: one judged search asks for it). Photo-type searches 0.815 -> 0.847 with it.
- **"Facts in one pass" fails with SmolVLM2-500M:** asked for a 7-line CAPTION/OBJECTS/... format (with and
  without a worked example) it echoed the template or wrote free prose, looped on a Hindi sign
  ("kalalakalala..." to the token limit) and invented a green tree in a black-and-white photo. Two short
  questions give usable answers.

## 2026-11-21: photo search baseline (hybrid photo search, step 0)

`python tools/eval_photo_search.py <set>`: 308 openly licensed Wikimedia Commons photos, 60 judged searches (graded
0/1/2 from what is visible), copied under neutral camera names (`IMG_0001.jpg`) so file names give nothing away;
the engine's own walk, Windows OCR (37 photos with text), MiniLM and SigLIP base. Reference PC, CPU.

| Ranking | recall@10 (grade 2) | nDCG@10 | MRR@10 |
|---|---|---|---|
| Find today (`search.search`, RRF of names/text/meaning/photo) | 0.780 | 0.755 | 0.875 |
| SigLIP similarity alone, no floors | **0.913** | **0.864** | **0.931** |

nDCG@10 by what the search mostly needs (Find / SigLIP alone): look 0.80 / 0.91, objects 0.77 / 0.88, actions
0.69 / 0.77, mood 0.50 / 0.65, text in photo 0.64 / 0.88, photo type 0.44 / 0.84.

- **Today's fusion makes photo search worse than its own photo channel.** Two causes seen in the weakest searches:
  the photo floors (`PHOTO_MIN`, `PHOTO_SPREAD`, `PHOTO_RATIO`) cut good photos ("a handwritten note" returns
  none; the frustrated-laptop search returns one), and OCR/meaning words pull in look-alikes ("coffee" on a menu
  ranks above a cup of coffee).
- With the set's own names (`dog-01.jpg`) Find scored 0.812: the name channel was reading the answer. Always run
  with neutral names.
- **The hybrid ranker's gate is therefore SigLIP alone (0.864 nDCG@10), not today's 0.755.**
- Index build 193 s for 308 photos (OCR + SigLIP + MiniLM, CPU); search p50 214 ms.

## 2026-11-21: Vision Phase 0, step 3: like-for-like Florence-2 runs and Qwen3-VL-2B speed-ups

Same PC, tool and 32-question set. Objects (detection) and descriptions are scored separately (columns).

**Same 768 px images, same tasks** (SmolVLM2 `--variant res768`; Florence-2 always takes 768 x 768):

| candidate | device | ms per photo | peak RAM MB | objects | text | describe | count | yes/no | overall |
|---|---|---|---|---|---|---|---|---|---|
| Florence-2-base-ft int8 | CPU | 9,142 | 2,263 | 0.49 | 0.11 | 0.62 | - | - | 0.37 |
| SmolVLM2-500M, 768 px | CPU | 5,596 | 1,174 | 0.76 | 0.69 | 0.92 | 1.00 | 0.75 | 0.78 |
| SmolVLM2-500M, 768 px | Vulkan | 2,296 | 1,657 (+848 GPU) | 0.76 | 0.69 | 0.92 | 1.00 | 0.75 | 0.78 |
| SmolVLM2-500M, 512 px (default) | Vulkan | 2,329 | 1,650 (+848 GPU) | 0.86 | 0.46 | 1.00 | 1.00 | 0.75 | 0.72 |

- Florence-2 accelerated (DirectML, `onnxruntime-directml` 1.24.4, onnx-community fp16 files) **could not be
  measured**: the fp16 merged decoder is an invalid graph for ONNX Runtime ("Subgraph output (logits) is an outer
  scope value"); the two plain fp16 decoders load on DirectML but only with basic graph optimization (full
  optimization fixes a dimension to 16), and then every answer is empty (fp16 numerics). The CPU int8 row is
  the only Florence-2 number we have; at like-for-like resolution SmolVLM2 is ahead on every column.
- SmolVLM2 at 768 px reads text better (0.46 -> 0.69) at the same speed on Vulkan, names fewer objects
  (0.86 -> 0.76), and on CPU costs 1.8x the time.

**Qwen3-VL-2B speed-ups on Vulkan** (`--variant`, see `tools/vision_bench/adapters.py` VARIANTS):

| variant | what changes | ms per photo | peak RAM MB | peak GPU MB | objects | text | count | yes/no | describe | overall |
|---|---|---|---|---|---|---|---|---|---|---|
| base | 768 px, up to 256 new tokens | 10,060 | 3,945 | 3,018 | 1.00 | 0.77 | 1.00 | 1.00 | 1.00 | 0.91 |
| short | answer length per task | 7,038 | 3,945 | 3,018 | 1.00 | 0.77 | 1.00 | 1.00 | 0.96 | 0.90 |
| fewtok | short + at most 256 image tokens | 7,017 | 3,558 | 2,690 | 0.90 | 0.69 | 1.00 | 1.00 | 0.96 | 0.85 |
| fast | fewtok + flash attention + 8-bit KV cache | 5,887 | 3,352 | 2,482 | 0.90 | 0.69 | 1.00 | 1.00 | 1.00 | 0.85 |
| fastest | fast, 512 px, at most 160 image tokens | 4,862 | 3,328 | 5,793 | 1.00 | 0.69 | 1.00 | 1.00 | 0.96 | 0.87 |

- `short` is free speed: -30 % time, same quality. `fastest` halves the time and keeps objects, counts and
  comparisons perfect; only exact text reading drops (0.77 -> 0.69). Its peak GPU figure (5.8 GB shared) is
  higher than the others' and is re-measured before it's relied on.

## 2026-11-21: Vision Phase 0, step 2 (Qwen3-VL-2B Q4_K_M) on the reference PC

Same tool, PC and 32-question set as step 1 (below).

| candidate | device | ms per photo | peak RAM MB | peak GPU MB | objects | text | count | yes/no | describe | overall | 10,000 photos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-VL-2B Q4_K_M | Vulkan | 10,060 | 3,945 | 3,018 | 1.00 | 0.77 | 1.00 | 1.00 | 1.00 | 0.91 | 27.9 h |
| Qwen3-VL-2B Q4_K_M | CPU | 16,395 | 3,120 | 0 | 1.00 | 0.77 | 1.00 | 1.00 | 0.96 | 0.90 | 45.5 h |

Median seconds per answer on Vulkan, by task (generation length dominates):

| | read text | objects | question | description | compare |
|---|---|---|---|---|---|
| SmolVLM2-500M | 1.5 | 7.0 | 1.2 | 6.0 | 2.6 |
| Qwen3-VL-2B | 6.4 | 17.5 | 5.2 | 18.9 | 9.3 |

- Qwen3-VL-2B read every English and German sign exactly (RAIL RESERVATION CENTRE, PARCEL OFFICE, EXIT,
  Scentral Bark, Airtel, the full German dog-park text), named every expected object, and got all 3 comparisons.
- **Hindi: it made text up.** On the Mirzapur shop photo it wrote fluent Devanagari that isn't on the sign
  ("द एयरलाइन्स एंड टेक्नोलॉजी", "मुंबई"...), and it read the Hindi line of the trilingual sign as Urdu-script
  gibberish. Its Hindi score is 0/3, the same as SmolVLM2, but it's confidently wrong, which is worse.
- Cost: about 4x SmolVLM2's time per answer and about 2.4x its RAM (3.9 GB + 3 GB shared GPU memory on Vulkan).

## 2026-11-21: Vision Phase 0, step 1 (Florence-2, SmolVLM2-500M) on the reference PC

`python -m tools.vision_bench` (dev only, `tools/vision_bench/README.md`), llama.cpp b12602, ONNX Runtime 1.27.0
(CPU build). PC: 12 cores / 16 threads, 15.7 GB RAM, Intel Iris Xe (shared memory; Vulkan used, proven by
llama.cpp's "using device Vulkan0" line). Set: 32 questions over 17 openly licensed Wikimedia Commons photos
(English, German and Hindi signs, objects, counts, questions, descriptions, comparisons); answers written by
looking at each photo; the photos are not in the repo. Window closed, nothing else heavy running.

| candidate | device | ms per photo | peak RAM MB | peak GPU MB | objects | text | count | yes/no | describe | overall | 10,000 photos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SmolVLM2-500M Q8_0 | Vulkan | 2,329 | 1,650 | 848 | 0.86 | 0.46 | 1.00 | 0.75 | 1.00 | 0.72 | 6.5 h |
| SmolVLM2-500M Q8_0 | CPU | 3,152 | 1,167 | 0 | 0.86 | 0.46 | 1.00 | 0.75 | 1.00 | 0.72 | 8.8 h |
| Florence-2-base-ft int8 | CPU | 9,142 | 2,263 | - | 0.49 | 0.11 | - | - | 0.62 | 0.37 | 25.4 h |

What the answers show (per-item answers in the run's `results.json`):
- SmolVLM2 answered every question right (2 people, chess, red, snow, German, a photographer: 7/7), every
  description, and 2 of 3 comparisons (it said two Tokyo night streets were not the same kind of place). Reading
  text is its weak part: asked to copy a sign, it often describes it instead ("The signboard is green and
  white..."); German came out garbled; **no Hindi text was read** (0/3).
- Florence-2 int8 on CPU was 3-4x slower and used more RAM than SmolVLM2, and was weaker everywhere: its text
  reading runs lines together ("ScentralBark", "Sairtel") and looped on the wide trilingual sign (repeated
  Arabic-script tokens); objects missed signs and the motorcycle. Its int8 graphs may be part of the cause.
- Hindi text needs a dedicated reader (not measured here; PaddleOCR Devanagari pinned in `models.json`).

## 2026-11-19 (late): 0.8.5 smart search (understood parts, best guess, autocomplete)

**Quality** (`tools/eval_search.py`, generated corpus: 31 answer files in English, Hindi, Spanish, French and German
plus 400 look-alike files made of the same words in other folders, Downloads / Desktop / Documents / Pictures /
Videos / Music-like folders with dates from today to 8 years back and sizes from 1 KB to 150 MB, 7 drawn pictures;
51 questions; reference PC, quiet). The models were copied from a local data folder into the temp data folder;
nothing was downloaded.

| Questions | n | recall@1 | recall@5 | MRR@10 | parts right | best guesses (right) |
|---|---|---|---|---|---|---|
| Keywords and filters (places, kinds, times, sizes, names, prefixes, text, 5 languages, Hinglish) | 39 | **1.000** | 1.000 | 1.000 | 39/39 | 32 (32) |
| Meaning, all-MiniLM-L6-v2 ("apartment lease", "plane ticket", "job application letter") | 5 | 0.400 | 0.600 | 0.495 | 5/5 | 1 (1) |
| Photo meaning, SigLIP base, drawn pictures ("2 boys in an image in downloads", "red circle", "sunset over the sea") | 7 | **1.000** | 1.000 | 1.000 | 7/7 | 2 (2) |
| All | 51 | 0.941 | 0.961 | 0.951 | 51/51 | 35 (35) |

- The best guess was never wrong on this set (precision 1.0); it stays away when two files are close (a photo of
  two people next to a photo of one person in the same folder: no guess).
- The meaning row is the weak part: with 400 look-alikes, "apartment lease" puts the rental agreement 7th behind
  look-alike names, "job application letter" misses the French letter. Keyword questions were not affected.
- The drawn pictures are simple shapes, stick figures and a card with words, not real photos: they show the
  routing ("2 boys" goes to photo meaning inside Downloads), not photo-model quality (that is the 55-photo set above).
- `pytest` runs the keyword part on every change (`tests/test_smart_search.py`, thresholds recall@1 ≥ 0.90, recall@5
  ≥ 0.95, MRR ≥ 0.90, every part right, guess precision ≥ 0.95).

**Speed per keystroke** (`tools/bench_search.py --smart`, 998,212-entry synthetic index, same index for both, quiet PC):

| | 0.8.5 base (8a4ca7a) p50 / p90 / max | With smart search p50 / p90 / max |
|---|---|---|
| 1-2 letters (30) | 3.3 / 5.0 / 11.1 ms | 3.3 / **4.3** / 9.4 ms |
| Names, 3+ letters (44) | 17.1 / 30.1 / 45.2 ms | 16.7 / **36.5** / 50.9 ms |
| Several words (16) | 40.4 / 103.9 / 109.5 ms | 41.4 / **95.1** / 113.5 ms |
| Plain-language questions (164 keystrokes of 7 questions) | not measured | 5.2 / **192** / 350 ms |
| Suggestions (`suggest`, 254 keystrokes, with history) | none | 0.4 / **2.3** / 5.2 ms |

The parts and the best guess cost nothing measurable (they reuse the ranked answer). The plain-language p90 is over
the 80 ms budget, and the slow keystrokes are all filter-only listings on this synthetic index, where sizes are
spread evenly so only 1 % of rows pass "small" or "big": "big videos" (330 ms before this change too), "small pdfs"
(new: "small" is now a size filter instead of a word) and "budget in documents" (330 ms before). They walk one kind's
files newest first checking the size; an index on (kind, size) would fix it and wasn't added (it grows the index).
"on d drive" with nothing from D: now answers in 1 ms (it scanned for 300-1,000 ms). On the eval corpus (small) search
is 1.2 / 2.1 / 9.6 ms without models and 29 / 36 / 42 ms with both question encoders.

**UI work per keystroke** (`test/widgets/typing_perf_test.dart`: 500 results on screen, suggestions and the best
guess on; build + layout + paint of the keystroke's three frames in the debug-mode test binding, no GPU raster; the PC
was shared with other builds, so runs vary 2x). Alternating runs against find-0.8.5 without smart search, main window:
base p50 282 / 123 / 136 ms, with smart search 169 / 123 / 108 ms; no difference beyond the noise. Bar: 56-100 ms p50.
These are debug-mode numbers (a release build is several times faster); they only show that suggestions, chips and
the guess add nothing measurable. A keystroke with results on screen now rebuilds the results once (when the answer
comes), not twice (the "busy" notice only redraws while there are no results yet); suggestions ask after a 70 ms pause.

## 2026-11-19 (night): review of #80, name results that are right at whole-PC scale (H1)

The first whole-PC fix capped name candidates with `IN (SELECT rowid … MATCH ? LIMIT 2000)`, which keeps the 2,000
*oldest* rows before any filter or ranking. Its repro: 2,500 `report*.dll` indexed first, then the one
`Documents\report.pdf`. Searching `report` gave only dlls, and `report pdf` gave nothing. bm25 can't rank instead:
on the trigram table every match of a word scores the same (-1.05e-6), so ties fall back to rowid order again.

**Now:** the engine counts the word's FTS matches (capped at 20,000, a few ms).
- Under 20,000: every match is joined and filtered, then ordered by name length (exact).
- More: the files are walked shortest name first through a covering index `files(length(name), mtime, name, kind, ext)`,
  with the filters applied, and the walk stops at 150 hits.

Either way the filters are part of the query, so `report pdf` finds the pdf. The index is built once in the
background with the name-word index: 50 s at a million entries.

**Right answers** (998k-entry synthetic index plus 6,000 long `zebrafile_NNNNN_backup.dll` indexed first, then
`zebrafile.pdf` last):

| Question | Before the fix: rank of zebrafile.pdf | After |
|---|---|---|
| zebrafile | not in the results | **1** |
| zebrafile pdf | no results at all | **1** |
| zebra / ze | not in the results | **1 / 1** |

On the plain synthetic index (names spread evenly) both versions match brute-force ground truth for the top 10 on 7
of 8 questions. The 8th, `setup exe`, is wrong in both: `setup` and `exe` are read as the App kind, a parser matter
and not H1.

**Speed per keystroke** (`tools/bench_search.py`, 1,004,217 entries, two runs, quiet PC):

| | p50 | p90 | max |
|---|---|---|---|
| 1-2 letters | 2.6-2.9 ms | **4.0-4.3 ms** | 7-8 ms |
| Names, 3+ letters | 14-15 ms | **28-30 ms** | 39-40 ms |
| Several words | 32-34 ms | **72-74 ms** | 97-109 ms |

Each is within the ≤ 80 ms p90 budget. One run while the PC was busy showed several-word p90 at 156 ms; the quiet runs
are the numbers above.

Also from the review:
- a cancelled search now reads as `cancelled: true` on SQLCipher too (its OperationalError isn't sqlite3's);
- cancelling is per connection *and* `channel`, so the Home list doesn't cancel the search box;
- Hinglish rules apply only when the focus is Hindi or many languages, or when the question is clearly Hinglish;
- photo vectors are written only under the model that made them;
- a rebuild never swaps in a model the user already left, and the swap and its model id are one transaction;
- vectors that don't fit their model are rebuilt, not left off;
- one meaning worker per round while switching;
- `capable` counts the vectors' disk space;
- one download per model, with its own part files;
- a photo model starts once downloaded;
- status cards name the models in use;
- the tray setting applies live;
- names and text are NFC.

## 2026-11-19 (0.8.0 engine): text models, English and Hindi search quality, whole-PC search speed

- **Branch:** `find-0.8-engine` (PR #80). **PC:** the reference PC (i5-12500H, 16 threads, 15.7 GB, Windows 11).
- **Models:** every candidate was fetched once through the engine's own `embed._fetch_verified` (pinned revision,
  exact size, SHA-256) into a throwaway data folder, never the real index. Licences were checked on each model's
  card; only MIT and Apache-2.0 are used. OpenAI CLIP isn't one of them.
- **Search quality:** `python tools/eval_text.py --models-dir <throwaway> --set english|hindi`. The test sets are
  `tools/evalset/*.json`, all content made up:
  - **English:** 112 personal files (letters, bills, a lease, payslips, insurance, recipes, READMEs, travel plans;
    8 long ones with the answer deep inside) and 68 questions: 31 paraphrases with no shared word, 21 keyword and
    16 mixed.
  - **Hindi:** 40 files (Devanagari, Hinglish, mixed) and 43 questions: 15 Hindi, 14 Hinglish, 14 cross-language.

  The files are indexed by the engine's own code (extract, chunks, name and chunk vectors) and each question goes
  through the real `search.search()`. **Model alone** = the best vector per file, with no keywords, filters or
  floors. **Search** = what a user gets. RAM is one process holding the model (the main process for questions;
  the meaning worker holds its own copy while indexing). Passages/s are while indexing, on 8 threads.
- **Not kept:**
  - LaBSE: its ONNX build lacks the final pooling layer, and it scores lower;
  - paraphrase-multilingual-MiniLM: lower everywhere;
  - l3cube Hindi / Indic SBERT (CC-BY-4.0): no ONNX build, and converting needs PyTorch;
  - arctic-embed s / m, nomic-embed v1.5, gte-base, bge-small: no better than GTE small and slower;
  - bge-m3: about as good as multilingual-e5-small on Hindi, but 17x slower to index and 821 MB;
  - SigLIP 2 large: about 880 MB, too big for a question encoder in the main process.

  Their numbers are below. The ONNX OCR (PaddleOCR / RapidOCR, Apache-2.0) is available, but its text detector needs
  OpenCV-style contour work that isn't in the locked dependencies; it's left for later (see Still open).

#### Text models

#### English set

| Model | MB | RAM MB (1 process) | Passages/s | Model alone R@5 / MRR / nDCG | 0.7.0 search nDCG | 0.8.0 search R@5 / MRR@10 / nDCG@10 | Search p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| keywords only (no model) | - | - | - | - | 0.309 | 0.382 / 0.382 / 0.382 | 0.9 / 1.1 |
| minilm-l6-v2 | 23 | 38 | 32.9 | 0.941 / 0.871 / 0.883 | 0.756 | 0.897 / 0.836 / 0.847 | 6.2 / 9.7 |
| gte-small | 33 | 56 | 54.3 | 0.941 / 0.880 / 0.903 | 0.801 | 0.897 / 0.864 / 0.873 | 6.7 / 8.3 |
| bge-small-en-v1.5 | 33 | 54 | 26.5 | 0.934 / 0.876 / 0.891 | 0.771 | 0.882 / 0.842 / 0.851 | 12.5 / 23.0 |
| arctic-embed-s | 33 | 54 | 23.4 | 0.875 / 0.801 / 0.832 | 0.732 | not run | 12.0 / 24.0 |
| gte-base | 106 | 128 | 12.9 | 0.941 / 0.898 / 0.908 | 0.785 | 0.897 / 0.859 / 0.864 | 15.2 / 18.8 |
| bge-base-en-v1.5 | 106 | 125 | 16.3 | 0.949 / 0.909 / 0.917 | 0.778 | 0.882 / 0.859 / 0.864 | 24.9 / 36.7 |
| arctic-embed-m-v1.5 | 106 | 127 | 11.8 | 0.926 / 0.849 / 0.872 | 0.738 | 0.875 / 0.811 / 0.822 | 24.1 / 33.3 |
| nomic-embed-text-v1.5 | 131 | 152 | 8.5 | 0.941 / 0.854 / 0.876 | 0.756 | 0.868 / 0.810 / 0.821 | 27.8 / 33.6 |
| multilingual-e5-small | 129 | 385 | 30.2 | 0.868 / 0.824 / 0.846 | 0.732 | 0.801 / 0.766 / 0.785 | 11.1 / 18.0 |
| multilingual-e5-base | 282 | 544 | 8.3 | 0.897 / 0.856 / 0.882 | 0.780 | 0.868 / 0.815 / 0.824 | 19.0 / 27.9 |
| paraphrase-multilingual-minilm | 122 | 386 | 14.0 | 0.904 / 0.828 / 0.855 | 0.724 | 0.846 / 0.801 / 0.817 | 8.3 / 19.9 |
| labse | 463 | 560 | 5.7 | 0.775 / 0.683 / 0.706 | 0.613 | not run | 28.1 / 66.0 |
| bge-m3 | 560 | 821 | 3.1 | 0.985 / 0.887 / 0.912 | 0.759 | 0.838 / 0.797 / 0.800 | 25.8 / 32.0 |

By kind of question (0.8.0 search nDCG@10): keyword, mixed, paraphrase

| Model | keyword | mixed | paraphrase |
|---|---|---|---|
| keywords only (no model) | 0.952 | 0.375 | 0.000 |
| minilm-l6-v2 | 0.995 | 0.995 | 0.671 |
| gte-small | 0.995 | 0.989 | 0.731 |
| bge-small-en-v1.5 | 0.995 | 0.976 | 0.690 |
| gte-base | 0.997 | 0.989 | 0.709 |
| bge-base-en-v1.5 | 0.996 | 0.987 | 0.712 |
| arctic-embed-m-v1.5 | 0.995 | 0.976 | 0.627 |
| nomic-embed-text-v1.5 | 0.996 | 0.976 | 0.623 |
| multilingual-e5-small | 1.000 | 0.989 | 0.535 |
| multilingual-e5-base | 0.996 | 0.953 | 0.642 |
| paraphrase-multilingual-minilm | 0.987 | 0.935 | 0.640 |
| bge-m3 | 0.998 | 0.953 | 0.586 |

#### Hindi set

| Model | MB | RAM MB (1 process) | Passages/s | Model alone R@5 / MRR / nDCG | 0.7.0 search nDCG | 0.8.0 search R@5 / MRR@10 / nDCG@10 | Search p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| keywords only (no model) | - | - | - | - | 0.209 | 0.233 / 0.233 / 0.233 | 0.5 / 0.7 |
| minilm-l6-v2 | 23 | 38 | 84.4 | 0.663 / 0.542 / 0.570 | 0.420 | 0.535 / 0.473 / 0.497 | 4.3 / 5.3 |
| gte-small | 33 | 56 | 36.8 | 0.674 / 0.514 / 0.562 | 0.454 | 0.593 / 0.525 / 0.546 | 9.2 / 15.5 |
| bge-small-en-v1.5 | 33 | 54 | 31.7 | 0.698 / 0.525 / 0.580 | 0.469 | 0.640 / 0.544 / 0.572 | 10.5 / 12.9 |
| arctic-embed-s | 33 | 54 | 41.8 | 0.547 / 0.482 / 0.537 | 0.456 | not run | 11.2 / 14.6 |
| gte-base | 106 | 128 | 13.1 | 0.674 / 0.517 / 0.569 | 0.446 | 0.570 / 0.477 / 0.520 | 12.7 / 15.9 |
| bge-base-en-v1.5 | 106 | 125 | 8.7 | 0.698 / 0.589 / 0.635 | 0.479 | 0.593 / 0.537 / 0.567 | 28.2 / 48.7 |
| arctic-embed-m-v1.5 | 106 | 127 | 13.0 | 0.698 / 0.604 / 0.640 | 0.477 | 0.628 / 0.546 / 0.571 | 29.2 / 41.1 |
| nomic-embed-text-v1.5 | 131 | 152 | 16.1 | 0.663 / 0.522 / 0.563 | 0.458 | 0.581 / 0.503 / 0.525 | 15.3 / 22.4 |
| multilingual-e5-small | 129 | 385 | 56.3 | 0.965 / 0.923 / 0.932 | 0.726 | 0.860 / 0.810 / 0.823 | 6.6 / 9.2 |
| multilingual-e5-base | 282 | 544 | 8.7 | 0.953 / 0.834 / 0.861 | 0.719 | 0.837 / 0.798 / 0.808 | 18.4 / 30.2 |
| paraphrase-multilingual-minilm | 122 | 386 | 36.2 | 0.919 / 0.704 / 0.757 | 0.569 | 0.791 / 0.640 / 0.691 | 7.1 / 10.8 |
| labse | 463 | 560 | 23.4 | 0.895 / 0.727 / 0.771 | 0.626 | not run | 10.9 / 17.6 |
| bge-m3 | 560 | 821 | 3.3 | 0.977 / 0.905 / 0.921 | 0.720 | 0.837 / 0.791 / 0.802 | 36.3 / 53.5 |

By kind of question (0.8.0 search nDCG@10): cross, hindi, hinglish

| Model | cross | hindi | hinglish |
|---|---|---|---|
| keywords only (no model) | 0.071 | 0.267 | 0.357 |
| minilm-l6-v2 | 0.128 | 0.498 | 0.865 |
| gte-small | 0.214 | 0.548 | 0.876 |
| bge-small-en-v1.5 | 0.197 | 0.638 | 0.876 |
| gte-base | 0.147 | 0.557 | 0.853 |
| bge-base-en-v1.5 | 0.153 | 0.661 | 0.879 |
| arctic-embed-m-v1.5 | 0.206 | 0.625 | 0.879 |
| nomic-embed-text-v1.5 | 0.071 | 0.619 | 0.879 |
| multilingual-e5-small | 0.733 | 0.875 | 0.857 |
| multilingual-e5-base | 0.688 | 0.875 | 0.857 |
| paraphrase-multilingual-minilm | 0.549 | 0.702 | 0.822 |
| bge-m3 | 0.674 | 0.871 | 0.857 |

#### The search changes, one at a time (English, search nDCG@10)

| Variant | none | minilm-l6-v2 | gte-small | bge-base-en-v1.5 |
|---|---|---|---|---|
| base | 0.309 | 0.756 | 0.802 | 0.777 |
| nofloor | 0.309 | 0.771 | 0.801 | 0.779 |
| noweak | 0.309 | 0.756 | 0.801 | 0.777 |
| fts_or | 0.459 | 0.534 | 0.539 | 0.535 |
| synonyms | 0.309 | 0.757 | 0.801 | 0.771 |
| rrf_equal | 0.309 | 0.756 | 0.801 | 0.777 |
| meaning_up | 0.309 | 0.756 | 0.802 | 0.778 |
| floors + soft time + no folder meaning (0.8.0) | 0.382 | 0.847 | 0.873 | 0.864 |
| floors only (soft time and folder rule off) | 0.309 | 0.771 | 0.793 | 0.774 |


**What the 0.8.0 search changes did:** the 0.7.0 search lost 0.08-0.14 nDCG against the model alone. The causes,
found query by query:
1. A time word became a filter on when the file changed ("electricity bill march" found nothing, because the March
   bill changed in April). Now, when such a filter matches no file, the time is read as words and a note says so.
2. Folders had name vectors and filled the meaning results ("Documents/Home" for "where I live"). They now count
   only when folders are asked for.
3. Each model scores on its own scale, so one set of floors for every model was wrong. The floors are now measured
   per model (5th percentile of right answers, 95th percentile of their distance to the best match) and live in the
   catalog.

Keeping only what won: OR-ed keywords, synonyms, equal or higher fusion weights and dropping the floors alone each
changed nDCG by under 0.02 or made it worse (OR: -0.22), so they stay off and remain as switches in
`search.VARIANTS` to measure again. Not tried yet: a cross-encoder reranker and longer-document chunking.

**What was picked** (`nobadfind/models.py`):

| Tier | English first | Many languages | Hindi |
|---|---|---|---|
| Light | GTE small (33 MB, 56 MB RAM, 0.873) | all-MiniLM-L6-v2 | all-MiniLM-L6-v2 |
| Balanced | GTE small | multilingual-e5-small (129 MB, 385 MB RAM; Hindi 0.823) | multilingual-e5-small |
| Best | GTE small (BGE base is offered; no better here, 3x slower) | multilingual-e5-base | multilingual-e5-small |

The focus is recommended from Windows' display and keyboard languages: a Hindi language means Hindi, another
non-English one means many languages, else English first. The user can change it (`model_language`). On a Light PC
(< 8 GB or ≤ 4 cores) a Hindi or many-languages user still gets all-MiniLM, because e5 small holds 385 MB in each
process that loads it.

**Where e5's memory goes:** 256 MB of its 385 MB is the tokenizer (`tokenizers` with XLM-R's 250,000-piece
vocabulary) and 130 MB the ONNX session; for all-MiniLM those are 7 and 32 MB. The graph optimisation level changes
nothing (383-385 MB at every level).

#### Photo models

| Model | Download | Question encoder RAM (main) | Photo worker RAM (vision) | A question | 16 pictures, English: right one first / mean rank | Hindi questions: mean rank (8.5 = chance) |
|---|---|---|---|---|---|---|
| SigLIP base | 211 MB | 156 MB | 144 MB | 56-65 ms | 16/16, 1.0 | 8.5 |
| SigLIP 2 base | 393 MB | 370 MB | 139 MB | 63 ms | 16/16, 1.0 | **3.6** |

The pictures are made-up coloured shapes (4 colours x 4 shapes), with questions like "a red circle" / "लाल गोला".
SigLIP 2 base is the Best tier's photo model: same speed, and it understands Hindi questions somewhat. It costs
another 214 MB in the main process while photo meaning is in use.

#### Search speed at whole-PC scale (`python tools/bench_search.py --rows 1000000`)

A synthetic index of 998,212 file entries (realistic names, folders and kinds, no text or vectors). 16 questions
are typed one letter at a time through `search.search()`; the cache is warm.

| Per keystroke | 0.8.0 before the fix: p50 / p90 / max | After: p50 / p90 / max |
|---|---|---|
| 1-2 letters (30) | 467 / 539 / 641 ms | **6.8 / 12.6 / 13.7 ms** |
| Names, 3+ letters (44) | 169 / 238 / 357 ms | **16.9 / 22.5 / 24.0 ms** |
| Several words (16) | 88 / 295 / 317 ms | **20.4 / 39.8 / 46.7 ms** |

- One or two letters used `name LIKE '%ta%'`, a scan of every row. They now use `names_w`: the words of every name
  in an FTS5 table with a prefix index, matching names with a word that starts with them. It's filled once in the
  background (6.5 s at a million entries), then kept up by triggers.
- "photos" alone (every photo, newest first) sorted them all: a `files(kind, mtime)` index fixed it (318-485 ms →
  under 25 ms).
- At most 2,000 name matches are looked at per question.
- A newer keystroke from the same pipe client cancels the search still running (SQLite progress handler). Its answer
  would be thrown away anyway.
- #79 measured p90 2.5 s / max 13 s on a real 940k-entry index with text, where the same scans were the cause. This
  bench has no text chunks, so a run on #79's index is the check still to do after both are merged.

#### Still open
- ONNX OCR for Devanagari: Windows OCR has no Hindi at all (Windows.Media.Ocr doesn't support hi-IN; this PC has
  en-GB, en-US and pt-BR). The PaddleOCR / RapidOCR models (Apache-2.0) exist, but need a text detector with
  contour post-processing; not built.
- A cross-encoder reranker (Best tier) and chunking tuned for long documents: not tried.
- e5's 256 MB tokenizer in each process: a smaller tokenizer (or one shared process for the question encoders) would
  bring the many-languages tiers down a lot.
- #79's "closed engine at about one core" from its backlog wasn't reproduced here (this branch doesn't have #79).
## 2026-11-19 (evening): a whole PC by name (the new default scope), and the turbo helper's own parts

- **Why:** the new defaults (maintainer decision 2026-11-19) index Windows, Program Files, ProgramData and AppData too
  (`include_system`, `include_caches` on), which 0.7.0's walk skipped, so the budgets were checked on the real fixed
  drives of the reference PC (16 threads, 15.7 GB, SSD). 0.7.0's own count on this PC wasn't measured. The walk is
  read-only, and the index went to a throwaway folder in %TEMP%, never the real one.
- **How:** `python tools/measure.py --whole-pc --files 20 --levels full ...` (new option: names only, real Whole PC
  scope, level fixed at Full, engine from source). Other agents were using the PC at the same time, so times vary
  run to run (436-534 s for the same scan).
- **The turbo index was not run:** it needs an elevated process (a UAC prompt for the maintainer). These are the
  walker's numbers to compare it with, plus the turbo helper's pure-Python parts on synthetic buffers of the same size.

### Walker only, no store (the walk itself, one process)

| | Entries | Folders | Time | CPU | Peak private |
|---|---|---|---|---|---|
| `Walker`, 32 threads, Whole PC rules, C: only, nothing written | 853 845 | 182 670 | 63 s | 124 CPU-s (2.0 cores) | 37 MB |
| same, writing into the encrypted store | 854 297 | 182 845 | 266 s | 292 CPU-s (1.1 cores) | 314 MB |

The store is the bottleneck, not the walk: about 3 200 rows/s into SQLCipher with the FTS5 trigram index on names.
The index is 953 MB for 854k names. **Turbo can only take away the 63 s walk part**; the inserts stay.

### The engine, a whole PC by name (`--whole-pc`, level Full)

| Commit | Entries | Name scan | Private MB while indexing (mean / max) | CPU while indexing | Idle, window open: CPU, reads | Window closed: CPU, reads | Search keystroke p50 / p90 / max |
|---|---|---|---|---|---|---|---|
| `a02d96f` (scope, before the two fixes below) | 941 697 | 436 s | 292 / 373 | 1.5 cores | 108 %, 145 MB/s | 219 %, 274 MB/s | 10.7 ms / 3 783 ms / 7 843 ms |
| `2e65ac1` (own data folder out, watching loop counts every 30 s) | 941 080 | 534 s | 313 / 375 | 1.4 cores | 99 %, 109 MB/s | 103 %, 112 MB/s | (not recorded) |
| `ece6784` (status counts cached by their cost) | 822 000 | 435 s | 289 / 353 | 1.0 core | **46 %, 48 MB/s** | 100 %, 129 MB/s | 13.4 ms / 2 505 ms / 13 011 ms |

CPU in % of one core. Idle with no UI: 0.4 % and 49 MB private in every run. The entry count changes between runs
because other programs (and agents) created and deleted files on the PC meanwhile.

Against the ROADMAP budgets:
- **Indexing ≤ 600 MB private: met** (max 353-375 MB for a whole PC by name, one process).
- **Window open, idle, engine ≤ 120 MB: at the edge** (119 MB mean, 132 MB max).
- **Search ≤ 80 ms for names: missed on a whole PC.** The median is fine (13 ms), but a question of one or two letters
  (each keystroke of "i", "in") is a `name LIKE '%i%'` over every row sorted by name length: 2.5 s at the 90th
  percentile, up to 13 s. Those searches queue on the pipe's 4 threads, which is most likely also the ~1 core and
  ~130 MB/s still seen "closed" (the closed scenario starts right after the typing). Open item for `search.py`
  (not changed here): skip or bound one- and two-letter name scans, and drop a search the next keystroke replaced.
- **Closed ≤ 60 MB: missed** (135 MB private; see the search backlog above, re-measure after the search fix).

### The turbo helper's Python work, synthetic (183 000 folders, 671 000 files, paths ~120 characters)

| Step | Time | Note |
|---|---|---|
| Parse the `FSCTL_ENUM_USN_DATA` buffers (854k `USN_RECORD_V2`) | 3.7 s per pass | two passes: folders first, then everything |
| Folder pass (the tree) | 4.5 s | |
| Filter and paths for every entry (scope rules, other profiles, metafiles) | 16.5 s | per folder once, per file a dict look-up |
| Parse one MFT record (fixups, `$STANDARD_INFORMATION`, `$DATA`) | 8.7 µs | 7.5 s for 854k; the `FSCTL_GET_NTFS_FILE_RECORD` calls themselves are on top and need the elevated run |
| Memory for the tree, the filter and the paths | +81 MB | in the helper process, not the engine |

About 35 s of one core in Python before the ioctls, against the walker's 63 s on two cores. The real comparison
(enumeration time, ioctl cost per file for both size/time options, change-journal latency) is what
`python -m nobadfind --turbo selftest` prints from an elevated terminal: to be added after the maintainer's run.

### Two fixes this found

- **Indexing its own database:** with AppData included and the index in %TEMP% (`NOBAD_FIND_DATA_DIR`), the engine
  indexed its own database writes, a feedback loop. NOBAD Find's data folder is now always out (`scope.Rules.own`);
  the real one was already out through the `nobad` name.
- **Counting a million rows on every poll:** after the scan, the engine still used ~1 core and read ~100 MB/s while
  idle (first two runs above). `Api.status` ran `Store.stats` (six `COUNT`s over every row) on every 2 s poll of the
  Indexing page, and the watching loop ran it every round. Now counts are reused for 10 s or 20x as long as they took
  (`api.STATS_TTL`, `COUNT_SHARE`; `indexer.STATS_EVERY`).

## 2026-11-19 (later): with both models, every process, and ONNX Runtime tuning

- **Commits:** before = `afd5581` (the review fixes for #78 + the harness's model scenarios, no tuning); after = the
  tuning commit on `find-measure`.
- **Same PC.** Engine started through `packaging/launch.py` (`--entry launch`, how the exe starts workers) with a
  venv built from `requirements-lock.txt` (`--python`), not the global Python.
- **Models:** all-MiniLM-L6-v2 (meaning) and SigLIP base (photos), fetched once through the engine's own
  `embed._fetch_verified` (pinned, SHA-256 checked) into a throwaway data folder, then linked into each run's fresh
  temp index. Never the real index or settings. Meaning, photo meaning and OCR on.
- **Corpus:** `--files 1000 --photos 150 --text-images 60`: the 1,000 generated documents (as before, 120 PDFs),
  150 camera-style JPEGs (gradient skies, sun, hills, shapes, grain; 640x480 to 1024x768), 60 screenshots with
  words for OCR. 2,107 index entries, 1,140 with text, 2,874 chunks, 270 images for the photo model.
- **Scenarios** (Gentle runs them all; Full and Light only index): indexing; warm searches (4 meaning questions and
  4 photo questions typed one letter at a time); models loaded and idle; waiting for `embed.Lazy` to release them
  (163 s here); released and idle; a cold search; window closed; reopen and type at once.
- Process roles come from the engine's own `status_full` (a second pipe connection, every 2 s). "Not yet named" =
  a worker the 2-second poll hadn't seen named yet. The venv launcher and the console host are left out of totals.

### What ONNX Runtime does with the models (isolated runs, real models, one fresh process per variant)

| Meaning worker (512 chunks, 8 threads) | Private after | Peak | Chunks/s |
|---|---|---|---|
| batch 64, arena on, mem pattern on (before) | **1,119 MB** | 1,145 MB | 30 |
| batch 64, arena off | 51 MB | 612 MB | 17 |
| batch 64, arena and mem pattern off | 51 MB | 508 MB | 23 |
| batch 64, mem pattern off | 1,119 MB | 1,144 MB | 31 |
| batch 64, `arena_extend_strategy` = kSameAsRequested | 1,362 MB | 1,388 MB | 32 |
| batch 16, arena on | 318 MB | 323 MB | 40 |
| batch 8, arena on | 185 MB | 187 MB | 40 |
| **batch 4, arena on (after)** | **113-115 MB** | 116 MB | **39-40** |
| batch 2 / 1, arena on | 78 / 59 MB | | 43 / 39 |
| batch 4 at 4 / 2 / 1 threads | | | 25-48 / 15-33 / 19 |

Batch 64 sequences of up to 256 tokens make the attention tensors big, and ONNX Runtime's arena keeps the peak.
Turning the arena off frees it but runs 25-45 % slower. Smaller batches fix both. Memory pattern made no difference,
and kSameAsRequested was worse. Threads: 8 beat 4 on repeat runs (one outlier aside), so the thread rule stays.

**Search quality.** All-MiniLM is dynamically quantized, so padding in a batch shifts the numbers a little: every
batch size is about the same distance from unpadded (batch 1) vectors, cosine mean 0.992 (min 0.98). Nearest-neighbour
lists agree as well with batch 4 as with batch 64: 77.7 % vs 76.8 % of top-10 neighbours shared with the unpadded
vectors. Arena and memory-pattern settings give bit-identical vectors.

| Other sessions (isolated) | Before | After |
|---|---|---|
| Photo model, vision (photo worker), photos/s at 2 / 4 / 8 threads | fixed 2 threads: 2.4 | threads by level: 4.7 / 7.1-7.5 at 4 / 8 |
| Photo question (SigLIP text, main process), ms per question at 2 / 4 threads | 45 ms (2 threads) | **28 ms** (4 threads) |
| Meaning question (MiniLM, main process) | 1.3 ms | unchanged |
| Arena on/off for these three | ≤ 30 MB difference, arena on faster | left on |

Vectors are already float16 in memory and in the index (`embed.to_blob`, `VectorIndex._mat`). That's 768 bytes per
text vector and 1.5 KB per photo vector: about 5 MB for this index, so there's nothing cheap left there.

### Changes kept

1. `embed.BATCH` 64 → 4: the meaning worker keeps 115 MB instead of 1.1 GB and runs faster.
2. The photo worker's threads follow the level, like the meaning worker (`min(cores / 2, readers for the level)`):
   8 at Full and Gentle on this PC, 1 at Light. Before: always 2.
3. The photo question encoder in the main process uses 4 threads instead of 2.

### Before → after, indexing (1,000 files + 150 photos + 60 screenshots)

| Level | Wall time | Find's private MB, mean / max | Meaning worker MB | Meaning chunks/s | Photos/s |
|---|---|---|---|---|---|
| Full | 132 s → **84 s** | 734 / 1,230 → **246 / 663** | 1,149 → **154** | 43 → **75** | 4.7 → **7.2** |
| Gentle | 190 s → **131 s** | 803 / 1,246 → **233 / 338** | 1,152 → **152** | 26 → **44** | 3.8 → **4.4** |
| Light | 615 s → **576 s** | 935 / 1,242 → **225 / 313** | 1,143 → **149** | 6.5 → **9.4** | 1.8 → 1.1 |

Text 150-250 files/s and OCR'd images 27-135/s were the same in both runs. At Light, photos got slower because the
photo worker now has 1 thread instead of 2 (Light means a game or a busy PC). The whole run is still faster.

### Before → after, the window and search (Gentle run)

| | Before | After |
|---|---|---|
| Meaning search while typing, p50 / p90 / max | 105 / 163 / 180 ms | **42 / 118 / 187 ms** |
| Photo search while typing, p50 / p90 / max | 108 / 123 / 146 ms | **42 / 50 / 53 ms** |
| First search with the models out of memory (both load) | 848 ms | 810 ms |
| Window reopened, typing at once | 957 ms | 627 ms |
| Main process, models loaded, idle | 303 MB private / 291 MB working set | 304 / 292 (unchanged) |
| Main process, models released (163 s idle) | 129 / 119 MB | 125 / 116 MB |
| Window closed (models released, working set handed back) | 134 MB private, 40 MB working set | 143 / 42 MB |

Every keystroke runs both question encoders, so the 28 ms photo encoder sets the floor; the meaning budget
(≤ 250 ms) is met. The first search after a release pays about 0.6-0.8 s for loading both models.

### Every process, after (per process: private and working set, mean / max; handles mean)

| Level | Scenario | Process | At once (pids seen) | Private MB | Working set MB | Handles |
|---|---|---|---|---|---|---|
| Gentle | idle, no UI | Main | 1 | 48 | 66 | 354 |
| Gentle | indexing | Main | 1 | 65 / 72 | 83 / 90 | 394 |
| Gentle | indexing | Text reader | 8 (16) | 31 / 43 | 45 / 56 | 224 |
| Gentle | indexing | Meaning worker | 1 | 152 / 157 | 171 / 177 | 224 |
| Gentle | indexing | Photo worker | 1 | 186 / 240 | 193 / 243 | 293 |
| Gentle | warm searches | Main | 1 | 300 / 305 | 288 / 291 | 380 |
| Gentle | models loaded, idle | Main | 1 | 304 | 292 | 380 |
| Gentle | models released, idle | Main | 1 | 125 / 130 | 116 / 120 | 368 |
| Gentle | window closed | Main | 1 | 143 / 309 | 42 / 296 | 364 |
| Full | indexing | Main | 1 | 65 / 72 | 84 / 90 | 397 |
| Full | indexing | Text reader | 15 (15) | 31 / 54 | 42 / 62 | 177 |
| Full | indexing | Meaning worker | 1 | 154 / 158 | 172 / 178 | 224 |
| Full | indexing | Photo worker | 1 | 186 / 243 | 195 / 218 | 291 |
| Light | indexing | Main | 1 | 66 / 72 | 85 / 90 | 391 |
| Light | indexing | Text reader | **1** (3) | 39 / 55 | 50 / 60 | 241 |
| Light | indexing | Meaning worker | 1 | 149 / 153 | 155 / 170 | 213 |
| Light | indexing | Photo worker | 1 | 181 / 241 | 183 / 216 | 282 |

Before, the meaning worker was 1,143-1,152 MB private at every level, and everything else was within a few MB of
the after numbers. The phases run one after another (text, images, meaning, photos), so the readers, the meaning
worker and the photo worker are never all alive at once. Light now really runs one reader (the recycling fix).

### The worker memory limit with the models

The limit is a quarter of RAM, 1-4 GB. The most the workers committed at once is now 663 MB (Full, 15 readers),
and 338 MB at Gentle. On a 4 GB PC the limit is 1 GB, and the workers stay well under it: readers for 4 threads plus
a 160 MB meaning worker or a 240 MB photo worker. Before the batch change, the meaning worker alone (1.15-1.18 GB)
would have been over a 4 GB PC's limit: it would have failed to load, and kept failing (it now backs off). DirectML
(the graphics-card build of ONNX Runtime) isn't shipped or installed here, so its memory isn't measured.

### Still open
- **The main process keeps about 75 MB after the models are released.** It's 125 MB vs 48 MB before loading, so the
  window-closed state is 143 MB private (42 MB working set) with models in use: over the 60 MB budget. In isolation a
  load-and-release gives it back (225 → 44 MB, three rounds, no growth). Suspects: per-thread ONNX Runtime buffers on
  the pipe's 4 worker threads, which run the questions, and SQLite's cache. Next step: encode questions on one
  dedicated thread and measure.
- Meaning search p90 118 ms and max 187 ms while typing: the ranking, plus both encoders on every keystroke.

## 2026-11-19: engine baseline with `tools/measure.py`, and the Phase 1 engine diet

- **Commits:** baseline `b945911` (= `find-flutter-prototype` `1e8a1e2` + the harness); after = the Phase 1 commit on
  branch `find-measure`.
- **PC:** the maintainer's (i5-12500H, 16 threads, 15.7 GB, Iris Xe, Windows 11 26300). Nothing else heavy running.
- **How:** `python tools/measure.py --files 3000 [--entry launch]` (dev only, see its docstring). 3,000 generated files
  (750 txt, 390 png, 360 pdf, 300 docx, 300 py, 240 md, 240 csv, 150 html, 150 json, 120 eml; 7.5 MB) → 5,161 index
  entries, 2,790 with text, 8,314 chunks. Each level runs on a fresh temp index with the level fixed
  (`NOBAD_FIND_MEASURE_LEVEL`) and its own pipe (`NOBAD_FIND_MEASURE_PIPE`), so it can run next to another engine.
  The harness samples every process in the engine's tree once a second. No models: the meaning and photo models
  aren't downloaded on this PC, so ONNX Runtime isn't in these numbers. Only processes the harness started were
  stopped, by PID.
- **`--entry launch`** starts the engine through `packaging/launch.py`, the script `NobadFind.exe` runs. That matters:
  a pool worker runs the parent's entry *script* again, but multiprocessing never re-runs a package's `__main__`, so
  `python -m nobadfind` workers looked fine while the shipped exe's didn't.
- Private = committed memory (`PagefileUsage`), working set = RAM in use, both summed over the tree. CPU % is of one
  core. Means over the scenario's samples, then the max.

### The ~4 GB commit, found

| | Private while indexing, Gentle (mean / max) | Full | Per text reader | Engine alone, idle |
|---|---|---|---|---|
| Baseline, `--entry launch` (like the exe) | **4,460 / 4,866 MB** | **8,002 / 8,474 MB** | 544 MB | 518 MB |
| After | **390 / 608 MB** | 549 / 689 MB | ≤ 60 MB | 34 MB |

Both causes come from numpy's OpenBLAS. As it loads, it commits about 32 MB per CPU thread: 515 MB on 16 threads
(measured: 1 thread 19 MB, 2 threads 53 MB, 4 threads 120 MB, 8 threads 255 MB, 16 threads 525 MB).
1. `packaging/launch.py` imported `nobadfind.app` at the top, so every worker of the exe loaded the whole app, numpy
   included (`-X importtime`: 0.78 s, 0.68 s of it numpy). Now the import comes after `freeze_support()`. A reader
   imports only `extract`: 35 ms, down from 219 ms, now that mail parsing loads only for .eml/.mbox files.
2. The main process paid the same cost. `nobadfind/__init__.py` now loads numpy with `OPENBLAS_NUM_THREADS=1`, then
   puts the variable back so programs Find opens don't inherit it (a value the user set wins). One thread is as fast
   or faster for Find's numpy work: scoring a 65,536 x 384 block takes 47.8 ms on 1 thread vs 47.4 ms on 16; the PCA
   fit (SVD of 8,000 x 384) takes 0.47 s on 1 thread vs **4.1 s** on 16.

### Indexing got 3-6x faster: background mode was thrashing the readers

Windows background mode (`PROCESS_MODE_BACKGROUND_BEGIN`) is what every worker used. Entered as a process starts, it
pins the working set near 32 MB, and a reader parsing PDFs then page-faults constantly. 30 PDFs in a real pool worker
took **6.2 s with 3.0 million page faults** (4.6 s of it kernel time), against **0.31 s and 7 thousand** at normal
priority. Workers now set the three priorities themselves (`winapi.worker_priority`): idle CPU class, low memory
priority (2) and very low I/O priority (0). Measured per process: memory 2, I/O 0 (before: 1 and 0, through
background mode).

| Indexing 3,000 files | Baseline `-m` | Baseline `--entry launch` | After (both entries) |
|---|---|---|---|
| Gentle (8 readers, 35 % CPU cap) | 17.1 s, 394 % CPU | 51.1 s, 547 % CPU | **15.0 s**, 180 % CPU |
| Full (15 readers, no cap) | 16.4 s | 58.3 s | **10.0 s**, 390 % CPU |
| Light (meant to be 1 reader, 15 % cap; EcoQoS on) | 50.1 s | | **31.0 s** (with up to 8 readers: see the correction below) |

For the same files, the workers' CPU time fell from 56 core-seconds (baseline `-m`) to about 25. The working set
while indexing is higher (Gentle 308 → 515 MB mean) because the readers are no longer squeezed into 32 MB each. Low
memory priority puts those pages first in line when Windows needs memory back.

### Every scenario, after (`--entry launch`, Gentle; baseline in brackets)

| Scenario | Procs | Working set MB (mean / max) | Private MB (mean / max) | CPU % mean | Handles | Threads |
|---|---|---|---|---|---|---|
| Cold start (5 s) | 2 | 50 / 54 (53 / 56) | **32 / 34** (515 / 519) | 7.1 (12.7) | 365 | 12 (27) |
| Idle, no UI | 2 | 54 (56) | **34** (519) | 0.0 | 365 | 12 |
| Indexing, Gentle | 17 (10)¹ | 515 / 783 (332 / 344) | **390 / 608** (4,460 / 4,866) | 182 (547) | 3,393 | 78 (215) |
| Idle, UI connected | 2 | 88 (90) | **62** (545) | 0.0 | 448 | 16 |
| Search typing | 2 | 96 (98) | **70** (554) | 13.5 | 449 | 13 |
| Window closed (`ui_hidden`) | 2 | **17** / 97 (91 / 99) | **64** / 71 (546 / 554) | 0.1 | 450 | 14 |

The 2 processes are the engine and its console host (it was started from a console). The engine is ready in 0.39 s
and gives its first pipe answer at 0.66 s. Search typing over the pipe (114 keystrokes, 10 questions): round trip
median 2.6 ms, 90th percentile 78 ms, max 94 ms, with 9 keystrokes over 80 ms (baseline: 2.9 / 69 / 105 ms, 5 over).
The pipe adds well under 1 ms. The slow keystrokes are short words that hit text inside files (as in the prototype
run below); that's ranking work, still open.

### Each change, and what it bought

| Change | Before → after | Kept because |
|---|---|---|
| `launch.py` imports the app after `freeze_support()` | 544 → ≤ 60 MB private per reader (exe) | it was the 4 GB commit |
| numpy with one OpenBLAS thread | engine 518 → 34 MB private idle; PCA fit 4.1 → 0.47 s | win |
| Mail parsing imported only for .eml/.mbox | reader import 219 → 35 ms | win (readers restart, see below) |
| `worker_priority` instead of background mode | Gentle 51 → 15 s, Full 58 → 10 s; 3.0 M → 7 k faults per 30 PDFs | win |
| `EmptyWorkingSet` when indexing goes idle (window closed) | closed: 91 → 17 MB working set (engine 10 MB) | win |
| Text readers end after 200 files (`max_tasks_per_child`, replaced, see the correction below) | no growth to give back on this corpus (readers ≤ 60 MB); a restart costs ~35 ms of imports | backstop for pdf/zip heap fragmentation |
| Worker job memory limit (`JOB_OBJECT_LIMIT_JOB_MEMORY`, ¼ of RAM, 1-4 GB) | 4 GB on this PC; normal indexing commits ≤ 0.7 GB | backstop above the watchdog: a worker over it gets a `MemoryError` (already handled) instead of the PC paging. The baseline exe (8 GB at Full) would have hit it, so the import fix had to come first |
| EcoQoS for workers at Light and Paused only | Light 31 s with it; in a test run with EcoQoS at Gentle too, a thrashing reader was 1.6x slower again | Light and Paused mean a game, a call or a busy PC, where staying out of the way matters most; Gentle and Full keep full clocks. The power saving can't be measured here |
| ONNX Runtime arenas | not measured: no model on this PC (and no download) | open |

**Correction (review of #78, 2026-11-19).** ¹ `max_tasks_per_child` on Python 3.11 grows the pool to
`max_workers` (the Full count, 15) each time it replaces a reader, so these runs had up to 15 readers at Gentle
and 8 at Light instead of 8 and 1. The Light time above is therefore with more readers than Light allows. Readers
are now recycled by starting a fresh pool every 200 files per reader, with a test on the process count. The
model runs in the next section use the fixed code.

### Against the ROADMAP budgets

| Budget | Target | Now |
|---|---|---|
| Indexing, Gentle, 16-thread PC | ≤ 600 MB private total | **390 MB mean, 608 MB max** (no models). Met on average. The max came from 15 readers alive at once (the correction below) |
| Window closed (idle process) | ≤ 60 MB, CPU ≈ 0 % | **17 MB working set** (engine alone 10 MB), **64 MB private**, 0.1 % CPU. Private is 4 MB over: Python, SQLCipher, the pipe server and their threads |
| Engine with the window open, idle, models released | ≤ 120 MB | 88 MB working set, 62 MB private |
| Cold start to usable engine | ≤ 1.5 s (window) | engine 0.39 s, first pipe answer 0.66 s |
| Search keystroke | ≤ 80 ms names | median 2.6 ms; 9 of 114 over 80 ms (short words matching text inside files) |
## 2026-11-19: UI round 2 (sidebar, compact density, size cap), Phase 3

- **How:** release build, fake engine, window sized with `SetWindowPos` (it can no longer be maximized), 10 s to
  settle, 15 s idle, on the 1920 x 1200 (125 %) screen. Same counters as the section below. Measured before the
  last polish commits (flat rows, Windows icons); later on-screen runs were not allowed (the maintainer's desktop),
  so these were not repeated.

| Window | Working set | Private | GPU memory | CPU idle | Frames per 5 s, settled |
|---|---|---|---|---|---|
| 1180 x 760, Home | 163-167 MB | 163-165 MB | 58 MB | 0.5-0.9 % (pointer moving over it) | 0-25 |
| 1440 x 900 (the largest), Home | 148 MB | 150 MB | 62 MB | 0.03 % | 0 |
| 1180 x 760, after every page (tour, no captures) | 160 MB | 158 MB | 57 MB | 0.05 % | 0 |
| Quick find bar hidden after focus loss | 1.7 MB | | | | |

Runs that capture every page to PNG in-process end at 220-260 MB: that is the captures, not the UI. Still over the
100 MB window budget, for the reason below (the GPU driver in-process).

## 2026-11-19: frosted glass redesign, maximized (Phase 3)

- **How:** release build, fake engine (`NOBAD_FIND_FAKE_ENGINE=1`), the window maximized on the 1920 x 1200 (125 %)
  screen, 10 s to settle, then 15 s idle. RAM from `Get-Process`; GPU from the `GPU Process Memory` and
  `GPU Engine` counters for the UI's PID; frames from `NOBAD_FIND_UI_FRAMES` (frames drawn per 5 s).

| Maximized, Home, idle | Working set | Private | GPU memory | GPU busy | CPU | Frames per 5 s |
|---|---|---|---|---|---|---|
| Before (the first full UI) | 152 MB | 156 MB | 76 MB | 0.7 % | 0.05 % | 10 (caret) |
| Redesign, with Flutter blur on the palette (sigma 28) | 296 MB | 300 MB | 117 MB | 2.8 % | 0.16 % | 10 (caret) |
| Redesign, palette blur sigma 12 | 201 MB | 210 MB | 79 MB | 1.5 % | 0.05 % | 10 (caret) |
| **Redesign as shipped** (blur only in dialogs) | **163 MB** | **167 MB** | **72 MB** | 1.2 % | 0.1 % | 10 (caret) |
| Redesign as shipped, window not focused | 160 MB | 163 MB | 73 MB | 0 % | 0.03 % | **0** |

The redesign costs about 11 MB more than the first full UI, mostly the variable font file registered for the thin
display weights (1.8 MB on disk) and the larger glass layers. Flutter's `BackdropFilter` over the palette cost
40-135 MB with only the still backdrop behind it, so it is used for dialogs only; the frost is Windows' Mica (and
Acrylic for the bar), composited by Windows outside this process. Idle and focused, the only frames are the text
caret blinking in the search box (about 2 a second); not focused, nothing is drawn.

## 2026-11-19: full Flutter UI (Phase 3)

- **Branch:** `find-flutter-ui` (draft PR #77), Flutter 3.50, release build, Skia, the same PC as below.
- **How:** the UI process only (`Get-Process` on its PID), sampled once a second. Engine: `python -m nobadfind --engine`
  from source on a throwaway data folder (`NOBAD_FIND_DATA_DIR`) with a 362-file made-up corpus. The UI typed its own
  searches (`NOBAD_FIND_UI_DEMO=1`) or went through every screen (`NOBAD_FIND_UI_DEMO=tour`).

| UI process | Working set | Private | Notes |
|---|---|---|---|
| Main window, Home, just started | 128 MB | 128 MB | real engine |
| Main window after 5 searches | 140 MB | 139 MB | real engine |
| Main window after every screen, dark and light, then 10 s idle | 150-168 MB | 150-162 MB | real engine and fake engine runs |
| Quick find bar, shown with 8 rows | ~140 MB | ~130 MB | |
| Quick find bar, hidden (Esc) | 2-10 MB | 109 MB | hiding empties Skia's cache and the working set |

Skia's GPU resource cache, after the full tour (fake engine): 8 MB cap → 145 MB, 12 MB → 150 MB, 24 MB → 163 MB,
64 MB → 212 MB, 256 MB (Flutter's default) → 207 MB and still growing. The UI caps it at 12 MB
(`NOBAD_FIND_SKIA_CACHE_MB`) and empties it while hidden. The ≤ 100 MB window budget is still missed, as for the
prototype: about 100 MB of each number is the Intel D3D11 driver loaded in-process.

## 2026-11-18: Flutter prototype vs the 0.7.0 WebView2 window (ROADMAP Phase 3 step 1)

- **Commit:** `610921b` (branch `find-flutter-prototype`), Flutter 3.50 stable (Dart 3.14), release build, Skia renderer.
- **PC:** the maintainer's: Intel Core i5-12500H (16 threads), 15.7 GB RAM, Intel Iris Xe, Windows 11 Home 26300.
- **Corpus:** 3,000 generated files (text, Markdown, CSV, JSON, code, small PNGs; 9.9 MB), 2,702 index entries,
  in a temp data folder (`NOBAD_FIND_DATA_DIR`). Same corpus and data folder for every row.
- **How:** a dev-only PowerShell harness (not committed) starts the engine (`python -m nobadfind --engine`, from
  source) and the UI, lets the UI type five fixed searches into its own box (`NOBAD_FIND_UI_DEMO`, one letter
  every 120 ms), then samples memory. The WebView2 row is the 0.7.0 app (`python -m nobadfind`, from source) on
  the same data folder, with its window open about 20 s. Only processes the harness started were stopped, by PID.
- The PC was locked for the first runs, so there are no screen captures from them; the UI saved pictures of itself.

### The window (what the move to Flutter changes)

| Window | Processes | Working set | Private | Notes |
|---|---|---|---|---|
| 0.7.0 WebView2 window, idle, same corpus | 7 | **465 MB** | 238 MB | today's UI (ROADMAP §2 measured 425 / 212 MB on the full index) |
| Flutter main window, just started | 1 | 114 MB | 114 MB | home screen, connected |
| Flutter main window, after 5 searches (up to 500 results, previews) | 1 | **132 MB** | **132 MB** | 20 s later: 132 / 132 MB |
| Flutter quick find bar, shown, 8 results | 1 | 132 MB | 121 MB | |
| Flutter quick find bar, hidden (Esc) | 1 | **8.6 MB** | 110 MB | hiding hands the working set back to Windows |
| Flutter main window with Impeller (Flutter's default) | 1 | 183 MB | 187 MB | after searches; not used, see below |
| Flutter, no engine, home screen only (floor) | 1 | 118 MB (Skia) / 172 MB (Impeller) | 117 / 176 MB | |

Where the Flutter window's memory goes (floor, Skia, `VirtualQueryEx`): 104 MB private, 205 MB image (DLLs, mostly
shared), 54 MB mapped. Most of the private part is the GPU driver: Intel's D3D11 driver and its shader compiler
(`igc64.dll`, an 83 MB image) load in-process because Flutter draws with ANGLE on Direct3D 11. Flutter itself is
`flutter_windows.dll` (20.5 MB) + the app's AOT code (5 MB). The WebView2 window pays the same driver cost in its
GPU process, on top of the browser.

**Result: the window drops from 465 MB in 7 processes to about 130 MB in one (−72 %).** That's still over the
ROADMAP target of ≤ 100 MB for the window. The rest is mostly the Intel driver; see "What would get it under 100 MB".

### Start and search

| What | 0.7.0 WebView2 | Flutter prototype | Target |
|---|---|---|---|
| UI process start to first frame | n/a (the window shows 1.8 s after the app starts, engine included) | **0.20 s** main, **0.13 s** bar (Impeller: 0.84-0.99 s) | ≤ 1.5 s cold start |
| Pipe + JSON round trip on top of the search | n/a (pywebview bridge) | **≤ 1 ms** (UI time − engine time; 4 ms for 500 results) | |
| Search keystroke to answer, engine side, 2,702 files (last 40 searches in the log) | not measured | median **2.8 ms**, 90th percentile 98 ms, max 122 ms; 6 of 40 over 80 ms, all short words that also match text inside files | ≤ 80 ms names, ≤ 250 ms meaning |

The engine log (`rpc search … ms (ranking … ms)`) and the UI timing file agree: the pipe adds under a millisecond;
the time is the ranking in `search.py`. Short words that hit text inside files (e.g. "tax": 95-121 ms) are over
the 80 ms names budget: that's Phase 1 engine work, not the UI.

### The engine (unchanged by the prototype, for reference)

| Engine | Processes | Working set | Private |
|---|---|---|---|
| `--engine`, idle after indexing, UI connected | 3 (venv launcher, console host, engine) | 132 MB | 567 MB |
| 0.7.0 app's engine process (same corpus) | 1 (+7 WebView2) | 147 MB | 583 MB |

The engine commits about 560 MB with nothing loaded: the Phase 1 "commit" problem (ROADMAP §2 cause 2), seen here
on a small index too. Running it headless doesn't change it.

### Impeller vs Skia (why the prototype uses Skia)

Same build, same runs, `NOBAD_FIND_RENDERER` switch: Impeller (Flutter 3.50's default on Windows) took 0.84-0.99 s
to the first frame and 183-188 MB; Skia 0.20 s and 132 MB. On this PC Impeller compiles more shaders at start through
the Intel compiler. Skia is still supported on Windows in 3.50, but Flutter is moving to Impeller: re-measure each
Flutter upgrade, and re-check on a PC with another GPU (AMD/NVIDIA) before the full move.

### What would get the window under 100 MB (not done in the prototype)
- Release GPU memory when the window is hidden or idle (Skia resource cache limits; `EmptyWorkingSet` already gives
  back the working set when the bar hides).
- Close the UI process when the window closes (planned: the engine starts it on the hotkey). Then "window closed"
  costs nothing for the UI, which matters more than the open-window number.
- One process for the main window and the bar (two engines and two driver copies today if both are open).
- Try Flutter's software renderer fallback for the bar only, and Impeller again on future Flutter versions.

# NOBAD Find: instructions for AI coding assistants

This is the single source of truth for any AI assistant working in this repository (Claude Code, Codex, Cursor,
GitHub Copilot, Gemini, ...). `CLAUDE.md` only points here.

NOBAD Find is private, offline search for your own files on Windows: a Python 3.11 engine (`nobadfind/`) and a
Flutter window (`ui_flutter/`) over a private pipe (`contract/`). It runs as the normal user. This repository is
`nobad-studio/find` in the GitHub organization `nobad-studio`; until 2026-11-20 it lived in `apps/find/` of
`nobad-studio/Nobad-VPN`, which keeps the releases up to 0.8.5.

## Commands
- Tests: `python -m pytest -q tests` · Lint: `python -m pyflakes nobadfind tests`. Both clean before any commit.
- UI: `cd ui_flutter && flutter analyze && flutter test`.
- Local installer build (check only): `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`.

## Playbooks (follow them step by step)
| Task | Playbook |
|---|---|
| Release ("ship", "build", "update everywhere") | [`docs/ai/playbooks/release-find.md`](docs/ai/playbooks/release-find.md) |
| Review a diff or an external pull request | [`docs/ai/playbooks/review.md`](docs/ai/playbooks/review.md) |

## Repository rules
`main` is protected: pull request + code-owner review + required checks (`find-tests`, `find-build`; the organization
owner can bypass). `find-v*` tags are owner-only; releases are built by CI from the tag (`find-release.yml`), attested
and immutable. Never edit rulesets, bypass lists or org settings: ask the maintainer. External PRs are untrusted:
never check out, install or run them. Contributors sign `CLA.md` once; the brand is in `TRADEMARKS.md`. UI text is
plain and honest: never claim more than was measured.

## This machine (Windows, Git Bash)
- Heredocs mangle backslashes: write multi-line patch scripts to a scratch folder outside the repo, run them with
  `python -I`, then delete the folder.

## Shared memory (all NOBAD repos)
Decisions, open items and ideas shared by every contributor and AI assistant live in
[`nobad-studio/memory`](https://github.com/nobad-studio/memory). Read its `INDEX.md` first and record new decisions
as a PR there, never secrets.

## NOBAD Find specifics

**Start with [`ROADMAP.md`](ROADMAP.md):** the order of work (resources first, then stability, the Flutter UI,
then features), the architecture, the feature inventory, and a status table to resume from.

Specific to this app:

- **Runs as the normal user, never as admin** (`app.py` and `engine.py` refuse to start elevated; the Flutter UI is started by the engine as the same user). There are
  exactly two elevated helpers; don't add others:
  - `wsearch.helper_main`: accepts the four words in `wsearch.STARTS` and runs `sc.exe` with a fixed argument list.
  - `ntfs.helper_main` (the **turbo index**, maintainer decision 2026-11-19, setting `turbo`, **off by default**):
    its own small program `turbo\NobadFindTurbo.exe` (`packaging/turbo_launch.py`; no models, OCR, numpy or
    SQLCipher), accepts only the words in `ntfs.WORDS` (`install`, `remove`, `service`; from source only `serve`,
    `selftest`), reads NTFS metadata (MFT enumeration, file records, change journal), never file contents. It
    drops other users' profiles, recycle bins, System Volume Information, NTFS metafiles, everything outside the
    user's scope and categories, and folders the user couldn't list (AccessCheck with the connected client's own
    token) before anything leaves it; the engine applies its own rules again. Read the docstrings of `ntfs.py` and
    `turbosvc.py` before changing it. Content reading (text, OCR, models) stays in the normal-user workers.
    **Maintainer decision 2026-11-21 (replaces "one UAC prompt per engine run"): administrator rights are asked for
    ONCE, when the user turns turbo on.** The elevated `install` step copies only the helper's folder (verified
    SHA-256 manifest, each file from one handle, checked again after the copy) into `<Program Files>\NOBAD Find
    Turbo\bin` (DACL SYSTEM/Administrators full, Users read; a reparse point or a weaker existing DACL is refused),
    records the installing user's SID (from Windows, never the command line) and NobadFind.exe's path in
    `install.json` there, and registers the demand-start service `NOBADFindTurbo` (LocalSystem with its privileges
    cut to SeChangeNotify + SeManageVolume; only that user may start/stop/query it). The engine starts it with no
    prompt and is the pipe's CLIENT; the service trusts nothing the engine claims: it checks the client's token SID,
    session, integrity, elevation and image against the record (and that the client's pid wasn't reused) and fails
    closed; it also checks itself each run (code only from its protected `bin`, a one-folder build; none of
    `turbosvc.POWERFUL_PRIVILEGES` in its token). The protected copy is only
    changed by an elevated step: a changed helper shows "needs update" and the normal walk until the user OKs it;
    turning turbo off, Remove and `--uninstall` delete the service and folder (one prompt).
  Tests never trigger UAC or install a service: fakes for the service manager and the folder DACL steps, synthetic
  USN/MFT buffers, and the pipe's DACL and both ends' identity checks on a real, unelevated pipe. From source the
  helper is dev only and refuses without `NOBAD_FIND_DEV_TURBO=1`; don't relax that (the prompt would name
  python.exe, imports come from the source tree), and `install`/`remove`/`service` always refuse from source.
- **Out of scope (maintainer decision 2026-11-17):** no activity timeline or usage history (Recent items, browser
  history, event logs, programs run). Indexing is the normal-user folder walk (`walker.py`) plus folder-change
  notifications (`watcher.py`); the turbo helper above is the one optional exception for names and changes.
  The one thing kept is the user's **own typed search questions** for autocomplete (maintainer decision 2026-11-19,
  `history.py`, setting `search_history`, on by default): inside the encrypted index, at most 200, "Clear search
  history" in Settings > Privacy, off deletes them. Never read anything Windows or other programs record. The one
  exception is the user's **opt-in to read app files that hold secrets** (maintainer ruling 2026-11-22, setting
  `secret_app_files`, **off by default**, `const.APP_SECRET_*`): command histories, FTP/SSH tools' saved sites and
  logins, developer tool tokens and `.env` files, read into the encrypted index only after the confirm dialog in
  Settings > Privacy that names them and says they may hold passwords and tokens and can appear in results (the
  engine turns it on only with `set_settings` `consent: "READ_APP_SECRETS"`, sent after that yes); a read that
  finishes after it went off is dropped (`Store.set_text` `allow`, checked under the write lock); off
  removes their content (and their rows while secrets are off) with a targeted purge (`Api._purge_app_files`), no
  rebuild. Recent items and jump lists stay out whatever it says.
- **Everything indexed is untrusted:** file names, folder names and file contents go to the UI only through
  `esc()`; FTS queries only through `store.fts_quote`; nothing builds a shell string; files are never executed
  except by the user's explicit Open (by result id, never a path from the page). Names, folders, snippets, drive
  and app names are drawn with direction controls and invisible characters made visible (`[U+202E]`; Dart
  `safe_text.dart` at parse time, Python `display.visible` in sentences the engine builds; one list in both), and
  a disguised name's details say its real extension (security review 2026-11-22, L7).
- What's indexed follows `scope.Rules` (maintainer decision 2026-11-19: nothing skipped silently; every category
  is shown by `scope_info`): system folders and caches are user choices (default on), secrets (`const.SECRET_*`:
  keys, browser passwords/cookies/history, Windows Credentials/Vault/Protect, chat and developer tokens, wallets,
  and what other programs record: PowerShell/shell/REPL command histories, FileZilla/WinSCP
  saved sites, GitHub CLI/Maven/Cargo/Terraform tokens; security review 2026-11-22) are
  off by default and **names only** when on (never read, never thumbnailed), except the `APP_SECRET_*` part while
  `secret_app_files` is on (above); `.env` files are names only until then. The lists are data in `const`
  (`SECRET_NAMES`, `SECRET_FILES`, `SECRET_FILES_IN`, `SECRET_PATHS`, `APP_SECRET_*`, `NAMES_ONLY_*`); growing one bumps
  `scope.RULES_REV`, and the indexer then drops the content of the newly covered files once
  (`Indexer._apply_new_rules`, meta `scope_rules`) without rebuilding anything else. Browser profiles and app databases
  (`const.NAMES_ONLY_*`) are names only even with caches on, other people's files and
  `const.FIXED_NAMES` and `const.ALWAYS_OUT_PATHS` (Windows' and Office's Recent items and jump lists in the
  user's profile, `Rules.always_out`: their names are the activity history ruled out above) are always out. The walk, `Walker.excluded` (live changes) and the turbo helper's `ntfs.Filter`
  all use `scope.Rules`; keep them in step. What Forget adds to `exclude` is never written in plain text: `Settings`
  keeps it in `forgotten.dat` next to settings.json, DPAPI-protected for the user (fix round 1, I5); in memory
  `exclude` holds both, so the walk, the turbo filter and the Never index list see one list. When that file
  can't be read or written, new entries stay in memory (a note says so, every save tries again), never in
  settings.json, and the one-time move isn't marked done while entries are still there.
- OCR (`ocr.py`) uses only the Windows built-in `Windows.Media.Ocr` through the pinned `winrt-*` 3.2.1 packages
  (keep every winrt package on one version), inside the text worker processes. No OCR model downloads.
- Call detection (`winapi.in_call`) reads the user's own CapabilityAccessManager records; stale records from
  crashed apps must not pause indexing forever (age limit + process check).
- `--uninstall` (run by the installer's uninstaller) only undoes what the app changed outside its data folder.
- The index is SQLCipher with a DPAPI-protected key. The only outbound connections are the in-app update check
  and download (`update.py`, maintainer decision 2026-11-20: HTTPS to GitHub for nobad-studio/find only, the
  check once a day while `update_check` is on, the installer only after the user's Install, run only when its
  size and SHA-256 match the release's .sha256 file and GitHub's digest) and the optional model
  downloads, all through `embed._fetch_verified` (HTTPS, exact size, SHA-256) from the pinned entries in
  `models.CATALOG`, each only after the user's consent (`model_download` with `consent: "DOWNLOAD"`, stored as
  `allow_model_download` / `allow_photo_model_download`). The llama.cpp runtimes for talk about a photo
  (`llama-cpu`, `llama-vulkan`, find 1.1) are one of those downloads: the pinned b12602 release zip over HTTPS from
  `github.com/ggml-org/llama.cpp/releases` (GitHub redirects to its `*.githubusercontent.com` asset host),
  unpacked by `vlm/runtime.py` to only the DLL names pinned in `llama_pins.py` (each size-capped and SHA-256
  checked, the zip deleted), and `vlm/llama_api.load` loads only the pinned backend DLLs, one by one, never
  `ggml_backend_load_all_from_path` and never `ggml-rpc.dll`. The talk models (`smolvlm2-500m`, `qwen3vl-2b`) and
  the runtimes store NO consent: each download is the user's click on one dialog that names the talk model and
  the runtime this PC needs (`models.talk_runtime`), both sizes and the total and both hosts (huggingface.co;
  github.com), in Settings → Models or on the photo's talk panel. A new model needs a catalog entry with its revision, file
  sizes and SHA-256s, a measured row in `docs/measurements.md` (`tools/eval_text.py`) and a permissive licence
  (OpenAI CLIP's model card rules out deployment, so it isn't used).
- Vectors carry their model's id (`meta vec_model`, `pvec_model`); a search never compares vectors from two models
  (`search._meaning_hits` / `_photo_hits` check it). A text-model switch rebuilds beside the old vectors
  (`vecs_next`) and swaps them in one transaction. So does a new photo vector identity (another photo model or a
  re-pin, `models.vector_tag`): `pvecs_next` + `meta pvec_next_model`, the old set answering in its own search
  channel until the new one covers every photo (`indexer._load_photo` / `_finish_photo_rebuild`). Never drop a
  working vector index on an identity change, and test the upgrade from the last release's index.
  A photo re-pin (`"vectors"` bumped) that changes the text side too must also set `"vectors_text": True`: the
  old vectors are then never asked with the new text half (they can't answer during the rebuild).
- Photos for photo meaning are decoded only by Windows' decoders in the one photo worker process (`photo.py`).
  Result previews come from Windows' thumbnail cache (`thumbs.py`), asked for by result id, never a page path.
- Models are `embed.Lazy`: loaded on use, released when idle. Don't hold a model outside that wrapper. The one
  exception is talk about a photo (find 1.1): the talk model lives only in the **talk worker** process
  (`vlm/worker.py`, a spawn child in the WORKERS job, one model resident, one question at a time), driven by
  `worker.Talker` in the engine; it follows the same rules (released after `IDLE` = `embed.Lazy.IDLE` seconds, on
  a pause or memory pressure, before a runtime reinstall), and the WORKERS commit limit is raised by the model's
  measured need while it is loaded (`models.talk_need_mb`: `max(ram_mb, vram_mb)` on Vulkan, `ram_mb` on the CPU).
  It stays under the governor's CPU cap and EcoQoS like every worker (maintainer ruling: the user's level wins), so
  its seconds are measured per runtime and level (`tools/measure_talk.py`, catalog `timing`, `models.talk_timing`)
  and the UI says only those. Talk models never use DirectML: `models.capable` has their own check.
  Photos reach it only by result id; it opens only the job's photos and the model / runtime files on disk.
  **Release fix (maintainer requirements 2026-11-22):** its hang deadline counts only real progress, per phase
  (`worker.PHASES`: llama's and mtmd's load fractions must grow, "still computing" from the encode / eval
  callbacks is capped per phase, tokens while answering, fixed bounds where llama.cpp has no callback); never
  turn the watchdog off or just raise a bound. Stop (and the engine's own stops) reach a load or an eval through
  those callbacks. While a job runs the worker's memory and I/O priority are normal (`winapi.worker_activity`),
  low again when it ends; its CPU priority, the job and the CPU cap never change. Whether a talk model can run now
  is `capability.assess` only (`api.talk_assess`), with its measured need on the runtime this PC uses
  (`models.talk_need_mb`: on Vulkan max(ram_mb, vram_mb), counted against system RAM); no fallback
  (`tests/test_vlm_progress.py::test_no_fallback_left`).
- Typed network paths (\\server\share) are never looked up on disk (`search.folder_checker`): only folders already
  in the index or the folder list count, so typing one can't make Windows contact a server.
- New setting: `const.DEFAULTS` + `settings.coerce` + a row on its Flutter Settings page
  (`ui_flutter/lib/features/settings/pages/`) + `contract/methods.schema.json` (`$defs/settings` and `settings_changes`).
- The window is the Flutter UI only (`ui_flutter/`, `nobad_find.exe` next to `NobadFind.exe`, started by
  `uilaunch.py`). The old pywebview UI was removed in 0.8.5; don't add a web view, a local server or pywebview back.
- The UI ⇄ engine pipe (`nobadfind/rpc/`) follows `contract/`: a new or changed method or event updates the schema,
  `contract/README.md`, a transcript (`python tests/test_rpc_contract.py --record`) and the Dart side together.
  Handlers stay thin (check params, call the `Api` method, shape the result); files only by result id.
  Both ends check the other (security review 2026-11-22, M1; keep the DACL too): the UI sends nothing until the
  pipe's owner is this user and its server process is `NobadFind.exe` next to `nobad_find.exe` (from source:
  Python) at medium integrity outside any AppContainer (`pipe_client.dart` `engineProblem`, `Link.untrusted`); the
  engine drops a client whose token is below medium or in an AppContainer (`rpc/server.py` `client_problem`).
- Tests: `python -m pytest -q tests`. Lint: `python -m pyflakes nobadfind tests`. Both clean before a commit.

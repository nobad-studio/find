# NOBAD Find: the UI ⇄ engine contract

The only thing the Flutter UI and the Python engine know about each other. If code and this folder disagree, the
tests fail (`tests/test_rpc_contract.py` on the Python side; the Dart side replays the same transcripts).

| File | What it is |
|---|---|
| [`methods.schema.json`](methods.schema.json) | Every method: JSON Schema of its `params` and its `result`, plus shared shapes in `$defs` |
| [`events.schema.json`](events.schema.json) | Every event the engine pushes: JSON Schema of its `params` |
| [`transcripts/*.jsonl`](transcripts) | Recorded sessions, replayed by both test suites |

Protocol version: **1** (`"protocol"` in both schema files and in `hello`'s answer). Version 1 only ever grows:
new methods, new events, new keys in an answer. A change that breaks an old UI raises the version.

## The connection

- Pipe `\\.\pipe\NOBADFind-<user SID>`, only for the current user, no remote clients. Before trusting it, the UI
  checks the pipe's server process runs as the same user (the prototype's `pipe_client.dart` does this).
- JSON-RPC 2.0, **one JSON object per line** (`\n`), UTF-8, at most 1 MiB per line either way. The engine writes
  ASCII only (non-ASCII as `\uXXXX`).
- Requests carry an `id` (number or string). Replies can come in any order: match them by `id`.
- Events are notifications (no `id`): `{"jsonrpc":"2.0","method":"<event>","params":{...}}`. Ignore event names you
  don't know.
- Errors: `{"jsonrpc":"2.0","id":…,"error":{"code":…,"message":"…"}}`. Codes: `-32700` not JSON, `-32600` not a
  request (also "Message too big", after which the engine closes the pipe), `-32601` unknown method, `-32602` bad
  params, `-32603` the engine failed (never with details). Wrong *types* are errors; a well-formed request the engine
  can't carry out is a normal result with `"ok": false` and a sentence in `"error"`. The engine checks what the
  schema says (types, the filter words, lengths, `seconds ≥ 1`): a request the schema refuses gets `-32602`.
  `NaN` and `Infinity` are not JSON: `-32700`.
- Unknown keys in `params` are ignored by the engine, but the schemas don't allow them: don't send them.
- At most 8 connections. Requests run on a pool of 4 threads, so a slow call doesn't hold up a search; the calls
  that wait for the user (`pick_folder`, `wsearch_set`, `use_instead_of_windows_search`, `turbo_set`, `turbo_helper`) run on threads of their own
  and only one of each waits at a time, so search, status and quit always get an answer.
- State reports (`status`, `status_full`, `hardware`, `capability_state`, `models`, `scope_info`, `turbo_state`,
  `wsearch_state`, `performance_state`; "reports", not "pure": a cold one may run the hardware scan, start a background
  count, or retry saving the forgotten list) run on a small pool of 2 threads of their own, so a slow one never makes a
  search wait. One client may have 2 running and 4 waiting there; the next gets the JSON-RPC error `-32603`
  "busy: try again" at once (no schema change, any method may answer an error). The UI session asks such a call again
  up to 3 times, after 250, 500 and 1000 ms. The cheap `status` beat is answered on the connection's reader thread:
  never refused as busy, never queued behind the others.

### Start-up order for a UI

1. `hello`: check `protocol` is 1 (refuse a newer engine and say why). `pid` is the engine's process id: call
   `AllowSetForegroundWindow(pid)` before `pick_folder` and `wsearch_set`, so their windows can come to the front.
2. `subscribe` to what this window needs (main window: `status level activity download notice show here quitting
   models turbo update notification`;
   bar: `show quitting`). The engine tells the two apart by this (a client with `here` is a main window): a
   `show` for a window no connected UI has starts that UI instead.
3. `status` once (events only report changes), then `ui_shown` when the window is on screen.
4. On `ui_hidden`/close, say `ui_hidden`. If the pipe breaks, reconnect with backoff, unless `quitting` came first.

## Methods

Types below are short; the schema is exact. `Ok` = `{ok: bool, error: string}` (`error` is `""` when `ok`, and may
be `""` when not). Files are always named by a result **`id`** from `search`, never by a path.

### Connection

- **`hello`** `{}` → `{protocol, app, version, pid, events: [string], methods: [string]}`. Who's there.
- **`subscribe`** `{events: [string]}` → `{events: [string]}`: start getting these events on this connection;
  the answer lists everything this connection now gets. Unknown names are ignored. If notices were waiting for a
  listener, they arrive just *before* this reply.
- **`unsubscribe`** `{events: [string]}` → `{events: [string]}`: stop getting them.

### Search and results

- **`search`** `{text?: string (≤ 2000), filters?: Filters}` → `{results: [Result], understood: [string], terms:
  [string], notes: [string], more: bool, ms: int, error: string, parts: [Part], best: BestGuess|null}`. Empty text
  with no filter gives no results.
  `filters` is an object or left out (`null` is refused). `understood`
  is how the question was read (show as chips), `terms` the words to highlight, `notes` sentences for the user,
  `more` = there were more matches than shown, `error` = `""` or a sentence when the search failed.
  - `Filters` (all optional, `""` = off): `kind` (`pdf document spreadsheet slides text code email image video audio
    archive ebook app folder secret`; 0.9.5 `secret` = key files and password stores, names only), `modified` (`today week month year`), `size` (`small medium large`), `folder`
    (`here`, a known folder word, or a folder path already in the index; ≤ 2000), `sort` (`newest oldest largest
    name`). Any other key or word is refused (`-32602`).
  - `Result`: `{id: int, path, name, dir, kind: string, size: int|null, mtime: number|null (seconds since 1970),
    ago: string, why: [string], snippet: string, weak: bool}`. `weak` = a loose match, show it as less sure.
    Every string is untrusted text from the user's disk: show it as plain text, never as markup.
  - `Part` (0.8.5, smart search): `{kind, label, without}`, how the question was understood, in display order
    (where, what kind, when, size, order, then what it's about): `kind` is `folder drive kind time size sort meaning
    words` (`meaning`: what it's about, searched by meaning with a model; `words`: the same by words only). `label`
    is the chip's text ("Downloads", "Images", "2 boys"); `without` is the question with that part taken out, so a
    chip's remove x just searches `without` (the engine stays the one place questions are understood).
    "2 boys in an image in downloads" → `[folder Downloads] [kind Images] [meaning "2 boys"]`, and "2 boys" goes to
    photo meaning restricted to Downloads.
  - `BestGuess`: `{id, reason}`, the one result the engine is sure of (an exact name, the only name that starts like
    what was typed, the only match, the picture that clearly fits best, a clear winner on name and content). When
    there is one it is always `results[0]`, so Enter opens it. `null` when unsure.
  `channel` (optional, default `"main"`): which search of the UI this is (`"home"` for the Home list, `"bar"`). A newer search on the same connection and channel cancels the one still running, which then answers with `cancelled: true` (and no results): ignore that answer. Other channels are left alone.
- **`search` → `needs`** (0.9.0, only when something isn't ready): `[{model: photo|meaning, state: missing|off|analyzing, id, size_mb, done, total, text}]`. A described photo search ("black shirt image") whose photo model isn't downloaded (`missing`: offer `model_download`), is switched off (`off`: offer `set_settings` `photo_meaning`), or is still looking at photos (`analyzing`: `done` of `total`; also while a new photo model or re-pin looks at them again beside the old vectors, which answer until then); a description that found little while meaning search is missing or off. `text` is the sentence to show.
- **`suggest`** `{text: string (≤ 2000), channel?: "main"|"bar"|...}` → `{items: [Suggestion], complete: string}`:
  autocomplete for every keystroke (well under a millisecond on the eval corpus, `docs/measurements.md`). Up to 8
  items (5 for `channel: "bar"`), in order: the user's own past questions (only while `search_history` is on), the
  phrases search understands that complete the last words ("in d" → "in downloads", "ima" → "images", "last w" →
  "last week", folders under the user's folders "in pro" → "in Projects", other drives "on d drive"), then names in
  the index whose words start with the last word typed. `Suggestion`: `{text, kind: history|filter|file|folder,
  label, detail, id?}`: `text` is the whole question to search, `label` what to show (plain text), `detail` a file's
  folder or a filter's kind, `id` a file's or folder's result id. `complete` is the inline (ghost) completion, it
  starts with exactly the typed text, or `""`. It never fails a keystroke: a problem gives no items.
- **`history_add`** `{text}` → `{ok, saved}`: the UI tells the engine a question was used (Enter, a result opened, a
  suggestion picked). Kept for autocomplete inside the encrypted index (at most 200, oldest dropped) while
  `search_history` is on; `saved: false` when it's off or the text is too short. Only the user's own typed questions:
  no activity history (maintainer decision 2026-11-19).
- **`history_forget`** `{text}` → `Ok`: the x on a history suggestion. `ok: false` when it wasn't kept.
- **`history_clear`** `{}` → `Ok`: Settings > Privacy, "Clear search history". Turning `search_history` off clears it
  too.
- **`open`** `{id}` → `Ok`: open with the default program (outside NOBAD Find's process group, so it survives Quit).
- **`open_with`** `{id}` → `Ok`: Windows' "Open with" list for that result. It runs in a small helper started outside
  NOBAD Find's process group, so the program chosen there survives Quit like `open`. By id only, never a path.
- **`reveal`** `{id}` → `Ok`: File Explorer with the file selected.
- **`thumbnail`** `{id}` → `{url: string}`: `data:image/png;base64,…` (or jpeg/bmp) from Windows' thumbnail cache for
  photos, videos and PDFs, or `""` (keep the kind badge).
- **`path_of`** `{id}` → `{path: string}`: for Copy path; `""` if the file is gone.
- **`forget`** `{id}` → `Ok`: remove from the index and add to the excluded folders. `ok: false` with an `error`
  the UI shows when it couldn't be kept out (the list holds at most 5000 entries; nothing is removed then). `ok:
  true` with an `error` (1.1.0) is a note to show instead of "Forgotten": it is out, but the protected list of
  forgotten files couldn't be saved, so it is kept in memory for now (the engine tries again).
- **`here_folder`** `{}` → `{path: string}`: the File Explorer folder the hotkey was pressed in (what "here" means), or
  `""`. The `here` event brings the same value as soon as it is known.
- **`to_main`** `{text?: string (≤ 2000)}` → `{ok: true}`: the bar's Alt+Enter. The engine sends `show {what: "main", text}`,
  so the main window comes up with the same words in its search box.

### Notifications

Crashes, restarted workers, model fallbacks, internal errors, suggestions, updates and long pauses
(`nobadfind/notify.py`, maintainer request 2026-11-21). Kept in memory and inside the encrypted index, at most 100,
newest first. The text never has a file path; `detail` is a file name only while `notify_show_names` is on. The
same kind of event is posted at most once per 10 minutes (its key), and at most 5 an hour also go to Windows as a
local toast (`notify_toasts`, from `notify_level` up, not while a game, a call or a presentation is on with
`notify_quiet`). Nothing goes over the network.

- `Notification` = `{id: int, t: number, kind, severity: info|warning|error, title (≤ 80), body (≤ 300), detail
  (≤ 120), action: null|{id, label}, read: bool}`. `kind` is `worker_crashed worker_restarted model_fallback
  model_released_memory internal_error suggestion update_available turbo_needs_ok indexing_paused_reason` (show an
  unknown kind like any other). `action.id` is `open_indexing open_performance open_models open_turbo update`; the UI
  opens that page (`update`: Settings > About, where Install asks for its own consent). `label` is the button's text.
- **`notifications_list`** `{}` → `{items: [Notification], unread: int}`: the bell's panel.
- **`notifications_read`** `{ids: [int]}` or `{all: true}` → `{ok, error, unread}`: mark read. Unknown ids are
  ignored; anything else (`{}`, `all: false`, both at once, ids that aren't whole numbers) is `-32602`.
- **`notifications_clear`** `{}` → `Ok`: the panel's Clear: every notification goes, from memory and the index.

### Status and the governor

- **`status`** `{}` → `StatusBrief` = `{level, reason, phase, files: int, paused: string}`: the status line.
  `level` is `full gentle light paused` (or `""` before the first decision), `reason` a sentence, `phase` one of
  `starting names text images meaning photos watching error`, `paused` = `""` or why indexing is paused.
- **`status_full`** `{}` → `Status`: everything the Indexing page shows. Always has: the counters (`files texts
  vectors with_text chunks name_vectors photo_vectors errors rate last_scan db_bytes`), `encrypted`, `version`,
  `model`/`photo_model` (`{state: missing|downloading|ready, got, size: bytes, error}`: the text / photo model in use, or the old fixed download while it runs), `memory_mb`,
  `models_loaded`, `admin`, `roots`, `ocr` (`true`, or a sentence saying why Windows OCR isn't there), `drives`
  (`[{root, type, label, present}]`), `level`, `reason`, `paused`, `phase`, `plan`, `history` (the last 5 minutes:
  `[{t, cpu, gpu, find_cpu, find_mb, level}]`, one point per 2 s), `resources` (`{cpu, memory_mb, read_mb_s, gpu,
  processes: [{name, role, about, pid, cpu, memory_mb, private_mb, age_s|null, readable, note}]}`: every process of
  NOBAD Find's own and nothing else, the engine first; `role` is `engine window bar text meaning photo turbo
  open_with ending mp_helper client other`, `memory_mb` the working set, `private_mb` the committed memory, `note`
  `""` or idle/starting/ending/not readable; sampled at most every 2 s; the totals count the UIs too), `phases` (`[{id: names|text|ocr|meaning|photos|watching, label,
  state: off|running|waiting|done, done, total|null, rate, eta_s|null}]`), `models` (cards: `[{id:
  meaning|photo|ocr, name, license, size_mb, on_disk, loaded, memory_mb|null, device, items, download:
  null|{got_mb, size_mb, mb_s}}]`), `activity` (newest first, at most 50: `[{t, kind, text}]`), `limits`
  (2026-11-21: how many of each operation may run at once now, `{walk, readers, photo, vision}`, each `{effective,
  user, cpu, memory, governor, gpu?, by}`: `effective` is the smallest of what the user set, the processor, free
  memory and the governor's level (vision: and the graphics card), `by` names which one set it; recomputed every
  2 s). Other keys may appear (indexer details); ignore them. It answers at once (1.1.1): the index totals (`with_text chunks
  vectors name_vectors photo_vectors`) are counted in the background, one count at a time; until the first count
  is in, `counting_totals` is `true` and they are the indexer's own running numbers or `0` (the Index page says
  "Counting…" for them); `files` is the indexer's live count, and `db_bytes` is always current.
  An engine before 1.1.1 sends no `counting_totals`. 1.2.0: each count says how fresh it is, for the totals (`totals_*`) and the phase counts (`counts_*`): `*_at` (epoch seconds of the last successful count, or `null`), `*_state` (`counting` first count running, `ready`, `refreshing` a newer count is running and the old numbers are shown, `failed` the last attempt failed and the previous numbers, if any, are still shown) and `*_error` (a short plain reason when failed, else `""`); `counting_totals` is `totals_state == "counting"`. A phase ending, a rescan or a wipe makes the next poll count again, never more often than every 10 s. An engine before 1.2.0 sends none of these.
- **`pause_for`** `{seconds: int ≥ 1}` → `Ok`: pause indexing (at most 24 hours; less than 1 is `-32602`).
- **`resume`** `{}` → `Ok`: end a pause now.
- **`learned_apps`** `{}` → `{apps: [{exe, seen: int, lag_events: int, worst_cpu: number|null, worst_gpu:
  number|null, start_level: level|null, last_seen: number|null, reason: string}]}`: what was learned about apps
  NOBAD Find slowed down (program file names only).
- **`reset_learned`** `{exe?: string (≤ 260)|null}` → `Ok`: forget one app, or every app (`exe` null or left out).
- **`hardware`** `{}` → `{ram_gb, cores, threads, avx2, avx512_vnni, gpu, vram_gb, directml, disk_free_gb, ssd:
  bool|null, gpus: [{vendor, name, dedicated_mb, shared_mb, integrated}], backends: {onnx: [...], llamacpp: [...]}}`:
  the "Your PC" facts (measured once per engine run; every adapter listed, shared memory is never video memory;
  a backend is listed only when installed and loadable; `backends` is re-read on every call, so a runtime downloaded while
  the engine runs shows up without a restart).

### Settings and the index

- **`get_settings`** `{}` → `Settings`: every setting (names and types: `$defs/settings` in the schema; they are
  `const.DEFAULTS`).
- **`hotkey_state`** `{}` → `{hotkey: {spec, state}, bar_hotkey: {spec, state}}`: whether each hotkey is registered and working now. `state` is `ok`, `taken` (another app holds it), `reserved` (Windows keeps it), `invalid` or `off` (the quick find bar is off).
- **`hotkey_probe`** `{which: "hotkey"|"bar_hotkey", spec}` → `{state, spec, reason}`: would that combination work, before it's saved? The engine registers it for a moment and lets it go. `same` means the other NOBAD Find hotkey uses it; `reason` is one sentence for Settings. A combination NOBAD Find already holds for `which` is `ok`.
- **`set_settings`** `{changes: {name: value}, consent?: string (≤ 40)}` → `{changed: [string], settings: Settings}`: the engine checks every
  value (`settings.coerce`); a value that doesn't fit becomes the default, unknown names and `wsearch_prev` are
  ignored. `secret_app_files: true` is ignored (not in `changed`) unless `consent` is `"READ_APP_SECRETS"`, which
  the UI sends only after the user's yes in its confirm dialog; turning it off needs no word. `browser_data`
  (1.2.0, `off`|`history`|`history_logins`, **off by default**) is ignored when it would read more than now (`off` →
  `history` → `history_logins`) unless `consent` is `"READ_BROWSER_DATA"`, sent only after the dialog that shows
  what is read; narrowing needs no word. `history` reads the browsers' history, bookmarks and downloads,
  `history_logins` also saved logins' site and user name (never a password value: not decrypted, stored or shown;
  Firefox's user names are encrypted, so only the site). The engine copies each database with full sharing and reads
  the copy in a worker process, so a browser is never closed or blocked. `off` deletes every row it read,
  `history` the logins' rows. `changed` lists what really changed, `settings` is the result. A new hotkey takes effect at once (`hotkeys` in the result says whether each one works); before 0.9.0 it took effect after the
  engine restarts.
  `stay_running` (0.8.5, default off): off, the engine quits when the last UI's pipe closes (its window closed),
  so nothing of NOBAD Find keeps running; on, it stays for the hotkeys and the notification-area icon.
  1.2.0: `performance_goal` (`quiet`|`balanced`|`fast`) decides how hard NOBAD Find works; `power` stays readable
  and writable for older UIs and mirrors it (`fast` ↔ `boost`, anything else ↔ `balanced`): writing a changed
  `power` changes the goal, writing the `power` you read changes nothing, and when both come in one call the goal
  wins. Under `fast` the manual `workers` number isn't used (every thread). The overrides (`gpu_background`,
  `backend_<feature>`, `variant_<model>`, `profile_override_<axis>`, `gpu_reserve_min_mb`) beat the goal but never
  a safety limit (spec 8b rule 0).
- **`performance_state`** `{}` → `{goal, rows: {name: {value, auto, why, options: [string], note}}}` (1.2.0):
  Settings > Performance. One row per override (`gpu_background`, `backend_photos`, `backend_text`,
  `backend_talk`, `variant_siglip2-base`, `workers`, `profile_override_gpu|cpu|storage|memory`,
  `gpu_reserve_min_mb`): its `value`, what `auto` would pick on this PC right now and `why` (one sentence),
  the `options` it may take here (only installed backends; `[]` for numbers), and `note` when the value isn't
  used now (`""` if none). From the cached hardware scan and the plan; ask again after a change.
- **`reset_safe_defaults`** `{}` → `{ok, reset: [string], kept: [string]}` (1.2.0): "Reset to safe defaults". The UI
  asks once first. The goal goes back to `balanced`, every override to `auto` (`workers` to 0, auto) and `gpu_reserve_min_mb` to 512,
  at once (the governor and the plan follow). `reset` names those settings; `kept` is always
  `["index", "models", "privacy", "folders", "learned_apps"]`: the index, the chosen models, privacy settings,
  folders and the learned apps (their own Reset) are never touched.
- **`pick_folder`** `{}` → `{path: string, busy: bool}`: Windows' folder dialog, shown by the engine, topmost;
  `path` `""` if cancelled. The answer comes when the user closes the dialog: **no time limit** on this call. Only
  one dialog at a time: while one is open, another call answers at once with `busy: true` (and `path: ""`) and
  brings the open dialog to the front again; don't treat that as a cancel.
- **`rescan`** `{}` → `Ok`: walk every folder again now.
- **`wipe`** `{confirm: string}` → `Ok`: delete the whole index and start over, only with `confirm: "DELETE"`; any
  other word gives `ok: false` and nothing happens. It also removes the Never index entries Forget added, empties
  the log and deletes old `*.unreadable-*` index copies; settings and the user's own Never index folders stay.

### Models

- **`download_model`** `{}` → `Ok`: download the meaning model; needs `allow_model_download` on (else `ok: false` with a
  sentence). Progress comes as `download` events.
- **`download_photo_model`** `{}` → `Ok`: the same for the photo model (`allow_photo_model_download`).
  Both stay for older UIs (they always fetch MiniLM / SigLIP base); every download button of the UI uses `model_download` below.
- **`models`** `{}` → `{pc: Hardware, tier_recommended: light|balanced|best, tier_current: light|balanced|best|custom,
  language_focus: english|multilingual|hindi, models: [Model]}`. `Model` = `{id, feature: text|photo|ocr, name, tier,
  licence, source, size_mb, ram_mb, speed_note, languages: [string], improves, builtin, state:
  not_downloaded|downloading|ready|active|failed, capable, capable_reason, recommended, quality?:
  {english, hindi}|null}`. `quality`: a text model's measured search quality on the English and Hindi test sets
  (nDCG@10 of the whole search, 0-1). `ram_mb` and `speed_note`
  were measured on the reference PC (0 / "" when not measured); `improves`, `licence`, `size_mb`, `source` and
  `ram_mb` are what the consent dialog shows. `recommended`: in the recommended tier for this PC and language focus.
  The `models` event brings the same object whenever it changes.
  1.1: `feature` may also be `talk` (SmolVLM2 500M and Qwen3-VL 2B, talk about a photo) or `runtime` (the llama.cpp
  runtimes `llama-cpu` / `llama-vulkan` they run on). A talk model also sends `vram_mb` (measured graphics memory on
  Vulkan) and `runtime` (the runtime id this PC uses for it). The UI's one consent dialog for a talk model names the
  model and that runtime (when it isn't on disk yet), both sizes and the total, and both sources (huggingface.co;
  github.com, which redirects to `*.githubusercontent.com`); its Download then sends `model_download` for each. No
  consent is stored for either. `model_use` is not for them; `model_remove` deletes a runtime's unpacked DLLs.
- **`capability_state`** `{}` → `{can_run: {id: bool}, why: {id: string}, device: {id: gpu|cpu}, budget: {live,
  installed_mb, free_mb, reserve_mb, usable_mb, commit_pct, commit_free_mb, gpu_kind: dedicated|shared|null,
  gpu_free_mb, gpu_budget_mb, cpu, gpu, battery, battery_saver}}` (2026-11-21): which models this PC can run RIGHT
  NOW (`capability.assess`), from the governor's last reading, not the installed memory alone: a model runs now
  only when its RAM need plus a margin fits in free memory after the 1.5 GB kept for Windows, Windows isn't close
  to its commit limit, battery saver is off (else light models only), on battery the best tier waits, other apps
  aren't using the processor, and its speed measured on this PC is enough. `why` is one sentence per model for
  Settings -> Models "Your PC, now"; `device` is where it would run (`gpu` only with DirectML and that much free
  graphics memory now; an integrated GPU's is `shared`). `null` in `budget` = unknown right now, never counted
  against a model; `live` false before the governor's first reading. Not an event: ask again while the page is open.
- **`model_use`** `{feature, id}` → `{ok, error, needs_download: bool}`: choose the model for a feature (and turn the
  feature on). Not downloaded yet: it is chosen, `needs_download` is true, and it's used once downloaded. A new text
  model rebuilds the meaning vectors in the background (`status_full.phases` has `{id: "rebuild"}`); the old vectors
  and their model stay in use until the new ones are complete, then they swap at once. Vectors of two models are
  never searched together.
- **`model_download`** `{id, consent}` → `Ok`: download a model, only with `consent: "DOWNLOAD"` (the consent dialog's
  button; anything else is `ok: false`). Pinned revision, exact size and SHA-256 are checked before a file is used.
  Progress comes as `download` events with `id` = the model id.
- **`run_action`** `{id}` → `Ok`: open what a search answer's `actions` offered: a Windows Settings page (ms-settings:), a Windows tool (Task Manager, Device Manager, ...) or an app from Windows' Start list. Only ids from the engine's own table and app list, never a path or a command. `search` answers carry `actions: [{id, kind: setting|tool|app, title, subtitle}]` when the question fits one ("open bluetooth", "chrome").
- **`update_state`** `{}` → `UpdateState` `{state, current, latest, size, got, bps, notes_url, error, auto, checked_at}`: in-app updates (0.9.0). `state` is idle, checking, uptodate, available, downloading, verifying, ready, installing or error. While `downloading`, `got` of `size` bytes have arrived and `bps` is the speed measured over the last few seconds (0 until known); `verifying`: every byte is in and its size and SHA-256 are being checked (again right before the installer runs).
- **`update_check`** `{}` → `Ok`: look for a newer release of nobad-studio/find now, in the background (also once a day while the `update_check` setting is on). The `update` event says how it went.
- **`update_install`** `{consent: "INSTALL"}` → `Ok`: download the newer installer over HTTPS, check its exact size and its SHA-256 against the release's .sha256 file and GitHub's digest, then run it silently outside NOBAD Find's job (it closes NOBAD Find, installs over it and starts it again). Any other consent word: ok false, nothing happens.
- **`model_folder`** `{id}` → `{ok, error}`: opens the folder that model is downloaded to in File Explorer (the models folder when it isn't there yet). Only a catalog id, never a path; each model in `models` also sends its `dir` ("" when built into Windows).
- **`model_remove`** `{id}` → `Ok`: delete a downloaded model's files; not for built-in models or the one in use.
- **`auto_configure`** `{}` → `{tier, steps: [{feature, id, needs_download}]}`: apply the recommended tier for this PC
  and language focus. Everything that needs no download is applied at once; for each step with `needs_download`, the
  UI asks for consent and calls `model_download`. A step's `id` is `""` when the tier turns that feature off.
- **`model_language`** `{focus: english|multilingual|hindi}` → `Ok`: "English first", "Many languages" or "Hindi" in
  Settings → Models. It changes the recommendation only; nothing is downloaded or switched by itself. Until it is
  set, the focus comes from Windows' display and keyboard languages (read from Windows, no network).

### Windows Search

- **`wsearch_state`** `{}` → `WsearchState` = `{missing: bool, start: ""|auto|delayed-auto|demand|disabled, running:
  bool, saved: same words}`: how Windows Search indexing is set up (`saved` = how it started before NOBAD Find
  turned it off, `""` if it didn't). Takes about 100 ms.
- **`wsearch_set`** `{off: bool}` → `{ok, error, state: WsearchState}`: Windows Search indexing off, or back as it was.
  Windows shows a permission prompt; the answer comes after it: **no time limit**. While a prompt is open, another
  call answers at once with `ok: false` and a sentence.
- **`use_instead_of_windows_search`** `{on: bool}` → `{ok, error, state: WsearchState}`: the one switch: Windows Search
  off and NOBAD Find starts with Windows (on), or Windows Search back (off). Same prompt.

### What is indexed, and the turbo index

- **`scope_info`** `{}` → `{scope: whole_pc|my_files|custom, roots: [string], categories: [Category]}`: what NOBAD Find
  indexes, for Settings. Nothing is skipped silently: every category is listed. `Category` = `{id, name, summary, why,
  examples: [string], included: bool, locked: bool, names_only: none|some|all, count: int|null}`, `id` one of `system` (Windows, Program Files,
  ProgramData: setting `include_system`), `caches` (AppData, temp, node_modules, .git, venv: `include_caches`),
  `secrets` (keys, browser passwords, cookies and history, Windows Credentials/Vault/Protect, chat and developer
  tokens, password vaults, wallets: `include_secrets`, **off by default, names only**, the content is never read;
  browser profiles and app databases are names only in `caches` too), `other_profiles` (other accounts' files, recycle bins, System Volume Information: always out, `locked`),
  `removable` (`index_removable`), `network` (`index_network`). `locked` = the user can't change it here (other
  people's files; system folders aren't part of My files; USB/network in Custom come from the folder list). `count`
  = entries of that category in the index, `null` when it can't be counted cheaply. `summary` = one short line for
  its card, `why` the full explanation. `names_only` = `all` (only names are indexed, the contents are never read:
  `secrets`), `some` (part of it is names only: browser profiles and app databases in `caches`) or `none`. Show
  `name`, `summary`, `why` and `examples` as plain text. Change the switches with `set_settings` (`scope`, `include_*`); the engine walks again.
  The one exception to "names only" is the setting **`secret_app_files`** (1.1.0, **off by default**, Settings >
  Privacy after a confirm dialog): command histories, FTP/SSH tools' saved sites and logins, developer tool tokens
  and `.env` files are then read into the encrypted index (`.env` files are names only until then). Turning it off
  removes their content, and their rows while `include_secrets` is off, without a rebuild. Keys, browser passwords,
  vaults, wallets and Recent items are never read.
- **`turbo_state`** `{}` → `TurboState` = `{available, enabled, running: bool, volumes: [{drive, ntfs: bool, files:
  int, usn_ok: bool, last_scan: number|null}], error: string, helper: not_installed|installed|needs_update}`: the
  optional turbo index, an elevated helper that reads NTFS's own file list and change journal (names, sizes, times
  and changes only, never file contents). `available` = an NTFS fixed drive is there, `enabled` = the `turbo`
  setting, `running` = the helper is connected, `usn_ok` = changes on that drive come from the change journal,
  `error` = `""` or why it isn't running (the normal folder walk is used then). `helper` (2026-11-21): the helper
  is set up ONCE with administrator permission (a protected copy and a Windows service only this account may
  start): `installed` = it starts with no prompt; `needs_update` = NOBAD Find was updated, or it was set up for
  a NOBAD Find in another folder: the normal walk is used and `error` says "Turbo needs your OK once to update its
  helper" until `turbo_helper` `update`; `not_installed` = nothing set up for this account (always so from source; one set up for another account on this PC counts as not installed here and is never removed from here). Show "Update
  helper" for `needs_update` and "Remove" whenever it isn't `not_installed`.
- **`turbo_set`** `{on: bool}` → `{ok, error, state: TurboState}`: on: if `helper` isn't `installed`, Windows shows a
  permission prompt once to set it up; the answer comes after it: **no time limit**. No at the prompt gives
  `ok: false` with a sentence and the setting stays off. After that, turbo starts with no prompt on every engine
  run. Off: the helper ends and Windows asks once to remove it; No there still turns turbo off (`ok: true`) and
  `error` says the helper is still installed. While a prompt is open, another call answers at once with
  `ok: false`. The `turbo` setting is read-only for `set_settings`: only `turbo_set` changes it.
- **`turbo_helper`** `{action: update|remove}` → `{ok, error, state: TurboState}`: `update` asks once to bring the
  helper up to date (then turbo starts if it is on); `remove` = `turbo_set` off (one prompt). Same prompt rules.

### Talk about a photo (1.1)

Photos only by result id. Every call answers at once `VisionAnswer` = `{ok, error, job, download?}`; `job` is the number
the `vision` events of that question carry, `null` when no job started (a refusal, `vision_cancel`, `vision_keep`).
`download` (optional) lists `{id, name, size_mb}` of what to fetch first when that is why it can't start. The answer
comes as `vision` events, after the reply that names the job. One job at a time: a new question cancels the old one.

- **`vision_state`** `{}` -> `{ok, error, job, not_now, models: [{id, name, deeper, ready, missing_mb, ram_mb, vram_mb,
  load_s, answer_s: [fastest, slowest], slow_note, can_run, why}], runtime: {id, ready, missing_mb}, loaded, busy, running}`: can
  it start now (`not_now` is a sentence when paused or the runtime is downloading, else empty), the quick model first
  and the deeper one second, what is in memory, whether a question is being answered (`job` its number, else null).
  `load_s` (seconds loading adds to the first question) and `answer_s` (seconds an answer takes once loaded) are the
  catalog's measured figures for the runtime in `runtime` (CPU or Vulkan) at the governor's level now (the talk
  worker runs under the worker group's CPU cap: Full none, Gentle 35 %, Very light 15 % and efficiency mode;
  docs/measurements.md, tools/measure_talk.py); 0 / [0, 0] when not measured. The UI says "about N s" only from these,
  never a number of its own. `slow_note` is a short sentence ("Slower now: NOBAD Find is in Very light mode.") when
  a typical answer at this level was measured at least 1.4 times as long as at Full (`models.SLOW_FACTOR`; on the
  reference PC: the processor at Very light), else empty.
- **`vision_describe`** `{file_id}` -> `VisionAnswer`.
- **`vision_ask`** `{file_id, question: string (<= 2000 characters before cleaning), deeper?: bool, more?: bool}` ->
  `VisionAnswer`. A question about writing in the photo may get a `done` event with note "Text read from the photo"
  (the text already read from it, no model); the model runs only with `more: true`.
- **`vision_compare`** `{a, b, question?: string|null}` -> `VisionAnswer`: two different photos.
- **`vision_cancel`** `{}` -> `VisionAnswer` (`job` null): stop the streaming answer; a `cancelled` event follows.
- **`vision_keep`** `{file_id, text: string (<= 2000 characters)}` -> `{ok, error, job: null, kept}`: keep the
  description so searches find it; empty text forgets it (`kept` false).

Wrong types (a string or boolean file id, a question that isn't a string or is too long, `deeper`/`more` not booleans)
are `-32602`; a photo that is gone, an empty question, a paused engine or a missing model are `ok: false` with a sentence.

### The window and quitting

These replace the 0.7.0 page's `heartbeat`, `page_visible` and `hide`: the engine knows the UI is alive because the
pipe is open.

- **`ui_shown`** `{window?: "main"|"bar"}` → `{ok: true}`: this UI's window is on screen (default `main`). For the
  main window, indexing starts (the engine starts idle unless "Keep indexing in the background" is on, as the
  0.7.0 app does when started with Windows) or resumes after a close stopped it, and the models warm up. A
  `ui_shown` still queued when its connection's pipe closed changes nothing.
- **`ui_hidden`** `{window?: "main"|"bar"}` → `{ok: true}`: the window was hidden or closed. For the main window
  with "Keep indexing in the background" off, indexing stops and only the engine's one idle process stays (the
  hotkey still works). A UI whose pipe closes after `ui_shown` counts as `ui_hidden`. Another UI still showing its
  main window keeps indexing as it is.
- **`quit`** `{confirm: string}` → `Ok`: end NOBAD Find, only with `confirm: "QUIT"`; any other word gives `ok:
  false`. The `quitting` event goes out before the reply; the engine stops only after the reply is written, and
  both stay readable after the engine closes the pipe.

## Events

Subscribe with `subscribe`. Each is `{"jsonrpc":"2.0","method":"<name>","params":{…}}`.

- **`status`** → `StatusBrief` (as the `status` method), every 2 s.
- **`status_full`** → `Status` (as the `status_full` method), every 2 s. It costs the engine real work: subscribe only
  while the Indexing page is open, `unsubscribe` when it closes.
- **`level`** → `{level, reason, paused}`: the work level, its reason or the pause changed (seen within half a second).
  Not sent for the state at the time you subscribed: read `status` once.
- **`activity`** → `{t, kind: level|kill|model|info, text}`: a new Recent decisions entry (within half a second).
- **`download`** → `{id: meaning|photo|<model id>, state: missing|downloading|ready, got_mb, size_mb, mb_s, error}`: a model
  download moved on: progress up to twice a second while `downloading`, then `ready`, or `missing` with `error` saying
  why it failed. `meaning` / `photo` follow the model in use for that feature (see `status_full`).
- **`update`** → `UpdateState`: an update was found, is downloading (progress at most 4 times a second while bytes
  arrive), verifying, ready, installing or failed. Install goes downloading → verifying → installing.
- **`notice`** → `{text}`: a sentence to show as a toast (for example a hotkey another app took). A notice nobody was
  subscribed to waits (the last 5) and goes to the first connection that subscribes to `notice`.
- **`models`** → the `models` result: something in it changed (a download changed state, a model was chosen,
  removed or became active, the language focus changed). Looked at about once a second.
- **`show`** → `{what: main|bar|settings|index, text: string|null}`: bring that window up (`settings`, `index`: the
  main window on that page, from the tray menu). `text` null: a hotkey was pressed, keep the
  search box as it is; a string: the bar's Alt+Enter (`to_main`), put it in the search box and search. The engine
  has already allowed the UI processes to take the front.
- **`here`** → `{path}`: after the main hotkey, the File Explorer folder it was pressed in (`""` if none). Comes shortly
  after `show`; a newer press wins.
- **`quitting`** → `{}`: the engine is ending. Exit instead of reconnecting.
- **`notification`** → `{item: Notification, unread: int}`: a new notification (sent on the next tick, within
  half a second); `unread` counts it. A duplicate (the same key within its time) isn't posted at all.
- **`turbo`** → `TurboState` (as `turbo_state`): the turbo index started, stopped, read a drive, lost a change journal
  (it reads the drive again) or hit an error.
- **`vision`** -> `{job, state: loading|answering|done|error|cancelled, text, model, note}`: the answer to a photo
  question moved on (subscribe to it before asking). `text` is the WHOLE answer so far while `answering` (replace what
  you show, never append), the final answer on `done`, empty on `error` and `cancelled`. `model` is the model id (empty
  for stored text). `note`: on `loading` what is loading: first "Loading <model name>", then, as the worker reports
  real progress, "Loading <model name>… 60 %", "Loading the vision part of <model name>…" / "… 40 %", or "Stopping
  the last answer…" (a new question waits for the last one to stop; it can't be cut in every step). A note with
  "…" is a whole line to show as it is. `loading` may come several times; `answering` with empty `text` is the photo
  being read. On `done` "Text read from the photo" (stored text, no model ran)
  or "may not be exact" (Devanagari in the answer); otherwise empty. States: `cancelled` with a non-empty `note` means
  the engine stopped it (a pause, memory, a runtime update, the model removed): show the note. `cancelled` with an
  empty `note` means the user cancelled or a newer question replaced it: show nothing. `error` means a crash, a hang,
  a failed start or a worker error: `note` carries the message (`text` is empty).

## Transcripts

`transcripts/*.jsonl`, one JSON object per line, in order:

- `{"send": <request>}`: the UI sent this.
- `{"recv": <response or event>}`: the engine sent this.
- `{"engine": {"do": …}}`: something happened inside the engine (a tick of the event clock, a level change, a hotkey,
  a download moving on). The Python replay performs it; a UI test skips it.
- `{"note": "…"}`: a comment.

They are recorded from the real handlers and events over a fake Api with fixed answers (`tests/contract_fake.py`), so
they never depend on a PC. The Python test replays every `send`/`engine` line and checks each `recv` comes out exactly
the same, and checks every line against the schemas (a deliberately bad request must be refused by the schema too).
After a deliberate contract change: `python tests/test_rpc_contract.py --record` (keeps the `send`/`engine`/`note`
lines, rewrites the `recv` lines), then review the diff.

| Transcript | Covers |
|---|---|
| `01-connect-and-search.jsonl` | hello, subscribe, status, ui_shown, search (words, filters only, empty), thumbnail, open, reveal, path_of, a path instead of an id (refused), a filter word that does not exist (refused), an unknown method, status events, ui_hidden |
| `02-events.jsonl` | every event: status, level, activity, download progress/ready/failed, show (hotkeys and to_main), here, a notice waiting for a listener, unsubscribe, quit and quitting |
| `03-settings-and-system.jsonl` | get/set_settings (and a bad one), pick_folder, Windows Search, model downloads with and without consent, rescan, wipe and quit confirm words, the creative apps list (a path dropped) |
| `04-indexing-page.jsonl` | status_full method and event, pause_for/resume with level events, bad pauses (a string, 0), learned_apps, reset_learned, hardware, forget |
| `05-scope-and-turbo.jsonl` | scope_info before and after a scope change, turbo_state, turbo_set declined at the prompt (and a bad one), turbo events (running, helper ended), turbo_set off (the helper kept: removal declined), the helper needing an update, turbo_helper update declined (and a bad one), turbo_helper remove |
| `06-models-and-tray.jsonl` | models (method and event), model_language, model_use (and a model for the wrong feature), model_download without and with consent and its download events, model_remove (downloaded, built-in, a bad id), auto_configure, open_with, show settings / index (the tray), capability_state |
| `07-smart-search.jsonl` | search with parts and a best guess, suggest (empty, typed, the bar's), history_add (kept, too short, with the setting off), history_forget (kept, never typed), history_clear |
| `08-talk-about-a-photo.jsonl` | vision_state, describe / ask (text read from the photo, `more`, a deeper model needing a download) / compare / cancel / keep, the vision events (loading, answering with the whole text so far, done, cancelled by the engine, error), refusals and bad params |
| `10-performance.jsonl` | performance_state, set_settings with the goal and with an older UI's power (mirrored both ways), fast leaving the manual workers unused, a forced backend that isn't installed, reset_safe_defaults (and the state after it) |
| `09-notifications.jsonl` | notifications_list (empty, three), notification events, a duplicate key not posted, a path kept out of the text, notifications_read (some ids, all, and bad ones), notifications_clear |

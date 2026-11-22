# NOBAD Find 1.1.0: browser data (opt-in) and the "Settings & apps" filter (design)

Status: design, maintainer decisions 2026-11-22. To build after Phase 2 ("talk about a photo") in 1.1.0. Local
branch only until the maintainer says push.

## 1. Maintainer decisions (2026-11-22)

1. **"Settings & apps" filter.** One filter option shows only Windows settings pages, Control Panel items, tools
   and installed apps (the launcher's actions), and no files.
2. **Browser data, opt-in.** If the user allows it, Find indexes the browsers' **history** (and the other browser
   data below) for a **unified browser search** across Chrome, Edge, Brave, Vivaldi, Opera and Firefox. This
   **replaces the 2026-11-17 rule** "no browser history" (AGENTS.md), for this opt-in only. Everything else in
   that rule stays: no Recent items, event logs or programs-run history.
3. **A date filter** is shown when the "History" filter is selected ("history from last week", "visited yesterday").
4. **Locked databases:** the browsers keep their SQLite files open while running. Find must **never kill or close
   a browser**. It copies the database (+ `-wal`, `-shm`) with full sharing and reads the copy.

## 2. What is read, and what never is

| Data | Source | Indexed | Never |
|---|---|---|---|
| History | Chromium `History` (`urls`: url, title, last_visit_time, visit_count); Firefox `places.sqlite` (`moz_places`) | title, url, host, last visit, visit count | page contents, cookies, session data |
| Bookmarks | Chromium `Bookmarks` (JSON); Firefox `places.sqlite` (`moz_bookmarks`) | title, url, folder | — |
| Saved logins | Chromium `Login Data` (`logins`: origin_url, username_value); Firefox `logins.json` (hostname, encrypted username: not decrypted, so host only) | **site + username** (plain-text fields only) | **password values: never decrypted, never stored, never shown** (app-bound encryption; bypassing it is a credential-theft technique) |
| Downloads | Chromium `History` (`downloads`: target_path, tab_url, end_time) | file path, source site, date | — |

- A saved-login result offers **"Open in the browser's password manager"** (`edge://password-manager`,
  `chrome://password-manager/passwords`, `about:logins`), launched through the existing launcher rules. The browser
  asks for the Windows PIN itself.
- Every browser profile is its own source ("Edge, Work profile"). Only the signed-in Windows user's own profiles are
  read (scope.Rules still drops other users).

## 3. How it is read safely

- **One setting, off by default:** `browser_data` (`off` | `history` | `history_logins`). Turning it on shows exactly
  what is read (the table above) and asks once. Off deletes everything it indexed.
- **Copy, don't lock:**
  1. Open the source with `CreateFileW(GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)`.
  2. Copy it into `<data>\tmp\browser-<random>\` (ACL: the user only), with the `-wal` and `-shm` copied the same
     way, so the copy is consistent.
  3. Open the copy with `sqlite3` read-only (`file:...?mode=ro&immutable=1`), read, close, and delete the copy at
     once (also on error; the folder is wiped at engine start).
  4. If the file can't be opened (exclusive lock, sharing violation): retry with backoff (1 min, 5 min, 30 min).
     Never `TerminateProcess` and never ask the browser to close.
- **Schema checks:** only the expected tables/columns are read. An unknown schema version is skipped with a note,
  not guessed. URLs and titles are untrusted: they reach the UI only through `esc()`, and FTS only through
  `fts_quote`.
- **Storage:** inside the encrypted index (SQLCipher + DPAPI key), in a `browser_items` table
  `(id, browser, profile, kind history|bookmark|login|download, title, url, host, at, visits)`, indexed by FTS.
  Text meaning is optional: titles only, if meaning search is on. Deleting a profile, turning the setting off, or
  "Clear browser data" in Settings > Privacy deletes the rows.
- **Freshness:** re-read when the database file's mtime changes (the watcher already sees the profile folders), at
  most every 10 minutes per profile.
- **Process:** reading happens in a text-reader worker (WORKERS job, low priority), never in the engine.

## 4. Search and filters

- New result kind `browser`. Each result carries the browser, profile, kind and date.
  - **Open:** history and bookmark results open the URL in the default browser. A login opens the browser's password
    manager. A download opens its file (if it still exists) or its folder.
- **Filter bar:**
  - `Settings & apps` (decision 1);
  - `Browser` with sub-options History / Bookmarks / Logins / Downloads;
  - when History is selected, a **date range** (today / yesterday / last 7 days / last 30 days / pick dates), using
    the parser's existing time words ("visited last week").
- Query words: "history", "visited", "bookmark", "saved login", "password for" map to the browser kinds (soft kinds:
  read as words when nothing matches).
- Ranking: browser results go through the existing name/text channels (RRF). Photo channels never apply.

## 5. Rules to update (in the same PR)

- **AGENTS.md:**
  - The 2026-11-17 "Out of scope" bullet gets this opt-in exception, worded like the search-history exception.
  - Browser profiles stay names-only for **files**; the browser databases are read only through this feature.
  - Password values are never decrypted.
- **Settings:** `browser_data` (const.DEFAULTS, settings.coerce, schema, a Settings > Privacy row with "Clear browser
  data").
- **Contract:** result kind `browser`, the filter values, and `browser_data_state` (per browser/profile: last read,
  item counts, last error).

## 6. Acceptance criteria

1. With Edge running, history is indexed without closing Edge, and Edge's own history still works afterwards
   (manual check, plus a test with a file held open by another handle).
2. A sharing violation never kills or blocks the browser: the read retries and then gives up with a note.
3. No password value appears anywhere: not in the index, logs, pipe transcripts or temp files. A test greps a
   synthetic Login Data copy whose password_value is a marker string.
4. Turning `browser_data` off deletes every `browser_items` row, and the temp folder is empty.
5. "Settings & apps" shows only launcher actions. "History" + "last week" shows only history visited in that range.
6. The mixed-file regression check (`tools/eval_search.py`) and the photo evaluation are unchanged with the setting
   off.

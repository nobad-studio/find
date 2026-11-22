# NOBAD Find changelog

## 1.1.0 · (in development)

### Talk about a photo
- **Describe a photo, ask about it, or compare two,** on a photo's detail pane. The answer appears word by word,
  is labelled as Find's reading of the photo, and can be copied, stopped (Stop or Esc) or kept: a kept description
  makes the photo findable by its words.
- **"What's written here?"** first shows the text Windows OCR already read from the photo; "Ask the model too"
  asks the model as well. An answer with Hindi script in it says it may not be exact.
- **Runs on this PC only,** with a small vision model (SmolVLM2 500M, 520 MB) and, for deeper answers, Qwen3-VL 2B
  (1,481 MB), on the llama.cpp runtime (24 MB for the processor, 37 MB for the graphics card). Nothing downloads
  until you say Download: one dialog names the model, the runtime it needs, both sizes and the total, and where
  they come from (huggingface.co; github.com). Files are pinned and checked by size and SHA-256; only the DLLs
  NOBAD Find loads are kept (29 MB for the processor, 71 MB for the graphics card), never the llama.cpp programs,
  their tool libraries or its network backend.
- **Measured on the reference PC (i5-12500H, Iris Xe), with NOBAD Find's own CPU limits in force:** SmolVLM2
  answers in about 1-4 s on the graphics and 3-10 s on the processor, using about 1 GB of memory; Qwen3-VL in about
  1-11 s on the graphics and 4-29 s on the processor once loaded (the first question also loads it: 1-3 s more
  when its files were read before), using about 2.5 GB. Talking about a photo follows NOBAD Find's level like the
  rest of its work: while it runs very light (a game, a call, a busy PC), answers on the processor take longer
  (SmolVLM2 5-16 s, Qwen3-VL 8-46 s) and the photo pane says so ("Slower now: NOBAD Find is in Very light mode.");
  on the graphics the level makes no difference.
- **Loading shows how far it got, and Stop works at once:** "Loading Qwen3-VL 2B… 60 %", then its vision part;
  Stop (or a new question) ends a load or the reading of the photo within about a second (measured 0.002-1.5 s).
  A model that is slow to load but still loading is never ended as "stopped responding"; one that stops making
  progress is.
- **Deeper analysis is only offered when it fits:** it says its memory cost, or why not now (too little free
  memory, NOBAD Find paused). Qwen3-VL shows a warning on PCs below its tier (16 GB and 8 cores, or a graphics
  card with 2.1 GB of its own memory).
- The model leaves memory 3 minutes after the last question, when memory runs short, or when NOBAD Find pauses.
- Settings > Models has a "Talk about photos" group: both models and both runtimes, with sizes, memory, Download
  (with the same consent) and Remove.

### Privacy and security (review of 2026-11-22)
- **What other programs record is no longer read:** PowerShell's command history, shell and database-client
  histories, Windows' Recent items, FileZilla and WinSCP saved servers, and sign-in files of the GitHub CLI, Maven,
  Cargo, Terraform, PostgreSQL and more now count as "Keys and password stores": left out by default, names only
  when you turn that on. After the update, NOBAD Find removes once what it had read from those files; the rest of
  the index stays as it is.
- Fixed: a change Windows reported with an old-style short name (`APPDAT~1\...\CREDEN~1`) could get a password
  store past those rules; such paths are now read by their full names first.
- Fixed: after 200 forgotten files, "Forget" said it worked but the next file came back at the next scan. The
  Never index list now holds 5000 entries; if it is ever full, Forget says so and leaves the file where it is.
- The window now checks that it is talking to NOBAD Find's own engine (NobadFind.exe next to it, a normal user
  process, not a sandboxed or low-rights one) before it sends a single search. If another program got there first,
  the window says so instead of connecting. The engine checks the window the same way.
- Windows' own programs that NOBAD Find starts (File Explorer, Task Manager, Control Panel tools, PowerShell for the
  Start menu list) now always come from the Windows folder by full path, never from a same-named file elsewhere.
- Messages to the engine nested absurdly deep get an error back instead of no answer.
- A file name can no longer hide what it is with invisible direction characters (a program named to look like
  `Invoice_exe.pdf`): those characters are shown as `[U+202E]`, the details show the real extension, and a
  disguised program says "opening it runs a program".
- "Delete the whole index" now also removes the list of files you forgot from the settings file, empties NOBAD
  Find's log, and deletes old index copies kept after a sign-in key problem. Your settings and your own Never index
  folders stay.
- Fixed: when a talk model was slow to close, NOBAD Find could lower its memory limit while the model was still
  in memory, so indexing work could fail for a moment. The limit now comes down only once it has really closed.

## 1.0.1 · 2026-11-22

### Opening Windows settings and apps
- Fixed: "open windows update" (and every other "open ..." question) opened the first file, often Settings on its
  home page, instead of the page. Since 0.9.1 the engine found the page but left it out of the answer it sent to
  the window. The same answer also left out the hints for photo and meaning search; both arrive again.
- Typos are corrected against NOBAD Find's own list of pages and tools: "opn windws update", "launch contrl pannle".
- "open ..." answers come quicker: when the question opens a page or an app, files are found by name and words
  only, without waiting for the meaning model.
- Network & internet opens `ms-settings:network-status`, the address in Microsoft's list (was `ms-settings:network`).

### Known
- If you use the SigLIP 2 photo model, photo search finds fewer photos while NOBAD Find looks at your photos again
  after the 1.0.0 update (about an hour per 10,000 photos; your own folders first). A later update keeps the old
  photo index answering during such a rebuild.

## 1.0.0 · 2026-11-22

### Fixed
- **Photo search finds the right photos more often.** A score cut-off threw away photos that clearly matched
  ("a cup of coffee" lost two of four real coffee photos), and loosely matching words read inside other photos
  pushed in wrong ones. Measured on 556 openly licensed photos and 146 described searches: the share of clearly
  matching photos in the top 10 went from 67% to 82%. On 45 searches that were never used to tune anything, the
  ranking score (nDCG@10) went from 0.60 to 0.71.
- **Photos that only may match are still shown,** after the sure results and marked "the picture may show it",
  instead of being dropped.
- **"Show me all photos", "find photos" and "pictures from yesterday" list your pictures again** (with the date or
  folder you gave), instead of ranking them by what the word "photos" looks like.
- **"A screenshot of program code" or "a screenshot of a spreadsheet" now searches your pictures.** Before, every
  word was read as a file type and nothing was left to look for.
- **The "best" photo model (SigLIP 2) found photos much worse than it should have:** the compressed part of the
  model that looks at pictures blurred them (measured: worse than the standard model). It now uses the
  full-precision version. If you use it, NOBAD Find downloads the one changed file (177 MB) and looks at your
  photos again; the standard model (SigLIP base) and its photo index are not affected. With the fix, SigLIP 2
  finds the right photos more often than the standard model (+0.035 on the 45 untouched searches).
- The photo model is no longer asked about folder names, dates, sort words or mixed Hindi and English: those go to
  the filters, and only the description goes to the photo model (it understands English).
- A file found by a loosely matching name is no longer dropped from photo results.
- The "needs its photo model" hint gives the size still to download, not the whole model's.

### Known
- A plain keyword search such as "lease" can also list weak photo matches after the sure results. The fix is being
  measured before it ships.
- `NOBAD_FIND_PHOTO_V2=0` (an environment variable) brings back the earlier photo ranking, if you need it.

## 0.9.6 · 2026-11-21

### Turbo index
- Windows asks for administrator permission once, when you turn turbo on, instead of every time NOBAD Find
  starts. A small helper (NobadFindTurbo.exe, 16 MB, without the search engine's models or libraries) is copied into
  `Program Files\NOBAD Find Turbo`, where only administrators can change it, and set up as a service that starts
  only when NOBAD Find asks and that only your account can start. Every copied file is checked against its SHA-256.
- The helper checks every connection: your account, your session, not elevated, the installed NobadFind.exe. It
  still reads file names, sizes and dates only, never contents, and drops other people's files.
- After an update that changes the helper, turbo asks for your OK once to update it; until then the normal folder
  walk is used. Turning turbo off, "Remove" in Settings > What to index, or uninstalling removes the helper and its
  service (Windows asks once).

## 0.9.5 · 2026-11-21

### Search bar
- A preview of the selected result beside the list: a picture for photos and videos, the name, folder, size, age,
  why it matched and the words that matched inside it. The bar is 840 px wide for it.
- "open bluetooth" + Enter opens it every time: Enter now waits for the answer to what you typed, and the Settings
  page or app comes to the front instead of opening behind other windows.
- Searches in the bar are much faster while you type: a photo question with a folder ("black shirt in downloads")
  took about 1 s on a whole-PC index and now takes about 0.16 s.
- As in the window: a hint when a search needs a model (download it, switch it on, photos still being looked at)
  and the answer's notes, up to four Windows settings and apps, Forget (Shift+Delete twice), Ctrl+C copies the path,
  Copy name.
- The same see-through glass as the main window.
- A question that names a setting or app exactly wins: "open windows update" is Windows Update, "open settings
  app" is Settings.

### Fixed
- "Open NOBAD Find" in the tray (and Settings, Index, and Alt+Enter from the search bar) sometimes did nothing
  after the search bar had been used and the window closed. It now opens the window, and every tray click is logged.
- The Download buttons on the Welcome screen and the Index page get the model Settings > Models would use (the one
  in use, or the one recommended for this PC), after the same consent, instead of always MiniLM / SigLIP base.
- The Forget message points to the right place: Settings > What to index > Never index.
- See-through window really follows Windows' Transparency effects switch.

### Privacy and security
- A "Keys & passwords (names only)" choice in the filter bar's Kind, offered while Settings > What to index has
  Keys and passwords on: it lists key files, password stores, wallets, .ssh and similar files by name. Their
  contents are never read, and browsers' saved passwords are never opened.
- Recent searches come only from your encrypted search history. The window no longer keeps its own plain-text list,
  and the old `ui-recent.json` is deleted. Search history off means none are kept or shown, and "Clear search
  history" clears them too.

### Updates
- Installing an update shows real progress: how much is downloaded, MB of the total, the speed and the time left,
  then a step while its size and checksum are checked, then the install and restart. While an update runs, a small
  card in the sidebar takes you to it.

### Index and settings
- The Index page lists every NOBAD Find process, as Task Manager shows them, and says what each one is: engine,
  window, search bar, text reader, meaning worker, photo worker, turbo helper. Each shows its own processor, memory
  (working set and private), how long it has run, and a note when it is idle, starting or ending.
- Settings > What to index: every category is a card with its icon, one plain line, its facts as chips (in or out,
  how many in the index, names only) and its switch; the long explanation and example paths are under Details. The
  page opens at once and fills in the counts when the engine has them; the turbo index is a card too.

## 0.9.4 · 2026-11-21

### Fixed
- Meaning search could find nothing for days after switching to another text model. When the old model's
  vectors had been cleared (a change in how vectors are made), search still waited for the new model's whole
  set, about 1.4 million pieces on a whole-PC index, before using any of it. Now the new model takes over at once,
  and each file counts in meaning search as soon as its vectors are made.
- A half-finished switch made the old way is started again instead of being kept.

## 0.9.3 · 2026-11-20

### Search bar
- Like Spotlight: with NOBAD Find's window closed, Win+Shift+F opens a small search bar over any app; with the
  window open, it goes to the window's search box. The bar shows Windows settings, tools and apps too ("open
  bluetooth", "battery percentage"), with Open. Settings > Shortcuts > Search bar turns it off (the shortcut then
  always opens the window). Updating turns the bar on once.

### Speed
- Settings > Performance > Speed: Balanced (as before) or Boost. Boost uses every processor thread for reading
  files, photos and meaning, even while you use the PC.
- Safety net (on by default): even at Boost, NOBAD Find works gently when other apps need the processor, uses one
  worker when free memory drops under 3 GB, and pauses as before for an app that stops responding, a busy PC or
  low memory. Off: only a frozen app and very low memory pause it.
- Text reading workers, Boost and the Safety net take effect the moment you change them; the worker count used to
  wait for a restart.
- Keep models loaded: turning it on loads the models at once. When NOBAD Find uses a lot of memory it now
  restarts its workers first and lets go of the models only if memory stays high (it used to drop them at once,
  so they seemed to unload even with the setting on). The log says why a model was released.

### New files first
- A file you just downloaded, saved or changed is read, looked at (photos) and understood before everything
  else. In your own folders NOBAD Find also moves on to it within moments instead of after the queue; changes
  elsewhere (app caches change all the time) go to the front of the queue only.

### Index page
- A new look, like the Models page: each step is a card with a coloured tile, its state, a meter and its numbers
  as chips; the numbers have icons and shorter labels.
- Scan speed shows the last scan's speed instead of a dash (scans by the turbo index count too).
- If the first numbers don't come within 3 seconds, the page asks again instead of waiting.

### Settings
- What to index opens at once: its counts (up to 4 seconds on a whole-PC index) are kept and refreshed in the
  background.
- Every switch answers at once: work it causes on the index (clearing search history, removing secret names or a
  drive's files) runs right after, instead of waiting for an indexing batch first.

### Fixed
- Slow answers from the engine are written to the log by name, so a slow page can be traced.

## 0.9.2 · 2026-11-20

### Fixed
- Updating from inside the app (Settings > About > Updates > Install) closed NOBAD Find and left the old version:
  setup stopped NOBAD Find together with every program it had started, and setup itself was one of them, so it
  ended before copying anything. Setup now stops NOBAD Find and its own workers by name only. The fix is in
  setup itself, so Install in 0.9.0 and 0.9.1 works with this version. 0.9.2 is otherwise the same as 0.9.1.

## 0.9.1 · 2026-11-20

### Fixed
- Indexing stopped with the turbo index on: its helper read nothing and NOBAD Find waited for it for good (no
  text, scans, photos or meaning, and file changes weren't followed). The helper's connection could not send
  while it waited to receive; it now can, and a drive the helper stops answering for is read the normal way
  after 2 minutes. Every step of the turbo index is in the log now.
- NOBAD Find worked on one worker all day when Windows wrongly said a full-screen game was running (seen with
  File Explorer in front). A game only counts when its window really fills the screen.
- Pause and Resume take effect at once, and the Index page shows it the moment you press the button.
- Recent decisions on the Index page stay in a fixed box instead of pushing the page down.
- The Index page asks for its first numbers sooner.

### Search
- Your own folders first: Downloads, Desktop, Documents, Pictures, Videos, Music and OneDrive are read, looked at
  and understood before the rest of the PC.
- A photo search in a folder ("in downloads black shirt image") looks at that folder's photos first and right
  away, says how many are done there, and shows new matches by itself as they come.
- Programming languages: "python", "c# code", "rust project", "sql scripts" and about 60 more find files in that
  language. Words that are also ordinary words (python, go, java, swift, ...) count when typed alone or with
  "code", "files", "project"; "python flask" tries Python files first.
- Keys, tokens and long random strings ("sk-proj-...", an ID, a hash) are found inside files, even as part of a
  longer string (up to 3 seconds of looking, your folders first).

### Open settings and apps
- Type "open bluetooth", "turn off wifi", "display settings", "brightness", "dark mode", "device manager",
  "open chrome" or an app's name: the Windows Settings page, Windows tool or app shows above the results, with
  Open; Enter opens it when you typed "open ...". Apps come from Windows' own Start list (with their version,
  publisher and install folder), read in the background.
- Every setting Windows' own Settings search knows, about 1,400 on Windows 11 ("battery percentage", "edit
  environment variables", "create a restore point", "screen saver", "mouse double-click speed"), in your Windows
  language: read from Windows' own catalog on your PC, so it matches your Windows version. Settings open their
  page; Control Panel ones open their Control Panel item or Windows program.

### Changed
- One NOBAD Find window with everything: the quick find bar is off (and no longer in Settings or the tray menu).
- Shortcuts can be cleared (Settings > Shortcuts > Clear); the Start menu and the icon still open NOBAD Find.

## 0.9.0 · 2026-11-20

### Shortcuts and closing
- Closing the window keeps NOBAD Find in the notification area, so its shortcuts always work (it used to quit
  completely, and with it every shortcut). The first time, a notification says how to get it back. Settings >
  Performance > "Keep running after closing the window" still turns this off.
- New default shortcuts: Win+Shift+F opens NOBAD Find, Ctrl+Shift+Space the quick find bar. The old Win+Shift+Space
  is Windows' own keyboard-layout switch and never worked on many PCs. When a default is taken on a PC, NOBAD Find
  picks the next free combination and says so. An upgrade moves old or Windows-reserved shortcuts to the new ones
  once; a shortcut you chose that works is kept.
- Settings > Shortcuts: each shortcut shows whether it works right now. Change it by pressing the new keys (or
  typing them); NOBAD Find checks first whether it's free, used by another app, or kept by Windows, and only then
  saves it. It takes effect at once, no restart.

### Photo search
- Photos are looked at while indexing goes on: photos, text, scans and meaning each get a turn of up to 2 minutes,
  so on a big index photos no longer wait until every document is read (that could take days).
- A photo search in a folder ("in downloads black shirt image") ranks the photos in that folder. Before, the best
  few hundred photos on the whole PC were picked first and the folder applied afterwards, which could leave none.
- A photo question is asked the way the photo model learned: as captions ("a photo of …"), averaged. About 87 ms
  for a new question on the reference PC (21 ms before), instant again; not yet measured for accuracy.
- When a search needs something that isn't ready, it says so above the results with one button: the photo model
  to download (with your OK), photo or meaning search to turn on, or "Still looking at your photos: 120 of 8,400".
- Every word of a photo question reaches the model as you typed it; nothing is filtered.

### Settings > Models
- Each model is a card: what it's for, its facts as chips (download size, memory, licence, languages, measured
  quality), and Details with its speed, how it was measured, where it comes from, how it's checked and the folder
  it's downloaded to, with Open folder.
- "Keep models loaded" (Memory): instant meaning and photo searches at the cost of memory; off by default (models
  leave memory a few minutes after the last use, as before).

### Updates
- NOBAD Find can update itself (Settings > About > Updates). Once a day, while "Check for updates automatically" is
  on, it asks GitHub for its newest release; Install downloads that installer, checks its exact size and SHA-256
  against the release's .sha256 file and GitHub's own digest, and installs it over this version. NOBAD Find closes
  and starts again; your index and settings are kept. The installer isn't code-signed yet, so the checksum (and
  HTTPS) is the check.
- The installer knows what is installed: it upgrades, repairs the same version, or asks before going back to an
  older one.

### Fixed
- The Index page, and then Settings pages such as Models, could stay blank for a while after starting: the first
  look at the Index page counted the whole index while the others waited. The counts now run in the background.
- A start-up card shows the moment NobadFind.exe starts, until the window is up.
- The window can be made smaller (720 x 500 at the least, was 860 x 600).

### Privacy and security
- New connection: the update check and download, HTTPS to GitHub for nobad-studio/find only. Nothing about your
  PC or your files is sent. Turn it off in Settings > About.

## 0.8.5 · 2026-11-19

0.8.0 was never released on its own; its changes ship in 0.8.5.

### Window
- A new window, drawn natively (Flutter) instead of a web page in Microsoft Edge WebView2. On the reference PC the
  window used about 465 MB in 7 processes; the new one about 130-170 MB in one (docs/measurements.md). Same screens:
  Home, results with previews, the filter bar, the quick find bar, the Indexing page and Settings, with a first-run
  welcome and a download consent dialog. Rounder controls and a frosted look.
- The old web window is gone completely: no WebView2, pywebview or .NET bridge is installed any more, and an
  upgrade removes the old files.
- NobadFind.exe runs the search engine (index, hotkeys, notification-area icon) and starts the window. Closing
  the window now quits NOBAD Find completely: no process stays running. Settings > Performance > "Keep running after
  closing the window" keeps it in the notification area for the hotkey and the quick find bar, as before. Starting
  NOBAD Find again brings the window up; `NobadFind.exe --page settings`, `--page index` and `--bar` open that page
  or the quick find bar.
- Settings > Performance has the notification-area icon switch.
- Dark only. A frosted, rounder look drawn inside the window (no live blur, so it stays smooth), glided mouse-wheel
  scrolling, quicker animations, and a tighter window size range (860 x 600 to 1280 x 820).

### Smart search
- Ask in plain words: "2 boys in an image in downloads" searches Downloads, pictures only, by what is in them.
  Places (Downloads, Desktop, your folders, a drive), kinds, times and sizes are understood and shown as chips you
  can remove.
- A best guess first when NOBAD Find is sure (an exact name, the only match, a clear winner); Enter opens it.
- Suggestions while you type: your own past searches, phrases NOBAD Find understands and your file names; Tab or →
  takes the grey completion.
- The quick find bar searches as much as the main window: it scrolls through every result, with the same chips,
  best guess and suggestions.
- Measured on a generated test set (docs/measurements.md): keyword, folder, time and size questions 100 % right at
  the top; meaning-only questions are the weak spot (40 % at the top, 60 % in the top five).

### Added
- Choose your models in Settings → Models. NOBAD Find looks at your PC (memory, cores, graphics card, disk) and your
  Windows languages, and recommends Light, Balanced or Best, for English first, many languages, or Hindi. Each
  model shows what it improves, its licence, its download size and how much memory it needs. Nothing downloads
  without your OK, and Auto-configure sets up everything else.
- Better English meaning search with GTE small (measured on a set of 68 questions, much of it phrased without any
  of the file's words).
- Hindi and mixed Hindi and English: multilingual-e5 finds Hindi files by meaning, and questions in Hindi or
  Hinglish ("pichle hafte ki rent wali pdf", "पिछले महीने का बिजली बिल") understand kinds, times, sizes and folders
  like English ones do. Hindi words in the text index stay whole.
- Photos with questions in many languages (SigLIP 2, Best tier).
- Switching the meaning model rebuilds it in the background; search keeps working with the old model until the new
  one is ready.
- A NOBAD Find icon in the notification area: open, the quick find bar, pause for an hour, Settings, Index, Quit.
- The hotkey or the icon opens NOBAD Find's window when it isn't running.
- "Open with" for a result.

### Privacy and security
- Search history: NOBAD Find remembers what you type in its own search box (on this PC only, inside the encrypted
  index, at most 200). Settings > Privacy > "Remember my searches" turns it off and clears it; "Clear history" and
  the x on a suggestion forget it. It never reads Windows' Recent items, browser history or event logs.

### Changed
- One- and two-letter searches, and "photos" alone, stay fast on a whole-PC index (a million files: under 25 ms a
  keystroke, was up to half a second), and an older search stops as soon as you type the next letter.
- "electricity bill march" finds the March bill even when it changed in another month.
- Folders no longer crowd the results of a meaning search.
- Much less memory: the background workers no longer load the whole app (about 4 GB committed while indexing on a
  16-thread PC, now about 0.4 GB), and the main process commits about 35 MB instead of 520 MB when idle.
- Indexing is 3-6 times faster: the workers use low CPU, memory and disk priority instead of Windows background mode,
  which squeezed each one into about 32 MB.
- Meaning search uses far less memory while indexing (about 150 MB instead of 1.1 GB for its worker) and indexes 1.7 times as fast; searching while you type with meaning and photos on is about 2.5 times as fast.
- Files that hit the background memory limit are read again instead of being skipped as "too big".
- Closing the window hands NOBAD Find's memory back to Windows (about 17 MB in use while closed).
- Workers run in efficiency mode while a game, a call or a busy PC slows indexing to Light or Paused, and the workers
  together have a hard memory limit.

## 0.7.0 · 2026-11-18

### Added
- A smarter way to stay out of your way. NOBAD Find checks every two seconds how much of your PC is free and works
  at full speed, gently, lightly (one worker) or not at all, always with a one-line reason. A game alone no longer
  stops indexing: it pauses only when the PC is really busy, an app stops responding or memory runs low.
  Settings → Performance → Games and presentations: Smart (recommended), Always pause or Don't change.
- It learns: an app that lagged while NOBAD Find was working gets more room next time. Settings → Performance lists
  those apps (by program name only, kept in the encrypted index), each with a Forget button.
- The Indexing page shows everything: each phase with progress and time left, NOBAD Find's own CPU, memory, disk and
  graphics use (with a 5-minute chart and a per-process list), every model, recent decisions, and Pause for 1 hour.
- Quick find bar on Ctrl+Alt+Space: a small floating search bar on the monitor with your mouse.
- A splash screen while it starts, a fuller home screen (example searches, quick tiles, recently changed files),
  Settings in six pages (General, Indexing, Models, Performance, Privacy, About), "Your PC" hardware info, and a
  working light theme.

### Changed
- Closing the window or pressing Esc now stops indexing and ends every worker process; one small idle process stays
  so the hotkey works. To keep indexing after closing, turn on Settings → Performance → Keep indexing in the
  background.
- All of NOBAD Find's processes run in one Windows job: quitting or a crash ends every one of them. Files and apps
  you open from NOBAD Find start outside it, so they stay open when NOBAD Find quits.
- A watchdog ends NOBAD Find's own stuck or oversized workers and reloads its window if the page stops answering.
  It never touches other apps. Every stop is listed on the Indexing page.
- Meaning vectors are made in a separate low-priority worker; searches stay quick while it works.

### Fixed
- Files that were being read when a long pause started are no longer skipped as "took too long".
- If quitting ever hangs, NOBAD Find ends itself after 15 seconds.

### Privacy and security
- No new internet connections. Model downloads are saved only after their size and SHA-256 check out.

## 0.6.2 · 2026-11-18

### Fixed
- "List all pdf in downloads having appreciation" now finds the PDFs with "appreciation" inside. Words like having,
  containing, mentioning, says, regarding and "the word" only say what's inside the file; before, NOBAD Find also
  looked for the word "having" itself and found nothing. "The word …" no longer limits the results to Word files.
- Enter opens the file and leaves NOBAD Find's window up. Before, the window hid, so it looked like the app closed.
  If you liked that, turn on Settings → Launch → Hide after opening a file.

## 0.6.1 · 2026-11-18

### Fixed
- Setup and uninstall no longer look stuck: stopping a running NOBAD Find took about 30 seconds per try
  (up to 3 minutes for an uninstall). Now it takes a moment.
- Opening NOBAD Find from the Start menu while it runs in the background now brings its window up. Before, nothing
  happened, so it looked like the app wouldn't start.
- You can now quit NOBAD Find completely: Settings → Launch → Quit. Closing the window still keeps it in the
  background for the hotkey; Quit stops it, indexing included.
- Started with "Run as administrator", it now says why it won't run instead of silently closing.
- If setup itself was run as administrator, the "Start NOBAD Find" box at the end now starts it as you, not as
  administrator.

### Changed
- New app icon: the NOBAD mark with a yellow "n", like every NOBAD app (each has its own colour).

## 0.6.0 · 2026-11-17

The first release of NOBAD Find: private, offline search for your own files on Windows 10 and 11.

### Added
- Find anything by name, by the words inside (documents, PDFs, Office and ODF files, EPUB, code, notes, e-mail
  files) and, optionally, by meaning with a small model on your PC (23 MB, downloaded only if you allow it).
- Photos by what's in them, optionally (a local image model, about 211 MB, downloaded only if you allow it), and
  the words in photos, screenshots and scanned PDFs with the OCR built into Windows.
- Plain-language questions: kinds, times, sizes, order, apps, your folders, drives and typed paths ("rent pdf
  from last week", "list all pdf here", "pdf in D:\Work bigger than 1 mb", "photos on my usb stick").
- A filter bar (kind, date, size, folder, order), previews in the results, and "here": the File Explorer folder
  you pressed the hotkey (Win+Shift+Space) in.
- Optional USB, external and network drives; unplugged drives stay findable, marked "not connected".
- One click to use NOBAD Find instead of Windows Search, and one click back.
- See-through window on Windows 11, and its own app icon.

### Privacy and security
- Nothing leaves your PC: no account, no telemetry. The only connections are the two optional model downloads,
  pinned and checked by SHA-256.
- The index is encrypted (SQLCipher) with a key only your Windows account can open (DPAPI).
- Runs as your normal account, never as admin. Other people's profiles, Windows itself, AppData and secret
  material (.ssh, key files, password managers) are never indexed. Files are read in separate low-priority
  processes and never run.

### Known
- The installer isn't code-signed yet, so Windows SmartScreen warns: More info, then Run anyway.

## Development builds

The versions below were test builds before the first release.

### 0.6.0 (development build, not released)
- Previews: photos, videos and PDFs in the results show Windows' own thumbnails, so you can see at a glance
  whether a photo match is right.
- More accurate photo meaning: the cut-off was tuned on 55 real photos in 19 topics (precision 0.73 -> 0.82 at
  the same recall); look-alikes ("flowers" -> a colourful cake) are shown dimmed under "Less sure"; when you ask
  for photos, what's in the picture counts most; OCR no longer turns stray marks in a photo into text.
- Light when idle: the models load when you search or when there's indexing work, warm up when you open the
  window, and leave memory after 3 minutes unused (idle memory 315 MB -> about 135 MB). Faster photo pass when
  you're away (photos in batches, out of Windows background mode).
- See-through window on Windows 11 (acrylic), following Windows' own Transparency effects switch (setting).
- The Index tab shows memory in use right now and which models are loaded.
- New app icon: a white magnifier with a spark on NOBAD orange.

### 0.5.0 (development build, not released)
- Photo meaning (optional): "dog on a beach" finds IMG_0042.jpg even with no words in it. A local image-text
  model (SigLIP base by Google, Apache-2.0, about 211 MB, pinned and SHA-256 checked) is downloaded only when you
  allow it. Photos are decoded by Windows' own decoders in a separate low-priority process; about 4 photos a
  second while you're away, gently while you use the PC.
- One click to use NOBAD Find instead of Windows Search: Windows Search indexing off (Windows asks once) and
  NOBAD Find starts with Windows; one click back restores Windows Search exactly as it was.
- NOBAD Find has its own app icon (a magnifying glass holding the NOBAD "n"); the NOBAD brand mark stays inside
  the app.

### 0.4.0 (development build, not released)
- Filter bar: kind, date, size, folder (with a folder picker), order, clear. Filters work with an empty search
  box, so "every PDF in this folder, newest first" is two clicks.
- "here" and "this folder": the folder you were looking at in File Explorer (or the desktop) when you pressed the
  hotkey. "list all pdf here" lists them; a "Here:" button puts that folder in the filter bar.
- Folder paths typed in the question: `pdf in D:\Work\Tax 2024`, `invoices "C:\My Files"`. Spaces are fine;
  something that only looks like a path is left out with a note. Network paths are only used when NOBAD Find
  already knows them, so typing one never makes Windows contact a server.
- Size and order words: "bigger than 100 mb", "under 2 mb", "big videos", "newest", "oldest", "largest".
- Lists of matching files show up to 500 and say when there are more.

### 0.3.1 (development build, not released)
- Your folders in the question: "list all download folder pdf", "photos on the desktop", "invoices in my
  documents". The real folders come from Windows, so Desktop and Documents moved to OneDrive work too.
- Fewer weak meaning matches: a file whose name alone is "car" or "garden" no longer shows up for "rent".
- "list", "all", "every", "give me" are understood as asking, not as words to look for; a question with only
  filters lists the newest matching files.

### 0.3.0 (development build, not released)
- Better meaning search: file and folder names have meaning too, so "seaside pictures" finds
  IMG_goa_beach_sunset.jpg and "power bill" finds electricity-bill-march.pdf; text is read together with its
  file's name. On a test set of vague questions the right file now comes first 16 times in 18 (was 7).
- Fewer misses: the meaning cut-off was tuned on measurements (it hid right answers before), and only matches
  close to the best one are shown.
- Fast on big indexes: 400,000 meaning vectors are searched in about 16 ms (was about half a second), with less
  memory use per search. Vectors of changed or deleted text no longer pile up in memory.
- Results say "name/text has a close / related / loosely related meaning" instead of a percentage.
- Rescans no longer rewrite the name index for files whose name didn't change.

### 0.2.0 (development build, not released)
- Words in photos, screenshots and scanned PDFs, read with the OCR built into Windows (offline, setting on).
- Places in the question: "on my usb stick", "on d:", "on the network drive", or a drive's name. USB, external
  and network drives can be indexed (settings, off by default); unplugged drives stay findable, marked
  "not connected".
- Apps in the question: "photoshop files", "blender projects", "after effects" and more.
- Gentler while you use the PC, full speed when you're away; pauses during calls (microphone or camera in use).
- Uninstalling puts Windows Search back the way it was if NOBAD Find turned it off.

### 0.1.0 (development build, not released)
- First build: instant name search, text inside documents/PDF/Office/EPUB/code/e-mail files, optional local
  meaning search, plain-language kinds and times, live updates, encrypted index, hotkey, Windows Search switch.

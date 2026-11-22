"""Constants and default settings for NOBAD Find."""
import os

APP_NAME = "NOBAD Find"
APP_VER = "1.0.1"

# NOBAD Find runs as the normal user, so its data lives in the user's own profile (not readable by other users).
DATA_DIR = os.environ.get("NOBAD_FIND_DATA_DIR") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")
DB_PATH = os.path.join(DATA_DIR, "index.db")
KEY_PATH = os.path.join(DATA_DIR, "index.key")          # the database key, protected with Windows DPAPI
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "find.log")
MODEL_DIR = os.path.join(DATA_DIR, "model")

# Meaning search model: all-MiniLM-L6-v2 (Apache-2.0), ONNX export, pinned to one revision and verified by SHA-256.
MODEL_REV = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_FILES = {   # local name: (path in the repository, size in bytes, SHA-256)
    "model.onnx": ("onnx/model_quint8_avx2.onnx", 23046789,
                   "b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21"),
    "tokenizer.json": ("tokenizer.json", 466247,
                       "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
}
MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{rev}/{path}"
MODEL_DIM = 384

# Paths that are never indexed, whatever the settings say: secrets, other people's data and system noise.
ALWAYS_EXCLUDE_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", "$recycle.bin", "system volume information",
    "windowsapps", "winsxs", "node_modules", "__pycache__", ".git", ".svn", ".hg", ".venv", "venv",
    ".cache", "cache", "cache2", "code cache", "gpucache", "temp", "tmp", "$windows.~bt", "$windows.~ws",
    "1password", "bitwarden", "keepass", "keepassxc", "lastpass", "dashlane", "nobad",
}
ALWAYS_EXCLUDE_EXT = {".kdbx", ".kdb", ".pem", ".key", ".pfx", ".p12", ".ppk", ".gpg", ".asc", ".ovpn", ".conf"}

# The same names, split into the categories Settings shows (scope.py; maintainer decision 2026-11-19: nothing is
# skipped silently, the user sees every category and chooses). Each name is in exactly one group.
SECRET_NAMES = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", "1password", "bitwarden", "keepass",
                "keepassxc", "lastpass", "dashlane"}
SECRET_NAMES |= {"gcloud"}
SECRET_EXT = set(ALWAYS_EXCLUDE_EXT) | {".1pux", ".1pif", ".wallet"}
# Credential stores inside AppData and the profile, by exact file name (a "-journal"/"-wal"/"-shm" twin too): browser
# passwords, cookies, history and form data (Chromium and Firefox), developer tokens, wallets. Security review of #79.
SECRET_FILES = {"key3.db", "key4.db", "logins.json", "cookies.sqlite", "places.sqlite", "formhistory.sqlite",
                "signons.sqlite", ".npmrc", ".pypirc", ".netrc", "_netrc", ".git-credentials", "wallet.dat"}
# Security review 2026-11-22 (M2). What other programs record (AGENTS.md: never read it) and more saved sign-ins, by
# exact file name. They are secrets: out by default, names only when the user turns secrets on. A change here bumps
# scope.RULES_REV, so an index made with the old rules loses their content once (indexer.Indexer._apply_new_rules).
SECRET_FILES |= {
    # command histories other programs keep (shells, REPLs, database clients, editors)
    "consolehost_history.txt", ".bash_history", ".zsh_history", ".sh_history", ".python_history",
    ".node_repl_history", ".psql_history", ".mysql_history", ".sqlite_history", ".rediscli_history",
    ".irb_history", ".lesshst", ".viminfo", "_viminfo", ".wget-hsts",   # (not ".history": VS Code's folder)
    # saved servers and passwords: FileZilla, WinSCP, PostgreSQL, S3 tools, Terraform, Vault
    "sitemanager.xml", "recentservers.xml", "filezilla.xml", "winscp.ini", ".pgpass", "pgpass.conf", ".s3cfg",
    ".boto", "credentials.tfrc.json", ".vault-token",
    # SSH keys and host lists outside .ssh (a copied key is still a key)
    "known_hosts", "known_hosts.old", "authorized_keys", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "id_ecdsa_sk", "id_ed25519_sk",
    # cloud sign-ins outside their own folders (gcloud, .aws, .azure, .docker, .kube are folders, above)
    "application_default_credentials.json",
}
# A file name that is a secret only inside a folder run (the last item is the file name, the rest the folders right
# above it): "settings.xml" in .m2 holds Maven passwords, elsewhere it's just settings.
SECRET_FILES_IN = ((".m2", "settings.xml"), (".m2", "settings-security.xml"), (".cargo", "credentials.toml"),
                   (".cargo", "credentials"), ("github cli", "hosts.yml"), ("gh", "hosts.yml"))
# Generic names that are secrets inside a browser profile (NAMES_ONLY_PATHS) only: "History" elsewhere is yours
BROWSER_SECRET_FILES = {"login data", "login data for account", "cookies", "history", "web data", "local state"}
# ... and by folder: these folder names one after the other anywhere in a path (lower case)
SECRET_PATHS = (("microsoft", "credentials"), ("microsoft", "vault"), ("microsoft", "protect"),
                ("discord", "local storage"), ("slack", "local storage"), ("teams", "local storage"),
                # security review 2026-11-22 (M2): PowerShell's command history, FileZilla's saved sites, GitHub
                # CLI tokens, GnuPG's keyrings on Windows
                ("powershell", "psreadline"), ("roaming", "filezilla"),
                ("roaming", "github cli"), (".config", "gh"), ("roaming", "gnupg"))
# Browser profiles and app databases: caches, not secrets, but their content is never read (binary noise)
NAMES_ONLY_PATHS = (("chrome", "user data"), ("chromium", "user data"), ("edge", "user data"),
                    ("brave-browser", "user data"), ("vivaldi", "user data"), ("opera software",),
                    ("firefox", "profiles"), ("thunderbird", "profiles"), ("leveldb",), ("indexeddb",),
                    # 2026-11-22: the other channels and forks of the same browsers
                    ("chrome beta", "user data"), ("chrome dev", "user data"), ("chrome sxs", "user data"),
                    ("edge beta", "user data"), ("edge dev", "user data"), ("edge sxs", "user data"),
                    ("yandexbrowser", "user data"), ("thorium", "user data"), ("arc", "user data"),
                    ("librewolf", "profiles"), ("waterfox", "profiles"), ("floorp", "profiles"),
                    ("zen", "profiles"))
NAMES_ONLY_EXT = {".sqlite", ".sqlite3", ".db", ".ldb", ".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm",
                  ".db-journal", ".leveldb", ".vscdb"}
CACHE_NAMES = {"node_modules", "__pycache__", ".git", ".svn", ".hg", ".venv", "venv", ".cache", "cache", "cache2",
               "code cache", "gpucache", "temp", "tmp"}
SYSTEM_NAMES = {"windowsapps", "winsxs", "$windows.~bt", "$windows.~ws"}
# Never indexed, whatever the settings say: other people's deleted files, restore points, Find's own data
FIXED_NAMES = {"$recycle.bin", "system volume information", "nobad"}
# ... and by folder run: the lists Windows and Office keep of what you opened (Recent items, jump lists). Their file
# NAMES are the activity history AGENTS.md rules out, so they are out even with secrets on (fix round 1, I1).
ALWAYS_OUT_PATHS = (("windows", "recent"), ("office", "recent"))

DEFAULTS = {
    "roots": [],                    # empty = the user's profile folders plus every other fixed drive
    "exclude": [],                  # extra folders never to index
    "content": True,                # read text inside documents
    "content_max_mb": 25,           # skip reading files bigger than this
    "semantic": False,              # meaning search (needs the model download, below)
    "photo_meaning": False,         # find photos by what's in them (needs the photo model download)
    "allow_photo_model_download": False,   # Hugging Face, once, about 211 MB, when you ask for it
    "allow_model_download": False,  # the only outbound connection: Hugging Face, once, when you ask for it
    "src_mail": True,               # .eml / .mbox files found while indexing
    "ocr": True,                    # words in photos, screenshots and scanned PDFs (Windows' own OCR)
    "index_removable": False,       # USB sticks, SD cards and external drives while they're plugged in
    "index_network": False,         # mapped network drives (your own network; slow on big shares)
    "pause_on_battery": True,
    "pause_fullscreen": True,       # old: replaced by games_mode, kept so a downgrade still reads it
    "games_mode": "smart",          # smart | always | off: what to do while a game is running
    "keep_background": False,
    "stay_running": True,           # on (0.9.0): closing the window keeps NOBAD Find in the notification area so the
                                    # hotkeys work; off: closing the last window quits it completely (no process left)
    "bar": True,                    # 0.9.3 (maintainer): the shortcut opens the search bar (like Spotlight) when the
                                    # window isn't open; with the window open it goes to the window's search box
    "bar_hotkey": "ctrl+shift+space",
    "pause_on_call": True,          # while the microphone or camera is in use
    "workers": 0,                   # 0 = pick from the CPU
    "power": "balanced",            # 0.9.3: balanced (leaves you room) | boost (every thread, even while you use the PC)
    "safety_net": True,             # 0.9.3: even at Boost, step down and free memory before the PC struggles
    "hotkey": "win+shift+f",
    "autostart": False,
    "hide_after_open": False,       # Enter opens the file and keeps the window up (on: hide it, like a launcher)
    "settings_rev": 3,              # which one-time settings changes (Settings.MIGRATIONS) have run; engine-only
    "wsearch_prev": "",             # Windows Search start type saved before NOBAD Find turned it off
    "theme": "dark",
    "glass": True,                  # see-through acrylic window on Windows 11 (follows Windows' transparency switch)
    "bg_notice_seen": False,        # the one-time "closing keeps NOBAD Find ready" notice was dismissed
    "welcome_seen": False,          # the Flutter UI's first-run welcome was dismissed (Start searching)
    "update_check": True,           # look for a newer NOBAD Find once a day (GitHub, nobad-studio/find; update.py)
    "models_stay_loaded": False,    # on: models stay in memory (instant searches, more memory); off: freed when idle
    "tray": True,                   # NOBAD Find's icon in the notification area (the engine's, works with the UI closed)
    "text_model": "minilm-l6-v2",   # meaning model (models.CATALOG, feature "text"); used once it is downloaded
    "photo_model": "siglip-base",   # photo model (models.CATALOG, feature "photo")
    "language_focus": "",           # "" = from Windows languages; "english", "multilingual" or "hindi" (Settings -> Models)
    # What to index (scope.py). Old settings get a scope from their roots: [] = whole_pc, folders = custom.
    "scope": "whole_pc",            # whole_pc | my_files | custom (custom = the folders in roots)
    "include_system": True,         # Windows, Program Files, ProgramData, Recovery, PerfLogs
    "include_caches": True,         # AppData, caches, temp, node_modules, .git, venv
    "include_secrets": False,       # key files, password stores, .ssh, wallets: NAMES ONLY, never their content
    "turbo": False,                 # the optional NTFS index helper (ntfs.py); asks for admin once (turbosvc.py)
    # your own typed search questions, kept in the encrypted index for autocomplete (history.py, maintainer
    # decision 2026-11-19); off deletes them. Not activity history: nothing from Windows or other programs.
    "search_history": True,
}

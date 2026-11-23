"""The index: one SQLite database, encrypted with SQLCipher when available, key protected with Windows DPAPI.

Tables
  files   every file and folder seen (path, name, size, times, kind)        + names  (FTS5 trigram: any part of a name)
  chunks  pieces of text read from inside files                           + text   (FTS5 words, with stemming)
  vecs    meaning-search vectors for chunks (float16)
  nvecs   meaning-search vectors for file and folder names (so a photo or a bill is found by what its name means)
  pvecs   photo-meaning vectors (what's in the picture), with the file time they were made for
  search_history  the questions you typed yourself, for autocomplete (setting search_history; history.py)
  vdesc   a photo description the user kept (talk about a photo, Keep this description), with the model that made
          it; it is also one chunk of that photo (ord KEPT_ORD) so words and meaning search find it
"""
import os
import secrets
import unicodedata
import sqlite3
import threading
import time

from . import winapi
from .log import log

try:
    import sqlcipher3 as _cipher
except ImportError:          # development without SQLCipher: the UI says plainly that the index isn't encrypted
    _cipher = None

# What an interrupted or failed query raises, from either driver (SQLCipher's isn't a subclass of sqlite3's)
OperationalError = (sqlite3.OperationalError,) + ((_cipher.OperationalError,) if _cipher is not None else ())

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS apps(exe TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL, dir TEXT NOT NULL, ext TEXT,
  kind TEXT, size INTEGER, mtime REAL, ctime REAL, gen INTEGER DEFAULT 0, text_mtime REAL, text_err TEXT);
CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS files_kind ON files(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS names USING fts5(name, dir, content='files', content_rowid='id',
  tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO names(rowid, name, dir) VALUES (new.id, new.name, new.dir); END;
CREATE TABLE IF NOT EXISTS nvecs(file_id INTEGER PRIMARY KEY, v BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS pvecs(file_id INTEGER PRIMARY KEY, mtime REAL, v BLOB NOT NULL, err TEXT);
CREATE TABLE IF NOT EXISTS vdesc(file_id INTEGER PRIMARY KEY, text TEXT NOT NULL, model TEXT, at REAL);
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO names(names, rowid, name, dir) VALUES ('delete', old.id, old.name, old.dir);
  DELETE FROM chunks WHERE file_id = old.id;
  DELETE FROM nvecs WHERE file_id = old.id;
  DELETE FROM pvecs WHERE file_id = old.id;
  DELETE FROM vdesc WHERE file_id = old.id; END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE OF name, dir ON files
  WHEN old.name IS NOT new.name OR old.dir IS NOT new.dir BEGIN
  INSERT INTO names(names, rowid, name, dir) VALUES ('delete', old.id, old.name, old.dir);
  INSERT INTO names(rowid, name, dir) VALUES (new.id, new.name, new.dir);
  DELETE FROM nvecs WHERE file_id = old.id; END;
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL, ord INTEGER, body TEXT);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS text USING fts5(body, content='chunks', content_rowid='id',
  tokenize='@TEXT_TOKENIZE@');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO text(rowid, body) VALUES (new.id, new.body); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO text(text, rowid, body) VALUES ('delete', old.id, old.body);
  DELETE FROM vecs WHERE chunk_id = old.id; END;
CREATE TABLE IF NOT EXISTS vecs(chunk_id INTEGER PRIMARY KEY, v BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS vecs_next(chunk_id INTEGER PRIMARY KEY, v BLOB NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS names_w USING fts5(name, content='files', content_rowid='id',
  tokenize='@NAME_TOKENIZE@', prefix='1 2');
CREATE TRIGGER IF NOT EXISTS files_ai_w AFTER INSERT ON files BEGIN
  INSERT INTO names_w(rowid, name) VALUES (new.id, new.name); END;
CREATE TRIGGER IF NOT EXISTS files_ad_w AFTER DELETE ON files BEGIN
  INSERT INTO names_w(names_w, rowid, name) VALUES ('delete', old.id, old.name); END;
CREATE TRIGGER IF NOT EXISTS files_au_w AFTER UPDATE OF name ON files WHEN old.name IS NOT new.name BEGIN
  INSERT INTO names_w(names_w, rowid, name) VALUES ('delete', old.id, old.name);
  INSERT INTO names_w(rowid, name) VALUES (new.id, new.name); END;
CREATE TABLE IF NOT EXISTS nvecs_next(file_id INTEGER PRIMARY KEY, v BLOB NOT NULL);
CREATE TRIGGER IF NOT EXISTS chunks_ad_next AFTER DELETE ON chunks BEGIN
  DELETE FROM vecs_next WHERE chunk_id = old.id; END;
CREATE TABLE IF NOT EXISTS search_history(k TEXT PRIMARY KEY, q TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 1,
  last REAL NOT NULL);
CREATE INDEX IF NOT EXISTS search_history_last ON search_history(last);
CREATE TRIGGER IF NOT EXISTS files_ad_next AFTER DELETE ON files BEGIN
  DELETE FROM nvecs_next WHERE file_id = old.id; END;
CREATE TRIGGER IF NOT EXISTS files_au_next AFTER UPDATE OF name, dir ON files
  WHEN old.name IS NOT new.name OR old.dir IS NOT new.dir BEGIN
  DELETE FROM nvecs_next WHERE file_id = old.id; END;
"""
# Devanagari vowel signs, viramas and nuktas are marks, which unicode61 treats as separators: "बिजली" became "ब"
# "जल" and "मह" matched "महीने". As token characters, a Hindi word stays one word (text_index "2").
DEVANAGARI_MARKS = "".join(chr(c) for r in ((0x0900, 0x0903), (0x093A, 0x094F), (0x0951, 0x0957), (0x0962, 0x0963))
                           for c in range(r[0], r[1] + 1))
TEXT_TOKENIZE = "porter unicode61 remove_diacritics 2 tokenchars ''" + DEVANAGARI_MARKS + "''"
TEXT_INDEX = "2"
# names_w: the words of every file name with a prefix index, for one- and two-letter questions (the trigram
# "names" table needs three letters; without this, "ta" scanned every row: seconds on a whole-PC index).
NAME_TOKENIZE = "unicode61 remove_diacritics 2 tokenchars ''" + DEVANAGARI_MARKS + "''"
NAME_INDEX = "4"
SCHEMA = SCHEMA.replace("@TEXT_TOKENIZE@", TEXT_TOKENIZE).replace("@NAME_TOKENIZE@", NAME_TOKENIZE)


# chunks.ord of a kept description (vdesc): the file's read text (OCR) is ord 0, 1, ...; re-reading the file replaces
# those and keeps this one
KEPT_ORD = -1


def fts_quote(term):
    """One FTS5 string literal: the term is always data, never query syntax."""
    return '"' + term.replace('"', '""') + '"'


def _load_key(key_path):
    """32 random bytes, stored only DPAPI-protected (readable by this Windows account on this PC)."""
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return winapi.dpapi_unprotect(f.read())
    key = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    tmp = key_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(winapi.dpapi_protect(key))
    os.replace(tmp, key_path)
    return key


class Store:
    def __init__(self, db_path, key_path=None, encrypt=True):
        self.db_path = db_path
        self.key_path = key_path or db_path + ".key"
        self.encrypted = bool(encrypt and _cipher and winapi.WIN)
        self._key = None
        if self.encrypted:
            try:
                self._key = _load_key(key_path or db_path + ".key")
            except OSError as e:
                # the key belongs to another account or PC: keep the old index aside and start a new one
                log(f"index key unreadable ({e}); starting a new index", "warn")
                stamp = time.strftime("%Y%m%d-%H%M%S")
                for p in (db_path, key_path):
                    if p and os.path.exists(p):
                        os.replace(p, f"{p}.unreadable-{stamp}")
                self._key = _load_key(key_path or db_path + ".key")
        self._local = threading.local()
        self.wlock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with self.wlock:
            # triggers from older versions are replaced (CREATE ... IF NOT EXISTS would keep them)
            self.db.executescript("DROP TRIGGER IF EXISTS files_ad; DROP TRIGGER IF EXISTS files_au;")
            self.db.executescript(SCHEMA)

    # ---------- connections: one per thread ----------
    @property
    def db(self):
        c = getattr(self._local, "c", None)
        if c is None:
            mod = _cipher if self.encrypted else sqlite3
            c = mod.connect(self.db_path, timeout=30, check_same_thread=False)
            if self.encrypted:
                c.execute(f"PRAGMA key = \"x'{self._key.hex()}'\"")
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.c = c
        return c

    def close(self):
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return r[0] if r else None

    def meta(self, k, default=None):
        v = self.one("SELECT v FROM meta WHERE k=?", (k,))
        return default if v is None else v

    def name_index_ready(self):
        if not getattr(self, "_name_index", False):
            self._name_index = self.meta("name_index") == NAME_INDEX
        return self._name_index

    def upgrade_name_index(self):
        """Fill names_w for the files indexed before it existed (new files go in by trigger). Once; a search
        meanwhile uses the old way. Returns True when it filled it."""
        if self.name_index_ready():
            return False
        with self.wlock:
            # "photos" alone lists every photo, newest first: without this, a sort of every photo on the PC
            self.db.execute("CREATE INDEX IF NOT EXISTS files_kind_mtime ON files(kind, mtime)")
            # common name words: files walked shortest name first until enough match (search._name_hits)
            self.db.execute("DROP INDEX IF EXISTS files_namelen")
            # covering: the walk tests the name, kind and extension without reading the table row
            self.db.execute("CREATE INDEX files_namelen ON files(length(name), mtime DESC, name, kind, ext)")
            self.db.execute("INSERT INTO names_w(names_w) VALUES('rebuild')")
            self.db.execute("INSERT INTO meta(k,v) VALUES('name_index', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            (NAME_INDEX,))
            self.db.commit()
        self._name_index = True
        return True

    def upgrade_text_index(self):
        """Indexes before 0.8.0 split Hindi words at their vowel signs: build the text index again with whole
        words, once, in one transaction (a search meanwhile sees the old one). Returns True when it rebuilt."""
        if self.meta("text_index") == TEXT_INDEX:
            return False
        with self.wlock:
            self.db.execute("BEGIN")
            try:
                self.db.execute("DROP TABLE IF EXISTS text")
                self.db.execute("CREATE VIRTUAL TABLE text USING fts5(body, content='chunks', content_rowid='id', "
                                f"tokenize='{TEXT_TOKENIZE}')")
                self.db.execute("INSERT INTO text(text) VALUES('rebuild')")
                self.db.execute("INSERT INTO meta(k,v) VALUES('text_index', ?) ON CONFLICT(k) DO UPDATE SET "
                                "v=excluded.v", (TEXT_INDEX,))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return True

    def set_meta(self, k, v):
        with self.wlock:
            self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
            self.db.commit()

    # ---------- learned app profiles (exe file names only) ----------
    def app_rows(self):
        return [(r[0], r[1]) for r in self.q("SELECT exe, data FROM apps")]

    def set_app(self, exe, data_json):
        with self.wlock:
            self.db.execute("INSERT INTO apps(exe,data) VALUES(?,?) ON CONFLICT(exe) DO UPDATE SET data=excluded.data",
                            (exe, data_json))
            self.db.commit()

    def drop_app(self, exe=None):
        with self.wlock:
            if exe is None:
                self.db.execute("DELETE FROM apps")
            else:
                self.db.execute("DELETE FROM apps WHERE exe=?", (exe,))
            self.db.commit()

    # ---------- files ----------
    def upsert_files(self, rows):
        rows = [(r[0], unicodedata.normalize("NFC", r[1])) + tuple(r[2:]) for r in rows]   # one spelling per name
        """rows: (path, name, dir, ext, kind, size, mtime, ctime, gen). A changed mtime makes the text stale."""
        if not rows:
            return
        with self.wlock:
            self.db.executemany(
                "INSERT INTO files(path,name,dir,ext,kind,size,mtime,ctime,gen) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, ctime=excluded.ctime, "
                "gen=excluded.gen, kind=excluded.kind, name=excluded.name, dir=excluded.dir, ext=excluded.ext",
                rows)
            self.db.commit()

    def drop_unseen(self, root, gen):
        """Delete files under root that the latest full scan (generation gen) didn't see."""
        like = root.rstrip("\\/").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\\\%"
        with self.wlock:
            n = self.db.execute("DELETE FROM files WHERE gen < ? AND (path LIKE ? ESCAPE '\\' OR path = ?)",
                                (gen, like, root)).rowcount
            self.db.commit()
        return n

    def remove_paths(self, paths):
        with self.wlock:
            for p in paths:
                like = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\\\%"
                self.db.execute("DELETE FROM files WHERE path = ? OR path LIKE ? ESCAPE '\\'", (p, like))
            self.db.commit()

    # ---------- the user's own folders first (0.9.1) ----------
    # Downloads, Desktop, Documents, Pictures, ... (the indexer sets them from Windows' known folders). Every work
    # queue takes their files first, then the rest of the PC, so on a whole-PC index your own files are read, looked
    # at and understood before Program Files and app caches. A path range uses the path index: no sort of the PC.
    prefer_roots = ()
    # Folders a search just asked about (a photo search "in downloads"): first of all, for a while (asked_until).
    asked_roots = ()

    # Files that just appeared or changed (0.9.3, the live watcher): before everything else, for FRESH_S.
    FRESH_S = 900
    FRESH_MAX = 400
    fresh = None                     # {path: when it changed}; None until the first change

    def mark_fresh(self, paths, now=None):
        now = time.time() if now is None else now
        if self.fresh is None:
            self.fresh = {}
        for p in paths:
            self.fresh[p] = now
        if len(self.fresh) > self.FRESH_MAX:            # the newest stay
            keep = sorted(self.fresh.items(), key=lambda x: -x[1])[:self.FRESH_MAX]
            self.fresh = dict(keep)

    def _fresh_paths(self, now=None):
        if not self.fresh:
            return []
        now = time.time() if now is None else now
        self.fresh = {p: t for p, t in self.fresh.items() if now - t <= self.FRESH_S}
        return sorted(self.fresh, key=lambda p: -self.fresh[p])[:200]

    def _roots_first(self):
        seen, out = set(), []
        for r in (*self.asked_roots, *self.prefer_roots):
            k = (r or "").rstrip("\\").lower()
            if k and k not in seen:
                seen.add(k)
                out.append(r.rstrip("\\"))
        return out

    def _first(self, build, args, limit, key=0):
        """build(extra) -> SQL with {extra} conditions on f.path; rows from the preferred roots first, then the rest.
        Files that just appeared or changed (mark_fresh) come before all of them."""
        out, seen = [], set()
        fresh = self._fresh_paths()
        if fresh:
            marks = ",".join("?" * len(fresh))
            for r in self.q(build(f" AND f.path IN ({marks})"), (*args, *fresh, limit)):
                if r[key] not in seen:
                    seen.add(r[key])
                    out.append(r)
        for root in self._roots_first():
            if len(out) >= limit:
                break
            lo = root + "\\"
            for r in self.q(build(" AND f.path >= ? AND f.path < ?"), (*args, lo, lo + "\uffff", limit - len(out))):
                if r[key] not in seen:
                    seen.add(r[key])
                    out.append(r)
        if len(out) < limit:
            for r in self.q(build(""), (*args, limit)):
                if r[key] not in seen:
                    seen.add(r[key])
                    out.append(r)
                    if len(out) >= limit:
                        break
        return out

    def needs_text(self, kinds_ext, max_bytes, limit=500, min_bytes=0, names=(), env=False):
        """Files to read, by extension; names: also these file names (lower case; text files without a readable
        extension, like .bash_history), env: also .env and .env.* files (secret_app_files)."""
        marks = ",".join("?" * len(kinds_ext))
        names = sorted(names)
        which = f"f.ext IN ({marks})"
        if names:
            which += f" OR (f.kind != 'folder' AND lower(f.name) IN ({','.join('?' * len(names))}))"
        if env:
            which += " OR (f.kind != 'folder' AND (lower(f.name) = '.env' OR lower(f.name) LIKE '.env.%'))"
        return self._first(lambda extra: (
            f"SELECT f.id, f.path, f.ext, f.size, f.mtime FROM files f WHERE ({which}) AND f.size <= ? "
            f"AND f.size >= ? AND (f.text_mtime IS NULL OR f.text_mtime <> f.mtime){extra} ORDER BY f.mtime DESC LIMIT ?"),
            (*sorted(kinds_ext), *names, max_bytes, min_bytes), limit)

    def read_again(self, file_ids, mark):
        """Files marked `mark` (names only) are read again: their text and photo marks go. Returns how many."""
        ids = list(file_ids)
        n = 0
        with self.wlock:
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                marks = ",".join("?" * len(part))
                n += self.db.execute(f"UPDATE files SET text_mtime = NULL, text_err = NULL WHERE text_err = ? AND id IN "
                                     f"({marks})", (mark, *part)).rowcount
                self.db.execute(f"DELETE FROM pvecs WHERE err = ? AND file_id IN ({marks})", (mark, *part))
            self.db.commit()
        return n

    def set_text(self, file_id, mtime, chunks, err=None, allow=None):
        """What was read from a file, and that it was read at mtime. allow: checked under the write lock, right
        before writing (the indexer's rules as they are NOW: a setting turned off while the file was being read,
        and the purge that followed, win); False = nothing is written and the file isn't marked read. A file whose
        row is gone gets nothing (no orphan text). Returns True when it was written."""
        with self.wlock:
            if allow is not None and not allow():
                return False
            if chunks and self.one("SELECT 1 FROM files WHERE id=?", (file_id,)) is None:
                return False
            self.db.execute("DELETE FROM chunks WHERE file_id=? AND ord IS NOT ?", (file_id, KEPT_ORD))
            self.db.executemany("INSERT INTO chunks(file_id, ord, body) VALUES(?,?,?)",
                                [(file_id, i, c) for i, c in enumerate(chunks)])
            self.db.execute("UPDATE files SET text_mtime=?, text_err=? WHERE id=?", (mtime, err, file_id))
            self.db.commit()
        return True

    def reset_scanned_pdfs(self, min_chars=200):
        """PDFs that gave (almost) no text are probably scans: read them again, now with OCR."""
        with self.wlock:
            n = self.db.execute(
                "UPDATE files SET text_mtime=NULL WHERE ext='.pdf' AND text_mtime IS NOT NULL AND text_err IS NULL "
                "AND COALESCE((SELECT sum(length(body)) FROM chunks WHERE file_id=files.id), 0) < ?",
                (min_chars,)).rowcount
            self.db.commit()
        return n

    # next=True: the tables a model switch fills (vecs_next, nvecs_next) while the current vectors stay in use
    def chunks_without_vectors(self, limit=256, next=False):
        t = "vecs_next" if next else "vecs"
        if not self._roots_first() and not self._fresh_paths():
            return self.q(f"SELECT c.id, c.body FROM chunks c LEFT JOIN {t} v ON v.chunk_id=c.id "
                          "WHERE v.chunk_id IS NULL LIMIT ?", (limit,))
        return self._first(lambda extra: (
            f"SELECT c.id, c.body FROM chunks c JOIN files f ON f.id = c.file_id LEFT JOIN {t} v ON v.chunk_id=c.id "
            f"WHERE v.chunk_id IS NULL{extra} LIMIT ?"), (), limit)

    def names_without_vectors(self, kinds, limit=256, next=False):
        t = "nvecs_next" if next else "nvecs"
        marks = ",".join("?" * len(kinds))
        return self._first(lambda extra: (
            f"SELECT f.id, f.name, f.dir FROM files f LEFT JOIN {t} v ON v.file_id=f.id "
            f"WHERE v.file_id IS NULL AND f.kind IN ({marks}){extra} LIMIT ?"), tuple(sorted(kinds)), limit)

    def add_name_vectors(self, rows, next=False):
        """rows: (file_id, blob). An empty blob means "looked at, no words worth a vector" (IMG_0042.jpg)."""
        t = "nvecs_next" if next else "nvecs"
        with self.wlock:
            self.db.executemany(f"INSERT OR REPLACE INTO {t}(file_id, v) VALUES(?,?)", rows)
            self.db.commit()

    def swap_vectors(self, model=None):
        """The new model's vectors replace the old ones and the index is tagged with `model`, all in one
        transaction: a search, or a crash, sees one set with its own model id or the other, never a mix."""
        with self.wlock:
            if model is not None:
                for k, v in (("vec_model", model), ("vec_model_next", "")):
                    self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                    (k, v))
            self.db.execute("DELETE FROM vecs")
            self.db.execute("INSERT INTO vecs(chunk_id, v) SELECT chunk_id, v FROM vecs_next")
            self.db.execute("DELETE FROM nvecs")
            self.db.execute("INSERT INTO nvecs(file_id, v) SELECT file_id, v FROM nvecs_next")
            self.db.execute("DELETE FROM vecs_next")
            self.db.execute("DELETE FROM nvecs_next")
            self.db.commit()

    def has_vectors(self):
        """True when the searched set has at least one text or name vector."""
        return bool(self.one("SELECT 1 FROM vecs LIMIT 1") or self.one("SELECT 1 FROM nvecs WHERE length(v) > 0 LIMIT 1"))

    def drop_next_vectors(self):
        with self.wlock:
            self.db.execute("DELETE FROM vecs_next")
            self.db.execute("DELETE FROM nvecs_next")
            self.db.commit()

    def photos_to_read(self, exts, min_bytes, max_bytes, limit=64):
        """Photos without a vector, or changed since theirs was made."""
        marks = ",".join("?" * len(exts))
        return self._first(lambda extra: (
            f"SELECT f.id, f.path, f.mtime FROM files f LEFT JOIN pvecs p ON p.file_id = f.id "
            f"WHERE f.ext IN ({marks}) AND f.size BETWEEN ? AND ? "
            f"AND (p.file_id IS NULL OR p.mtime IS NOT f.mtime){extra} ORDER BY f.mtime DESC LIMIT ?"),
            (*sorted(exts), min_bytes, max_bytes), limit)

    def count_readable(self, kinds_ext, max_bytes, min_bytes=0):
        """How many files the text reader is meant to read (same filter as needs_text)."""
        marks = ",".join("?" * len(kinds_ext))
        return self.one(f"SELECT count(*) FROM files WHERE ext IN ({marks}) AND size <= ? AND size >= ?",
                        (*sorted(kinds_ext), max_bytes, min_bytes)) or 0

    def count_needs_text(self, kinds_ext, max_bytes, min_bytes=0):
        marks = ",".join("?" * len(kinds_ext))
        return self.one(f"SELECT count(*) FROM files WHERE ext IN ({marks}) AND size <= ? AND size >= ? "
                        "AND (text_mtime IS NULL OR text_mtime <> mtime)",
                        (*sorted(kinds_ext), max_bytes, min_bytes)) or 0

    def count_chunks_without_vectors(self, next=False):
        t = "vecs_next" if next else "vecs"
        return self.one(f"SELECT count(*) FROM chunks c LEFT JOIN {t} v ON v.chunk_id=c.id "
                        "WHERE v.chunk_id IS NULL") or 0

    def count_names(self, kinds):
        marks = ",".join("?" * len(kinds))
        return self.one(f"SELECT count(*) FROM files WHERE kind IN ({marks})", tuple(sorted(kinds))) or 0

    def count_names_without_vectors(self, kinds, next=False):
        t = "nvecs_next" if next else "nvecs"
        marks = ",".join("?" * len(kinds))
        return self.one(f"SELECT count(*) FROM files f LEFT JOIN {t} v ON v.file_id=f.id "
                        f"WHERE v.file_id IS NULL AND f.kind IN ({marks})", tuple(sorted(kinds))) or 0

    def count_photos(self, exts, min_bytes, max_bytes):
        marks = ",".join("?" * len(exts))
        return self.one(f"SELECT count(*) FROM files WHERE ext IN ({marks}) AND size BETWEEN ? AND ?",
                        (*sorted(exts), min_bytes, max_bytes)) or 0

    def count_photos_to_read(self, exts, min_bytes, max_bytes):
        marks = ",".join("?" * len(exts))
        return self.one(f"SELECT count(*) FROM files f LEFT JOIN pvecs p ON p.file_id = f.id "
                        f"WHERE f.ext IN ({marks}) AND f.size BETWEEN ? AND ? "
                        f"AND (p.file_id IS NULL OR p.mtime IS NOT f.mtime)",
                        (*sorted(exts), min_bytes, max_bytes)) or 0

    def set_photo_vector(self, file_id, mtime, blob, err=None):
        with self.wlock:
            self.db.execute("INSERT OR REPLACE INTO pvecs(file_id, mtime, v, err) VALUES(?,?,?,?)",
                            (file_id, mtime, blob, err))
            self.db.commit()

    def drop_photo_vectors(self):
        """Every photo vector out (another photo model): every photo is looked at again."""
        with self.wlock:
            self.db.execute("DELETE FROM pvecs")
            self.db.commit()

    def drop_vectors(self):
        """Forget every meaning vector (the way they're made changed): they're computed again."""
        with self.wlock:
            self.db.execute("DELETE FROM vecs")
            self.db.execute("DELETE FROM nvecs")
            self.db.commit()

    def chunk_titles(self, chunk_ids):
        marks = ",".join("?" * len(chunk_ids))
        return dict(self.q(f"SELECT c.id, f.name FROM chunks c JOIN files f ON f.id=c.file_id WHERE c.id IN ({marks})",
                           chunk_ids)) if chunk_ids else {}

    def add_vectors(self, rows, next=False, bodies=None):
        """Meaning vectors (chunk_id, blob) into vecs (vecs_next: a model switch's). Only for chunks that are still
        there when the write lock is held (and, with bodies {chunk_id: text}, still hold the text the vector was
        made from: a chunk id can be used again): a purge between reading the text and this write (secret_app_files
        off, fix round 2) leaves no vector of it behind. Returns the chunk ids written, in order."""
        t = "vecs_next" if next else "vecs"
        rows = list(rows)
        with self.wlock:
            live = {}
            ids = [r[0] for r in rows]
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                live.update(self.q(f"SELECT id, body FROM chunks WHERE id IN ({','.join('?' * len(part))})", part))
            keep = [r for r in rows if r[0] in live and (bodies is None or bodies.get(r[0]) == live[r[0]])]
            self.db.executemany(f"INSERT OR REPLACE INTO {t}(chunk_id, v) VALUES(?,?)", keep)
            self.db.commit()
        return [r[0] for r in keep]

    # ---------- talk about a photo: what was read from it, and the description the user kept ----------
    def read_text(self, file_id):
        """The text read from inside a file (OCR for a photo), in order, when it was read from the file as it is now
        (text_mtime = mtime); "" otherwise. A kept description is not part of it."""
        if not self.one("SELECT 1 FROM files WHERE id=? AND text_mtime IS NOT NULL AND text_mtime = mtime",
                        (file_id,)):
            return ""
        rows = self.q("SELECT body FROM chunks WHERE file_id=? AND ord IS NOT ? ORDER BY ord", (file_id, KEPT_ORD))
        return "\n".join(r[0] for r in rows if r[0]).strip()

    def keep_description(self, file_id, text, model=""):
        """Store the user's kept description of a photo (vdesc) and make it that photo's KEPT_ORD chunk (searched by
        words, and by meaning once the indexer gives it a vector). Replaces an earlier one."""
        with self.wlock:
            self.db.execute("INSERT OR REPLACE INTO vdesc(file_id, text, model, at) VALUES(?,?,?,?)",
                            (file_id, text, model or "", time.time()))
            self.db.execute("DELETE FROM chunks WHERE file_id=? AND ord=?", (file_id, KEPT_ORD))
            self.db.execute("INSERT INTO chunks(file_id, ord, body) VALUES(?,?,?)", (file_id, KEPT_ORD, text))
            self.db.commit()

    def forget_description(self, file_id):
        with self.wlock:
            self.db.execute("DELETE FROM vdesc WHERE file_id=?", (file_id,))
            self.db.execute("DELETE FROM chunks WHERE file_id=? AND ord=?", (file_id, KEPT_ORD))
            self.db.commit()

    def kept_description(self, file_id):
        """{"text", "model", "at"} or None."""
        r = self.q("SELECT text, model, at FROM vdesc WHERE file_id=?", (file_id,))
        return {"text": r[0][0], "model": r[0][1] or "", "at": r[0][2] or 0.0} if r else None

    def with_content(self):
        """(id, path) of every file something was read from: text chunks, a photo vector or a kept description."""
        return self.q("SELECT id, path FROM files WHERE id IN (SELECT file_id FROM chunks) OR id IN "
                      "(SELECT file_id FROM pvecs WHERE length(v) > 0) OR id IN (SELECT file_id FROM vdesc)")

    def drop_content(self, file_ids, mark):
        """What was read from these files goes (text, its words and vectors, photo vectors, a kept description); the
        rows, their names and name vectors stay, marked `mark` so nothing reads them again. One transaction."""
        ids = list(file_ids)
        if not ids:
            return 0
        with self.wlock:
            self.db.execute("BEGIN")
            try:
                for i in range(0, len(ids), 500):
                    part = ids[i:i + 500]
                    marks = ",".join("?" * len(part))
                    self.db.execute(f"DELETE FROM chunks WHERE file_id IN ({marks})", part)   # text, vecs: triggers
                    self.db.execute(f"DELETE FROM vdesc WHERE file_id IN ({marks})", part)
                    self.db.execute(f"UPDATE pvecs SET v = x'', err = ? WHERE file_id IN ({marks})", (mark, *part))
                    self.db.execute(f"UPDATE files SET text_mtime = mtime, text_err = ? WHERE id IN ({marks})",
                                    (mark, *part))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return len(ids)

    # ---------- forgetting ----------
    def forget_path(self, path):
        self.remove_paths([path])

    def wipe(self):
        with self.wlock:
            for t in ("vecs", "nvecs", "vecs_next", "nvecs_next", "pvecs", "chunks", "files", "meta", "apps",
                      "search_history", "vdesc"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("INSERT INTO names(names) VALUES('rebuild')")
            self.db.execute("INSERT INTO text(text) VALUES('rebuild')")
            self.db.commit()
            self.db.execute("VACUUM")

    def remove_aside_copies(self):
        """Delete the index and key copies set aside when the key couldn't be read (*.unreadable-<stamp>): they hold
        an old index (Wipe: nothing of it stays). Returns how many went."""
        n = 0
        for p in (self.db_path, self.key_path):
            folder, base = os.path.split(p)
            try:
                names = os.listdir(folder or ".")
            except OSError:
                continue
            for name in names:
                if name.startswith(base + ".unreadable-"):
                    try:
                        os.remove(os.path.join(folder, name))
                        n += 1
                    except OSError as e:
                        log(f"couldn't delete an old index copy (error {e.errno})", "warn")
        return n

    def stats(self):
        return {
            "files": self.one("SELECT count(*) FROM files") or 0,
            "with_text": self.one("SELECT count(*) FROM files WHERE text_mtime IS NOT NULL AND text_err IS NULL") or 0,
            "chunks": self.one("SELECT count(*) FROM chunks") or 0,
            "vectors": self.one("SELECT count(*) FROM vecs") or 0,
            "name_vectors": self.one("SELECT count(*) FROM nvecs WHERE length(v) > 0") or 0,
            "photo_vectors": self.one("SELECT count(*) FROM pvecs WHERE length(v) > 0") or 0,
            "encrypted": self.encrypted,
            "db_bytes": sum(os.path.getsize(p) for p in (self.db_path, self.db_path + "-wal") if os.path.exists(p)),
        }


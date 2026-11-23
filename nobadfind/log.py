"""A tiny rotating log. Never pass file contents or secrets here, only short facts."""
import os
import threading
import time

_lock = threading.Lock()
_path = None
_MAX = 2 * 1024 * 1024


def init(path):
    global _path
    _path = path
    os.makedirs(os.path.dirname(path), exist_ok=True)


def log(msg, level="info"):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {level:5} {msg}"
    if _path is None:
        return
    with _lock:
        try:
            if os.path.exists(_path) and os.path.getsize(_path) > _MAX:
                os.replace(_path, _path + ".1")
            with open(_path, "a", encoding="utf-8") as f:
                f.write(line[:2000] + "\n")
        except OSError:
            pass


def clear():
    """Empty the log and drop the rotated copy (Wipe: nothing of the old index is left in plain text)."""
    if _path is None:
        return
    with _lock:
        for p in (_path + ".1", _path):
            try:
                if p == _path:
                    open(p, "w", encoding="utf-8").close()
                else:
                    os.remove(p)
            except OSError:
                pass

"""Notifications (notify.py): one place to post, dedupe and rate limits, the encrypted history, no file names by
default, Windows toasts only through a fake (never a real toast on this PC), and every hook posting the right kind."""
import os
import threading

import pytest

from nobadfind import notify
from nobadfind.const import DEFAULTS
from nobadfind.settings import coerce
from nobadfind.store import Store


class Clock:
    def __init__(self, t=1_763_400_000.0):
        self.t = t

    def __call__(self):
        return self.t


class S:
    def __init__(self, **kw):
        self.data = dict(DEFAULTS, **kw)

    def get(self, k):
        return self.data.get(k)


def center(store=None, quiet=lambda: False, **settings):
    toasts = []
    c = Clock()
    n = notify.Center(S(**settings), store=store, toast=lambda title, body: toasts.append((title, body)) or True,
                      quiet=quiet, clock=c, run=lambda fn: fn())
    return n, toasts, c


# ---------- posting, dedupe and rate limits ----------
def test_post_keeps_it_in_the_app_and_lists_newest_first():
    n, _toasts, c = center()
    a = n.post("suggestion", "First", "One", "info")
    c.t += 1
    b = n.post("internal_error", "Second", "Two", "error")
    got = n.list()
    assert [i["id"] for i in got["items"]] == [b["id"], a["id"]]
    assert got["unread"] == 2
    item = got["items"][0]
    assert set(item) == {"id", "t", "kind", "severity", "title", "body", "detail", "action", "read"}
    assert item["kind"] == "internal_error" and item["severity"] == "error" and item["read"] is False


def test_the_same_key_at_most_once_per_ten_minutes():
    n, toasts, c = center()
    assert n.post("worker_restarted", "T", "B", "warning", key="k") is not None
    c.t += 599
    assert n.post("worker_restarted", "T", "B", "warning", key="k") is None
    assert n.post("worker_restarted", "T", "B", "warning", key="other") is not None
    c.t += 2
    assert n.post("worker_restarted", "T", "B", "warning", key="k") is not None
    assert len(n.list()["items"]) == 3 and len(toasts) == 3


def test_a_key_can_ask_for_a_longer_gap():
    n, _t, c = center()
    assert n.post("suggestion", "T", "B", key="s", every=86400)
    c.t += 3600
    assert n.post("suggestion", "T", "B", key="s", every=86400) is None


def test_at_most_a_few_toasts_an_hour_the_rest_in_the_app_only():
    n, toasts, c = center()
    for i in range(notify.TOASTS_PER_HOUR + 3):
        c.t += 60
        assert n.post("worker_crashed", f"T{i}", "B", "warning", key=f"k{i}") is not None
    assert len(toasts) == notify.TOASTS_PER_HOUR
    assert len(n.list()["items"]) == notify.TOASTS_PER_HOUR + 3
    c.t += 3600
    n.post("worker_crashed", "later", "B", "warning", key="later")
    assert toasts[-1][0] == "later"


def test_bad_kind_and_severity_are_refused_without_raising():
    n, toasts, _c = center()
    assert n.post("not_a_kind", "T", "B") is None
    assert n.post("suggestion", "T", "B", "panic") is None
    assert n.post("suggestion", "", "") is None
    assert toasts == [] and n.list()["items"] == []


def test_long_text_is_cut():
    n, _t, _c = center()
    it = n.post("suggestion", "x" * 500, "y" * 2000)
    assert len(it["title"]) <= notify.MAX_TITLE and len(it["body"]) <= notify.MAX_BODY


# ---------- toasts: which ones go to Windows ----------
def test_by_default_warnings_and_errors_toast_and_info_stays_in_the_app():
    n, toasts, _c = center()
    n.post("suggestion", "Info", "B", "info")
    n.post("worker_restarted", "Warn", "B", "warning")
    n.post("internal_error", "Err", "B", "error")
    assert [t for t, _b in toasts] == ["Warn", "Err"]


def test_notify_level_and_the_toast_switch():
    n, toasts, _c = center(notify_level="error")
    n.post("worker_restarted", "Warn", "B", "warning")
    n.post("internal_error", "Err", "B", "error")
    assert [t for t, _b in toasts] == ["Err"]
    n, toasts, _c = center(notify_level="info")
    n.post("suggestion", "Info", "B", "info")
    assert toasts == [("Info", "B")]
    n, toasts, _c = center(notify_toasts=False)
    n.post("internal_error", "Err", "B", "error")
    assert toasts == [] and n.list()["unread"] == 1


def test_do_not_disturb_while_gaming_or_in_a_call_keeps_it_in_the_app():
    busy = {"on": True}
    n, toasts, _c = center(quiet=lambda: busy["on"])
    n.post("internal_error", "Err", "B", "error", key="a")
    assert toasts == [] and n.list()["unread"] == 1
    busy["on"] = False
    n.post("internal_error", "Err2", "B", "error", key="b")
    assert toasts == [("Err2", "B")]
    n, toasts, _c = center(quiet=lambda: True, notify_quiet=False)
    n.post("internal_error", "Err", "B", "error")
    assert len(toasts) == 1


def test_a_failing_toast_store_or_listener_never_raises():
    s = S()
    n = notify.Center(s, store=None, toast=lambda t, b: 1 / 0, quiet=lambda: 1 / 0, run=lambda fn: fn())
    n.listen(lambda item, unread: 1 / 0)
    assert n.post("internal_error", "T", "B", "error") is not None
    notify.CENTER, old = n, notify.CENTER
    try:
        n.post = lambda *a, **k: 1 / 0
        assert notify.post("internal_error", "T", "B", "error") is None      # the module helper never raises
    finally:
        notify.CENTER = old


def test_no_center_means_posting_does_nothing():
    old, notify.CENTER = notify.CENTER, None
    try:
        assert notify.post("suggestion", "T", "B") is None
    finally:
        notify.CENTER = old


# ---------- no file names or paths in the text by default ----------
def test_paths_never_reach_the_text_by_default():
    n, toasts, _c = center()
    it = n.post("worker_crashed", r"Reader stopped on C:\Users\me\secret plans.docx",
                r"While reading \\server\share\x.pdf and D:/notes/a.txt", "warning",
                detail=r"C:\Users\me\secret plans.docx")
    text = it["title"] + it["body"] + it["detail"] + "".join(t + b for t, b in toasts)
    for bad in ("secret", "server", "notes", "Users", "x.pdf"):
        assert bad not in text
    assert it["detail"] == ""


def test_the_sentence_around_a_path_stays():
    assert notify.scrub(r"Stopped on C:\Users\me\tax 2025.pdf. It is skipped", 300) == "Stopped on a file. It is skipped"
    assert notify.scrub("NOBAD Find 0.9.1 is out: https://github.com/nobad-studio/find", 300).endswith("/find")
    assert notify.scrub("Fewer workers in Settings > Performance use less memory.", 300) == \
        "Fewer workers in Settings > Performance use less memory."


def test_with_the_setting_on_only_the_file_name_is_shown():
    n, toasts, _c = center(notify_show_names=True)
    it = n.post("worker_crashed", "A file stopped the text reader", "It is skipped until it changes", "warning",
                detail=r"C:\Users\me\secret plans.docx")
    assert it["detail"] == "secret plans.docx"
    assert "Users" not in toasts[0][1] and "secret plans.docx" in toasts[0][1]


def test_turning_names_off_hides_the_ones_already_kept(tmp_path):
    st = Store(str(tmp_path / "i.db"), encrypt=False)
    s = S(notify_show_names=True)
    n = notify.Center(s, store=st, toast=lambda t, b: True, run=lambda fn: fn())
    n.post("worker_crashed", "T", "B", "warning", detail="a.docx")
    s.data["notify_show_names"] = False
    assert n.list()["items"][0]["detail"] == ""
    n.forget_names()
    assert st.one("SELECT count(*) FROM notifications WHERE detail != ''") == 0
    s.data["notify_show_names"] = True
    assert n.list()["items"][0]["detail"] == ""
    st.close()


# ---------- read, clear ----------
def test_read_some_all_and_clear(tmp_path):
    st = Store(str(tmp_path / "i.db"), encrypt=False)
    n = notify.Center(S(), store=st, toast=lambda t, b: True, run=lambda fn: fn())
    ids = [n.post("suggestion", f"T{i}", "B", key=f"k{i}")["id"] for i in range(3)]
    assert n.read(ids=[ids[0], 999])["unread"] == 2
    assert n.read(all=True)["unread"] == 0
    again = notify.Center(S(), store=st, toast=lambda t, b: True, run=lambda fn: fn())
    again.load()
    assert again.list()["unread"] == 0 and len(again.list()["items"]) == 3
    assert n.clear()["ok"] is True
    assert n.list() == {"items": [], "unread": 0}
    assert st.one("SELECT count(*) FROM notifications") == 0
    st.close()


# ---------- the history: inside the encrypted index, capped ----------
def test_history_is_capped_and_kept_inside_the_encrypted_index(tmp_path):
    st = Store(str(tmp_path / "e.db"), str(tmp_path / "e.key"))
    assert st.encrypted
    before = set(os.listdir(tmp_path))
    n = notify.Center(S(), store=st, toast=lambda t, b: True, run=lambda fn: fn(), clock=Clock())
    for i in range(notify.CAP + 30):
        n.clock.t += 1
        n.post("suggestion", f"Marker title {i}", "Marker body", key=f"k{i}")
    assert st.one("SELECT count(*) FROM notifications") == notify.CAP
    assert len(n.list()["items"]) == notify.CAP
    assert n.list()["items"][0]["title"] == f"Marker title {notify.CAP + 29}"
    again = notify.Center(S(), store=st, toast=lambda t, b: True, run=lambda fn: fn())
    again.load()
    assert [i["title"] for i in again.list()["items"]] == [i["title"] for i in n.list()["items"]]
    st.close()
    after = set(os.listdir(tmp_path))
    assert {f for f in after - before if not f.startswith("e.db")} == set()      # no other file
    for f in after:
        with open(tmp_path / f, "rb") as fh:
            assert b"Marker" not in fh.read()                                       # never in plain text


def test_wipe_deletes_the_history(tmp_path):
    st = Store(str(tmp_path / "i.db"), encrypt=False)
    n = notify.Center(S(), store=st, toast=lambda t, b: True, run=lambda fn: fn())
    n.post("suggestion", "T", "B")
    st.wipe()
    assert st.one("SELECT count(*) FROM notifications") == 0
    st.close()


def test_settings_are_checked():
    assert DEFAULTS["notify_toasts"] is True and DEFAULTS["notify_show_names"] is False
    assert DEFAULTS["notify_level"] == "warning" and DEFAULTS["notify_quiet"] is True
    assert coerce("notify_level", "error") == "error"
    assert coerce("notify_level", "loud") == "warning"
    assert coerce("notify_show_names", "yes") is False


def test_listeners_hear_each_new_notification_with_the_unread_count():
    n, _t, _c = center()
    heard = []
    n.listen(lambda item, unread: heard.append((item["title"], unread)))
    n.post("suggestion", "A", "B", key="a")
    n.post("suggestion", "C", "D", key="b")
    assert heard == [("A", 1), ("C", 2)]


def test_an_action_must_be_one_the_ui_knows():
    n, _t, _c = center()
    assert n.post("update_available", "T", "B", action="update")["action"] == {"id": "update", "label": "Update"}
    assert n.post("suggestion", "T", "B", action="run C:\\x.exe", key="z")["action"] is None


def test_the_toast_xml_escapes_its_text():
    xml = notify.toast_xml('<b>&"x"</b>', "it's")
    assert "<b>" not in xml and "&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;" in xml and "it&apos;s" in xml


def test_the_toast_uses_the_installers_app_id():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "packaging", "installer.iss"), encoding="utf-8") as f:
        assert f'AppUserModelID: "{notify.AUMID}"' in f.read()


def test_the_real_toast_falls_back_to_the_tray_balloon(monkeypatch):
    """Never a real toast: the WinRT call is replaced by one that fails, then by the balloon fake."""
    balloons = []
    monkeypatch.setattr(notify, "_winrt_toast", lambda title, body: (_ for _ in ()).throw(OSError("no AUMID")))
    show = notify.windows_toast(balloon=lambda t, b: balloons.append((t, b)) or True)
    assert show("T", "B") is True and balloons == [("T", "B")]
    monkeypatch.setattr(notify, "_winrt_toast", lambda title, body: True)
    balloons.clear()
    assert show("T", "B") is True and balloons == []


# ---------- hooks: each posts the right kind (fakes only) ----------
@pytest.fixture
def posted(monkeypatch):
    got = []

    class Rec:
        def post(self, kind, title, body, severity="info", action=None, key=None, detail="", every=None, once=False):
            got.append({"kind": kind, "title": title, "body": body, "severity": severity, "action": action,
                        "key": key, "detail": detail})
            return got[-1]
    monkeypatch.setattr(notify, "CENTER", Rec())
    return got


def test_watchdog_hooks(posted):
    from test_watchdog import make
    w, c, log, act = make(pids=[11], mem={11: 1638}, names={11: "text reader"})
    w.check()
    assert [p["kind"] for p in posted] == ["worker_restarted"] and posted[0]["severity"] == "warning"
    posted.clear()
    w, c, log, act = make(job_mb=3100)
    w.check()
    assert [p["kind"] for p in posted] == ["model_released_memory"]
    posted.clear()
    w, c, log, act = make(job_mb=3100)
    w._keep_models = lambda: True
    w.check()
    assert [p["kind"] for p in posted] == ["worker_restarted"]


def test_watchdog_twice_suggests(posted):
    from test_watchdog import make
    w, c, log, act = make(pids=[3], mem={3: 1600}, names={3: "photo worker"})
    w.check()
    c.t += 10
    w.check()
    assert "suggestion" in [p["kind"] for p in posted]


def test_update_available_hook(posted, tmp_path):
    from test_update import make, release
    rel, sha, _body = release("0.9.1")
    u, _started = make(tmp_path, rel, sha)
    u.check()
    assert u.state == "available"
    assert [p["kind"] for p in posted] == ["update_available"] and posted[0]["action"] == "update"
    assert posted[0]["key"] == "update:0.9.1"
    posted.clear()
    u.check()                                                   # the same version again: the Center dedupes by key
    assert posted[0]["key"] == "update:0.9.1"
    rel, sha, _body = release("0.9.0")
    u, _started = make(tmp_path, rel, sha)
    posted.clear()
    u.check()
    assert posted == []                                         # up to date: nothing


def test_unhandled_thread_errors_are_reported(posted):
    notify.install_thread_hook()
    try:
        t = threading.Thread(target=lambda: 1 / 0, name="test-thread")
        t.start()
        t.join()
    finally:
        notify.uninstall_thread_hook()
    assert [p["kind"] for p in posted] == ["internal_error"] and posted[0]["severity"] == "error"
    assert "ZeroDivisionError" in posted[0]["body"]


def test_governor_long_pause_hook(posted):
    from nobadfind.governor import Governor, Sample
    from nobadfind.activity import Activity

    class Apps:
        def start_level(self, exe):
            return None

        def record_lag(self, exe, s):
            pass

        def seen(self, exe):
            pass

    t = {"now": 1000.0}

    def sense():
        return Sample(t=t["now"], cpu=5.0, gpu=None, mem_load=90, free_mb=100, find_cpu=0.0, foreground="",
                      game=False, presentation=False, hung=False, battery=False, call=False, idle_s=0)
    g = Governor(S(), Apps(), Activity(), sense=sense, jobs=type("J", (), {"WORKERS": None, "OUTER": None})())
    g._read_usage = lambda: {"cpu_seconds": 0.0, "memory_mb": 0}
    g.tick()
    t["now"] += notify.LONG_PAUSE - 1
    g.tick()
    assert posted == []
    t["now"] += 2
    g.tick()
    t["now"] += 60
    g.tick()
    assert [p["kind"] for p in posted] == ["indexing_paused_reason"]
    assert "low on memory" in posted[0]["body"].lower()


def test_governor_your_own_break_is_never_reported(posted):
    from nobadfind.governor import Governor, Sample
    from nobadfind.activity import Activity
    t = {"now": 1000.0}

    def sense():
        return Sample(t=t["now"], cpu=5.0, gpu=None, mem_load=10, free_mb=9000, find_cpu=0.0, foreground="",
                      game=False, presentation=False, hung=False, battery=False, call=False, idle_s=0)
    g = Governor(S(), None, Activity(), sense=sense, jobs=type("J", (), {"WORKERS": None, "OUTER": None})())
    g._read_usage = lambda: {"cpu_seconds": 0.0, "memory_mb": 0}
    g.brain.pause_until = 10 ** 10
    g.tick()
    t["now"] += notify.LONG_PAUSE + 5
    g.tick()
    assert posted == []


import test_turbo_service  # noqa: E402

eng = test_turbo_service.eng          # the fixture: a Turbo with a fake setup and link (never UAC, never a service)


def test_turbo_needs_ok_hook(posted, eng):
    t, st, setup, launched = eng
    setup.st = "needs_update"
    st.update({"turbo": True})
    t.ensure()
    assert [p["kind"] for p in posted] == ["turbo_needs_ok"] and posted[0]["action"] == "open_turbo"


def _indexer(tmp_path):
    from nobadfind.indexer import Indexer
    st = Store(str(tmp_path / "i.db"), encrypt=False)
    st.upsert_files([("C:/Users/me/secret plans.docx", "secret plans.docx", "C:/Users/me", ".docx", "document",
                      10, 1.0, 1.0, 1)])
    return Indexer(st, S(), None), st


def test_indexer_crashed_reader_hooks(posted, tmp_path):
    ix, st = _indexer(tmp_path)
    job = (1, "C:/Users/me/secret plans.docx", ".docx", 1.0, 100, False)
    ix._reader_crashed("text reader", job, skipped=False)
    ix._reader_crashed("text reader", job, skipped=True)
    ix._reader_crashed("photo reader", None, skipped=False)
    assert [p["kind"] for p in posted] == ["worker_crashed"] * 3
    assert all("secret" not in p["title"] + p["body"] for p in posted)
    assert posted[1]["detail"] == "C:/Users/me/secret plans.docx"     # the Center keeps it only if names are on
    st.close()


def test_indexer_model_fallback_hook(posted, tmp_path, monkeypatch):
    from nobadfind import indexer as ix_mod, models
    ix, st = _indexer(tmp_path)
    ix.settings.data["semantic"] = True
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: False)
    monkeypatch.setattr(ix_mod, "vector_model", lambda store: "gone-model")
    ix._load_embedder()
    assert [p["kind"] for p in posted] == ["model_fallback"]
    st.close()


def test_governor_says_when_a_game_or_call_is_on():
    from nobadfind.governor import Governor, Sample
    from nobadfind.activity import Activity
    s = {"game": False, "call": False}

    def sense():
        return Sample(t=1000.0, cpu=5.0, gpu=None, mem_load=10, free_mb=9000, find_cpu=0.0, foreground="",
                      game=s["game"], presentation=False, hung=False, battery=False, call=s["call"], idle_s=0)
    g = Governor(S(), None, Activity(), sense=sense, jobs=type("J", (), {"WORKERS": None, "OUTER": None})())
    g._read_usage = lambda: {"cpu_seconds": 0.0, "memory_mb": 0}
    assert g.busy_with() is False
    g.tick()
    assert g.busy_with() is False
    s["game"] = True
    g.tick()
    assert g.busy_with() is True
    s["game"], s["call"] = False, True
    g.tick()
    assert g.busy_with() is True

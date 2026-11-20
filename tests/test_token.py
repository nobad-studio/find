"""0.9.1: keys, tokens and long random strings are found inside files, even as part of a longer string."""
from nobadfind import search
from nobadfind.store import Store

DL, APP = r"C:\Users\me\Downloads", r"C:\Program Files\App"


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(DL + r"\keys.env", "keys.env", DL, ".env", "text", 100, 1.0, 1.0, 1),
                    (APP + r"\app.log", "app.log", APP, ".log", "text", 100, 2.0, 1.0, 1),
                    (DL + r"\notes.txt", "notes.txt", DL, ".txt", "text", 100, 3.0, 1.0, 1)])
    ids = dict(s.q("SELECT name, id FROM files"))
    s.set_text(ids["keys.env"], 1.0, ["OPENAI_API_KEY=sk-proj-Xa83kd92Qz7 and more"])
    s.set_text(ids["app.log"], 2.0, ["token used: sk-proj-Xa83kd92Qz7 at 10:42"])
    s.set_text(ids["notes.txt"], 3.0, ["shopping list: milk, eggs"])
    return s, ids


def test_a_piece_of_a_key_finds_the_files_that_contain_it(tmp_path):
    s, ids = _store(tmp_path)
    r = search.search(s, "a83kd92Qz7")["results"]                 # the middle of "sk-proj-Xa83kd92Qz7"
    assert {x["name"] for x in r} == {"keys.env", "app.log"}
    snip = next(x["snippet"] for x in r if x["name"] == "keys.env")
    assert "\x02a83kd92Qz7\x03" in snip                            # the found text, marked for highlighting
    s.close()


def test_your_folders_first_and_the_budget(tmp_path, monkeypatch):
    s, ids = _store(tmp_path)
    s.prefer_roots = (DL,)
    found, _snips, complete = search._token_hits(s, "a83kd92Qz7", search.parse("a83kd92Qz7"), 1)
    assert found == [ids["keys.env"]] and complete                 # Downloads before Program Files
    t = [0.0]

    def clock():
        t[0] += 10.0                                               # every look takes "10 s": the budget is gone
        return t[0]
    found, _snips, complete = search._token_hits(s, "a83kd92Qz7", search.parse("a83kd92Qz7"), 10, clock=clock)
    assert complete is False
    s.close()


def test_file_names_and_words_dont_scan_the_text(tmp_path, monkeypatch):
    s, ids = _store(tmp_path)
    calls = []
    monkeypatch.setattr(search, "_token_hits", lambda *a, **k: calls.append(a[1]) or ([], {}, True))
    search.search(s, "report_v2.docx")
    search.search(s, "milk")
    assert calls == []
    search.search(s, "INV-2025-00417")
    assert calls == ["INV-2025-00417"]
    s.close()


def test_a_newer_search_still_cancels_a_token_scan(tmp_path):
    s, ids = _store(tmp_path)
    r = search.search(s, "a83kd92Qz7", cancelled=lambda: True)
    assert r.get("cancelled") is True
    r = search.search(s, "a83kd92Qz7", cancelled=lambda: False)    # and the handler is back for the next search
    assert len(r["results"]) == 2 and s._cancel is None
    s.close()

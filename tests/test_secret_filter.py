"""0.9.5: the "Keys & passwords" filter lists the files scope.Rules calls secrets, by name only."""
from nobadfind.search import search
from nobadfind.store import Store

H = "C:\\Users\\me"
FILES = [
    (H + "\\.ssh\\id_ed25519", "id_ed25519", H + "\\.ssh", "", "other"),
    (H + "\\.ssh", ".ssh", H, "", "folder"),
    (H + "\\Documents\\vault.kdbx", "vault.kdbx", H + "\\Documents", ".kdbx", "other"),
    (H + "\\.git-credentials", ".git-credentials", H, "", "other"),
    (H + "\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Login Data", "Login Data",
     H + "\\AppData\\Local\\Google\\Chrome\\User Data\\Default", "", "other"),
    (H + "\\Documents\\history.txt", "history.txt", H + "\\Documents", ".txt", "text"),   # yours, not a browser's
    (H + "\\Documents\\Login Data", "Login Data", H + "\\Documents", "", "other"),        # outside a browser profile
    (H + "\\Documents\\notes_100%.txt", "notes_100%.txt", H + "\\Documents", ".txt", "text"),
]


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(p, n, d, e, k, 10, 1.0, 1.0, 1) for p, n, d, e, k in FILES])
    return s


def names(r):
    return sorted(x["name"] for x in r["results"])


def test_the_filter_alone_lists_the_secrets_and_nothing_else(tmp_path):
    r = search(_store(tmp_path), "", filters={"kind": "secret"})
    assert names(r) == [".git-credentials", "Login Data", "id_ed25519", "vault.kdbx"]
    assert all("Documents\\Login Data" not in x["path"] for x in r["results"])


def test_the_filter_narrows_a_question(tmp_path):
    assert names(search(_store(tmp_path), "vault", filters={"kind": "secret"})) == ["vault.kdbx"]
    assert names(search(_store(tmp_path), "history", filters={"kind": "secret"})) == []


def test_the_filter_lists_the_2026_11_22_rules_too(tmp_path):
    """Program records and tokens (security review M2) by name, and a file that is a secret only in its folder."""
    s = _store(tmp_path)
    psr = H + "\\AppData\\Roaming\\Microsoft\\Windows\\PowerShell\\PSReadLine"
    more = [(H + "\\.m2\\settings.xml", "settings.xml", H + "\\.m2", ".xml", "text"),
            (H + "\\Documents\\settings.xml", "settings.xml", H + "\\Documents", ".xml", "text"),
            (H + "\\.config\\gh\\hosts.yml", "hosts.yml", H + "\\.config\\gh", ".yml", "text"),
            (psr + "\\ConsoleHost_history.txt", "ConsoleHost_history.txt", psr, ".txt", "text")]
    s.upsert_files([(p, n, d, e, k, 10, 1.0, 1.0, 1) for p, n, d, e, k in more])
    r = search(s, "", filters={"kind": "secret"})
    paths = {x["path"] for x in r["results"]}
    assert H + "\\.m2\\settings.xml" in paths and H + "\\Documents\\settings.xml" not in paths
    assert H + "\\.config\\gh\\hosts.yml" in paths
    assert any(p.endswith("ConsoleHost_history.txt") for p in paths)

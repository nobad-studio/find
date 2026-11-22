"""CHANGELOG.md as the release workflow (find-release.yml) reads it: one heading per version, notes under each,
and the "(in development)" check matching the heading format in use ("## 1.1.0 · (in development)")."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _dev_pattern(version):
    """The workflow's "still in development" -Pattern for `version`, as a Python regex (.NET and Python agree on it)."""
    wf = _read(".github", "workflows", "find-release.yml")
    m = re.search(r'-Pattern "(\^## \$\(\[regex\]::Escape\(\$env:APP_VER\)\)[^"]*)"', wf)
    assert m, "find-release.yml: the in-development check is gone"
    return m.group(1).replace("$([regex]::Escape($env:APP_VER))", re.escape(version))


def test_in_development_check_matches_the_heading_format():
    p = re.compile(_dev_pattern("1.1.0"), re.M)
    assert p.search("## 1.1.0 · (in development)\n")
    assert p.search("## 1.1.0 (in development)\n")
    assert not p.search("## 1.1.0 · 2026-12-01\n")
    assert not p.search("## 1.1.01 · (in development)\n")
    assert not p.search("## 1.0.0 · (in development)\n")


def test_each_version_has_one_heading_and_notes():
    s = _read("CHANGELOG.md")
    heads = re.findall(r"^## (\d+\.\d+\.\d+)\b", s, re.M)
    assert heads and len(heads) == len(set(heads)), "a version heading appears twice"
    for v in heads:     # the workflow's release-notes extraction must find text under each heading
        m = re.search(r"^## " + re.escape(v) + r"\b.*?(?=^## |\Z)", s, re.S | re.M)
        assert m and m.group(0).strip().count("\n") >= 2, f"{v} has no notes under its heading"

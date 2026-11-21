"""Scores a model's answer against the expected answer of one benchmark item (dev only, never shipped).

Kinds: `objects` (fraction of expected things named; a list entry is a synonym group), `text` (expected text
appears), `count` (first number or number word equals), `yesno` (first yes/no equals), `describe` (fraction of
expected keywords present). Everything is compared after normalize(), so case, spacing, punctuation and Unicode
forms (Hindi typed two ways) don't change a score.
"""
import re
import unicodedata

KINDS = ("objects", "text", "count", "yesno", "describe")
_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
NUMBER_WORDS = {w: i for i, w in enumerate(_WORDS)}


def normalize(text):
    """NFC, case-folded, punctuation as spaces (letters, digits and combining marks such as Hindi matras kept),
    whitespace collapsed."""
    text = unicodedata.normalize("NFC", str(text)).casefold()
    # format characters (ZWJ/ZWNJ inside Hindi words) are dropped, not turned into word breaks
    out = [ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text if unicodedata.category(ch) != "Cf"]
    return " ".join("".join(out).split())


def _has(haystack, needle):
    """needle (normalized) appears in haystack (normalized) as whole words."""
    n = normalize(needle)
    return bool(n) and f" {n} " in f" {haystack} "


def _first_number(answer):
    for tok in answer.split():
        if tok.isdecimal():          # not isdigit(): "²" and "①" are digits int() can't read
            return int(tok)
        if tok in NUMBER_WORDS:
            return NUMBER_WORDS[tok]
    return None


def score_item(item, answer):
    """0.0-1.0 for `answer` against item["expect"], by item["kind"]."""
    kind, expect, a = item["kind"], item["expect"], normalize(answer)
    if kind == "text":
        return 1.0 if _has(a, expect) else 0.0
    if kind in ("objects", "describe"):
        groups = [g if isinstance(g, list) else [g] for g in expect]
        if not groups:
            return 0.0
        return sum(1 for g in groups if any(_has(a, s) for s in g)) / len(groups)
    if kind == "count":
        return 1.0 if _first_number(a) == int(expect) else 0.0
    if kind == "yesno":
        m = re.search(r"\b(yes|no)\b", a)
        return 1.0 if m and (m.group(1) == "yes") == bool(expect) else 0.0
    raise ValueError(f"unknown kind {kind!r}")


def aggregate(scores):
    """[(kind, score)] -> mean per kind, plus "all" (mean of every item)."""
    by = {}
    for kind, s in scores:
        by.setdefault(kind, []).append(s)
    out = {k: sum(v) / len(v) for k, v in by.items()}
    out["all"] = sum(s for _, s in scores) / len(scores) if scores else 0.0
    return out

"""Fixed prompts for talk about a photo, and the rules for the user's question.

The image marker is not here: the session inserts mtmd's own marker (mtmd_default_marker()) where the picture goes.
"""
import re

MAX_QUESTION = 500
_TOKENS = {"describe": 200, "ask": 120, "compare": 160}
_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_TEXT_WORDS = re.compile(
    r"\b(written|write|read|reads|reading|says|say|text|sign|signs|number|numbers|price|prices|word|words)\b",
    re.IGNORECASE)


def describe():
    return ("Describe this photo in two or three plain sentences: what is in it and what is happening. "
            "Say only what you can see. If you are not sure, say so.")


def ask(question):
    return ("Answer the question about this photo briefly, using only what you can see. "
            "If the photo does not show the answer, say so.\nQuestion: " + clean_question(question))


def compare(question):
    q = clean_question(question) if question else ""
    base = "These are two photos. Say briefly how they differ and what they have in common, using only what you can see."
    return base + ("\nQuestion: " + q if q else "")


def clean_question(q):
    """Control characters (and terminal escape sequences) removed, whitespace collapsed, at most 500 characters."""
    q = _CONTROL.sub(" ", q or "")
    return " ".join(q.split())[:MAX_QUESTION].strip()


def is_text_question(q):
    """Does the question ask about writing in the photo? Then the stored OCR text is given first."""
    return bool(_TEXT_WORDS.search(q or "") or _DEVANAGARI.search(q or ""))


def max_tokens(kind):
    return _TOKENS[kind]


def flag_unverified(answer):
    """Devanagari in an answer: the UI adds "may not be exact"."""
    return bool(_DEVANAGARI.search(answer or ""))

"""Fixed prompts for talk about a photo, and the rules for the user's question.

The image marker is not here: the session inserts mtmd's own marker (mtmd_default_marker()) where the picture goes.
"""
import re

MAX_QUESTION = 500
_TOKENS = {"describe": 200, "ask": 120, "compare": 160}
_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]")
# Invisible characters that reorder or join text (bidi controls, zero-width marks, the word joiner, the BOM): a
# question can look harmless on screen and say something else, or hide a special token from the rule below.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
# Chat special-token shapes. The session tokenizes the whole prompt with parse_special on (mtmd needs it for the
# template's own tokens), so a typed "<|im_end|>" or "<end_of_utterance>" would become a real control token and
# steer the turn. Removed: <|anything|>, and <word> tokens without spaces (<start_of_turn>, <image>, </s>, mtmd's
# own <__media__> marker). Cost: a literal "<b>" can't be asked about. "a < b > c" (spaces) is kept.
_SPECIAL = re.compile(r"<\|[^\s<>]{0,64}?\|>|</?[A-Za-z_][\w:./-]{0,63}>")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_TEXT_WORDS = re.compile(
    r"\b(written|write|read|reads|reading|says|say|text|sign|signs|number|numbers|price|prices|word|words)\b",
    re.IGNORECASE)


def describe():
    return ("Describe this photo in two or three plain sentences: what is in it and what is happening. "
            "Say only what you can see. If you are not sure, say so.")


def ask(question):
    """ValueError when nothing is left of the question once cleaned (only spaces or control characters)."""
    q = clean_question(question)
    if not q:
        raise ValueError("empty question")
    return ("Answer the question about this photo briefly, using only what you can see. "
            "If the photo does not show the answer, say so.\nQuestion: " + q)


def compare(question):
    q = clean_question(question) if question else ""
    base = "These are two photos. Say briefly how they differ and what they have in common, using only what you can see."
    return base + ("\nQuestion: " + q if q else "")


def clean_question(q):
    """Control characters (and terminal escape sequences), invisible bidi / zero-width characters and chat
    special-token shapes (mtmd's picture marker included) removed, whitespace collapsed, at most 500 characters."""
    q = _INVISIBLE.sub("", q if isinstance(q, str) else "")
    q = _CONTROL.sub(" ", q)
    # A space, so "what<image>is" stays two words. It can't rebuild a token: a shape has no whitespace inside, so
    # "<<|x|>|im_end|>" becomes "< |im_end|>", plain text. The loop is kept as a belt for shapes found later.
    while True:
        out = _SPECIAL.sub(" ", q)
        if out == q:
            break
        q = out
    return " ".join(q.split())[:MAX_QUESTION].strip()


def clean_text(text, limit):
    """Text the user keeps (a description): control and invisible characters removed, whitespace collapsed, at most
    `limit` characters. Special-token shapes stay: this text is stored and searched, never given to a model."""
    t = _INVISIBLE.sub("", text if isinstance(text, str) else "")
    return " ".join(_CONTROL.sub(" ", t).split())[:limit].strip()


def is_text_question(q):
    """Does the question ask about writing in the photo? Then the stored OCR text is given first."""
    return bool(_TEXT_WORDS.search(q or "") or _DEVANAGARI.search(q or ""))


def max_tokens(kind):
    return _TOKENS[kind]


def flag_unverified(answer):
    """Devanagari in an answer: the UI adds "may not be exact"."""
    return bool(_DEVANAGARI.search(answer or ""))

"""Text the engine builds for people out of names it doesn't control (security review 2026-11-22, L7).

A file name, a folder or a Start menu app name was chosen by whoever made it: a right-to-left override makes
"Invoice_<RLO>fdp.exe" read as "Invoice_exe.pdf". Wherever the engine puts such a name into a sentence or a label
(why a result matched, a suggestion, an app action), the direction controls and invisible characters below are
shown as "[U+202E]", so the text reads in the order it really is. The Flutter UI does the same for every name it
draws (ui_flutter/lib/engine/models/safe_text.dart); keep the two lists in step. ZWJ / ZWNJ stay (Hindi, emoji).
Data fields (a result's name, dir, path) stay as they are on disk: the UI cleans them when it draws them.
"""
import re

HIDDEN = (0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x061C,
          0x200B, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x180E, 0xFEFF)
_HIDDEN = re.compile("[" + "".join(chr(c) for c in HIDDEN) + "]")


def visible(s):
    """s with every HIDDEN character shown as [U+XXXX]; s itself when there is none (or it isn't a string)."""
    if not isinstance(s, str) or not _HIDDEN.search(s):
        return s
    return _HIDDEN.sub(lambda m: f"[U+{ord(m.group()):04X}]", s)

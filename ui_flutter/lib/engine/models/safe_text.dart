/// File and folder names come from the disk: anyone who can put a file there chose them. Security review 2026-11-22
/// (L7): a right-to-left override makes `Invoice_<RLO>fdp.exe` look like `Invoice_exe.pdf`, and a double click
/// would run it. Every name and folder from the index is drawn through [visibleControls]: the direction controls
/// and invisible characters below become a visible `[U+202E]`, so the text reads in the order it really is and
/// the real extension stays at the end. (ZWJ / ZWNJ stay: Hindi and emoji need them, and they don't move text.)
/// The engine does the same for the sentences it builds (nobadfind/display.py); keep the two lists in step.
library;

/// The characters made visible: LRE RLE PDF LRO RLO (U+202A-U+202E), LRI RLI FSI PDI (U+2066-U+2069), LRM RLM
/// (U+200E, U+200F), the Arabic letter mark (U+061C), and the invisible zero width space (U+200B), word joiner
/// (U+2060) and byte order mark (U+FEFF).
const hiddenControls = <int>{
  0x202A, 0x202B, 0x202C, 0x202D, 0x202E, //
  0x2066, 0x2067, 0x2068, 0x2069, //
  0x200E, 0x200F, 0x061C, //
  0x200B, 0x2060, 0xFEFF,
};

final _hidden = RegExp('[${hiddenControls.map((c) => String.fromCharCode(c)).join()}]');

/// [s] with every [hiddenControls] character shown as `[U+XXXX]`; the same string when there is none.
String visibleControls(String s) {
  if (!_hidden.hasMatch(s)) return s;
  return s.replaceAllMapped(
    _hidden,
    (m) => '[U+${m.group(0)!.codeUnitAt(0).toRadixString(16).toUpperCase().padLeft(4, '0')}]',
  );
}

/// True when [s] has a character [visibleControls] would show.
bool hasHiddenControls(String s) => _hidden.hasMatch(s);

/// The extension Windows goes by (what really opens the file), lower case with its dot: '.exe' for
/// `Invoice_<RLO>fdp.exe`; '' when there is none.
String realExtension(String name) {
  final s = name.replaceAll(_hidden, '').trimRight();
  final slash = s.lastIndexOf(r'\');
  final base = slash < 0 ? s : s.substring(slash + 1);
  final dot = base.lastIndexOf('.');
  if (dot <= 0 || dot == base.length - 1) return '';
  return base.substring(dot).toLowerCase();
}

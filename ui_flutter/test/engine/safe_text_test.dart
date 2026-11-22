// Security review 2026-11-22 (L7): names with direction controls or invisible characters are drawn with them shown.
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/safe_text.dart';

void main() {
  test('every direction control and invisible character becomes visible', () {
    for (final c in hiddenControls) {
      final s = visibleControls('a${String.fromCharCode(c)}b');
      expect(s, 'a[U+${c.toRadixString(16).toUpperCase().padLeft(4, '0')}]b');
      expect(hasHiddenControls(s), isFalse); // and the result is clean
    }
    expect(visibleControls('Invoice_\u202Efdp.exe'), 'Invoice_[U+202E]fdp.exe');
    expect(visibleControls('\u2067x\u2069'), '[U+2067]x[U+2069]');
  });

  test('ordinary names, Hindi and emoji are left alone', () {
    for (final s in ['tax return 2025.pdf', 'बिजली का बिल.pdf', 'क्\u200Dष.txt', 'family 👨\u200D👩\u200D👧.jpg', 'עברית.docx']) {
      expect(visibleControls(s), s);
      expect(hasHiddenControls(s), isFalse);
    }
  });

  test('the real extension is what Windows opens it by', () {
    expect(realExtension('Invoice_\u202Efdp.exe'), '.exe');
    expect(realExtension('Report.PDF'), '.pdf');
    expect(realExtension('archive.tar.gz'), '.gz');
    expect(realExtension('README'), '');
    expect(realExtension('.gitignore'), '');
    expect(realExtension('x.exe\u200B'), '.exe');
  });

  test('every text from the index that is drawn is cleaned when it is parsed', () {
    final r = FileResult.fromJson({
      'id': 1,
      'name': 'a\u202Eb.txt',
      'dir': 'C:\\x\u202E',
      'path': 'C:\\x\u202E\\a\u202Eb.txt',
      'snippet': 'one \u2066two',
      'why': ['in \u202Ex'],
      'kind': 'text',
    })!;
    expect(r.name, 'a[U+202E]b.txt');
    expect(r.dir, 'C:\\x[U+202E]');
    expect(r.path, 'C:\\x\u202E\\a\u202Eb.txt'); // the real path, for Copy path; never drawn
    expect(r.snippet, 'one [U+2066]two');
    expect(r.why, ['in [U+202E]x']);
    expect(r.disguised, isTrue);
    final s = Suggestion.fromJson({'text': 'a', 'kind': 'file', 'label': 'a\u202Eb', 'detail': 'C:\\\u202E'})!;
    expect(s.label, 'a[U+202E]b');
    expect(s.detail, 'C:\\[U+202E]');
    expect(QueryPart.fromJson({'kind': 'folder', 'label': 'in \u202Ex'})!.label, 'in [U+202E]x');
    expect(SearchAction.fromJson({'id': 'app:1:x', 'title': 'Spot\u202Eify'})!.title, 'Spot[U+202E]ify');
  });
}

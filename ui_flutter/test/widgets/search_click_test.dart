// 1.2: a click previews, it never opens. Double-click, Enter or the pane's Open opens; Ctrl+Enter / Ctrl+click shows
// the file in its folder.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/features/search/result_tile.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

/// A result's name inside its list row or card (the pane and Home show names too).
Finder row(String name) => find
    .descendant(of: find.byWidgetPredicate((w) => w is ResultTile || w is ResultCard), matching: find.text(name))
    .first;

Finder paneOpen() => find.byWidgetPredicate((w) => w is NbButton && w.label == 'Open').first;

void main() {
  testWidgets('a single click selects and previews; it never opens', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'tax');
    await tester.tap(row('tax notes.txt'));
    await tester.pump(const Duration(milliseconds: 600)); // past any double-click wait
    expect(engine.opened, isEmpty);
    expect(engine.revealed, isEmpty);
    // the detail pane shows what was clicked
    expect(row('tax notes.txt'), findsWidgets);
    expect(find.descendant(of: find.byType(DetailPane), matching: find.text('tax notes.txt')), findsOneWidget);
    expect(paneOpen(), findsOneWidget);
  });

  testWidgets('clicking a row selects it at once: the pane follows without waiting for a double-click', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'tax');
    final second = row('tax return 2025.pdf');
    await tester.tap(second);
    await tester.pump(const Duration(milliseconds: 20));
    expect(engine.opened, isEmpty);
    expect(find.descendant(of: find.byType(DetailPane), matching: find.text('tax return 2025.pdf')), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 500)); // the double-click window ends
  });

  testWidgets('a double-click opens', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'notes');
    final target = row('tax notes.txt');
    await tester.tap(target);
    await tester.pump(const Duration(milliseconds: 80));
    await tester.tap(target);
    await tester.pump();
    expect(engine.opened, [2]);
  });

  testWidgets('two clicks on different rows do not open anything', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'tax');
    await tester.tap(row('tax notes.txt'));
    await tester.pump(const Duration(milliseconds: 80));
    await tester.tap(row('tax return 2025.pdf'));
    await tester.pump(const Duration(milliseconds: 600));
    expect(engine.opened, isEmpty);
  });

  testWidgets('the pane\'s Open button opens the selected result', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'notes');
    await tester.tap(row('tax notes.txt'));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.tap(paneOpen());
    await tester.pump();
    expect(engine.opened, [2]);
  });

  testWidgets('Enter opens the selected result, Ctrl+Enter shows it in its folder', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'notes');
    await tester.tap(row('tax notes.txt'));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.opened, [2]);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(engine.revealed, [2]);
  });

  testWidgets('Ctrl+click shows the file in its folder and opens nothing', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'notes');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.tap(row('tax notes.txt'));
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump(const Duration(milliseconds: 600));
    expect(engine.revealed, [2]);
    expect(engine.opened, isEmpty);
  });

  testWidgets('in the card view too: click previews, double-click opens', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'notes');
    await tester.tap(find.text('Cards'));
    await tester.pumpAndSettle();
    final card = row('tax notes.txt');
    await tester.tap(card);
    await tester.pump(const Duration(milliseconds: 600));
    expect(engine.opened, isEmpty);
    await tester.tap(card);
    await tester.pump(const Duration(milliseconds: 60));
    await tester.tap(card);
    await tester.pump();
    expect(engine.opened, [2]);
  });
}

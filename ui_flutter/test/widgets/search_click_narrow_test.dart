// 1.2: in a window too narrow for the detail pane (960 wide: 760 of content), a click previews in a strip under the
// results. It never covers the list, so a second click still opens; its Open opens; Ctrl+click reveals; Esc closes it.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/features/search/preview_strip.dart';
import 'package:nobad_find/features/search/result_tile.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

const narrow = Size(960, 700);

Finder row(String name) => find
    .descendant(of: find.byWidgetPredicate((w) => w is ResultTile || w is ResultCard), matching: find.text(name))
    .first;

Finder stripButton(String label) => find.descendant(
  of: find.byType(PreviewStrip),
  matching: find.byWidgetPredicate((w) => w is NbButton && w.label == label),
);

/// Past the double-click window and the strip's size animation (it starts on the frame after the click).
Future<void> later(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 16));
  await tester.pump(const Duration(milliseconds: 600));
}

Future<FakeEngine> open(WidgetTester tester) async {
  final engine = FakeEngine();
  await pumpApp(tester, engine, size: narrow);
  await type(tester, 'tax');
  return engine;
}

void main() {
  testWidgets('no detail pane and no strip until a result is clicked', (tester) async {
    await open(tester);
    expect(find.byType(DetailPane), findsNothing);
    expect(find.byType(PreviewStrip), findsNothing);
  });

  testWidgets('a click selects and shows the strip; nothing opens', (tester) async {
    final engine = await open(tester);
    await tester.tap(row('tax return 2025.pdf'));
    await later(tester);
    expect(engine.opened, isEmpty);
    expect(find.byType(PreviewStrip), findsOneWidget);
    expect(find.descendant(of: find.byType(PreviewStrip), matching: find.text('tax return 2025.pdf')), findsOneWidget);
    // the strip follows the keyboard selection too
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await later(tester);
    expect(find.descendant(of: find.byType(PreviewStrip), matching: find.text('tax return 2025.pdf')), findsNothing);
    expect(engine.opened, isEmpty);
  });

  testWidgets('the strip does not cover the list: a second click on the row opens it', (tester) async {
    final engine = await open(tester);
    final target = row('tax return 2025.pdf');
    await tester.tap(target);
    await tester.pump(const Duration(milliseconds: 80));
    expect(find.byType(PreviewStrip), findsOneWidget);
    await tester.tap(target);
    await later(tester);
    expect(engine.opened, [1]);
  });

  testWidgets("the strip's Open opens and Show in folder reveals the selected result", (tester) async {
    final engine = await open(tester);
    await tester.tap(row('tax return 2025.pdf'));
    await later(tester);
    await tester.tap(stripButton('Open'));
    await tester.pump();
    expect(engine.opened, [1]);
    await tester.tap(stripButton('Show in folder'));
    await tester.pump();
    expect(engine.revealed, [1]);
  });

  testWidgets('Ctrl+click reveals and opens nothing', (tester) async {
    final engine = await open(tester);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.tap(row('tax return 2025.pdf'));
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await later(tester);
    expect(engine.revealed, [1]);
    expect(engine.opened, isEmpty);
  });

  testWidgets('the close button and Esc close the strip; Esc leaves the typed words for the next press', (tester) async {
    await open(tester);
    await tester.tap(row('tax return 2025.pdf'));
    await later(tester);
    await tester.tap(find.bySemanticsLabel('Close preview'));
    await later(tester);
    expect(find.byType(PreviewStrip), findsNothing);

    await tester.tap(row('tax return 2025.pdf'));
    await later(tester);
    expect(find.byType(PreviewStrip), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await later(tester);
    expect(find.byType(PreviewStrip), findsNothing);
    expect(find.text('tax'), findsOneWidget); // the box still holds the words
  });

  testWidgets('a wide window has the pane and never the strip', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1280, 800));
    await type(tester, 'tax');
    await tester.tap(row('tax return 2025.pdf'));
    await later(tester);
    expect(find.byType(DetailPane), findsOneWidget);
    expect(find.byType(PreviewStrip), findsNothing);
  });
}

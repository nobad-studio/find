// 1.2: a search that takes a while shows a small ring in the search box, only after 150 ms; it goes away with the
// answer or when the box is cleared, and is a still dot when Windows' animation effects are off.
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField, ValueKey;

import '../support/fake_engine.dart';

const ring = ValueKey('searching-ring');
const dot = ValueKey('searching-dot');

Future<FakeEngine> slow(WidgetTester tester, {bool? reduceMotion, int ms = 1000}) async {
  final engine = FakeEngine()..searchDelay = Duration(milliseconds: ms);
  await pumpApp(tester, engine, reduceMotion: reduceMotion);
  return engine;
}

void main() {
  testWidgets('no ring at first, a ring after 150 ms, gone with the answer', (tester) async {
    await slow(tester, reduceMotion: false);
    await tester.enterText(find.byType(TextField).first, 'tax');
    await tester.pump(const Duration(milliseconds: 60)); // the debounce: the search starts
    expect(find.byKey(ring), findsNothing);
    await tester.pump(const Duration(milliseconds: 100)); // 100 ms into the search
    expect(find.byKey(ring), findsNothing);
    await tester.pump(const Duration(milliseconds: 100)); // 200 ms in
    expect(find.byKey(ring), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1000));
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(ring), findsNothing);
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
  });

  testWidgets('a search that answers in under 150 ms never shows the ring', (tester) async {
    await slow(tester, reduceMotion: false, ms: 100);
    await tester.enterText(find.byType(TextField).first, 'tax');
    await tester.pump(const Duration(milliseconds: 120));
    var seen = false;
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 20));
      seen |= find.byKey(ring).evaluate().isNotEmpty;
    }
    expect(seen, isFalse);
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
  });

  testWidgets('clearing the box (cancel) takes the ring away', (tester) async {
    await slow(tester, reduceMotion: false, ms: 5000);
    await tester.enterText(find.byType(TextField).first, 'tax');
    await tester.pump(const Duration(milliseconds: 120));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(ring), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '');
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(ring), findsNothing);
    await tester.pump(const Duration(seconds: 6)); // the old answer arrives late: nothing comes back
    expect(find.byKey(ring), findsNothing);
  });

  testWidgets('with reduce-motion the same wait shows a still dot, not a turning ring', (tester) async {
    await slow(tester, reduceMotion: true);
    await tester.enterText(find.byType(TextField).first, 'tax');
    await tester.pump(const Duration(milliseconds: 120));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(dot), findsOneWidget);
    expect(find.byKey(ring), findsNothing);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(dot), findsNothing);
  });
}

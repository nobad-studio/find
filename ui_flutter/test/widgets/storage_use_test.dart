// 1.2: what NOBAD Find keeps on disk (storage_use) on the Index page and in Settings > Models; "Free up" goes to Models.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/models_info.dart';

import '../support/fake_engine.dart';

Future<void> goTo(WidgetTester tester, LogicalKeyboardKey digit) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(digit);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
}

void main() {
  test('storage_use parses what the engine sends and survives missing parts', () {
    final u = StorageUse.fromJson({
      'index_mb': 412.5,
      'wal_mb': 3.2,
      'models': [
        {'id': 'minilm-l6-v2', 'mb': 23.0},
        {'nope': 1},
      ],
      'runtime_mb': 4.0,
      'tmp_mb': 0.0,
      'total_mb': 442.7,
    });
    expect((u.indexMb, u.walMb, u.runtimeMb, u.tmpMb, u.totalMb), (412.5, 3.2, 4.0, 0.0, 442.7));
    expect(u.models.map((m) => m.id), ['minilm-l6-v2']);
    expect(u.modelsMb, 23.0);
    expect(StorageUse.fromJson(null).totalMb, 0);
  });

  testWidgets('the Index page shows what is kept on disk, and Free up opens Settings > Models', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1180, 2600));
    await goTo(tester, LogicalKeyboardKey.digit2);
    expect(engine.calls, contains('storage_use'));
    expect(find.text('Stored on this PC'), findsOneWidget);
    expect(find.textContaining('650 MB'), findsWidgets); // the fake engine's total
    await tester.tap(find.text('Free up'));
    await tester.pumpAndSettle();
    expect(find.text('Recommended for this PC: Balanced'), findsOneWidget); // Settings > Models
  });

  testWidgets('Settings > Models shows the same figures', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1180, 2600));
    await goTo(tester, LogicalKeyboardKey.digit3);
    await tester.tap(find.textContaining('Models').last);
    await tester.pumpAndSettle();
    expect(find.text('Stored on this PC'), findsOneWidget);
    expect(find.text('Free up'), findsNothing); // already there: remove a model below
  });

  testWidgets('an older engine without storage_use shows nothing, not a made-up figure', (tester) async {
    final engine = FakeEngine()..storage = null;
    await pumpApp(tester, engine, size: const Size(1180, 2600));
    await goTo(tester, LogicalKeyboardKey.digit2);
    expect(find.text('Stored on this PC'), findsNothing);
  });
}

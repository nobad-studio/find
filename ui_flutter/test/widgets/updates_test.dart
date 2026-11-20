// Settings > About > Updates (0.9.0): up to date, a newer version with Install, and the toast when one is found.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/update.dart';

import '../support/fake_engine.dart';

Future<void> openAbout(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1080, 1400));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.text('About'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('up to date: says so, Check now asks the engine', (tester) async {
    final engine = FakeEngine();
    await openAbout(tester, engine);
    expect(engine.calls, contains('update_state'));
    expect(find.text('NOBAD Find is up to date (0.9.0).'), findsOneWidget);
    expect(find.text('Install'), findsNothing);
    await tester.tap(find.text('Check now'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('update_check'));
  });

  testWidgets('a newer version: Install starts the update and says NOBAD Find restarts', (tester) async {
    final engine = FakeEngine()
      ..updates = const UpdateState(state: 'available', current: '0.9.0', latest: '0.9.1', size: 41943040);
    await openAbout(tester, engine);
    expect(find.text('NOBAD Find 0.9.1 is available (40 MB).'), findsOneWidget);
    expect(find.textContaining("isn't code-signed yet"), findsOneWidget);
    await tester.tap(find.text('Install'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('update_install'));
    expect(find.textContaining('closes and starts again'), findsOneWidget);
  });

  testWidgets('an update found while NOBAD Find runs shows a toast once', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    const u = UpdateState(state: 'available', current: '0.9.0', latest: '0.9.1');
    engine.emit(const UpdateEvent(u));
    await tester.pump();
    expect(find.textContaining('NOBAD Find 0.9.1 is available'), findsOneWidget);
    await tester.pump(const Duration(seconds: 10));
    engine.emit(const UpdateEvent(u));                 // the same version again: no second toast
    await tester.pump();
    expect(find.textContaining('NOBAD Find 0.9.1 is available'), findsNothing);
    await tester.pump(const Duration(seconds: 10));
  });

  test('update_state is read from the engine; an empty one reads as idle', () {
    final u = UpdateState.fromJson({'state': 'ready', 'current': '0.9.0', 'latest': '0.9.1', 'size': 10, 'got': 10});
    expect(u.canInstall, isTrue);
    expect(UpdateState.fromJson(null).state, 'idle');
    expect(const UpdateState(state: 'uptodate', current: '0.9.0', latest: '0.9.0').canInstall, isFalse);
  });
}

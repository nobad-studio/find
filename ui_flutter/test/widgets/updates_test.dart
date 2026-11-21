// Settings > About > Updates (0.9.0): up to date, a newer version with Install, and the toast when one is found.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/update.dart';
import 'package:nobad_find/features/settings/update_progress.dart';
import 'package:nobad_find/widgets/panels.dart';

import '../support/fake_engine.dart';

Future<void> openAbout(WidgetTester tester, FakeEngine engine, {bool? reduceMotion}) async {
  await pumpApp(tester, engine, size: const Size(1080, 1400), reduceMotion: reduceMotion);
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
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300)); // not pumpAndSettle: the current step's dot breathes
    expect(engine.calls, contains('update_install'));
    // the engine says downloading: the three steps and an empty bar, no speed claimed before it's measured
    expect(find.byKey(const ValueKey('update-progress')), findsOneWidget);
    expect(find.text('Downloading NOBAD Find 0.9.1'), findsOneWidget);
    expect(find.text('0%'), findsOneWidget);
    expect(find.text('0.0 of 40.0 MB'), findsOneWidget);
    expect(find.text('Install'), findsOneWidget); // the step's label; the button is gone while it runs
    expect(find.text('Check now'), findsOneWidget);

    // progress events from the engine move the bar, the numbers and the sidebar
    engine.emit(UpdateEvent(engine.updates.copyWith(got: 10485760, bps: 2097152)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('25%'), findsOneWidget);
    expect(find.text('10.0 of 40.0 MB  ·  2.0 MB/s  ·  about 15 s left'), findsOneWidget);
    expect(find.text('Updating · 25%'), findsOneWidget);

    // every byte in: the checksum step, with its own words; no percent any more
    engine.emit(UpdateEvent(engine.updates.copyWith(state: 'verifying', got: 41943040, bps: 0)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Checking the download'), findsOneWidget);
    expect(find.textContaining('SHA-256 must match'), findsOneWidget);
    expect(find.text('25%'), findsNothing);
    expect(find.byType(NbSweep), findsOneWidget);
    expect(find.text('Checking the update'), findsOneWidget);

    engine.emit(UpdateEvent(engine.updates.copyWith(state: 'installing')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Installing 0.9.1'), findsOneWidget);
    expect(find.textContaining('closes and starts again'), findsOneWidget);
    expect(find.text('Installing the update'), findsOneWidget);
    if (Platform.environment['NOBAD_FIND_TEST_MOTION'] != 'off') {
      expect(tester.hasRunningAnimations, isTrue); // the sweep and the current step's dot move
    }
  });

  testWidgets('with Animation effects off the checking step is still', (tester) async {
    final engine = FakeEngine()
      ..updates = const UpdateState(state: 'ready', current: '0.9.0', latest: '0.9.1', size: 41943040, got: 41943040);
    await openAbout(tester, engine, reduceMotion: true);
    await tester.tap(find.text('Install now'));
    await tester.pumpAndSettle(); // settles: nothing repeats
    expect(find.text('Checking the download'), findsOneWidget);
    expect(find.byType(NbSweep), findsOneWidget);
    expect(tester.hasRunningAnimations, isFalse);
  });

  testWidgets('the sidebar read-out opens About while an update downloads', (tester) async {
    const u = UpdateState(state: 'downloading', current: '0.9.0', latest: '0.9.1', size: 1000, got: 400, bps: 100);
    final engine = FakeEngine()..updates = u; // what update_state answers when About opens
    await pumpApp(tester, engine);
    expect(find.byKey(const ValueKey('sidebar-update')), findsNothing);
    engine.emit(const UpdateEvent(u));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Updating · 40%'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('sidebar-update')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Downloading NOBAD Find 0.9.1'), findsOneWidget);
    engine.emit(const UpdateEvent(UpdateState(state: 'error', current: '0.9.0', latest: '0.9.1', error: 'Try again.')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('sidebar-update')), findsNothing);
    expect(find.byKey(const ValueKey('update-progress')), findsNothing);
  });

  test('the download line says only what was measured', () {
    const u = UpdateState(state: 'downloading', size: 41943040, got: 1048576);
    expect(downloadLine(u), '1.0 of 40.0 MB'); // no speed yet: no speed, no time left
    expect(u.secondsLeft, isNull);
    final fast = u.copyWith(bps: 1048576);
    expect(downloadLine(fast), '1.0 of 40.0 MB  ·  1.0 MB/s  ·  about 39 s left');
    expect(fast.copyWith(got: 1048576 * 10, bps: 104858).secondsLeft, 300);
    expect(timeLeft(300), 'about 5 min left');
    expect(UpdateState.fromJson({'state': 'downloading', 'size': 10, 'got': 5}).bps, 0); // an older engine
    expect(const UpdateState(state: 'verifying').installing, isTrue);
    expect(const UpdateState(state: 'verifying').busy, isTrue);
    expect(const UpdateState(state: 'ready').installing, isFalse);
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

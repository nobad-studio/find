// Settings > Shortcuts (0.9.0): a hotkey is changed by pressing the keys (or typing them), checked by the engine
// before it's saved, and takes effect at once; Settings says whether each one works.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/features/settings/hotkey_setting.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> ctrl(WidgetTester tester, LogicalKeyboardKey k) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(k);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
}

Future<void> openShortcuts(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1080, 1200));
  await ctrl(tester, LogicalKeyboardKey.digit3);
  await tester.tap(find.text('Shortcuts'));
  await tester.pumpAndSettle();
}

/// Holds [mods], presses [key], lets go of everything.
Future<void> press(
  WidgetTester tester,
  List<LogicalKeyboardKey> mods,
  LogicalKeyboardKey key,
) async {
  for (final m in mods) {
    await tester.sendKeyDownEvent(m);
  }
  await tester.sendKeyDownEvent(key);
  await tester.pumpAndSettle();
  await tester.sendKeyUpEvent(key);
  for (final m in mods.reversed) {
    await tester.sendKeyUpEvent(m);
  }
  await tester.pumpAndSettle();
}

void main() {
  test('pressed keys become the engine\'s spelling; modifiers alone or other keys are not a hotkey', () {
    const k = LogicalKeyboardKey.keyF;
    expect(
      hotkeyFromKeys(k, {
        LogicalKeyboardKey.shiftLeft,
        LogicalKeyboardKey.metaLeft,
      }),
      'win+shift+f',
    );
    expect(
      hotkeyFromKeys(LogicalKeyboardKey.space, {
        LogicalKeyboardKey.controlRight,
        LogicalKeyboardKey.shiftLeft,
      }),
      'ctrl+shift+space',
    );
    expect(
      hotkeyFromKeys(LogicalKeyboardKey.f9, {LogicalKeyboardKey.altLeft}),
      'alt+f9',
    );
    expect(hotkeyFromKeys(k, {}), isNull); // needs a modifier
    expect(
      hotkeyFromKeys(LogicalKeyboardKey.tab, {LogicalKeyboardKey.controlLeft}),
      isNull,
    );
    expect(hotkeyCaps('win+shift+f'), ['Win', 'Shift', 'F']);
    expect(hotkeyCaps('ctrl+alt+f11'), ['Ctrl', 'Alt', 'F11']);
  });

  testWidgets(
    'shows the keys and that they work; a pressed free combination is checked, then saved at once',
    (tester) async {
      final engine = FakeEngine();
      await openShortcuts(tester, engine);
      expect(engine.calls, contains('hotkey_state'));
      expect(
        find.text('Works now, anywhere in Windows.'),
        findsNWidgets(2),
      ); // both hotkeys
      expect(
        find.byWidgetPredicate((w) => w is Kbd && w.label == 'Win'),
        findsWidgets,
      );
      await tester.tap(find.text('Change').first);
      await tester.pumpAndSettle();
      expect(find.textContaining('Press the new shortcut now'), findsOneWidget);
      await press(tester, [
        LogicalKeyboardKey.controlLeft,
        LogicalKeyboardKey.altLeft,
      ], LogicalKeyboardKey.keyK);
      expect(engine.calls, contains('hotkey_probe'));
      expect(find.text('Ctrl+Alt+K is free to use.'), findsOneWidget);
      await tester.tap(find.text('Use it'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'hotkey': 'ctrl+alt+k'});
      expect(find.text('Use it'), findsNothing); // back to the row
      expect(
        find.byWidgetPredicate((w) => w is Kbd && w.label == 'K'),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'a combination another app holds, or Windows keeps, is explained and can\'t be saved',
    (tester) async {
      final engine = FakeEngine()..takenHotkeys.add('ctrl+alt+k');
      await openShortcuts(tester, engine);
      await tester.tap(find.text('Change').first);
      await tester.pumpAndSettle();
      await press(tester, [
        LogicalKeyboardKey.controlLeft,
        LogicalKeyboardKey.altLeft,
      ], LogicalKeyboardKey.keyK);
      expect(
        find.text('Another app on this PC already uses it.'),
        findsOneWidget,
      );
      await tester.tap(find.text('Use it'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet, isEmpty);
      await press(tester, [
        LogicalKeyboardKey.metaLeft,
        LogicalKeyboardKey.shiftLeft,
      ], LogicalKeyboardKey.digit1);
      expect(
        find.text('Windows uses Win+Shift+number for the taskbar.'),
        findsOneWidget,
      );
      await press(tester, const [], LogicalKeyboardKey.escape); // Esc cancels
      expect(find.text('Use it'), findsNothing);
    },
  );

  testWidgets(
    'typing works too, for combinations Windows never hands to an app',
    (tester) async {
      final engine = FakeEngine();
      await openShortcuts(tester, engine);
      await tester.tap(find.text('Change').last); // the quick find bar's
      await tester.pumpAndSettle();
      await tester.tap(find.text('Type it instead'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byWidgetPredicate(
          (w) => w is NbField && w.label == 'Type the shortcut',
        ),
        'Win+Alt+G',
      );
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();
      expect(find.text('Win+Alt+G is free to use.'), findsOneWidget);
      await tester.tap(find.text('Use it'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'bar_hotkey': 'win+alt+g'});
    },
  );

  testWidgets('a hotkey that stopped working says so', (tester) async {
    final engine = FakeEngine()..takenHotkeys.add('win+shift+f');
    await openShortcuts(tester, engine);
    expect(
      find.text('Not working: another app on this PC uses it. Change it.'),
      findsOneWidget,
    );
  });
}

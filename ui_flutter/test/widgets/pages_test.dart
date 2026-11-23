import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField;
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/settings.dart' show BrowserDataState;
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> ctrl(WidgetTester tester, LogicalKeyboardKey k) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(k);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
}

void main() {
  group('Index', () {
    testWidgets('shows the level and its reason; Pause for 1 hour, then Resume', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit2);
      expect(find.text('Working gently'), findsOneWidget);
      expect(find.text('Reading documents'), findsOneWidget);
      expect(find.text('31,877 / 40,112'), findsOneWidget);
      expect(find.textContaining('done in about 9 min'), findsOneWidget);
      expect(find.text('Processes'), findsOneWidget);
      expect(find.text('Text reader worker'), findsNWidgets(2));
      expect(find.text('Meaning worker'), findsOneWidget);
      expect(find.text('Runs the AI model for text, so you can search by what files mean.'), findsOneWidget);
      expect(find.text('Idle: waiting for work'), findsOneWidget);
      expect(find.text('14 min'), findsOneWidget); // the window, 871 s
      expect(find.textContaining("5 processes of NOBAD Find's own"), findsOneWidget);
      expect(find.textContaining('The index is encrypted on disk'), findsOneWidget);
      await tester.tap(find.text('Pause for 1 hour'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('pause_for'));
      expect(find.text('Paused'), findsWidgets);
      expect(find.text('Paused: you paused NOBAD Find for 60 min'), findsWidgets);
      await tester.tap(find.text('Resume'));
      await tester.pumpAndSettle();
      expect(find.text('Working gently'), findsOneWidget);
    });

    testWidgets('2026-11-21: how many of each operation run at once now, and what set it', (tester) async {
      final engine = FakeEngine()
        ..limits = const OpLimits(
          walk: OpLimit(8, 'governor'),
          readers: OpLimit(2, 'memory'),
          photo: OpLimit(4, 'cpu'),
          vision: OpLimit(0, 'gpu'),
        );
      await pumpApp(tester, engine, size: const Size(1080, 2600));
      await ctrl(tester, LogicalKeyboardKey.digit2);
      expect(find.text('Running at once now'), findsOneWidget);
      expect(find.text('Text readers · set by free memory'), findsOneWidget);
      expect(find.text('File walk threads · set by the current level'), findsOneWidget);
      expect(find.text('Vision streams · set by the graphics card'), findsOneWidget);
    });

    testWidgets('watches status_full only while open; there is no light theme to pick (0.8.5 is dark only)', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine);
      await ctrl(tester, LogicalKeyboardKey.digit2);
      expect(engine.watching, isTrue);
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.pumpAndSettle();
      expect(find.text('Light'), findsNothing);
      await ctrl(tester, LogicalKeyboardKey.digit1);
      expect(engine.watching, isFalse);
    });

    testWidgets('a model card downloads the recommended model only after consent, then shows the progress', (
      tester,
    ) async {
      final engine = FakeEngine();
      final want = engine.modelsInfo.byFeature('text').firstWhere((m) => m.recommended);
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit2);
      await tester.ensureVisible(find.text('Download…').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Download…').first);
      await tester.pumpAndSettle();
      expect(find.text('Download ${want.name}?'), findsOneWidget); // the model it gets, not a fixed one
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      expect(engine.calls, isNot(contains('model_download')));
      await tester.ensureVisible(find.text('Download…').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Download…').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Download'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('model_download'));
      expect(engine.calls, isNot(contains('download_meaning'))); // never the old fixed MiniLM download
      engine.emit(const DownloadEvent(id: 'meaning', state: 'downloading', gotMb: 11.5, sizeMb: 23, mbS: 4));
      await tester.pumpAndSettle();
      expect(find.text('Downloading 12 MB of 23 MB at 4.0 MB/s'), findsOneWidget);
    });
  });

  group('Settings', () {
    testWidgets('eight pages in the sidebar; a switch goes to the engine', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      for (final p in [
        'General',
        'Search',
        'What to index',
        'Models & languages',
        'Performance',
        'Privacy & data',
        'Shortcuts',
        'About',
      ]) {
        expect(find.text(p), findsWidgets);
      }
      await tester.tap(find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Start with Windows'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'autostart': true});
      await tester.tap(find.text('Performance'));
      await tester.pumpAndSettle();
      expect(find.text('Cyberpunk2077'), findsOneWidget);
      await tester.ensureVisible(find.text('Forget').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Forget').first);
      await tester.pumpAndSettle();
      expect(find.text('Cyberpunk2077'), findsNothing);
      await tester.tap(find.text('About'));
      await tester.pumpAndSettle();
      expect(find.text('NOBAD. Software with a point of view.'), findsOneWidget);
    });

    testWidgets('a folder is added through the engine; Delete index needs DELETE typed', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1200));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('What to index'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Custom'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'scope': 'custom'});
      await tester.tap(find.text('Add folder').first);
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {
        'roots': [r'C:\Users\me\Projects'],
      });
      expect(find.text(r'C:\Users\me\Projects'), findsOneWidget);

      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Delete index')); // below the fold with the Notifications group
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete index'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, 'delete');
      await tester.pump();
      await tester.tap(find.text('Delete index').last); // disabled: nothing happens
      await tester.pump();
      expect(engine.calls, isNot(contains('wipe')));
      await tester.enterText(find.byType(TextField).last, 'DELETE');
      await tester.pump();
      await tester.tap(find.text('Delete index').last);
      await tester.pumpAndSettle();
      expect(engine.calls, contains('wipe'));
      expect(find.text('Index deleted. Rebuilding.'), findsOneWidget);
    });

    testWidgets('reading app files asks once, says what is read, and off needs no question', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      const label = 'Read command histories, saved logins and tool tokens';
      expect(find.text(label), findsOneWidget);
      for (final words in [
        'command histories (PowerShell, bash',
        'saved-site and login files of FTP/SSH tools (FileZilla, WinSCP',
        'developer tool tokens (GitHub CLI, npm',
        'Cargo',
        '.env files',
        'Recent items are never read',
      ]) {
        expect(find.textContaining(words), findsOneWidget, reason: words);
      }
      final sw = find.byWidgetPredicate((w) => w is NbSwitch && w.label == label);
      await tester.ensureVisible(sw);
      await tester.pumpAndSettle();
      await tester.tap(sw);
      await tester.pumpAndSettle();
      expect(find.text('Read these files?'), findsOneWidget);
      expect(find.textContaining('may include passwords and tokens'), findsOneWidget);
      expect(find.textContaining("NOBAD Find's encrypted index on this PC"), findsOneWidget);
      expect(find.textContaining('can appear in search results'), findsOneWidget);
      expect(find.textContaining('"App data, caches and code folders" is on'), findsOneWidget); // M2
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.where((c) => c.containsKey('secret_app_files')), isEmpty);
      await tester.tap(sw);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Read them'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'secret_app_files': true});
      expect(engine.consents.last, 'READ_APP_SECRETS'); // the engine turns it on only with this word (M7)
      expect(tester.widget<NbSwitch>(sw).value, isTrue); // the engine took it
      await tester.tap(sw); // off: no question and no word, the engine removes what was read
      await tester.pumpAndSettle();
      expect(find.text('Read these files?'), findsNothing);
      expect(engine.settingsSet.last, {'secret_app_files': false});
      expect(engine.consents.last, isNull);
    });

    testWidgets('browser data: off by default, reading more asks once, narrowing needs no question', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      for (final words in ['Never passwords', 'page contents, cookies', 'your browser keeps running', 'Firefox']) {
        expect(find.textContaining(words), findsOneWidget, reason: words);
      }
      Future<void> pick(String option) async {
        final box = find.byWidgetPredicate((w) => w is NbSelect && w.label == 'Search my browsers');
        await tester.ensureVisible(box);
        await tester.pumpAndSettle();
        await tester.tap(box);
        await tester.pumpAndSettle();
        await tester.tap(find.text(option).last);
        await tester.pumpAndSettle();
      }

      expect(find.text('Off'), findsWidgets);
      await pick('History, bookmarks and downloads');
      expect(find.text('Read your browsers?'), findsOneWidget);
      expect(find.textContaining('Passwords are never read'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.where((c) => c.containsKey('browser_data')), isEmpty);
      await pick('Also saved logins (no passwords)');
      await tester.tap(find.text('Read them'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'browser_data': 'history_logins'});
      expect(engine.consents.last, 'READ_BROWSER_DATA');
      expect(find.text('Edge (Work): 131 items, read 5 min ago'), findsOneWidget); // browser_data_state
      await pick('History, bookmarks and downloads'); // narrowing: no question, no word
      expect(find.text('Read your browsers?'), findsNothing);
      expect(engine.settingsSet.last, {'browser_data': 'history'});
      expect(engine.consents.last, isNull);
      // Clear browser data: asks first, then the engine clears and the line says so
      final clear = find.widgetWithText(NbButton, 'Clear browser data');
      await tester.ensureVisible(clear);
      await tester.pumpAndSettle();
      await tester.tap(clear);
      await tester.pumpAndSettle();
      expect(find.text('Clear browser data?'), findsOneWidget);
      expect(find.textContaining('Your browsers keep their own history'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(engine.calls, isNot(contains('browser_clear')));
      await tester.tap(clear);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Clear'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('browser_clear'));
      expect(find.text('Browser data cleared.'), findsOneWidget);
      expect(find.text('Edge (Work): 0 items, read 5 min ago'), findsOneWidget);
    });

    test('browser_data_state: one plain line, the problem instead of the counts', () {
      final now = DateTime.fromMillisecondsSinceEpoch(1700000600 * 1000);
      final st = BrowserDataState.fromJson({
        'setting': 'history',
        'profiles': [
          {
            'browser': 'Edge',
            'profile': 'Work',
            'last_read': 1700000000.0,
            'error': '',
            'counts': {'history': 120, 'bookmark': 8, 'download': 3, 'login': 0},
          },
          {
            'browser': 'Firefox',
            'profile': 'default',
            'last_read': null,
            'error': 'in use by the browser; trying again in 5 min',
            'counts': {},
          },
        ],
      });
      expect(
        st.summary(now),
        'Edge (Work): 131 items, read 10 min ago · Firefox (default): in use by the browser; trying again in 5 min',
      );
      expect(BrowserDataState.fromJson({'setting': 'off', 'profiles': []}).summary(now), '');
      expect(
        BrowserDataState.fromJson({'setting': 'history', 'profiles': []}).summary(now),
        startsWith('Not read yet'),
      );
    });

    testWidgets('Windows Search: one click, and the words say what happens', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Windows Search indexing is on (delayed-auto, running)'), findsOneWidget);
      await tester.tap(find.text('Switch to NOBAD Find'));
      await tester.pumpAndSettle();
      expect(find.text('Done.'), findsOneWidget);
      expect(find.text('Go back to Windows Search'), findsOneWidget);
    });

    testWidgets('Quit asks the engine to quit', (tester) async {
      final engine = FakeEngine();
      final w = await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('About'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Quit').last);
      await tester.pumpAndSettle();
      expect(engine.calls, contains('quit'));
      expect(w.calls, contains('close')); // the quitting event closes the window
    });
  });

  testWidgets('first run: the welcome, then Start searching remembers it', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': false, 'bg_notice_seen': true});
    await pumpApp(tester, engine);
    await tester.pumpAndSettle();
    expect(find.text('Start searching'), findsOneWidget);
    expect(find.text('Software with a point of view.'), findsOneWidget);
    await tester.ensureVisible(find.text('Start searching'));
    await tester.tap(find.text('Start searching'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'welcome_seen': true});
    expect(find.text('Start searching'), findsNothing);
  });

  testWidgets('the one-time notice on Index goes away with Got it', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': true, 'bg_notice_seen': false});
    await pumpApp(tester, engine);
    await ctrl(tester, LogicalKeyboardKey.digit2);
    expect(find.textContaining('Closing the window now stops indexing.'), findsOneWidget);
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Closing the window now stops indexing.'), findsNothing);
  });

  testWidgets('a notice from the engine shows as a toast', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(const NoticeEvent('The hotkey is used by another app. Pick another one in Settings.'));
    await tester.pump();
    expect(find.text('The hotkey is used by another app. Pick another one in Settings.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 4));
  });
}

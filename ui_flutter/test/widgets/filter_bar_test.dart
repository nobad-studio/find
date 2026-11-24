// 1.2.0 (browser spec §4): the filter bar's "Settings & apps" and "Browser" choices, the Browser kinds, the date
// range that shows only with History, and browser results opened by their id (the engine opens them).
import 'package:flutter/gestures.dart' show kSecondaryButton;
import 'package:flutter/widgets.dart' show Size, ValueKey;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show MenuItemButton, TextField;
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/features/search/result_tile.dart' show DetailPane;
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Finder select(String label) => find.byWidgetPredicate((w) => w is NbSelect && w.label == label);

NbSelect selectOf(WidgetTester tester, String label) => tester.widget<NbSelect>(select(label));

List<String> options(WidgetTester tester, String label) => [for (final o in selectOf(tester, label).options) o.$1];

Future<void> choose(WidgetTester tester, String label, String value) async {
  selectOf(tester, label).onChanged(value);
  await tester.pumpAndSettle();
}

const _on = {'welcome_seen': true, 'bg_notice_seen': true, 'browser_data': 'history_logins'};

const _web = FileResult(
  id: -3,
  name: 'GitHub: pull requests',
  path: 'https://github.com/pulls',
  dir: 'Edge (Work) · github.com',
  kind: 'browser',
  mtime: 1763300000,
  ago: '3 days ago',
  why: ['title matches'],
  browser: BrowserItem(browser: 'Edge', profile: 'Work', kind: 'history', title: 'GitHub: pull requests',
      url: 'https://github.com/pulls', host: 'github.com', at: 1763300000, visits: 9),
);

const _login = FileResult(
  id: -4,
  name: 'github.com',
  path: 'https://github.com/login',
  dir: 'Edge (Work) · saved login for alice',
  kind: 'browser',
  browser: BrowserItem(browser: 'Edge', profile: 'Work', kind: 'login', title: 'alice',
      url: 'https://github.com/login', host: 'github.com'),
);

void main() {
  setUp(() {});

  testWidgets('Settings & apps is always offered; Browser not while browser data is off', (tester) async {
    final off = FakeEngine();
    await pumpApp(tester, off);
    await type(tester, 'x');
    expect(options(tester, 'Kind'), contains('launcher'));
    expect(options(tester, 'Kind'), isNot(contains('browser')));
  });

  testWidgets('with browser data on, the Browser kind is offered', (tester) async {
    final on = FakeEngine(settings: _on);
    await pumpApp(tester, on);
    await type(tester, 'x');
    expect(options(tester, 'Kind'), containsAll(['launcher', 'browser']));
  });

  testWidgets('the date range shows only when History is selected', (tester) async {
    final engine = FakeEngine(settings: _on)..browserResults = [_web, _login];
    await pumpApp(tester, engine);
    await type(tester, 'github');
    expect(select('Browser'), findsNothing);
    expect(select('Visited'), findsNothing);

    await choose(tester, 'Kind', 'browser');
    expect(select('Browser'), findsOneWidget);
    expect(options(tester, 'Browser'), ['', 'history', 'bookmark', 'login', 'download']);
    expect(select('Visited'), findsNothing); // Everything: no dates
    expect(select('Changed'), findsNothing); // a file's date, size and folder don't apply
    expect(select('Size'), findsNothing);

    await choose(tester, 'Browser', 'history');
    expect(select('Visited'), findsOneWidget);
    expect(options(tester, 'Visited'), ['', 'today', 'yesterday', 'week', 'month', 'pick']);
    await choose(tester, 'Visited', 'week');
    expect(engine.searchFilters.last.toJson(), containsPair('visited', 'week'));
    expect(engine.searchFilters.last.toJson(), containsPair('browser', 'history'));

    await choose(tester, 'Browser', 'bookmark');
    expect(select('Visited'), findsNothing);
    expect(engine.searchFilters.last.toJson().containsKey('visited'), isFalse);

    // back to files: the browser's choices go
    await choose(tester, 'Kind', '');
    expect(select('Browser'), findsNothing);
    expect(engine.searchFilters.last.browser, '');
  });

  testWidgets('Pick dates asks for two days and searches between them', (tester) async {
    final engine = FakeEngine(settings: _on)..browserResults = [_web];
    await pumpApp(tester, engine);
    await type(tester, 'github');
    await choose(tester, 'Kind', 'browser');
    await choose(tester, 'Browser', 'history');
    await choose(tester, 'Visited', 'pick');
    expect(find.text('Pick the days'), findsOneWidget);
    final fields = find.descendant(of: find.byKey(const ValueKey('pick-dates')), matching: find.byType(TextField));
    await tester.enterText(fields.at(0), '2026-11-20');
    await tester.enterText(fields.at(1), '2026-11-01');
    await tester.tap(find.text('Search these days'));
    await tester.pumpAndSettle();
    expect(engine.searchFilters.last.visited, '2026-11-01..2026-11-20'); // in order, whichever came first
    expect(selectOf(tester, 'Visited').options.map((o) => o.$2), contains('2026-11-01 to 2026-11-20'));

    // a day that isn't one: nothing is searched, the dialog says so
    await choose(tester, 'Visited', 'pick');
    await tester.enterText(fields.at(0), '2026-02-30');
    await tester.enterText(fields.at(1), '2026-03-01');
    await tester.tap(find.text('Search these days'));
    await tester.pumpAndSettle();
    expect(find.textContaining('YYYY-MM-DD'), findsWidgets);
    expect(engine.searchFilters.last.visited, '2026-11-01..2026-11-20');
  });

  testWidgets('Saved logins only while logins are read', (tester) async {
    final engine = FakeEngine(settings: {..._on, 'browser_data': 'history'});
    await pumpApp(tester, engine);
    await type(tester, 'github');
    await choose(tester, 'Kind', 'browser');
    expect(options(tester, 'Browser'), isNot(contains('login')));
  });

  testWidgets('Settings & apps shows the settings and apps, and no files', (tester) async {
    final engine = FakeEngine()
      ..searchActions = const [
        SearchAction(id: 'set:display', kind: 'setting', title: 'Display', subtitle: 'Windows Settings'),
        SearchAction(id: 'set:night-light', kind: 'setting', title: 'Night light', subtitle: 'Windows Settings'),
        SearchAction(id: 'set:text-size', kind: 'setting', title: 'Text size', subtitle: 'Windows Settings'),
        SearchAction(id: 'set:colors', kind: 'setting', title: 'Colors', subtitle: 'Windows Settings'),
      ];
    await pumpApp(tester, engine);
    await type(tester, 'notes'); // the sample files have notes
    await choose(tester, 'Kind', 'launcher');
    expect(engine.searchFilters.last.kind, 'launcher');
    expect(find.text('Colors'), findsOneWidget); // all of them, not just the first three
    expect(find.textContaining('Nothing matches'), findsNothing);
    expect(find.textContaining('.txt'), findsNothing);
    await tester.tap(find.text('Display'));
    await tester.pumpAndSettle();
    expect(engine.actionsRun, ['set:display']);
  });

  testWidgets('a browser result shows where it is from and opens by its id', (tester) async {
    final engine = FakeEngine(settings: _on)..browserResults = [_web, _login];
    await pumpApp(tester, engine, size: const Size(1280, 800)); // wide: the detail pane beside the list
    await type(tester, 'github');
    await choose(tester, 'Kind', 'browser');
    expect(find.text('GitHub: pull requests'), findsWidgets);
    expect(find.text('Edge (Work) · github.com'), findsWidgets);
    expect(find.text('Open page'), findsOneWidget); // the detail pane says what Open does
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(engine.opened, [-3]); // by the result id: the engine opens the page, never the window
    expect(find.descendant(of: find.byType(DetailPane), matching: find.text('Open with…')), findsNothing); // a web page: no Open with, no Forget, no folder
    expect(find.descendant(of: find.byType(DetailPane), matching: find.text('Forget…')), findsNothing);
    expect(find.descendant(of: find.byType(DetailPane), matching: find.text('Show in folder')), findsNothing);
    await choose(tester, 'Browser', 'login');
    expect(find.text('Password manager'), findsOneWidget);
    expect(find.textContaining('password:'), findsNothing);
  });

  testWidgets('the right-click menu of a browser result lists only what applies to it', (tester) async {
    final engine = FakeEngine(settings: _on)..browserResults = [_web, _login];
    await pumpApp(tester, engine, size: const Size(900, 700));
    await type(tester, 'github');
    await choose(tester, 'Kind', 'browser');
    await tester.tap(find.text('GitHub: pull requests').first, buttons: kSecondaryButton);
    await tester.pumpAndSettle();
    final menu = find.byType(MenuItemButton);
    Finder item(String label) => find.descendant(of: menu, matching: find.text(label));
    expect(item('Open'), findsOneWidget);
    expect(item('Copy address'), findsOneWidget); // a web address, not a path
    expect(item('Copy name'), findsOneWidget);
    for (final label in ['Open with…', 'Show in folder', 'Forget…', 'Copy path']) {
      expect(item(label), findsNothing, reason: label);
    }
  });
}

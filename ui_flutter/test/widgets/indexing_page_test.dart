import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/scope_info.dart';
import 'package:nobad_find/platform/languages.dart';
import 'package:nobad_find/state/categories.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> openScope(WidgetTester tester, FakeEngine engine, {bool? reduceMotion}) async {
  await pumpApp(tester, engine, size: const Size(1180, 1600), reduceMotion: reduceMotion);
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.text('What to index'));
  await tester.pumpAndSettle();
}

/// A card's Details (or Hide details) button, found by what screen readers hear.
Finder detailsOf(String about, {bool hide = false}) => find.byWidgetPredicate(
  (w) => w is NbButton && w.semanticLabel == '${hide ? 'Hide details' : 'Details'} about $about',
);

void main() {
  test('scope_info and turbo_state as the engine sends them', () {
    final s = ScopeInfo.fromJson({
      'scope': 'whole_pc',
      'roots': [r'C:\'],
      'categories': [
        {
          'id': 'secrets',
          'name': 'Keys',
          'why': 'w',
          'examples': ['.ssh'],
          'included': false,
          'locked': false,
        },
        {'id': 'other_profiles', 'name': 'Others', 'locked': true, 'count': null},
        {'nope': 1},
      ],
    });
    expect(s.scope, IndexScope.wholePc);
    expect(s.categories, hasLength(2));
    expect(s.categories.first.setting, 'include_secrets');
    expect(s.categories.last.count, isNull);
    // an engine before summary / names_only: the first sentence of why, and not names only
    expect(s.categories.first.line, 'w');
    expect(s.categories.first.namesOnly, NamesOnly.none);
    final k = ScopeCategory.fromJson({'id': 'caches', 'summary': 'Short.', 'why': 'One. Two.', 'names_only': 'some'})!;
    expect((k.line, k.namesOnly), ('Short.', NamesOnly.some));
    expect(const ScopeCategory(id: 'x', why: 'One. Two.').line, 'One.');
    final t = TurboState.fromJson({
      'available': true,
      'enabled': true,
      'running': true,
      'volumes': [
        {'drive': r'C:\', 'ntfs': true, 'files': 5, 'usn_ok': true, 'last_scan': 1.5},
      ],
      'error': '',
    });
    expect(t.line, 'Turbo: on (C: NTFS)');
    expect(t.helper, TurboHelper.notInstalled); // an engine before 2026-11-21 sends no helper
    expect(const TurboState(available: true, error: 'Windows said no.').line, 'Turbo: off. Windows said no.');
    expect(const TurboState().line, startsWith('Turbo: not available'));
    final u = TurboState.fromJson({'available': true, 'enabled': true, 'helper': 'needs_update', 'error': 'x'});
    expect((u.needsUpdate, u.removable), (true, true));
    expect(u.line, startsWith('Turbo: needs your OK once to update its helper'));
    expect(TurboState.fromJson({'helper': 'installed'}).helper, TurboHelper.installed);
    expect(TurboState.fromJson({'helper': 'nonsense'}).helper, TurboHelper.notInstalled);
  });

  testWidgets('turbo: a helper that needs an update offers Update helper; one left installed offers Remove', (
    tester,
  ) async {
    final engine = FakeEngine()
      ..turbo = const TurboState(
        available: true,
        enabled: true,
        helper: TurboHelper.needsUpdate,
        error: 'Turbo needs your OK once to update its helper.',
        volumes: [TurboVolume(drive: 'C:', ntfs: true)],
      );
    await openScope(tester, engine);
    final update = find.byWidgetPredicate((w) => w is NbButton && w.label == 'Update helper');
    expect(update, findsOneWidget);
    expect(find.text('Helper needs your OK once to update'), findsOneWidget);
    await tester.ensureVisible(update);
    await tester.tap(update);
    await tester.pumpAndSettle();
    expect(engine.turboHelperCalls, ['update']);
    expect(update, findsNothing);
    expect(find.text('Helper set up: starts without asking'), findsOneWidget);
    // turned off with the removal declined: the helper stays, Remove is offered
    engine.turbo = const TurboState(available: true, helper: TurboHelper.installed);
    engine.emit(TurboEvent(engine.turbo));
    await tester.pumpAndSettle();
    final remove = find.byWidgetPredicate((w) => w is NbButton && w.label == 'Remove');
    await tester.ensureVisible(remove);
    await tester.tap(remove);
    await tester.pumpAndSettle();
    expect(engine.turboHelperCalls, ['update', 'remove']);
    expect(remove, findsNothing);
  });

  test("Windows' languages suggest a focus like the engine's rule", () {
    expect(focusFromLangIds([0x0409]), 'english');
    expect(focusFromLangIds([0x0409, 0x0439]), 'hindi');
    expect(focusFromLangIds([0x0407]), 'multilingual');
  });

  test('a category is read from the filters in use', () {
    expect(SearchCategory.of(const SearchFilters(kind: 'pdf')), SearchCategory.documents);
    expect(SearchCategory.of(const SearchFilters(kind: 'audio')), SearchCategory.media);
    expect(SearchCategory.of(const SearchFilters(folder: 'downloads', kind: 'pdf')), SearchCategory.downloads);
    expect(SearchCategory.of(const SearchFilters(modified: 'week', sort: 'newest')), SearchCategory.recent);
    expect(SearchCategory.of(SearchFilters.none), SearchCategory.all);
  });

  testWidgets('every category with why and examples; secrets say names only; locked ones have no switch', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openScope(tester, engine);
    expect(find.text('Keys and password stores'), findsOneWidget);
    expect(find.text('Names only: the contents of these files are never read.'), findsOneWidget);
    expect(find.text("Other people's files"), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is NbSwitch && w.label == "Other people's files"), findsNothing);
    await tester.tap(find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'App data and caches'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'include_caches': true});
    expect(find.text('96,214 in the index'), findsOneWidget);
  });

  testWidgets('turbo: the switch asks Windows; No keeps it off and says why; Yes shows the drives', (tester) async {
    final engine = FakeEngine()..turboPromptYes = false;
    await openScope(tester, engine);
    final sw = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Turbo index');
    await tester.ensureVisible(sw);
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(find.textContaining("Windows didn't give permission"), findsOneWidget);
    engine.turboPromptYes = true;
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(find.text('Turbo: on (C:, D: NTFS)'), findsOneWidget);
    expect(find.text('C: · NTFS · 612,408 files'), findsOneWidget);
    await tester.tap(detailsOf('Turbo index'));
    await tester.pumpAndSettle();
    expect(find.text('612,408'), findsOneWidget); // the per-drive table, under Details
  });

  testWidgets('a category card: one line and chips first, the full explanation and examples under Details', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openScope(tester, engine);
    final why = engine.scope.categories.firstWhere((k) => k.id == 'secrets').why;
    expect(find.text('Keys, saved browser passwords, sign-in tokens, password vaults and wallets.'), findsOneWidget);
    expect(find.text('Names only, never read'), findsOneWidget);
    expect(find.text('App databases: names only'), findsOneWidget);
    expect(find.text('Whole PC only'), findsOneWidget); // My files: system folders are out and locked
    expect(find.text(why), findsNothing);
    expect(find.text(r'…\wallet.dat'), findsNothing);
    final open = detailsOf('Keys and password stores');
    expect(open, findsOneWidget);
    final semantics = tester.ensureSemantics();
    await tester.pump();
    expect(find.bySemanticsLabel('Details about Keys and password stores'), findsOneWidget);
    expect(find.bySemanticsLabel('Keys and password stores'), findsWidgets); // its switch
    semantics.dispose();
    await tester.ensureVisible(open);
    await tester.tap(open);
    await tester.pumpAndSettle();
    expect(find.text(why), findsOneWidget);
    expect(find.text(r'…\wallet.dat'), findsOneWidget);
    final hide = detailsOf('Keys and password stores', hide: true);
    expect(hide, findsOneWidget);
    await tester.tap(hide);
    await tester.pumpAndSettle();
    expect(find.text(why), findsNothing);
  });

  testWidgets('switches still change their settings, and the cards follow the engine', (tester) async {
    final engine = FakeEngine();
    await openScope(tester, engine);
    expect(find.text('Included'), findsNothing); // My files, nothing extra switched on
    final sw = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Network drives');
    await tester.ensureVisible(sw);
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'index_network': true});
    expect(find.text('Included'), findsOneWidget);
    expect((tester.widget(sw) as NbSwitch).value, isTrue);
    await tester.ensureVisible(find.text('Whole PC'));
    await tester.tap(find.text('Whole PC'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'scope': 'whole_pc'});
    expect(find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Windows and programs'), findsOneWidget);
    expect(find.text('Whole PC only'), findsNothing);
  });

  testWidgets('the page opens before the counts arrive, and the counts appear when they do', (tester) async {
    final engine = FakeEngine(settings: {'welcome_seen': true, 'bg_notice_seen': true, 'include_caches': true});
    final counted = Completer<void>();
    engine.scopeWait = counted.future;
    await openScope(tester, engine);
    expect(find.text('Counting what is in the index…'), findsOneWidget);
    expect(find.text('Never index'), findsOneWidget); // the parts from the settings are there at once
    expect(find.text('Read the text inside files'), findsOneWidget);
    expect(find.text('96,214 in the index'), findsNothing);
    counted.complete();
    await tester.pumpAndSettle();
    expect(find.text('Counting what is in the index…'), findsNothing);
    expect(find.text('96,214 in the index'), findsOneWidget);
    expect(find.text('Not counted'), findsWidgets); // network drives: the engine sends no count
  });

  testWidgets('with animations off, Details opens at once', (tester) async {
    await openScope(tester, FakeEngine(), reduceMotion: true);
    final open = detailsOf('Network drives');
    await tester.ensureVisible(open);
    await tester.tap(open);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 2));
    expect(find.text('Mapped network drives. Big shares take a while and use your network.'), findsOneWidget);
  });

  testWidgets('an older engine: the older rows, and why', (tester) async {
    final engine = FakeEngine()..old = true;
    await openScope(tester, engine);
    expect(find.textContaining('needs a newer engine'), findsOneWidget);
    expect(find.text('Folders to search'), findsOneWidget);
  });
}

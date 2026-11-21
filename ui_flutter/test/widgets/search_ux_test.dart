import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField;
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/engine/engine_api.dart' show Link;
import 'package:nobad_find/platform/window.dart' show debugTransparencyOff;
import 'package:nobad_find/state/recent_searches.dart';

import '../support/fake_engine.dart';

String boxText(WidgetTester tester) => tester.widget<TextField>(find.byType(TextField).first).controller!.text;

void main() {
  testWidgets('while typing, "pdf" is offered as a filter; Tab takes it', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'tax pdf');
    expect(find.text('Kind: PDFs   Tab'), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.pumpAndSettle();
    expect(boxText(tester), 'tax');
    expect(engine.searchFilters.last.kind, 'pdf');
    expect(find.text('PDFs'), findsWidgets); // the filter bar shows it
  });

  testWidgets('an understood chip can be removed', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'tax pdf');
    await tester.tap(find.bySemanticsLabel('Remove PDFs'), warnIfMissed: false); // the engine's part (0.8.5)
    await tester.pumpAndSettle();
    expect(boxText(tester), 'tax');
  });

  testWidgets('recent searches show in the empty palette and can be cleared', (tester) async {
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final engine = FakeEngine(suggestions: true);
    engine.history.addAll(['budget', 'rent agreement']); // the engine's own search history, newest first
    final recent = RecentSearches(engine);
    addTearDown(recent.dispose);
    await tester.pumpWidget(NobadFindApp(engine: engine, window: FakeWindow(), splash: false, recent: recent));
    await tester.pumpAndSettle();
    expect(find.text('budget'), findsOneWidget);
    await tester.tap(find.text('rent agreement'));
    await tester.pumpAndSettle();
    expect(boxText(tester), 'rent agreement');
    await tester.enterText(find.byType(TextField).first, '');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    expect(find.text('budget'), findsNothing);
    expect(recent.items, isEmpty);
    expect(engine.history, isEmpty); // Clear is the engine's history: the UI has no copy of its own
  });

  testWidgets('using a result remembers the search in the engine, and it shows as recent', (tester) async {
    final engine = FakeEngine(suggestions: true);
    final recent = RecentSearches(engine);
    addTearDown(recent.dispose);
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(NobadFindApp(engine: engine, window: FakeWindow(), splash: false, recent: recent));
    await tester.pump();
    await type(tester, 'notes');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.history, ['notes']);
    expect(recent.items, ['notes']);
  });

  testWidgets('with "Remember my searches" off no recent searches are kept or shown', (tester) async {
    final engine = FakeEngine(settings: {'welcome_seen': true, 'bg_notice_seen': true, 'search_history': false});
    final recent = RecentSearches(engine);
    addTearDown(recent.dispose);
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(NobadFindApp(engine: engine, window: FakeWindow(), splash: false, recent: recent));
    await tester.pump();
    await type(tester, 'notes');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.history, isEmpty);
    expect(recent.items, isEmpty);
  });

  testWidgets('nothing found: says so and offers ways on', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'zebra tax');
    await tester.pumpAndSettle();
    expect(find.text('Search “zebra”'), findsOneWidget);
    await tester.tap(find.text('Search “zebra”'));
    await tester.pumpAndSettle();
    expect(boxText(tester), 'zebra');
  });

  testWidgets("Home's recently changed list asks on its own channel; the box on the main one", (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    expect(engine.channels.first, 'home');
    await type(tester, 'tax');
    expect(engine.channels.last, 'main');
  });

  testWidgets("Home without the engine says so instead of an empty list", (tester) async {
    await pumpApp(tester, FakeEngine(link: Link.offline));
    expect(find.textContaining("engine isn't running, so there is nothing to show"), findsOneWidget);
  });

  testWidgets("See-through window follows Windows' Transparency effects switch", (tester) async {
    debugTransparencyOff = true;
    addTearDown(() => debugTransparencyOff = false);
    final w = FakeWindow();
    await tester.pumpWidget(NobadFindApp(engine: FakeEngine(), window: w, splash: false));
    await tester.pumpAndSettle();
    expect(w.looks, isNotEmpty);
    expect(w.looks.every((l) => !l.$2), isTrue); // the glass setting is on, but Windows says no transparency
  });
}

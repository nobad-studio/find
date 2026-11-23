// Equal sizes and alignment where they keep the original look (task D3): at the main window's size (1180 x 760)
// the search box, Home's category row, its Recent card and the status line share their left and right edges, and
// the category tiles are one width in one row; on every Settings page every card spans the same width and every
// row's control ends on one column.
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show MaterialApp, Tooltip;
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/app/theme/tokens.dart';
import 'package:nobad_find/features/search/home_view.dart';
import 'package:nobad_find/features/search/search_screen.dart';
import 'package:nobad_find/features/settings/settings_parts.dart';
import 'package:nobad_find/widgets/badges.dart';
import 'package:nobad_find/widgets/glass.dart';
import 'package:nobad_find/widgets/icons.dart';
import 'package:nobad_find/widgets/panels.dart';
import 'package:nobad_find/widgets/pressable.dart';

import '../support/fake_engine.dart';

const seen = {'welcome_seen': true, 'bg_notice_seen': true};

void edges(Rect a, Rect b, String what) {
  expect(a.left, moreOrLessEquals(b.left, epsilon: .5), reason: '$what: left $a vs $b');
  expect(a.right, moreOrLessEquals(b.right, epsilon: .5), reason: '$what: right $a vs $b');
}

/// Every icon tile on screen has room: at least 8 px from each edge of the card or box it sits in, and a
/// Settings header's tile at least 8 px above its group's card.
void tilesHaveRoom(WidgetTester tester, String where) {
  final tiles = [...find.byType(GlyphTile).evaluate(), ...find.byType(NbAvatar).evaluate()];
  expect(tiles, isNotEmpty, reason: where);
  for (final e in tiles) {
    final f = find.byWidget(e.widget);
    final r = tester.getRect(f);
    final box = find.ancestor(of: f, matching: find.byWidgetPredicate((w) => w is Glass || w is Pressable));
    final group = find.ancestor(of: f, matching: find.byType(SettingsGroup));
    if (group.evaluate().isNotEmpty && box.evaluate().isEmpty) {
      final card = tester.getRect(find.descendant(of: group.first, matching: find.byKey(SettingsGroup.cardKey)));
      expect(card.top - r.bottom, greaterThanOrEqualTo(8), reason: '$where: a header tile touches its card');
      continue;
    }
    if (box.evaluate().isEmpty) continue; // not in a box
    final b = tester.getRect(box.first);
    for (final (side, gap) in [
      ('left', r.left - b.left),
      ('right', b.right - r.right),
      ('top', r.top - b.top),
      ('bottom', b.bottom - r.bottom),
    ]) {
      expect(
        gap,
        greaterThanOrEqualTo(8 - .5),
        reason: '$where: a tile is ${gap.toStringAsFixed(1)} px from its box ($side)',
      );
    }
  }
}

/// Every grid of tiles on screen: one width for all its tiles, and in each row one height.
void gridsAreEven(WidgetTester tester, String where) {
  for (final g in find.byType(TileGrid).evaluate()) {
    final cells = [
      for (final e in find.descendant(of: find.byWidget(g.widget), matching: find.byType(TileCell)).evaluate())
        tester.getRect(find.byWidget(e.widget)),
    ];
    for (final r in cells) {
      expect(r.width, moreOrLessEquals(cells.first.width, epsilon: .5), reason: '$where: tile width');
      for (final o in cells.where((o) => (o.top - r.top).abs() < .5)) {
        expect(o.height, moreOrLessEquals(r.height, epsilon: .5), reason: '$where: tile height in a row');
      }
    }
  }
}

void main() {
  // the real Windows fonts: whether a text fits depends on them (the test font's boxes are much wider)
  setUpAll(loadWindowsFonts);

  testWidgets('a long text ellipsizes in its tile (full text in a tooltip) and never makes the tile bigger', (
    tester,
  ) async {
    final long = 'An extraordinarily long graphics card name that goes on and on ' * 3;
    Widget grid(String value) => MaterialApp(
      home: Center(
        child: SizedBox(
          width: 600,
          child: TileGrid(
            min: 130,
            children: [
              StatTile(value: value, label: 'Graphics card $long', icon: NbGlyph.graphics),
              const StatTile(value: '15.7 GB', label: 'Memory', icon: NbGlyph.memory),
            ],
          ),
        ),
      ),
    );
    await tester.pumpWidget(grid('Intel(R) Iris(R) Xe'));
    final normal = tester.getSize(find.byType(TileCell).first);
    await tester.pumpWidget(grid(long));
    final cells = [for (final e in find.byType(TileCell).evaluate()) tester.getSize(find.byWidget(e.widget))];
    expect(cells[0], cells[1], reason: 'the row keeps one size');
    expect(cells[0].height, lessThanOrEqualTo(normal.height + 4 * 18), reason: 'capped at 2 + 3 lines');
    final p = tester.renderObject<RenderParagraph>(find.textContaining('An extraordinarily').first);
    expect(p.didExceedMaxLines, isTrue);
    expect(find.byWidgetPredicate((w) => w is Tooltip && (w.message ?? '').contains(long)), findsOneWidget);
  });

  testWidgets('Home, Index and What to index: every grid of tiles is even', (tester) async {
    await pumpApp(tester, FakeEngine(settings: seen), size: const Size(1180, 760));
    await tester.pumpAndSettle();
    final nav = AppScope.of(tester.element(find.byType(Text).first)).nav;
    gridsAreEven(tester, 'Home');
    nav.go(AppTab.indexing);
    await tester.pumpAndSettle();
    gridsAreEven(tester, 'Index');
  });

  testWidgets('Home: the search box, the category row, the Recent card and the status line share their edges', (
    tester,
  ) async {
    await pumpApp(tester, FakeEngine(settings: seen), size: const Size(1180, 760));
    await tester.pumpAndSettle();
    final box = tester.getRect(find.byKey(SearchScreen.boxKey));
    edges(tester.getRect(find.byKey(HomeView.tilesKey)), box, 'category row');
    edges(tester.getRect(find.byKey(HomeView.listKey)), box, 'Recent card');
    // the status line's rule runs inside its own gutter margin
    final status = tester.getRect(find.byKey(SearchScreen.statusKey));
    edges(
      Rect.fromLTRB(status.left + NbSpace.gutter, status.top, status.right - NbSpace.gutter, status.bottom),
      box,
      'status line',
    );
    // the category tiles: one width, one height, one row from edge to edge
    final tiles = [
      for (final e in find.descendant(of: find.byKey(HomeView.tilesKey), matching: find.byType(Pressable)).evaluate())
        tester.getRect(find.byWidget(e.widget)),
    ];
    expect(tiles, hasLength(6));
    for (final t in tiles) {
      expect(t.width, moreOrLessEquals(tiles.first.width, epsilon: .5));
      expect(t.height, tiles.first.height);
      expect(t.top, tiles.first.top);
    }
    expect(tiles.first.left, moreOrLessEquals(box.left, epsilon: .5));
    expect(tiles.last.right, moreOrLessEquals(box.right, epsilon: .5));
    tilesHaveRoom(tester, 'Home');
  });

  testWidgets('a narrow window (860 px): every row of category tiles spans the search box', (tester) async {
    await pumpApp(tester, FakeEngine(settings: seen), size: const Size(860, 760));
    await tester.pumpAndSettle();
    final box = tester.getRect(find.byKey(SearchScreen.boxKey));
    final tiles = [
      for (final e in find.descendant(of: find.byKey(HomeView.tilesKey), matching: find.byType(Pressable)).evaluate())
        tester.getRect(find.byWidget(e.widget)),
    ];
    expect(tiles, hasLength(6));
    final rows = <double, List<Rect>>{};
    for (final t in tiles) {
      (rows[t.top] ??= []).add(t);
    }
    expect(rows.length, greaterThan(1)); // it does wrap at this width
    for (final row in rows.values) {
      expect(row.length, rows.values.first.length, reason: 'every row holds as many tiles');
      expect(row.first.left, moreOrLessEquals(box.left, epsilon: .5));
      expect(row.last.right, moreOrLessEquals(box.right, epsilon: .5));
    }
  });

  testWidgets('Models: the graphics card name and the memory labels show in full beside their icon tiles', (
    tester,
  ) async {
    await pumpApp(tester, FakeEngine(settings: seen), size: const Size(1180, 760));
    await tester.pumpAndSettle();
    AppScope.of(tester.element(find.byType(Text).first)).nav.openSettings(SettingsPage.models);
    await tester.pumpAndSettle();
    for (final words in ['Intel(R) Iris(R) Xe', 'Memory free of', 'Of the memory Windows', 'Graphics memory free']) {
      final f = find.textContaining(words);
      expect(f, findsWidgets, reason: words);
      for (final e in f.evaluate()) {
        final p = e.renderObject! as RenderParagraph;
        expect(p.didExceedMaxLines, isFalse, reason: '$words is cut short');
      }
    }
  });

  for (final page in SettingsPage.values) {
    testWidgets('Settings > ${page.label}: one width for every card, one column for every control', (tester) async {
      await pumpApp(tester, FakeEngine(settings: seen), size: const Size(1180, 760));
      await tester.pumpAndSettle();
      AppScope.of(tester.element(find.byType(Text).first)).nav.openSettings(page);
      await tester.pumpAndSettle();

      final cards = [
        for (final e in find.byKey(SettingsGroup.cardKey).evaluate()) tester.getRect(find.byWidget(e.widget)),
      ];
      expect(cards, isNotEmpty);
      for (final r in cards.skip(1)) {
        edges(r, cards.first, '${page.label} card');
      }
      // and any other card on the page (one not inside another card) spans the same width
      final pageArea = find.byKey(PageStorageKey(page));
      var top = 0;
      for (final e in find.descendant(of: pageArea, matching: find.byType(Glass)).evaluate()) {
        final g = find.byWidget(e.widget);
        if (find.ancestor(of: g, matching: find.byType(Glass)).evaluate().isNotEmpty) continue;
        top++;
        edges(tester.getRect(g), cards.first, '${page.label} other card');
      }
      expect(top, greaterThanOrEqualTo(cards.length), reason: '${page.label}: the page area was found');

      // every row's control ends on the card's inner right edge (the row's 12 px right padding)
      final rights = <double>{
        for (final e in find.byType(SettingRow).evaluate())
          if ((e.widget as SettingRow).control case final ctl?)
            tester.getRect(find.byWidget(ctl)).right.roundToDouble(),
      };
      if (rights.isNotEmpty) {
        expect(rights, {(cards.first.right - 12).roundToDouble()}, reason: '${page.label}: controls end on one column');
      }
      tilesHaveRoom(tester, page.label);
      gridsAreEven(tester, page.label);
    });
  }
}

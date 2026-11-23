// The theme style (Settings > General): Classic by default, Minimal ice at once when chosen (the window's glass and
// the palette), and the icon tiles follow it.
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/app/theme/colors.dart';
import 'package:nobad_find/widgets/icons.dart';

import '../support/fake_engine.dart';

/// The colour of [g]'s glyph inside its icon tile.
Color glyphColour(WidgetTester tester, NbGlyph g) {
  final icon = find.byWidgetPredicate((w) => w is NbIcon && w.glyph == g);
  return tester.widget<NbIcon>(find.descendant(of: find.byType(GlyphTile), matching: icon).first).color;
}

void main() {
  testWidgets('Classic by default; Minimal ice applies at once, and back', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': true, 'bg_notice_seen': true});
    final w = await pumpApp(tester, engine, size: const Size(1180, 900));
    await tester.pumpAndSettle();
    final scope = AppScope.of(tester.element(find.byType(Text).first));
    scope.nav.openSettings(SettingsPage.general);
    await tester.pumpAndSettle();
    expect(find.text('Theme style'), findsOneWidget);
    expect(find.text('Classic'), findsOneWidget);
    expect(w.ices.last, isFalse); // Mica
    var c = NbColors.of(tester.element(find.text('Theme style')));
    expect(c.ice, isFalse);
    expect(glyphColour(tester, NbGlyph.palette), c.tint(GlyphTile.tints[NbGlyph.palette]!)); // its own colour

    await scope.settings.set('theme_style', 'ice');
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'theme_style': 'ice'});
    expect(w.ices.last, isTrue); // Acrylic, asked for again at once
    c = NbColors.of(tester.element(find.text('Theme style')));
    expect(c.ice, isTrue);
    expect(glyphColour(tester, NbGlyph.palette), c.iceGlyph); // the quiet tiles

    await scope.settings.set('theme_style', 'classic');
    await tester.pumpAndSettle();
    expect(w.ices.last, isFalse);
    expect(NbColors.of(tester.element(find.text('Theme style'))).ice, isFalse);
  });
}

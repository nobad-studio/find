// The theme style (Settings > General): Classic by default, Minimal ice at once when chosen (the palette and the
// icons), and back. Both styles ask Windows for the same glass (Acrylic), so the backdrop isn't asked for again.
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/app/theme/colors.dart';
import 'package:nobad_find/widgets/icons.dart';

import '../support/fake_engine.dart';

/// The palette's icon box: its glyph's colour, and whether it draws a tile.
(Color, bool) glyphLook(WidgetTester tester, NbGlyph g) {
  final tile = find.byWidgetPredicate((w) => w is GlyphTile && w.glyph == g).first;
  final icon = tester.widget<NbIcon>(find.descendant(of: tile, matching: find.byType(NbIcon)));
  final boxed = find.descendant(of: tile, matching: find.byType(Container)).evaluate().isNotEmpty;
  return (icon.color, boxed);
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
    final looks = w.looks.length;
    var c = NbColors.of(tester.element(find.text('Theme style')));
    expect(c.ice, isFalse);
    // Classic: the meaning's own hue, on a tile
    expect(glyphLook(tester, NbGlyph.palette), (c.tint(GlyphTile.tints[NbGlyph.palette]!), true));

    await scope.settings.set('theme_style', 'ice');
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'theme_style': 'ice'});
    c = NbColors.of(tester.element(find.text('Theme style')));
    expect(c.ice, isTrue);
    // Minimal ice: the cool white glyph on its monochrome tile
    expect(glyphLook(tester, NbGlyph.palette), (c.iceGlyph, true));
    expect(w.looks.length, looks); // the same Acrylic for both styles

    await scope.settings.set('theme_style', 'classic');
    await tester.pumpAndSettle();
    expect(NbColors.of(tester.element(find.text('Theme style'))).ice, isFalse);
  });
}

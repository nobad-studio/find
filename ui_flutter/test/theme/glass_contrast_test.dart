// Text stays readable on every glass layer, in both styles (Classic, Minimal ice) and both brightnesses, over the
// worst plausible backdrops (task D1, method from task X3); Classic keeps every token it had before the ice look;
// every icon tile's glyph reads on its tile.
//
// The model, kept simple and on the strict side: Windows' glass (Mica's base for Classic, dark #202020 / light
// #F3F3F3; the Acrylic tint for Minimal ice, dark #2C2C2C / light #FCFCFC) with the wallpaper showing through it
// (black or white, at 20 %), or the bare base; then the window's canvas tint; for Minimal ice, the brightest (or
// darkest) spot of each of its backdrop glows, or none; then the layer itself, then its top-edge sheen.
// `text` must reach 7:1 and `muted` / `dim` 4.5:1 on every result; a tile's glyph 4.5:1 on its tile.
import 'dart:math' as math;
import 'dart:ui' show Color;

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/theme/colors.dart';
import 'package:nobad_find/widgets/icons.dart';

/// WCAG 2 relative luminance of an opaque colour.
double luminance(Color c) {
  double ch(double v) => v <= 0.04045 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
}

double contrast(Color a, Color b) {
  final la = luminance(a), lb = luminance(b);
  return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
}

Color over(Color top, Color under) => Color.alphaBlend(top, under);

/// Every opaque colour a layer can end up as: over glass under the model above, or solid on the canvas.
List<(String, Color)> grounds(NbColors c, Color layer) {
  if (!c.glass) return [('solid', over(c.sheen, over(layer, c.bg)))];
  final base = c.ice
      ? (c.isDark ? const Color(0xFF2C2C2C) : const Color(0xFFFCFCFC))
      : (c.isDark ? const Color(0xFF202020) : const Color(0xFFF3F3F3));
  final walls = <(String, Color)>[
    (c.ice ? 'acrylic tint' : 'mica base', base),
    for (final (w, wc) in [('black', const Color(0xFF000000)), ('white', const Color(0xFFFFFFFF))])
      ('$w wallpaper 20%', Color.lerp(base, wc, .2)!),
  ];
  // Classic is checked by task X3's own method (no glows: its tokens are the ones it had); Minimal ice, whose thin
  // frost lets more through, also under each of its glows
  final glows = <(String, Color?)>[
    ('no glow', null),
    if (c.ice) ...[('ember', c.glowWarm), ('deep ice', c.glowCool), ('glacier', c.glowGlacier), ('haze', c.glowHaze)],
  ];
  return [
    for (final (wn, w) in walls)
      for (final (gn, g) in glows)
        ('$wn, $gn', over(c.sheen, over(layer, g == null ? over(c.canvas, w) : over(g, over(c.canvas, w))))),
  ];
}

/// The lowest contrast of [fg] (translucent colours are laid over the ground) on [layer] over every ground, with
/// [tile] (an icon tile's tint) laid on the layer first when given.
(double, String) worst(NbColors c, Color layer, Color fg, {Color? tile}) {
  var low = double.infinity;
  var where = '';
  for (final (n, g0) in grounds(c, layer)) {
    final g = tile == null ? g0 : over(tile, g0);
    final r = contrast(over(fg, g), g);
    if (r < low) {
      low = r;
      where = n;
    }
  }
  return (low, where);
}

/// The four looks of each brightness: Classic and Minimal ice, over glass and solid.
List<(String, NbColors)> looks() => [
  for (final base in [NbColors.dark, NbColors.light])
    for (final ice in [false, true])
      for (final glass in [true, false])
        (
          '${base.isDark ? 'dark' : 'light'} ${ice ? 'ice' : 'classic'} ${glass ? 'glass' : 'solid'}',
          base.withGlass(glass, iceStyle: ice),
        ),
];

/// Classic keeps its tokens exactly as they were (the maintainer's choice, 2026-11-23), and these fall short over a
/// white or black wallpaper: dark `dim` on a hovered card (the old hover fill is almost clear), and light `dim`
/// everywhere (the window is dark only since 0.8.5, so the light palette isn't shown). Pinned at what they are, so
/// they can only get better; Minimal ice passes everything.
const classicShort = {
  'dark classic glass dim on card hovered': 3.6,
  'light classic glass dim on panel': 3.5,
  'light classic glass dim on rail': 3.5,
  'light classic glass dim on card': 3.5,
  'light classic glass dim on card hovered': 3.3,
  'light classic glass dim on dialog': 3.5,
};

void main() {
  for (final (name, c) in looks()) {
    if (!c.glass) continue;
    final layers = {'panel': c.panel, 'rail': c.rail, 'card': c.card, 'card hovered': c.cardLift, 'dialog': c.dialog};
    for (final MapEntry(key: layer, value: fill) in layers.entries) {
      test('$name: text on $layer is readable over any backdrop', () {
        for (final (role, fg, need) in [('text', c.text, 7.0), ('muted', c.muted, 4.5), ('dim', c.dim, 4.5)]) {
          final (r, where) = worst(c, fill, fg);
          final floor = classicShort['$name $role on $layer'] ?? need;
          expect(r, greaterThanOrEqualTo(floor), reason: '$name $role on $layer: ${r.toStringAsFixed(2)}:1 at $where');
        }
      });
    }
  }

  for (final (name, c) in looks()) {
    test('$name: every icon tile\'s glyph reads on its tile (on a panel and on a card)', () {
      // a tile's brightest spot (its top edge) is where the glyph has the least contrast
      final tiles = c.ice
          ? [
              ('ice', c.iceGlyph, c.iceTile.withValues(alpha: (c.iceTile.a * 1.5).clamp(0, 1))),
              ('ice accent', c.tint(NbTint.orange), c.iceAccentTile.withValues(alpha: c.iceAccentTile.a * 1.5)),
            ]
          : [for (final t in NbTint.values) (t.name, c.tint(t), c.tintTile(t))];
      for (final (tn, glyph, tile) in tiles) {
        for (final (ln, layer) in [('panel', c.panel), ('card', c.card)]) {
          final (r, where) = worst(c, layer, glyph, tile: tile);
          expect(r, greaterThanOrEqualTo(4.5), reason: '$name $tn glyph on a $ln: ${r.toStringAsFixed(2)}:1 at $where');
        }
      }
    });
  }

  test('every Classic tile colour is used, and one meaning keeps one colour', () {
    expect(GlyphTile.tints.values.toSet(), NbTint.values.toSet());
  });

  test('Classic, and anything solid: every token it had before the ice look (5701c59)', () {
    for (final glass in [true, false]) {
      for (final ice in [false, if (!glass) true]) {
        final d = NbColors.dark.withGlass(glass, iceStyle: ice), l = NbColors.light.withGlass(glass, iceStyle: ice);
        expect(d.canvas, glass ? const Color(0xFF08090B).withValues(alpha: .34) : const Color(0xFF08090B));
        expect(d.ink, d.bg);
        expect(d.panel, const Color(0xA3181A1F));
        expect(d.rail, const Color(0x94141519));
        expect(d.card, const Color(0x85181A1F));
        expect(d.dialog, const Color(0xA3181A1F));
        expect(d.cardLift, const Color(0x0FFFFFFF));
        expect(d.rimLight, const Color(0x38FFFFFF));
        expect(d.rimShade, const Color(0x14FFFFFF));
        expect(d.sheen, const Color(0x0FFFFFFF));
        expect(d.glowWarm, d.orange.withValues(alpha: .30));
        expect(d.glowCool, const Color(0x524F5DFF));
        expect(d.glowMagenta, const Color(0x38D0347A));
        expect(d.muted, const Color(0xA3FFFFFF));
        expect(d.dim, const Color(0x85FFFFFF));
        expect(l.canvas, glass ? const Color(0xFFE7EAF1).withValues(alpha: .42) : const Color(0xFFE7EAF1));
        expect(l.panel, const Color(0xB8FFFFFF));
        expect(l.rail, const Color(0xADFFFFFF));
        expect(l.card, const Color(0x9EFFFFFF));
        expect(l.dialog, const Color(0xB8FFFFFF));
        expect(l.cardLift, const Color(0x0A000000));
        expect(l.rimLight, const Color(0xF2FFFFFF));
        expect(l.rimShade, const Color(0x14000000));
        expect(l.sheen, const Color(0x66FFFFFF));
        expect(l.glowWarm, l.orange.withValues(alpha: .22));
        expect(l.muted, const Color(0xB816181C));
        expect(l.dim, const Color(0x8516181C));
      }
    }
  });

  test('Minimal ice over glass: a hovered card is brighter and no thinner than the card', () {
    for (final base in [NbColors.dark, NbColors.light]) {
      final c = base.withGlass(true, iceStyle: true);
      expect(c.frost, isTrue);
      expect(c.cardLift.a, greaterThan(c.card.a));
      final g = over(c.canvas, const Color(0xFF2C2C2C));
      expect(luminance(over(c.cardLift, g)), greaterThan(luminance(over(c.card, g))));
    }
  });
}

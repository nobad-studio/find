// Text stays readable on every glass layer, in both styles (Classic, Minimal ice) and both brightnesses, over the
// worst plausible backdrops (tasks D1/D3, method from task X3); the solid look keeps every token it had; every icon
// reads on what it sits on.
//
// The model, kept simple and on the strict side: Windows' Acrylic (its tint, dark #2C2C2C / light #FCFCFC) with
// the wallpaper showing through it (black or white, at 20 %), or the bare tint; then the window's canvas tint; then
// the brightest (or darkest) spot of each of the style's backdrop glows, or none; then the layer itself, then its
// top-edge sheen. `text` must reach 7:1 and `muted` / `dim` 4.5:1 on every result; an icon's glyph 4.5:1.
import 'dart:math' as math;
import 'dart:ui' show Color;

import 'package:flutter/painting.dart' show HSVColor;
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
  final tint = c.isDark ? const Color(0xFF2C2C2C) : const Color(0xFFFCFCFC);
  final walls = <(String, Color)>[
    ('acrylic tint', tint),
    for (final (w, wc) in [('black', const Color(0xFF000000)), ('white', const Color(0xFFFFFFFF))])
      ('$w wallpaper 20%', Color.lerp(tint, wc, .2)!),
  ];
  final glows = <(String, Color?)>[
    ('no glow', null),
    if (c.ice) ...[
      ('glacier', c.glowGlacier),
      ('deep ice', c.glowCool),
      ('haze', c.glowHaze),
      ('ember', c.glowWarm),
    ] else ...[
      ('warm', c.glowWarm),
      ('indigo', c.glowCool),
      ('magenta', c.glowMagenta),
    ],
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

void main() {
  for (final (name, c) in looks()) {
    if (!c.glass) continue; // solid is the look it always had (pinned below)
    final layers = {
      'panel': c.panel,
      'rail': c.rail,
      'card': c.card,
      'card hovered': c.cardLift,
      'dialog': c.dialog,
    };
    for (final MapEntry(key: layer, value: fill) in layers.entries) {
      test('$name: text on $layer is readable over any backdrop', () {
        for (final (role, fg, need) in [('text', c.text, 7.0), ('muted', c.muted, 4.5), ('dim', c.dim, 4.5)]) {
          final (r, where) = worst(c, fill, fg);
          expect(r, greaterThanOrEqualTo(need), reason: '$name $role on $layer: ${r.toStringAsFixed(2)}:1 at $where');
        }
      });
    }
  }

  for (final (name, c) in looks()) {
    test('$name: every icon reads on what it sits on (a panel, a card, the sidebar)', () {
      // a Classic tile's brightest spot (its top edge) is where the glyph has the least contrast; Minimal ice's
      // glyph sits on the layer itself
      final icons = c.ice
          ? [
              ('ice', c.iceGlyph, c.iceTile.withValues(alpha: (c.iceTile.a * 1.5).clamp(0, 1))),
              ('ice accent', c.orange, c.iceAccentTile.withValues(alpha: c.iceAccentTile.a * 1.5)),
            ]
          : [for (final t in NbTint.values) (t.name, c.tint(t), c.tileTop(t))];
      for (final (tn, glyph, tile) in icons) {
        for (final (ln, layer) in [('panel', c.panel), ('card', c.card), ('rail', c.rail)]) {
          final (r, where) = worst(c, layer, glyph, tile: tile);
          expect(r, greaterThanOrEqualTo(4.5), reason: '$name $tn glyph on a $ln: ${r.toStringAsFixed(2)}:1 at $where');
        }
      }
    });
  }

  for (final (name, c) in looks()) {
    if (!c.ice) continue;
    test('$name: the ice-blue accent reads as text on every layer, and its label reads on it', () {
      for (final (ln, layer) in [('panel', c.panel), ('card', c.card), ('rail', c.rail), ('dialog', c.dialog)]) {
        final (r, where) = worst(c, layer, c.orange);
        expect(r, greaterThanOrEqualTo(4.5), reason: '$name accent on a $ln: ${r.toStringAsFixed(2)}:1 at $where');
      }
      // a primary button: its label on the accent
      expect(contrast(c.onOrange, c.orange), greaterThanOrEqualTo(4.5));
    });
  }

  test('Minimal ice has no orange or red anywhere: no token is near the NOBAD orange hue', () {
    final orangeHue = HSVColor.fromColor(NbColors.dark.orange).hue; // about 18°
    for (final base in [NbColors.dark, NbColors.light]) {
      for (final glass in [true, false]) {
        final c = base.withGlass(glass, iceStyle: true);
        final tokens = {
          'accent': c.orange,
          'accent tint': c.orangeA(.12),
          'ember glow': c.glowWarm,
          'accent tile': c.iceAccentTile,
          'ice tile': c.iceTile,
          'ice glyph': c.iceGlyph,
          'panel': c.panel,
          'card': c.card,
          'rail': c.rail,
          'dialog': c.dialog,
          'rim': c.rimLight,
          'sheen': c.sheen,
          'canvas': c.canvas,
        };
        for (final MapEntry(key: n, value: col) in tokens.entries) {
          final hsv = HSVColor.fromColor(col.withValues(alpha: 1));
          if (hsv.saturation < .15) continue; // greys have no hue to speak of
          final d = (hsv.hue - orangeHue).abs() % 360;
          expect(math.min(d, 360 - d), greaterThan(45), reason: '${base.isDark ? 'dark' : 'light'} ice $n is orange-ish');
        }
      }
    }
    // Classic keeps the NOBAD orange
    expect(NbColors.dark.withGlass(true).orange, const Color(0xFFFF4D00));
  });

  test('every Classic tile colour is used, and one meaning keeps one colour', () {
    expect(GlyphTile.tints.values.toSet(), NbTint.values.toSet());
  });

  test('solid (glass off), both styles: every token it had before the glass looks (5701c59)', () {
    for (final ice in [false, true]) {
      final d = NbColors.dark.withGlass(false, iceStyle: ice), l = NbColors.light.withGlass(false, iceStyle: ice);
      expect(d.canvas, const Color(0xFF08090B));
      expect(d.ink, d.bg);
      expect(d.panel, const Color(0xA3181A1F));
      expect(d.rail, const Color(0x94141519));
      expect(d.card, const Color(0x85181A1F));
      expect(d.dialog, const Color(0xA3181A1F));
      expect(d.cardLift, const Color(0x0FFFFFFF));
      expect(d.muted, const Color(0xA3FFFFFF));
      expect(d.dim, const Color(0x85FFFFFF));
      expect(l.canvas, const Color(0xFFE7EAF1));
      expect(l.panel, const Color(0xB8FFFFFF));
      expect(l.rail, const Color(0xADFFFFFF));
      expect(l.card, const Color(0x9EFFFFFF));
      expect(l.dialog, const Color(0xB8FFFFFF));
      expect(l.cardLift, const Color(0x0A000000));
      expect(l.muted, const Color(0xB816181C));
      expect(l.dim, const Color(0x8516181C));
    }
    // Classic's own light and rim stay the old ones
    final d = NbColors.dark.withGlass(false), l = NbColors.light.withGlass(false);
    expect(d.rimLight, const Color(0x38FFFFFF));
    expect(d.rimShade, const Color(0x14FFFFFF));
    expect(d.sheen, const Color(0x0FFFFFFF));
    expect(d.glowWarm, d.orange.withValues(alpha: .30));
    expect(d.glowCool, const Color(0x524F5DFF));
    expect(d.glowMagenta, const Color(0x38D0347A));
    expect(l.rimLight, const Color(0xF2FFFFFF));
    expect(l.sheen, const Color(0x66FFFFFF));
    expect(l.glowWarm, l.orange.withValues(alpha: .22));
  });

  test('Classic over glass: see-through all over (sidebar 35 %, cards 30 %, panels 40 %, dialogs 64 %), its own '
      'colours', () {
    for (final base in [NbColors.dark, NbColors.light]) {
      final c = base.withGlass(true);
      expect(c.rail.a, closeTo(.35, .01));
      expect(c.card.a, closeTo(.30, .01));
      expect(c.panel.a, closeTo(.40, .01)); // the search box and the detail pane
      expect(c.dialog.a, closeTo(.64, .01));
      expect(c.card.withValues(alpha: 1), base.isDark ? const Color(0xFF181A1F) : const Color(0xFFFFFFFF));
      expect(c.glowWarm, base.orange.withValues(alpha: base.isDark ? .30 : .22)); // the original light
    }
  });

  test('Minimal ice over glass: as built (18a4f7b)', () {
    final d = NbColors.dark.withGlass(true, iceStyle: true);
    expect(d.panel, const Color(0x70121A24));
    expect(d.rail, const Color(0x66121A24));
    expect(d.card, const Color(0x57121A24));
    expect(d.dialog, const Color(0xA3121A24));
    expect(d.rimLight, const Color(0x4DCFE8FF));
    expect(d.sheen, const Color(0x17E6F4FF));
  });

  test('over glass: a hovered card is brighter and no thinner than the card', () {
    for (final base in [NbColors.dark, NbColors.light]) {
      for (final ice in [false, true]) {
        final c = base.withGlass(true, iceStyle: ice);
        expect(c.cardLift.a, greaterThan(c.card.a));
        final g = over(c.canvas, const Color(0xFF2C2C2C));
        expect(luminance(over(c.cardLift, g)), greaterThan(luminance(over(c.card, g))));
      }
    }
  });
}

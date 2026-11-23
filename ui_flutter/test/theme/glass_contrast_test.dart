// Text stays readable on every glass layer, over the worst plausible backdrops (task D1, method from task X3), and
// the solid look (glass off) keeps every token it had.
//
// The model, kept simple and on the strict side: Windows' frost (the Acrylic tint, dark #2C2C2C / light #FCFCFC)
// with the wallpaper showing through it (black or white, at 20 % as for Mica: Acrylic's luminosity layer keeps
// it near that), or the bare tint; then the window's canvas tint; then the brightest (or darkest) spot of each of
// the backdrop's glows, or none; then the layer itself, then its top-edge sheen.
// `text` must reach 7:1 and `muted` / `dim` 4.5:1 on every result.
import 'dart:math' as math;
import 'dart:ui' show Color;

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/theme/colors.dart';

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

/// Every opaque colour a glass layer can end up as, under the model above.
List<(String, Color)> grounds(NbColors c, Color layer) {
  final tint = c.isDark ? const Color(0xFF2C2C2C) : const Color(0xFFFCFCFC);
  final walls = <(String, Color)>[
    ('acrylic tint', tint),
    for (final (w, wc) in [('black', const Color(0xFF000000)), ('white', const Color(0xFFFFFFFF))])
      for (final k in [.2]) ('$w wallpaper ${(k * 100).round()}%', Color.lerp(tint, wc, k)!),
  ];
  final glows = <(String, Color?)>[
    ('no glow', null),
    ('glacier', c.glowGlacier),
    ('deep ice', c.glowCool),
    ('haze', c.glowHaze),
    ('ember', c.glowWarm),
  ];
  return [
    for (final (wn, w) in walls)
      for (final (gn, g) in glows)
        ('$wn, $gn', over(c.sheen, over(layer, g == null ? over(c.canvas, w) : over(g, over(c.canvas, w))))),
  ];
}

/// The lowest contrast of [fg] (translucent text is laid over the ground) on [layer] over every ground.
(double, String) worst(NbColors c, Color layer, Color fg) {
  var low = double.infinity;
  var where = '';
  for (final (n, g) in grounds(c, layer)) {
    final r = contrast(over(fg, g), g);
    if (r < low) {
      low = r;
      where = n;
    }
  }
  return (low, where);
}

void main() {
  for (final base in [NbColors.dark, NbColors.light]) {
    final c = base.withGlass(true);
    final name = c.isDark ? 'dark' : 'light';
    final layers = {'panel': c.panel, 'rail': c.rail, 'card': c.card, 'card hovered': c.cardLift, 'dialog': c.dialog};
    for (final MapEntry(key: layer, value: fill) in layers.entries) {
      test('$name glass: text on $layer is readable over any backdrop', () {
        for (final (role, fg, need) in [('text', c.text, 7.0), ('muted', c.muted, 4.5), ('dim', c.dim, 4.5)]) {
          final (r, where) = worst(c, fill, fg);
          expect(r, greaterThanOrEqualTo(need), reason: '$name $role on $layer: ${r.toStringAsFixed(2)}:1 at $where');
        }
      });
    }
  }

  test('glass off: the solid look keeps every token it had', () {
    final d = NbColors.dark.withGlass(false), l = NbColors.light.withGlass(false);
    expect(d.canvas, const Color(0xFF08090B));
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
    expect(l.canvas, const Color(0xFFE7EAF1));
    expect(l.panel, const Color(0xB8FFFFFF));
    expect(l.rail, const Color(0xADFFFFFF));
    expect(l.card, const Color(0x9EFFFFFF));
    expect(l.dialog, const Color(0xB8FFFFFF));
    expect(l.cardLift, const Color(0x0A000000));
    expect(l.rimLight, const Color(0xF2FFFFFF));
    expect(l.rimShade, const Color(0x14000000));
    expect(l.sheen, const Color(0x66FFFFFF));
    expect(l.glowWarm, l.orange.withValues(alpha: .22));
  });

  test('glass on: a hovered card is brighter and no thinner than the card', () {
    for (final base in [NbColors.dark, NbColors.light]) {
      final c = base.withGlass(true);
      expect(c.cardLift.a, greaterThan(c.card.a));
      final g = over(c.canvas, const Color(0xFF2C2C2C));
      expect(luminance(over(c.cardLift, g)), greaterThan(luminance(over(c.card, g))));
    }
  });
}

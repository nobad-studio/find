/// NOBAD colour tokens for frosted glass: Windows' Acrylic behind the window (the desktop shows through, frosted by
/// Windows), a tinted canvas over it, and see-through layers on that: the sidebar, cards, panels and dialogs, each
/// with a fine light rim. Two styles (setting `theme_style`, Settings > General): Classic, the default (the
/// original colours, glows and shapes, see-through over the frost, colourful icon tiles), and Minimal ice (glacier
/// cyan and deep ice light, cool frost panels, cool monochrome tiles). In both the NOBAD orange is the one warm
/// accent, for actions. Glass off: one solid look for both, as before.
///
/// Screens read them with `NbColors.of(context)`; nothing outside lib/app/theme hard-codes a colour.
library;

import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart' show Theme, ThemeExtension;

/// The colours an icon tile can take in the Classic style, one per meaning (the glyph → tint table is next to the
/// glyphs, lib/widgets/icons.dart). Drawn from the Classic palette's orange and its old glow and badge hues.
enum NbTint { orange, green, teal, amber, violet, blue, cyan, magenta, pink, neutral }

@immutable
class NbColors extends ThemeExtension<NbColors> {
  const NbColors({
    required this.brightness,
    required this.orange,
    required this.onOrange,
    required this.bg,
    required this.surface,
    required this.raised,
    required this.text,
    required this.muted,
    required this.dim,
    required this.line,
    required this.line2,
    required this.warn,
    required this.danger,
    required this.shadow,
    this.glass = false,
    this.ice = false,
  });

  final Brightness brightness;

  /// The one NOBAD orange. Light uses the darker step from app.css so orange text on white keeps its contrast.
  final Color orange;
  final Color onOrange;

  /// Window canvas, panels, and controls inside panels.
  final Color bg;
  final Color surface;
  final Color raised;
  final Color text;
  final Color muted;
  final Color dim;

  /// Hairlines (dividers, panel edges) and outlines (controls).
  final Color line;
  final Color line2;
  final Color warn;
  final Color danger;
  final Color shadow;

  /// Windows draws its Acrylic backdrop behind the window (Mica if it refuses Acrylic): the canvas is see-through
  /// and every surface is frosted glass, macOS style.
  final bool glass;

  /// The Minimal ice style was chosen: cool frost and monochrome icon tiles. Classic (false) keeps the original
  /// colours.
  final bool ice;

  /// Glass and Minimal ice: the cold look.
  bool get frost => glass && ice;

  bool get isDark => brightness == Brightness.dark;
  Color orangeA(double a) => orange.withValues(alpha: a);

  /// The ink under the glass: a cold blue-black (dark) or a pale frost (light) for Minimal ice, the canvas colour
  /// otherwise.
  Color get ink => !frost ? bg : (isDark ? const Color(0xFF070A0F) : const Color(0xFFEAF1F8));

  /// The window canvas under the backdrop: a thin ink tint over Windows' frost, solid otherwise.
  Color get canvas => glass ? ink.withValues(alpha: isDark ? .34 : .42) : bg;

  /// Classic over glass: its own colours (neutral dark, or white), see-through at [alpha].
  Color _classic(double alpha, {bool quiet = false}) =>
      (isDark ? (quiet ? const Color(0xFF141519) : const Color(0xFF181A1F)) : const Color(0xFFFFFFFF))
          .withValues(alpha: alpha);

  /// Floating panels (the search box, the detail pane). Classic over glass: see-through at 40 %. Minimal ice: cool
  /// frost at 44 % (dark), pale frost at 58 % (light). Solid: neutral dark at 64 %, or white at 72 %.
  Color get panel => frost
      ? (isDark ? const Color(0x70121A24) : const Color(0x94F6FAFE))
      : glass
      ? _classic(.40)
      : (isDark ? const Color(0xA3181A1F) : const Color(0xB8FFFFFF));

  /// The sidebar, a little quieter than panels. Classic over glass: 35 %.
  Color get rail => frost
      ? (isDark ? const Color(0x66121A24) : const Color(0x8AF6FAFE))
      : glass
      ? _classic(.35, quiet: true)
      : (isDark ? const Color(0x94141519) : const Color(0xADFFFFFF));

  /// Cards on the backdrop: fainter than panels. Classic over glass: 30 %, the desktop frosted behind them.
  Color get card => frost
      ? (isDark ? const Color(0x57121A24) : const Color(0x7AF6FAFE))
      : glass
      ? _classic(.30)
      : (isDark ? const Color(0x85181A1F) : const Color(0x9EFFFFFF));

  /// Dialogs and menus that float over results (consent, download, context menus, popovers): kept readable
  /// whatever is under them (64 %), with real blur behind them.
  Color get dialog => frost
      ? (isDark ? const Color(0xA3121A24) : const Color(0xB8F6FAFE))
      : glass
      ? _classic(.64)
      : (isDark ? const Color(0xA3181A1F) : const Color(0xB8FFFFFF));

  /// A faint lift laid over something transparent when hovered (buttons, rows).
  Color get cardHover => isDark ? const Color(0x0FFFFFFF) : const Color(0x0A000000);

  /// A hovered card. Over glass it brightens (a little more fill and a faint white lift), never thins; solid, the
  /// hover tint as before.
  Color get cardLift => glass
      ? Color.alphaBlend(
          isDark ? const Color(0x08FFFFFF) : const Color(0x14FFFFFF),
          card.withAlpha((card.a * 255).round() + 0x10),
        )
      : cardHover;

  /// A selected row: a quiet lift, the orange only in its small indicator.
  Color get selected => isDark ? const Color(0x17FFFFFF) : const Color(0x12000000);

  /// The 1 px light rim on the top edge of glass, fading down the sides: icy in Minimal ice.
  Color get rimLight => frost
      ? (isDark ? const Color(0x4DCFE8FF) : const Color(0xF2FFFFFF))
      : (isDark ? const Color(0x38FFFFFF) : const Color(0xF2FFFFFF));
  Color get rimShade => frost
      ? (isDark ? const Color(0x14CFE8FF) : const Color(0x1A1B3A5C))
      : (isDark ? const Color(0x14FFFFFF) : const Color(0x14000000));

  /// The backdrop's soft light. Minimal ice: glacier cyan (large, top left), deep ice (bottom right), a pale ice
  /// haze, and only a small ember of the orange (the orange belongs to actions). Classic: the warm orange, the
  /// magenta and the indigo.
  Color get glowWarm =>
      frost ? orange.withValues(alpha: isDark ? .09 : .07) : orange.withValues(alpha: isDark ? .30 : .22);
  Color get glowCool => frost
      ? (isDark ? const Color(0x473B6CFF) : const Color(0x2E3B6CFF))
      : (isDark ? const Color(0x524F5DFF) : const Color(0x3D4F5DFF));
  Color get glowMagenta => isDark ? const Color(0x38D0347A) : const Color(0x2ED0347A);
  Color get glowGlacier => isDark ? const Color(0x2E6FD3FF) : const Color(0x336FD3FF);
  Color get glowHaze => isDark ? const Color(0x12BFE6FF) : const Color(0x33BFE6FF);

  /// Frosted glass: a faint light falling from the top edge of each layer (icy and a little stronger in Minimal
  /// ice), and its fine grain.
  Color get sheen => frost
      ? (isDark ? const Color(0x17E6F4FF) : const Color(0x80FFFFFF))
      : (isDark ? const Color(0x0FFFFFFF) : const Color(0x66FFFFFF));
  Color get grain => isDark ? const Color(0x0AFFFFFF) : const Color(0x0D000000);

  /// Minimal ice's icon tile (Settings groups, model rows, PC tiles, Home's categories): a cool tint, the glyph a
  /// cool white; the orange only for the selected or suggested one.
  Color get iceTile => isDark ? const Color(0x1F9FD8FF) : const Color(0x1A3B6CFF);
  Color get iceGlyph => isDark ? const Color(0xFFDCEFFF) : const Color(0xFF1E3A66);
  Color get iceAccentTile => orangeA(isDark ? .10 : .09);

  /// Classic's icon tiles: each meaning its own hue. The tile: a soft gradient of the hue ([tileTop] → [tileBottom])
  /// with a 1 px rim of it ([tileRim]); the glyph: the hue's light step on a dark card (dark), its deep step on
  /// white (light), so it keeps 4.5:1 on its tile (test/theme/glass_contrast_test.dart). The hues are the Classic
  /// palette's orange, indigo and magenta and the old badge colours.
  static const _tints = <NbTint, (Color, Color, Color)>{
    NbTint.orange: (Color(0xFFFFCDB6), Color(0xFF9A2E00), Color(0xFFFF4D00)),
    NbTint.green: (Color(0xFF86E4C4), Color(0xFF175A47), Color(0xFF2B8A6E)),
    NbTint.teal: (Color(0xFF8AE3E8), Color(0xFF0F5A61), Color(0xFF1C9AA3)),
    NbTint.amber: (Color(0xFFFADBA0), Color(0xFF7A4E00), Color(0xFFE0A030)),
    NbTint.violet: (Color(0xFFD4C8FF), Color(0xFF5428B8), Color(0xFF7B3FE4)),
    NbTint.blue: (Color(0xFFC2CCFF), Color(0xFF3140C4), Color(0xFF4F5DFF)),
    NbTint.cyan: (Color(0xFF9ADFF6), Color(0xFF085E7A), Color(0xFF1E9BD7)),
    NbTint.magenta: (Color(0xFFF6C4F3), Color(0xFF8A2684), Color(0xFFB83CC0)),
    NbTint.pink: (Color(0xFFFFC6DA), Color(0xFF8F1848), Color(0xFFD0347A)),
    NbTint.neutral: (Color(0xFFCDD3DD), Color(0xFF434956), Color(0xFF8A92A0)),
  };

  /// The glyph colour of [t] in this brightness.
  Color tint(NbTint t) {
    final (d, l, _) = _tints[t]!;
    return isDark ? d : l;
  }

  /// A Classic tile of hue [t]: its top (22 %), its bottom (10 %) and its rim (30 %).
  Color tileTop(NbTint t) => _tints[t]!.$3.withValues(alpha: .22);
  Color tileBottom(NbTint t) => _tints[t]!.$3.withValues(alpha: .10);
  Color tileRim(NbTint t) => _tints[t]!.$3.withValues(alpha: .30);

  /// The soft shadow under floating things.
  Color get float => isDark ? const Color(0x73000000) : const Color(0x1A1B2440);

  static const dark = NbColors(
    brightness: Brightness.dark,
    orange: Color(0xFFFF4D00),
    onOrange: Color(0xFF000000),
    bg: Color(0xFF08090B), // near black (0.7.0)
    surface: Color(0xFF161922),
    raised: Color(0x14FFFFFF),
    text: Color(0xFFF4F5F8),
    muted: Color(0xA3FFFFFF), // white .64: secondary text
    dim: Color(0x85FFFFFF), // white .52: still over 4.5:1 on the canvas
    line: Color(0x14FFFFFF), // .08
    line2: Color(0x26FFFFFF), // .15
    warn: Color(0xFFFFB38A),
    danger: Color(0xFFFF8A8A),
    shadow: Color(0xFF000000),
  );

  static const light = NbColors(
    brightness: Brightness.light,
    orange: Color(0xFFE84400),
    onOrange: Color(0xFFFFFFFF),
    bg: Color(0xFFE7EAF1),
    surface: Color(0xFFFBFBFD),
    raised: Color(0x0F1B2440),
    text: Color(0xFF12141A),
    muted: Color(0xB816181C), // .72
    dim: Color(0x8516181C), // .52
    line: Color(0x17000000), // .09
    line2: Color(0x2E000000), // .18
    warn: Color(0xFFB33A00),
    danger: Color(0xFFB3261E),
    shadow: Color(0x33000000),
  );

  static NbColors of(BuildContext context) => Theme.of(context).extension<NbColors>() ?? dark;

  /// Over glass, secondary text is raised just enough to stay readable over a bright (or dark) wallpaper showing
  /// through the frost (test/theme/glass_contrast_test.dart), per style and brightness: (muted, dim). Classic:
  /// `muted` keeps its value, `dim` (.52 solid) is .63 dark and .62 light. Minimal ice: as built (dark .67 both,
  /// light dim .61). Solid: as before.
  static const _glassText = {
    (false, true): (Color(0xA3FFFFFF), Color(0xA0FFFFFF)), // Classic dark
    (false, false): (Color(0xB816181C), Color(0x9E16181C)), // Classic light
    (true, true): (Color(0xAAFFFFFF), Color(0xAAFFFFFF)), // Minimal ice dark (as in 18a4f7b)
    (true, false): (Color(0xB816181C), Color(0x9B16181C)), // Minimal ice light (as in 18a4f7b)
  };

  /// This palette over glass ([on]) or solid, in the Classic or the Minimal ice ([iceStyle]) style.
  NbColors withGlass(bool on, {bool iceStyle = false}) {
    if (on == glass && iceStyle == ice) return this;
    final base = isDark ? dark : light;
    final (m, d) = on ? _glassText[(iceStyle, isDark)]! : (base.muted, base.dim);
    return NbColors(
      brightness: brightness,
      orange: orange,
      onOrange: onOrange,
      bg: bg,
      surface: surface,
      raised: raised,
      text: text,
      muted: m,
      dim: d,
      line: line,
      line2: line2,
      warn: warn,
      danger: danger,
      shadow: shadow,
      glass: on,
      ice: iceStyle,
    );
  }

  @override
  NbColors copyWith() => this;

  @override
  NbColors lerp(NbColors? other, double t) {
    if (other == null) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t)!;
    return NbColors(
      brightness: t < .5 ? brightness : other.brightness,
      orange: l(orange, other.orange),
      onOrange: l(onOrange, other.onOrange),
      bg: l(bg, other.bg),
      surface: l(surface, other.surface),
      raised: l(raised, other.raised),
      text: l(text, other.text),
      muted: l(muted, other.muted),
      dim: l(dim, other.dim),
      line: l(line, other.line),
      line2: l(line2, other.line2),
      warn: l(warn, other.warn),
      danger: l(danger, other.danger),
      shadow: l(shadow, other.shadow),
      glass: t < .5 ? glass : other.glass,
      ice: t < .5 ? ice : other.ice,
    );
  }
}

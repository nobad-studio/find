/// NOBAD colour tokens for frosted glass: a deep (or pale) backdrop with soft glows, and translucent layers over
/// it: panels, cards and popovers, each with a fine light rim. Over Windows' Acrylic the look is cold ice (glacier
/// cyan and deep ice light, cool frost panels); the NOBAD orange stays the one warm accent, for actions.
///
/// Screens read them with `NbColors.of(context)`; nothing outside lib/app/theme hard-codes a colour.
library;

import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart' show Theme, ThemeExtension;

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

  /// Windows draws Acrylic (or Mica) behind the window: the canvas is see-through and panels are tinted glass.
  final bool glass;

  bool get isDark => brightness == Brightness.dark;
  Color orangeA(double a) => orange.withValues(alpha: a);

  /// Glass on (Windows took its Acrylic or Mica backdrop): the cold "ice" look below. Glass off (the setting,
  /// Windows 10, or Windows' Transparency effects switch off): every token exactly as it was before the ice look.

  /// The ink under the glass: a cold blue-black (dark) or a pale frost (light).
  Color get ink => !glass ? bg : (isDark ? const Color(0xFF070A0F) : const Color(0xFFEAF1F8));

  /// The window canvas under the backdrop: a thin ink tint over Windows' frost, solid otherwise.
  Color get canvas => glass ? ink.withValues(alpha: isDark ? .34 : .42) : bg;

  /// Floating panels (the detail pane, the search box): cool frost at 44 % over Windows' Acrylic (dark), pale
  /// frost at 58 % (light). Solid: neutral dark at 64 %, or white at 72 %.
  Color get panel => glass
      ? (isDark ? const Color(0x70121A24) : const Color(0x94F6FAFE))
      : (isDark ? const Color(0xA3181A1F) : const Color(0xB8FFFFFF));

  /// The sidebar, a little quieter than panels.
  Color get rail => glass
      ? (isDark ? const Color(0x66121A24) : const Color(0x8AF6FAFE))
      : (isDark ? const Color(0x94141519) : const Color(0xADFFFFFF));

  /// Cards on the backdrop: fainter than panels.
  Color get card => glass
      ? (isDark ? const Color(0x57121A24) : const Color(0x7AF6FAFE))
      : (isDark ? const Color(0x85181A1F) : const Color(0x9EFFFFFF));

  /// Dialogs and menus that float over results (consent, download, context menus, popovers): kept readable
  /// whatever is under them, with real blur behind them.
  Color get dialog => glass
      ? (isDark ? const Color(0xA3121A24) : const Color(0xB8F6FAFE))
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

  /// The 1 px light rim on the top edge of glass, fading down the sides: icy over glass.
  Color get rimLight => glass
      ? (isDark ? const Color(0x4DCFE8FF) : const Color(0xF2FFFFFF))
      : (isDark ? const Color(0x38FFFFFF) : const Color(0xF2FFFFFF));
  Color get rimShade => glass
      ? (isDark ? const Color(0x14CFE8FF) : const Color(0x1A1B3A5C))
      : (isDark ? const Color(0x14FFFFFF) : const Color(0x14000000));

  /// The backdrop's soft light. Over glass: glacier cyan (large, top left), deep ice (bottom right), a pale ice
  /// haze, and only a small ember of the orange (the orange belongs to actions). Solid: the warm look as before.
  Color get glowWarm => glass
      ? orange.withValues(alpha: isDark ? .09 : .07)
      : orange.withValues(alpha: isDark ? .30 : .22);
  Color get glowCool => glass
      ? (isDark ? const Color(0x473B6CFF) : const Color(0x2E3B6CFF))
      : (isDark ? const Color(0x524F5DFF) : const Color(0x3D4F5DFF));
  Color get glowMagenta => isDark ? const Color(0x38D0347A) : const Color(0x2ED0347A);
  Color get glowGlacier => isDark ? const Color(0x2E6FD3FF) : const Color(0x336FD3FF);
  Color get glowHaze => isDark ? const Color(0x12BFE6FF) : const Color(0x33BFE6FF);

  /// Frosted glass: a faint light falling from the top edge of each layer (icy and a little stronger over
  /// glass), and its fine grain.
  Color get sheen => glass
      ? (isDark ? const Color(0x17E6F4FF) : const Color(0x80FFFFFF))
      : (isDark ? const Color(0x0FFFFFFF) : const Color(0x66FFFFFF));
  Color get grain => isDark ? const Color(0x0AFFFFFF) : const Color(0x0D000000);

  /// The small frosted tile an icon sits in (Settings groups, model rows, PC tiles): a cool tint, the glyph a cool
  /// white; the orange only for the selected or suggested one.
  Color get iceTile => isDark ? const Color(0x1F9FD8FF) : const Color(0x1A3B6CFF);
  Color get iceGlyph => isDark ? const Color(0xFFDCEFFF) : const Color(0xFF1E3A66);

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

  /// Over glass, secondary text is raised just enough to stay readable over a bright wallpaper showing through
  /// (test/theme/glass_contrast_test.dart): dark muted and dim white .67, light dim .61. Solid: as before.
  static const _glassMutedDark = Color(0xAAFFFFFF), _glassDimDark = Color(0xAAFFFFFF);
  static const _glassDimLight = Color(0x9B16181C);

  NbColors withGlass(bool on) => on == glass
      ? this
      : NbColors(
          brightness: brightness,
          orange: orange,
          onOrange: onOrange,
          bg: bg,
          surface: surface,
          raised: raised,
          text: text,
          muted: !on ? (isDark ? dark.muted : light.muted) : (isDark ? _glassMutedDark : muted),
          dim: !on ? (isDark ? dark.dim : light.dim) : (isDark ? _glassDimDark : _glassDimLight),
          line: line,
          line2: line2,
          warn: warn,
          danger: danger,
          shadow: shadow,
          glass: on,
        );

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
    );
  }
}

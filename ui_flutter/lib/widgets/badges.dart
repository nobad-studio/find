/// The Models page look, shared (0.9.3): an icon tile for what something is, and small fact chips, so a
/// card reads at a glance instead of in sentences. Used by the Index page.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import 'controls.dart';
import 'icons.dart';

/// The kind of work a tile stands for; its colour comes from the theme's one tint table ([NbTint]).
enum NbHue { folder, text, page, meaning, photo, library, use }

/// Each kind of work's hue (Classic), from the same table as every other icon tile.
NbTint hueTint(NbHue h) => switch (h) {
  NbHue.folder => NbTint.amber,
  NbHue.text => NbTint.orange,
  NbHue.page => NbTint.green,
  NbHue.meaning => NbTint.violet,
  NbHue.photo => NbTint.pink,
  NbHue.library => NbTint.blue,
  NbHue.use => NbTint.cyan,
};

/// An icon tile with a glyph (or short text such as "Aa"): the same tile as [GlyphTile], one size everywhere.
class NbAvatar extends StatelessWidget {
  const NbAvatar({super.key, required this.hue, this.glyph, this.text, this.dim = false});
  final NbHue hue;
  final NbGlyph? glyph;
  final String? text;
  final bool dim;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final (top, bottom, rim, ink) = GlyphTile.look(c, glyph ?? NbGlyph.info, hue: hueTint(hue));
    return Opacity(
      opacity: dim ? .45 : 1,
      child: Container(
        width: GlyphTile.size,
        height: GlyphTile.size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          borderRadius: const BorderRadius.all(Radius.circular(NbRadius.tile)),
          gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [top, bottom]),
          border: Border.all(color: rim),
        ),
        child: text != null
            ? Text(text!, style: NbType.text(13, ink, weight: FontWeight.w600, height: 1))
            : NbIcon(glyph ?? NbGlyph.info, color: ink),
      ),
    );
  }
}

/// A small chip with a glyph and a fact ("142,000 files", "2 min left").
class NbFact extends StatelessWidget {
  const NbFact(this.glyph, this.text, {super.key, this.strong = false});
  final NbGlyph glyph;
  final String text;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: strong ? c.orange.withValues(alpha: .12) : c.cardHover,
        borderRadius: NbRadius.pillAll,
        border: Border.all(color: strong ? c.orange.withValues(alpha: .45) : c.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          NbIcon(glyph, size: 12, color: strong ? c.orange : c.dim),
          const SizedBox(width: 5),
          Flexible(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: NbType.text(11.5, strong ? c.orange : c.muted, height: 1.3),
            ),
          ),
        ],
      ),
    );
  }
}

/// The Models and What to index cards' frame: a rounded card, orange-edged when [active] (in use, switched on).
class NbCard extends StatelessWidget {
  const NbCard({super.key, required this.child, this.active = false});
  final Widget child;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
        decoration: BoxDecoration(
          color: active ? c.orange.withValues(alpha: .06) : c.card,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: active ? c.orange.withValues(alpha: .45) : c.line),
        ),
        child: child,
      ),
    );
  }
}

/// "Details" under a card: folds [child] (the long text) open and shut. Screen readers hear "Details about [about]"
/// and whether it is open; the fold animates only when Windows' animation effects are on.
class NbDetails extends StatefulWidget {
  const NbDetails({super.key, required this.about, required this.child});
  final String about;
  final Widget child;

  @override
  State<NbDetails> createState() => _NbDetailsState();
}

class _NbDetailsState extends State<NbDetails> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: Semantics(
            expanded: _open,
            child: NbButton(
              _open ? 'Hide details' : 'Details',
              small: true,
              kind: NbButtonKind.quiet,
              semanticLabel: '${_open ? 'Hide details' : 'Details'} about ${widget.about}',
              onPressed: () => setState(() => _open = !_open),
            ),
          ),
        ),
        AnimatedSize(
          duration: NbMotion.size(context, NbMotion.base),
          curve: NbMotion.curve,
          alignment: Alignment.topCenter,
          child: _open ? widget.child : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

/// One line inside Details: a dim label on the left, the value beside it.
class NbDetailLine extends StatelessWidget {
  const NbDetailLine(this.label, this.value, {super.key});
  final String label;
  final Widget value;

  /// A plain-text value.
  static Widget text(BuildContext context, String s) =>
      Text(s, style: NbType.text(12, NbColors.of(context).text, height: 1.45));

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 118, child: Text(label, style: NbType.text(12, c.dim, height: 1.45))),
          Expanded(child: value),
        ],
      ),
    );
  }
}

/// A number with a coloured tile beside it: the Index page's stats.
class NbStat extends StatelessWidget {
  const NbStat({super.key, required this.hue, required this.glyph, required this.value, required this.label,
    this.live = false});
  final NbHue hue;
  final NbGlyph glyph;
  final String value;
  final String label;
  final bool live;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 10, 12, 10),
      decoration: BoxDecoration(
        color: c.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: live ? c.orange.withValues(alpha: .45) : c.line),
      ),
      child: Row(
        children: [
          NbAvatar(hue: hue, glyph: glyph),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: value.length > 12
                      ? NbType.text(13.5, live ? c.orange : c.text, weight: FontWeight.w600, height: 1.3)
                      : NbType.data(16, live ? c.orange : c.text, weight: FontWeight.w600, height: 1.25),
                ),
                Text(
                  label,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: NbType.text(11.5, c.dim, height: 1.3),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

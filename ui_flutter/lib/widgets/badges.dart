/// The Models page look, shared (0.9.3): a coloured tile for what something is, and small fact chips, so a
/// card reads at a glance instead of in sentences. Used by the Index page.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import 'icons.dart';

/// Two colours for a tile's gradient, one pair per kind of work.
enum NbHue { folder, text, page, meaning, photo, library, use }

(Color, Color) hueColors(NbColors c, NbHue h) => switch (h) {
  NbHue.folder => (const Color(0xFFE0A030), c.orange),
  NbHue.text => (c.orange, const Color(0xFFD0347A)),
  NbHue.page => (const Color(0xFF2B8A6E), const Color(0xFF4F5DFF)),
  NbHue.meaning => (const Color(0xFFD0347A), const Color(0xFF7B3FE4)),
  NbHue.photo => (const Color(0xFF4F5DFF), const Color(0xFFD0347A)),
  NbHue.library => (const Color(0xFF7B3FE4), const Color(0xFF4F5DFF)),
  NbHue.use => (const Color(0xFF3A7BD5), const Color(0xFF2B8A6E)),
};

/// A rounded gradient tile with a glyph (or short text such as "Aa").
class NbAvatar extends StatelessWidget {
  const NbAvatar({super.key, required this.hue, this.glyph, this.text, this.size = 40, this.dim = false});
  final NbHue hue;
  final NbGlyph? glyph;
  final String? text;
  final double size;
  final bool dim;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final (a, b) = hueColors(c, hue);
    const white = Color(0xFFFFFFFF);
    return Opacity(
      opacity: dim ? .45 : 1,
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(size * .28),
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [a, b]),
        ),
        child: text != null
            ? Text(text!, style: NbType.text(size * .36, white, weight: FontWeight.w700, height: 1))
            : NbIcon(glyph ?? NbGlyph.info, size: size * .45, color: white),
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
          NbAvatar(hue: hue, glyph: glyph, size: 34),
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

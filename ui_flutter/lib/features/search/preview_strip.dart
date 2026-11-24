/// The preview of the selected result in a window too narrow for the detail pane (1.2): a slim strip docked under
/// the results, never over them (no scrim, nothing covers the list, so a second click on a row still opens it).
/// Name, folder, a line of facts, Open and Show in folder; a close button (Esc closes it too).
library;

import 'package:flutter/widgets.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class PreviewStrip extends StatelessWidget {
  const PreviewStrip({
    super.key,
    required this.result,
    required this.onOpen,
    required this.onReveal,
    required this.onClose,
  });
  final FileResult result;
  final VoidCallback onOpen;
  final VoidCallback onReveal;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = result;
    final facts = [
      kindTag(r.kind),
      r.ext,
      r.ago,
      humanSize(r.size),
      if (r.why.isNotEmpty) r.why.first,
    ].where((s) => s.isNotEmpty).join('   ');
    return Padding(
      padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 4, NbSpace.gutter, 6),
      child: Glass(
        level: GlassLevel.panel,
        radius: NbRadius.card,
        padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    r.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600),
                  ),
                  TailText(r.dir, textAlign: TextAlign.left, style: NbType.data(11.5, c.muted)),
                  Text(facts, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(11.5, c.dim)),
                ],
              ),
            ),
            const SizedBox(width: 12),
            NbButton('Open', small: true, icon: NbGlyph.external, onPressed: onOpen),
            const SizedBox(width: 8),
            NbButton(
              'Show in folder',
              small: true,
              kind: NbButtonKind.ghost,
              icon: NbGlyph.folder,
              onPressed: onReveal,
            ),
            const SizedBox(width: 4),
            Pressable(
              onTap: onClose,
              semanticLabel: 'Close preview',
              tooltip: 'Close (Esc)',
              canRequestFocus: false,
              ringRadius: NbRadius.pillAll,
              builder: (context, p) => Container(
                padding: const EdgeInsets.all(7),
                decoration: BoxDecoration(color: p.lit ? c.cardHover : null, shape: BoxShape.circle),
                child: NbIcon(NbGlyph.close, size: 13, color: p.lit ? c.text : c.dim),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

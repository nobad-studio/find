/// 0.9.1: above the results, the Windows Settings pages, tools and apps the question fits ("open bluetooth",
/// "chrome"), each with Open. The engine runs them by id (run_action); the window never hands it a path.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class ActionsBlock extends StatelessWidget {
  const ActionsBlock(this.actions, {super.key});
  final List<SearchAction> actions;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      decoration: BoxDecoration(
        color: c.card,
        borderRadius: NbRadius.cardAll,
        border: Border.all(color: c.line),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [for (final (i, a) in actions.take(3).indexed) _ActionRow(a, first: i == 0)],
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow(this.a, {required this.first});
  final SearchAction a;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final f = AppScope.of(context).find;
    void go() => unawaited(f.runAction(a));
    final glyph = switch (a.kind) {
      'app' => NbGlyph.grid,
      'tool' => NbGlyph.gauge,
      _ => NbGlyph.settings,
    };
    return Pressable(
      onTap: go,
      semanticLabel: 'Open ${a.title}',
      builder: (context, p) => Container(
        padding: const EdgeInsets.fromLTRB(12, 9, 10, 9),
        decoration: BoxDecoration(
          color: p.lit ? c.cardHover : null,
          border: first ? null : Border(top: BorderSide(color: c.line)),
        ),
        child: Row(
          children: [
            Container(
              width: 30,
              height: 30,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: c.orange.withValues(alpha: .12), borderRadius: BorderRadius.circular(8)),
              child: NbIcon(glyph, size: 15, color: c.orange),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(a.title, style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.25)),
                  if (a.subtitle.isNotEmpty)
                    Text(
                      a.subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: NbType.text(11.5, c.dim, height: 1.3),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            NbButton(first ? 'Open  ↵' : 'Open', small: true, kind: first ? NbButtonKind.primary : NbButtonKind.ghost, onPressed: go),
          ],
        ),
      ),
    );
  }
}

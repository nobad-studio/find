/// 0.9.0: above the results, what this search would need that isn't ready (the engine's `needs`): the photo model
/// to download, photo or meaning search to switch on, or photos still being looked at, with one button that does
/// it. Downloads still go through the consent dialog; nothing is fetched without a yes.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../state/models_controller.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../consent/download_consent_dialog.dart';

class NeedHint extends StatefulWidget {
  const NeedHint(this.need, {super.key, this.onChanged});
  final SearchNeed need;

  /// After switching something on: search again so the new results show.
  final VoidCallback? onChanged;

  @override
  State<NeedHint> createState() => _NeedHintState();
}

class _NeedHintState extends State<NeedHint> {
  bool _busy = false;

  String get _setting => widget.need.model == 'photo' ? 'photo_meaning' : 'semantic';

  Future<void> _turnOn() async {
    setState(() => _busy = true);
    final ok = await AppScope.of(context).settings.set(_setting, true);
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) widget.onChanged?.call();
  }

  Future<void> _download() async {
    final s = AppScope.of(context);
    setState(() => _busy = true);
    final m = ModelsController(s.engine, toasts: s.toasts);
    try {
      await m.refresh();
      final info = m.info.models.where((x) => x.id == widget.need.id).firstOrNull;
      if (info == null || !mounted) {
        s.toasts.show("That model isn't available. Open Settings > Models.");
        return;
      }
      final ok = await m.download(info, consent: (x) => askModelConsent(context, x));
      if (ok && !s.settings.settings.flag(_setting)) await s.settings.set(_setting, true);
    } finally {
      m.dispose();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final n = widget.need;
    final (String? action, VoidCallback? onTap) = switch (n.state) {
      'missing' => ('Download…', () => unawaited(_download())),
      'off' => (n.model == 'photo' ? 'Turn on photo search' : 'Turn on meaning search', () => unawaited(_turnOn())),
      _ => (null, null),
    };
    final frac = n.total > 0 ? (n.done / n.total).clamp(0.0, 1.0) : 0.0;
    return Semantics(
      container: true,
      label: n.text,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        decoration: BoxDecoration(
          color: c.orange.withValues(alpha: .07),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: c.orange.withValues(alpha: .35)),
        ),
        child: Row(
          children: [
            NbIcon(n.model == 'photo' ? NbGlyph.image : NbGlyph.info, size: 18, color: c.orange),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(n.text, style: NbType.text(12.5, c.text, height: 1.35)),
                  if (n.state == 'analyzing' && n.total > 0) ...[
                    const SizedBox(height: 7),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(3),
                      child: SizedBox(
                        height: 5,
                        child: Stack(
                          children: [
                            Container(color: c.line2),
                            FractionallySizedBox(widthFactor: frac, child: Container(color: c.orange)),
                          ],
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (action != null) ...[
              const SizedBox(width: 10),
              NbButton(action, small: true, onPressed: _busy ? null : onTap),
            ],
          ],
        ),
      ),
    );
  }
}

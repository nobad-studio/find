/// "Stored on this PC" (1.2): what NOBAD Find keeps on disk, as the engine measured it from file sizes (`storage_use`):
/// the index, each downloaded model, the runtimes and temporary files. On the Index page it has a "Free up" link to
/// Settings > Models, where a model's files can be removed. An engine without `storage_use` shows nothing.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/format.dart';
import '../../engine/models/models_info.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';

class StorageUseCard extends StatefulWidget {
  const StorageUseCard({super.key, this.freeUp = false, this.names = const {}});

  /// Show "Free up", which opens Settings > Models (leave it off on Models itself).
  final bool freeUp;

  /// Model names by id (the catalogue's); an id without a name is shown as it is.
  final Map<String, String> names;

  @override
  State<StorageUseCard> createState() => _StorageUseCardState();
}

class _StorageUseCardState extends State<StorageUseCard> {
  StorageUse? _use;
  bool _asked = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_asked) return;
    _asked = true;
    unawaited(_load(AppScope.of(context)));
  }

  Future<void> _load(AppScope s) async {
    StorageUse? u;
    try {
      u = await s.engine.storageUse();
    } on Object {
      u = null; // an older engine or a dropped pipe: no figures, never made-up ones
    }
    if (mounted) setState(() => _use = u);
  }

  @override
  Widget build(BuildContext context) {
    final u = _use;
    if (u == null) return const SizedBox.shrink();
    final c = NbColors.of(context);
    Widget row(String label, double v) => Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        children: [
          Expanded(child: Text(label, style: NbType.text(NbSize.small, c.muted))),
          Text(mb(v), style: NbType.text(NbSize.small, c.text)),
        ],
      ),
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: NbPanel(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Stored on this PC', style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600)),
                ),
                Text(mb(u.totalMb), style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600)),
                if (widget.freeUp) ...[
                  const SizedBox(width: 14),
                  Pressable(
                    onTap: () => AppScope.of(context).nav.openSettings(SettingsPage.models),
                    semanticLabel: 'Free up',
                    builder: (context, p) => Text(
                      'Free up',
                      style: NbType.text(NbSize.small, c.orange, weight: FontWeight.w600).copyWith(
                        decoration: p.lit ? TextDecoration.underline : TextDecoration.none,
                        decorationColor: c.orange,
                      ),
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 2),
            Text(
              'Measured from the files on disk. Only models you downloaded take room.',
              style: NbType.text(NbSize.small, c.dim),
            ),
            row('Index', u.indexMb),
            if (u.walMb > 0) row('Index, changes not merged yet', u.walMb),
            for (final m in u.models) row(widget.names[m.id] ?? m.id, m.mb),
            if (u.runtimeMb > 0) row('Runtime for talk about a photo', u.runtimeMb),
            if (u.tmpMb > 0) row('Temporary files', u.tmpMb),
          ],
        ),
      ),
    );
  }
}

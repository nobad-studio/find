/// Install's progress (Settings > About > Updates): three steps, Download, Check, Install, each from the engine's
/// own `update` events. Download shows the bytes that really arrived (percent, MB of MB, the measured speed and the
/// time left at that speed); Check (size and SHA-256) and Install have no byte count, so they show a moving sweep,
/// which runs only for those few seconds. With Windows' Animation effects off nothing moves: a still tinted bar.
library;

import 'package:flutter/widgets.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/update.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/panels.dart';

const _mib = 1048576;

/// "12.3 MB": one decimal under 100 MB, whole above.
String updateMb(int bytes) {
  final m = bytes / _mib;
  return '${m >= 100 ? m.round() : m.toStringAsFixed(1)} MB';
}

/// "about 8 s left", "about 2 min left".
String timeLeft(int s) => s < 60 ? 'about $s s left' : 'about ${(s / 60).ceil()} min left';

/// The line under the bar: "12.3 of 40.0 MB · 3.4 MB/s · about 8 s left" (the speed only once it's measured).
String downloadLine(UpdateState u) {
  final parts = <String>[
    u.size > 0 ? '${updateMb(u.got).replaceFirst(' MB', '')} of ${updateMb(u.size)}' : updateMb(u.got),
    if (u.bps > 0) '${(u.bps / _mib).toStringAsFixed(1)} MB/s',
    if (u.secondsLeft != null) timeLeft(u.secondsLeft!),
  ];
  return parts.join('  ·  ');
}

class UpdateProgress extends StatelessWidget {
  const UpdateProgress(this.u, {super.key});
  final UpdateState u;

  /// 0 Download, 1 Check, 2 Install.
  int get step => switch (u.state) {
    'downloading' => 0,
    'verifying' => 1,
    _ => 2,
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final pct = '${(u.fraction * 100).floor()}%';
    final (String title, String detail) = switch (step) {
      0 => ('Downloading NOBAD Find ${u.latest}', downloadLine(u)),
      1 => ('Checking the download', "Its size and SHA-256 must match the release's .sha256 file and GitHub's digest."),
      _ => ('Installing ${u.latest}', 'NOBAD Find closes, installs over this version and starts again in a moment.'),
    };
    return Semantics(
      liveRegion: true,
      label: step == 0 ? '$title, $pct' : title,
      child: Container(
        key: const ValueKey('update-progress'),
        padding: const EdgeInsets.fromLTRB(NbSpace.x4, NbSpace.x3, NbSpace.x4, NbSpace.x4),
        decoration: BoxDecoration(
          color: c.cardHover,
          borderRadius: NbRadius.rowAll,
          border: Border.all(color: c.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Steps(step),
            const SizedBox(height: NbSpace.x4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: AnimatedSwitcher(
                    duration: NbMotion.of(context, NbMotion.slow),
                    layoutBuilder: (cur, prev) => Stack(alignment: Alignment.centerLeft, children: [...prev, ?cur]),
                    child: Text(
                      title,
                      key: ValueKey(title),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: NbType.text(13, c.text, weight: FontWeight.w600, height: 1.3),
                    ),
                  ),
                ),
                if (step == 0) Text(pct, style: NbType.data(13, c.orange, weight: FontWeight.w600, height: 1.3)),
              ],
            ),
            const SizedBox(height: NbSpace.x2),
            if (step == 0) NbMeter(fraction: u.fraction, busy: u.size == 0) else const NbSweep(),
            const SizedBox(height: NbSpace.x2),
            Text(
              detail,
              key: const ValueKey('update-progress-detail'),
              style: (step == 0 ? NbType.data(11.5, c.muted, height: 1.4) : NbType.text(11.5, c.muted, height: 1.4)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Download, Check, Install: done ones filled with a tick, the current one ringed (and breathing while motion is
/// on), the rest waiting.
class _Steps extends StatelessWidget {
  const _Steps(this.step);
  final int step;

  static const labels = ['Download', 'Check', 'Install'];

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, NbMotion.slow);
    return Row(
      children: [
        for (var i = 0; i < labels.length; i++) ...[
          if (i > 0)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: NbSpace.x2),
                child: AnimatedContainer(
                  duration: d,
                  curve: NbMotion.curve,
                  height: 1.5,
                  color: i <= step ? c.orange : c.line2,
                ),
              ),
            ),
          _Node(state: i < step ? _NodeState.done : (i == step ? _NodeState.now : _NodeState.waiting)),
          const SizedBox(width: 6),
          Text(
            labels[i],
            style: NbType.text(
              12,
              i == step ? c.text : (i < step ? c.muted : c.dim),
              weight: i == step ? FontWeight.w600 : FontWeight.w400,
              height: 1.2,
            ),
          ),
        ],
      ],
    );
  }
}

enum _NodeState { done, now, waiting }

class _Node extends StatelessWidget {
  const _Node({required this.state});
  final _NodeState state;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, NbMotion.slow);
    return AnimatedContainer(
      duration: d,
      curve: NbMotion.curve,
      width: 18,
      height: 18,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: state == _NodeState.done ? c.orange : const Color(0x00000000),
        border: Border.all(color: state == _NodeState.waiting ? c.line2 : c.orange, width: 1.5),
      ),
      child: switch (state) {
        _NodeState.done => NbIcon(NbGlyph.check, size: 10, color: c.onOrange),
        _NodeState.now => const _Breathe(),
        _NodeState.waiting => null,
      },
    );
  }
}

/// The current step's dot: grows and fades gently, once a second and a bit. Still with motion off.
class _Breathe extends StatefulWidget {
  const _Breathe();

  @override
  State<_Breathe> createState() => _BreatheState();
}

class _BreatheState extends State<_Breathe> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reduceMotion(context)) {
      _c
        ..stop()
        ..value = 1;
    } else if (!_c.isAnimating) {
      _c.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final t = NbMotion.curve.transform(_c.value);
        return Container(
          width: 5 + 3 * t,
          height: 5 + 3 * t,
          decoration: BoxDecoration(shape: BoxShape.circle, color: c.orange.withValues(alpha: .55 + .45 * t)),
        );
      },
    );
  }
}

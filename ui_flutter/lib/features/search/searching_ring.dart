/// The search box's "still looking" mark (1.2): a small ring turning where the search glyph is, shown only when a
/// search has taken longer than 150 ms (a quicker answer never shows it, so the box doesn't flicker while typing).
/// With Windows' animation effects off it is a still dot instead. It goes with the answer or when the box is cleared.
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import '../../widgets/motion.dart';

class SearchingRing extends StatefulWidget {
  const SearchingRing({
    super.key,
    required this.searching,
    required this.color,
    required this.size,
    required this.child,
  });

  /// True while a search is on its way (`FindController.searching`).
  final ValueListenable<bool> searching;
  final Color color;

  /// The glyph's size: the ring and the dot take the same room.
  final double size;

  /// The search glyph, shown whenever the ring isn't.
  final Widget child;

  /// How long a search runs before the ring appears.
  static const delay = Duration(milliseconds: 150);

  @override
  State<SearchingRing> createState() => _SearchingRingState();
}

class _SearchingRingState extends State<SearchingRing> with SingleTickerProviderStateMixin {
  late final AnimationController _turn = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
  Timer? _wait;
  bool _show = false;

  @override
  void initState() {
    super.initState();
    widget.searching.addListener(_changed);
    _changed();
  }

  @override
  void didUpdateWidget(SearchingRing old) {
    super.didUpdateWidget(old);
    if (old.searching != widget.searching) {
      old.searching.removeListener(_changed);
      widget.searching.addListener(_changed);
      _changed();
    }
  }

  void _changed() {
    if (widget.searching.value) {
      if (_show || (_wait?.isActive ?? false)) return;
      _wait = Timer(SearchingRing.delay, () {
        if (!mounted || !widget.searching.value) return;
        setState(() => _show = true);
      });
    } else {
      _wait?.cancel();
      if (_show) setState(() => _show = false);
    }
  }

  @override
  void dispose() {
    widget.searching.removeListener(_changed);
    _wait?.cancel();
    _turn.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_show) {
      if (_turn.isAnimating) _turn.stop();
      return widget.child;
    }
    final s = widget.size;
    if (reduceMotion(context)) {
      if (_turn.isAnimating) _turn.stop();
      return SizedBox(
        key: const ValueKey('searching-dot'),
        width: s,
        height: s,
        child: Center(
          child: DecoratedBox(
            decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
            child: const SizedBox(width: 7, height: 7),
          ),
        ),
      );
    }
    if (!_turn.isAnimating) unawaited(_turn.repeat());
    return Semantics(
      label: 'Searching',
      child: RotationTransition(
        key: const ValueKey('searching-ring'),
        turns: _turn,
        child: RepaintBoundary(
          child: CustomPaint(size: Size.square(s), painter: _RingPainter(widget.color)),
        ),
      ),
    );
  }
}

/// A faint full circle with a brighter quarter turning on it.
class _RingPainter extends CustomPainter {
  _RingPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final r = Rect.fromLTWH(1.2, 1.2, size.width - 2.4, size.height - 2.4);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(r, 0, math.pi * 2, false, p..color = color.withValues(alpha: .25));
    canvas.drawArc(r, -math.pi / 2, math.pi / 2, false, p..color = color);
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.color != color;
}

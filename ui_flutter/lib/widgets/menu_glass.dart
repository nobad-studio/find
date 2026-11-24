/// Drop-down and right-click menus as frosted glass: the same blurred, rimmed layer as dialogs, opening with a short
/// fade, a small rise and a scale from its corner (macOS-like), instead of Material's tall height grow.
///
/// Flutter's menu panel is made invisible (theme.dart: transparent, no elevation, no padding) and the items sit in
/// [MenuGlass]. The panel clips its children, so the glass keeps [MenuGlass.room] around itself for its soft shadow;
/// menus opened at a position subtract it ([MenuGlass.at]) so the glass lands where it used to.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/tokens.dart';
import 'glass.dart';

class MenuGlass extends StatefulWidget {
  const MenuGlass({super.key, required this.children});
  final List<Widget> children;

  /// Room left around the glass for its shadow (the menu panel clips).
  static const room = 14.0;

  /// The glass's corners: concentric with the stadium rows inside its 4 px padding.
  static const radius = 16.0;

  /// [items] as the menu's one child: pass this to MenuAnchor.menuChildren.
  static List<Widget> wrap(List<Widget> items) => [MenuGlass(children: items)];

  /// A menu position that puts the glass's corner (not its shadow room) at [p].
  static Offset at(Offset p) => p - const Offset(room, room);

  static const opening = Duration(milliseconds: 180);

  @override
  State<MenuGlass> createState() => _MenuGlassState();
}

class _MenuGlassState extends State<MenuGlass> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: MenuGlass.opening);
  late final _a = CurvedAnimation(parent: _c, curve: NbMotion.curve);
  var _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (NbMotion.of(context, MenuGlass.opening) == Duration.zero) {
      _c.value = 1;
    } else {
      _c.forward();
    }
  }

  @override
  void dispose() {
    _a.dispose();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final glass = Padding(
      padding: const EdgeInsets.all(MenuGlass.room),
      child: Glass(
        level: GlassLevel.blur,
        radius: MenuGlass.radius,
        padding: const EdgeInsets.all(NbSpace.x1),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: widget.children,
        ),
      ),
    );
    return AnimatedBuilder(
      animation: _a,
      child: glass,
      builder: (context, child) {
        final t = _a.value;
        if (t == 1) return child!;
        return Opacity(
          opacity: Curves.easeOut.transform((t * 1.6).clamp(0, 1)),
          child: Transform.translate(
            offset: Offset(0, -6 * (1 - t)),
            child: Transform.scale(scale: .96 + .04 * t, alignment: Alignment.topLeft, child: child),
          ),
        );
      },
    );
  }
}

/// The notification bell in every page header, with the unread count, and its panel: each notification's title,
/// what happened, when, how serious, and at most one button (a page to open). Mark all read and Clear. The text
/// is the engine's, shown as plain text; nothing here claims more than the engine said.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../engine/models/format.dart';
import '../../state/notifications_controller.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class NotificationBell extends StatefulWidget {
  const NotificationBell({super.key, required this.controller});
  final NotificationsController controller;

  static const panelWidth = 380.0;

  @override
  State<NotificationBell> createState() => _NotificationBellState();
}

class _NotificationBellState extends State<NotificationBell> {
  final _panel = OverlayPortalController();
  final _link = LayerLink();
  final _group = Object();
  final _focus = FocusNode(debugLabel: 'notifications');

  void _toggle() {
    if (_panel.isShowing) return _close();
    setState(_panel.show);
    // the panel takes the keyboard (Tab through its buttons, Escape closes it); the search box keeps its text
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _panel.isShowing) _focus.requestFocus();
    });
  }

  void _close() {
    if (!_panel.isShowing) return;
    final had = _focus.hasFocus;
    setState(_panel.hide);
    if (had) _focus.unfocus(disposition: UnfocusDisposition.previouslyFocusedChild);
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return CompositedTransformTarget(
      link: _link,
      child: OverlayPortal(
        controller: _panel,
        overlayChildBuilder: (context) => Positioned(
          width: NotificationBell.panelWidth,
          child: CompositedTransformFollower(
            link: _link,
            targetAnchor: Alignment.bottomRight,
            followerAnchor: Alignment.topRight,
            offset: const Offset(0, 6),
            child: TapRegion(
              groupId: _group,
              onTapOutside: (_) => _close(),
              child: CallbackShortcuts(
                bindings: {const SingleActivator(LogicalKeyboardKey.escape): _close},
                child: Focus(
                  focusNode: _focus,
                  child: NotificationsPanel(controller: widget.controller, onDone: _close),
                ),
              ),
            ),
          ),
        ),
        child: TapRegion(
          groupId: _group,
          child: ListenableBuilder(
            listenable: widget.controller,
            builder: (context, _) {
              final n = widget.controller.unread;
              final label = n == 0 ? 'Notifications' : 'Notifications, $n unread';
              return Pressable(
                onTap: _toggle,
                semanticLabel: label,
                selected: _panel.isShowing,
                builder: (context, s) => SizedBox(
                  width: 34,
                  height: 30,
                  // the label says the count; the badge's digits aren't read out again
                  child: ExcludeSemantics(
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        Positioned.fill(
                          child: AnimatedContainer(
                            duration: NbMotion.of(context, NbMotion.fast),
                            decoration: BoxDecoration(
                              color: s.lit || _panel.isShowing ? c.cardHover : const Color(0x00000000),
                              borderRadius: NbRadius.controlAll,
                            ),
                            child: Center(
                              child: NbIcon(NbGlyph.bell, size: 16, color: n > 0 || s.lit ? c.text : c.muted),
                            ),
                          ),
                        ),
                        if (n > 0)
                          Positioned(
                            right: 1,
                            top: 0,
                            child: Container(
                              key: const ValueKey('unread-badge'),
                              constraints: const BoxConstraints(minWidth: 16),
                              height: 16,
                              padding: const EdgeInsets.symmetric(horizontal: 4),
                              decoration: BoxDecoration(color: c.orange, borderRadius: NbRadius.pillAll),
                              alignment: Alignment.center,
                              child: Text(
                                n > 99 ? '99+' : '$n',
                                style: NbType.data(10.5, c.onOrange, weight: FontWeight.w700, height: 1),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

/// The list itself (also used on its own in tests).
class NotificationsPanel extends StatelessWidget {
  const NotificationsPanel({super.key, required this.controller, this.onDone, this.now});
  final NotificationsController controller;

  /// Called after a button opened a page (the panel closes).
  final VoidCallback? onDone;

  /// The time "ago" is counted from (tests); null: now.
  final DateTime Function()? now;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Glass(
      level: GlassLevel.blur,
      radius: NbRadius.card,
      padding: const EdgeInsets.fromLTRB(4, 10, 4, 6),
      child: ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
          final items = controller.items;
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 8, 6),
                child: Row(
                  children: [
                    Expanded(
                      child: Text('Notifications', style: NbType.text(14, c.text, weight: FontWeight.w600)),
                    ),
                    NbButton(
                      'Mark all read',
                      small: true,
                      kind: NbButtonKind.quiet,
                      onPressed: controller.unread == 0 ? null : () => unawaited(controller.markAllRead()),
                    ),
                    const SizedBox(width: 4),
                    NbButton(
                      'Clear',
                      small: true,
                      kind: NbButtonKind.quiet,
                      onPressed: items.isEmpty ? null : () => unawaited(_clear(context)),
                    ),
                  ],
                ),
              ),
              Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 10), color: c.line),
              if (items.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(14, 18, 14, 18),
                  child: Text(
                    'Nothing yet. NOBAD Find tells you here when one of its workers stops or restarts, a model '
                    "can't be used, an internal error happens, or an update is ready.",
                    style: NbType.text(12.5, c.dim, height: 1.45),
                  ),
                )
              else
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 420),
                  child: ListView.builder(
                    shrinkWrap: true,
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    itemCount: items.length,
                    itemBuilder: (context, i) =>
                        _Row(item: items[i], now: (now ?? DateTime.now)(), onAction: (a) => _act(context, items[i], a)),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _clear(BuildContext context) async {
    final s = AppScope.maybeOf(context);
    final ok = await controller.clear();
    if (!ok) s?.toasts.show("Couldn't clear the notifications.");
  }

  void _act(BuildContext context, AppNotification n, NotifyAction a) {
    unawaited(controller.markRead(n.id));
    final nav = AppScope.maybeOf(context)?.nav;
    if (nav != null) {
      switch (a.id) {
        case 'open_indexing':
          nav.go(AppTab.indexing);
        case 'open_performance':
          nav.openSettings(SettingsPage.performance);
        case 'open_models':
          nav.openSettings(SettingsPage.models);
        case 'open_turbo':
          nav.openSettings(SettingsPage.indexing);
        case 'update':
          nav.openSettings(SettingsPage.about);
      }
    }
    onDone?.call();
  }
}

/// "just now", "5 min ago", "3 h ago", or the date and time for older ones.
String notificationTime(double t, DateTime now) {
  if (t <= 0) return '';
  final at = DateTime.fromMillisecondsSinceEpoch((t * 1000).round());
  final s = now.difference(at).inSeconds;
  if (s < 60) return 'just now';
  if (s < 3600) return '${s ~/ 60} min ago';
  if (s < 86400) return '${s ~/ 3600} h ago';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return '${at.day} ${months[at.month - 1]}, ${clock(t)}';
}

class _Row extends StatelessWidget {
  const _Row({required this.item, required this.now, required this.onAction});
  final AppNotification item;
  final DateTime now;
  final void Function(NotifyAction) onAction;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final (glyph, tone, word) = switch (item.severity) {
      NotifySeverity.error => (NbGlyph.error, c.danger, 'Error'),
      NotifySeverity.warning => (NbGlyph.warning, c.warn, 'Warning'),
      NotifySeverity.info => (NbGlyph.info, c.muted, 'Info'),
    };
    final a = item.action;
    return Semantics(
      container: true,
      label: '$word${item.read ? '' : ', unread'}',
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
        decoration: BoxDecoration(color: item.read ? null : c.orangeA(.06), borderRadius: NbRadius.rowAll),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: NbIcon(glyph, size: 15, color: tone),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          item.title,
                          style: NbType.text(13, c.text, weight: item.read ? FontWeight.w500 : FontWeight.w600),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(notificationTime(item.t, now), style: NbType.text(NbSize.micro, c.dim)),
                    ],
                  ),
                  if (item.body.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(item.body, style: NbType.text(12.5, c.muted, height: 1.4)),
                  ],
                  if (item.detail.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(item.detail, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(11.5, c.dim)),
                  ],
                  if (a != null) ...[
                    const SizedBox(height: 7),
                    NbButton(a.label, small: true, kind: NbButtonKind.ghost, onPressed: () => onAction(a)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

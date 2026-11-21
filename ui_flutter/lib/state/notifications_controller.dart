/// The notification bell: the engine's notifications (crashes, restarted workers, fallbacks, internal errors,
/// suggestions, updates), from `notifications_list` once per connection and the `notification` event after that.
/// Never polled. With no engine nothing old is shown as if it were current.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';

class NotificationsController extends ChangeNotifier {
  NotificationsController(this.engine) {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_linkChanged);
    if (engine.link.value == Link.connected) unawaited(load());
  }

  final EngineApi engine;
  late final StreamSubscription<EngineEvent> _sub;
  List<AppNotification> _items = const [];
  var _disposed = false;

  /// Newest first.
  List<AppNotification> get items => _items;
  int get unread => _items.where((n) => !n.read).length;

  Future<void> load() async {
    try {
      final l = await engine.notificationsList();
      _items = l.items;
    } on Object {
      return; // no engine, or one that has no notifications: nothing to show
    }
    _changed();
  }

  void _event(EngineEvent e) {
    if (e is! NotificationEvent) return;
    _items = [
      e.item,
      for (final n in _items)
        if (n.id != e.item.id) n,
    ];
    _changed();
  }

  void _linkChanged() {
    if (engine.link.value == Link.connected) {
      unawaited(load());
    } else if (engine.link.value == Link.offline) {
      _items = const [];
      _changed();
    }
  }

  /// One was acted on (its button): read.
  Future<void> markRead(int id) async {
    if (!_items.any((n) => n.id == id && !n.read)) return;
    _items = [for (final n in _items) n.id == id ? n.asRead() : n];
    _changed();
    try {
      await engine.notificationsRead(ids: [id]);
    } on Object {
      // the engine's list says the truth the next time it's loaded
    }
  }

  Future<void> markAllRead() async {
    if (unread == 0) return;
    _items = [for (final n in _items) n.read ? n : n.asRead()];
    _changed();
    try {
      await engine.notificationsRead(all: true);
    } on Object {
      await load();
    }
  }

  /// Clear: every notification goes. False if the engine couldn't (the list stays as it was).
  Future<bool> clear() async {
    final before = _items;
    _items = const [];
    _changed();
    try {
      final r = await engine.notificationsClear();
      if (r.ok) return true;
    } on Object {
      // below
    }
    _items = before;
    _changed();
    return false;
  }

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_sub.cancel());
    engine.link.removeListener(_linkChanged);
    super.dispose();
  }
}

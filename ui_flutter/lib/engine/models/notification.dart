/// Notifications (contract: `notifications_list`, `notifications_read`, `notifications_clear`, the `notification`
/// event): crashes, restarted workers, model fallbacks, internal errors, suggestions, updates, long pauses.
/// Text is plain and untrusted: shown as text, never markup. It never has a file path; [AppNotification.detail] is a
/// file name only while the `notify_show_names` setting is on.
library;

import 'json.dart';

enum NotifySeverity {
  info,
  warning,
  error;

  static NotifySeverity parse(Object? v) => switch (v) {
    'error' => error,
    'warning' => warning,
    _ => info,
  };
}

/// The one button a notification may have: [id] is a page to open (open_indexing, open_performance, open_models,
/// open_turbo, update), [label] its text.
class NotifyAction {
  const NotifyAction(this.id, this.label);
  final String id;
  final String label;

  static const known = {'open_indexing', 'open_performance', 'open_models', 'open_turbo', 'update'};

  static NotifyAction? fromJson(Object? v) {
    final m = jMap(v);
    final id = jStr(m['id']);
    final label = jStr(m['label']);
    return known.contains(id) && label.isNotEmpty ? NotifyAction(id, label) : null;
  }
}

class AppNotification {
  const AppNotification({
    required this.id,
    required this.t,
    required this.kind,
    required this.severity,
    required this.title,
    this.body = '',
    this.detail = '',
    this.action,
    this.read = false,
  });

  final int id;

  /// Seconds since 1970.
  final double t;
  final String kind;
  final NotifySeverity severity;
  final String title;
  final String body;
  final String detail;
  final NotifyAction? action;
  final bool read;

  AppNotification asRead() => AppNotification(
    id: id,
    t: t,
    kind: kind,
    severity: severity,
    title: title,
    body: body,
    detail: detail,
    action: action,
    read: true,
  );

  static AppNotification? fromJson(Object? v) {
    final m = jMap(v);
    final id = jIntOrNull(m['id']);
    final title = jStr(m['title']);
    if (id == null || title.isEmpty) return null;
    return AppNotification(
      id: id,
      t: jNum(m['t']),
      kind: jStr(m['kind']),
      severity: NotifySeverity.parse(m['severity']),
      title: title,
      body: jStr(m['body']),
      detail: jStr(m['detail']),
      action: NotifyAction.fromJson(m['action']),
      read: jBool(m['read']),
    );
  }
}

/// `notifications_list`: newest first, and how many are unread.
class NotificationList {
  const NotificationList(this.items, this.unread);
  final List<AppNotification> items;
  final int unread;

  static const empty = NotificationList([], 0);

  static NotificationList fromJson(Object? v) {
    final m = jMap(v);
    return NotificationList(jList(m['items'], AppNotification.fromJson), jInt(m['unread']));
  }
}

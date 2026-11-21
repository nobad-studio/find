// The notification bell (header) and its panel: the unread count, new ones from the engine's event, each row's
// title, text, time, severity and its one button, Mark all read and Clear, and the settings rows.
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/engine/engine_api.dart';
import 'package:nobad_find/features/notifications/notification_bell.dart';
import 'package:nobad_find/widgets/icons.dart';

import '../support/fake_engine.dart';

const _now = 1763400000.0;

AppNotification note(
  int id,
  String title, {
  NotifySeverity severity = NotifySeverity.warning,
  String body = 'What happened.',
  NotifyAction? action,
  bool read = false,
  double t = _now,
  String detail = '',
}) => AppNotification(
  id: id,
  t: t,
  kind: 'worker_restarted',
  severity: severity,
  title: title,
  body: body,
  action: action,
  read: read,
  detail: detail,
);

Finder get bell => find.byType(NotificationBell);
Finder get badge => find.byKey(const ValueKey('unread-badge'));

Future<void> openPanel(WidgetTester tester) async {
  await tester.tap(bell.first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the bell is in the header with no count when nothing is unread', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    expect(bell, findsOneWidget);
    expect(badge, findsNothing);
    expect(engine.calls, contains('notifications_list'));
    await openPanel(tester);
    expect(find.text('Notifications'), findsOneWidget);
    expect(find.textContaining('Nothing yet.'), findsOneWidget);
  });

  testWidgets('the unread count comes from the list and grows with each notification event', (tester) async {
    final engine = FakeEngine()..notifications.addAll([note(2, 'Second'), note(1, 'First', read: true)]);
    await pumpApp(tester, engine);
    expect(find.descendant(of: badge, matching: find.text('1')), findsOneWidget);
    engine.notify(note(3, 'The text reader stopped', severity: NotifySeverity.error));
    await tester.pump();
    expect(find.descendant(of: badge, matching: find.text('2')), findsOneWidget);
    final semantics = tester.ensureSemantics();
    await tester.pump();
    expect(find.bySemanticsLabel('Notifications, 2 unread'), findsOneWidget);
    semantics.dispose();
  });

  testWidgets('the panel lists title, text, time, severity and the one button', (tester) async {
    final engine = FakeEngine()
      ..notifications.addAll([
        note(
          3,
          'NOBAD Find 0.9.9 is available',
          severity: NotifySeverity.info,
          body: 'You have 0.9.3.',
          action: const NotifyAction('update', 'Update'),
          t: DateTime.now().millisecondsSinceEpoch / 1000 - 300,
        ),
        note(2, 'The text reader stopped', severity: NotifySeverity.error, detail: 'tax 2025.pdf'),
        note(1, 'NOBAD Find restarted its workers', read: true),
      ]);
    await pumpApp(tester, engine);
    await openPanel(tester);
    expect(find.text('NOBAD Find 0.9.9 is available'), findsOneWidget);
    expect(find.text('You have 0.9.3.'), findsOneWidget);
    expect(find.text('5 min ago'), findsOneWidget);
    expect(find.text('tax 2025.pdf'), findsOneWidget); // the engine only sends a name when the setting is on
    expect(find.byWidgetPredicate((w) => w is NbIcon && w.glyph == NbGlyph.error), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is NbIcon && w.glyph == NbGlyph.warning), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is NbIcon && w.glyph == NbGlyph.info), findsOneWidget);
    expect(find.text('Update'), findsOneWidget); // only the one with an action has a button

    // its button opens Settings > About and marks it read
    await tester.tap(find.text('Update'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('notifications_read'));
    expect(engine.notifications.firstWhere((n) => n.id == 3).read, isTrue);
    final nav = AppScope.of(tester.element(bell.first)).nav;
    expect(nav.tab, AppTab.settings);
    expect(nav.page, SettingsPage.about);
    expect(find.text('NOBAD Find 0.9.9 is available'), findsNothing); // the panel closed
  });

  testWidgets('Mark all read clears the count, Clear empties the list', (tester) async {
    final engine = FakeEngine()..notifications.addAll([note(2, 'Second'), note(1, 'First')]);
    await pumpApp(tester, engine);
    await openPanel(tester);
    await tester.tap(find.text('Mark all read'));
    await tester.pumpAndSettle();
    expect(badge, findsNothing);
    expect(engine.notifications.every((n) => n.read), isTrue);
    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('notifications_clear'));
    expect(engine.notifications, isEmpty);
    expect(find.text('Second'), findsNothing);
    expect(find.textContaining('Nothing yet.'), findsOneWidget);
  });

  testWidgets('Escape and a click outside close the panel', (tester) async {
    final engine = FakeEngine()..notifications.add(note(1, 'First'));
    await pumpApp(tester, engine);
    await openPanel(tester);
    expect(find.text('First'), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.text('First'), findsNothing);
    await openPanel(tester);
    await tester.tapAt(const Offset(400, 600));
    await tester.pumpAndSettle();
    expect(find.text('First'), findsNothing);
  });

  testWidgets('with no engine nothing old is shown', (tester) async {
    final engine = FakeEngine()..notifications.add(note(1, 'First'));
    await pumpApp(tester, engine);
    expect(badge, findsOneWidget);
    engine.linkState = Link.offline;
    await tester.pump();
    expect(badge, findsNothing);
  });

  test('times read as plain words', () {
    final now = DateTime.fromMillisecondsSinceEpoch((_now * 1000).round());
    expect(notificationTime(_now - 10, now), 'just now');
    expect(notificationTime(_now - 600, now), '10 min ago');
    expect(notificationTime(_now - 7200, now), '2 h ago');
    expect(notificationTime(_now - 3 * 86400, now), contains(','));
    expect(notificationTime(0, now), '');
  });

  testWidgets('Settings > General has the notification settings; Privacy has file names', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1080, 1400));
    final nav = AppScope.of(tester.element(bell.first)).nav;
    nav.openSettings(SettingsPage.general);
    await tester.pumpAndSettle();
    expect(find.text('Windows notifications'), findsOneWidget);
    expect(find.text('Which ones go to Windows'), findsOneWidget);
    expect(find.text('Warnings and errors'), findsOneWidget); // the default
    expect(find.text('Quiet during games and calls'), findsOneWidget);
    nav.showPage(SettingsPage.privacy);
    await tester.pumpAndSettle();
    expect(find.text('Show file names in notifications'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('Show file names in notifications').last); // its switch
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'notify_show_names': true});
  });
}

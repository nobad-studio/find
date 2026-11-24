import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField;
import 'package:nobad_find/engine/models/settings.dart';
import 'package:nobad_find/features/settings/pages/performance.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> openPerformance(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1180, 2600));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.text('Performance'));
  await tester.pumpAndSettle();
}

const seen = {'welcome_seen': true, 'bg_notice_seen': true};

Finder workersField() => find.byWidgetPredicate((w) => w is NbField && w.label == WorkersSetting.label);

bool workersEditable(WidgetTester tester) =>
    tester.widget<TextField>(find.descendant(of: workersField(), matching: find.byType(TextField))).enabled ?? true;

void main() {
  test('performance_state and reset_safe_defaults as the engine sends them', () {
    final p = PerformanceState.fromJson({
      'goal': 'fast',
      'rows': {
        'workers': {'value': 4, 'auto': 16, 'why': 'Fast uses all 16 threads.', 'options': [], 'note': 'n'},
        'backend_text': {
          'value': 'auto',
          'auto': 'cpu',
          'why': 'w',
          'options': ['auto', 'cpu'],
        },
        'odd': 3,
      },
    });
    expect(p.goal, 'fast');
    expect(p.rows['workers']!.auto, 16);
    expect(p.rows['workers']!.note, 'n');
    expect(p.rows['backend_text']!.options, ['auto', 'cpu']);
    expect(p.rows['odd']!.why, '');
    expect(PerformanceState.fromJson(null).goal, 'balanced');
    final r = ResetResult.fromJson({
      'ok': true,
      'reset': ['performance_goal'],
      'kept': ['index'],
    });
    expect(r.ok, isTrue);
    expect(r.reset, ['performance_goal']);
    expect(r.kept, ['index']);
  });

  testWidgets('under Fast the workers field is disabled and says why; Balanced shows what auto picks', (tester) async {
    final engine = FakeEngine(settings: const {...seen, 'performance_goal': 'fast', 'power': 'boost', 'workers': 4});
    await openPerformance(tester, engine);
    expect(workersField(), findsOneWidget);
    expect(workersEditable(tester), isFalse);
    expect(find.text(WorkersSetting.fastReason), findsOneWidget);
    // the goal back to Balanced: the number is used again, with what auto would pick now and why
    await tester.tap(find.text('Fast: every thread'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Balanced (recommended)').last);
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'performance_goal': 'balanced'});
    expect(workersEditable(tester), isTrue);
    expect(find.text(WorkersSetting.fastReason), findsNothing);
    expect(
      find.text("Auto now: 15. 15 while you're away and 8 while you use the PC, from 16 threads."),
      findsOneWidget,
    );
    // every override row says what auto would pick now (built-in graphics: no graphics-memory reserve row)
    expect(find.textContaining('Auto now: '), findsNWidgets(10));
  });

  testWidgets('Reset to safe defaults asks once, then resets the goal and the overrides', (tester) async {
    final engine = FakeEngine(
      settings: const {
        ...seen,
        'performance_goal': 'quiet',
        'gpu_background': 'on',
        'workers': 5,
        'photo_meaning': true,
      },
    );
    await openPerformance(tester, engine);
    await tester.ensureVisible(find.text('Reset'));
    await tester.pumpAndSettle();
    // No: nothing is reset
    await tester.tap(find.text('Reset'));
    await tester.pumpAndSettle();
    expect(find.text('Put the goal and every choice on this page back to the safe defaults?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(engine.calls, isNot(contains('reset_safe_defaults')));
    // Yes: one question, then applied at once
    await tester.tap(find.text('Reset'));
    await tester.pumpAndSettle();
    expect(find.text('Put the goal and every choice on this page back to the safe defaults?'), findsOneWidget);
    expect(find.text('Reset'), findsNWidgets(2)); // the row's button and the dialog's yes
    await tester.tap(find.text('Reset').last);
    await tester.pumpAndSettle();
    expect(find.text('Put the goal and every choice on this page back to the safe defaults?'), findsNothing);
    expect(engine.calls.where((c) => c == 'reset_safe_defaults'), hasLength(1));
    final s = await engine.getSettings();
    expect((s.text('performance_goal'), s.text('gpu_background'), s.number('workers')), ('balanced', 'auto', 0));
    expect(s.flag('photo_meaning'), isTrue); // kept
    expect(find.text('Balanced (recommended)'), findsOneWidget);
  });

  testWidgets('an engine before 1.2.0 still shows the power choice and no overrides', (tester) async {
    final engine = FakeEngine()..old = true;
    await openPerformance(tester, engine);
    expect(find.text('How hard NOBAD Find works'), findsOneWidget);
    expect(find.text('Your choices'), findsNothing);
    expect(workersEditable(tester), isTrue);
  });
}

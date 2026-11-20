// 0.9.1: Windows settings and apps the question fits show above the results; Enter opens the first one when the
// question asks to open something, and a file otherwise.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/features/search/actions_block.dart';

import '../support/fake_engine.dart';

const bt = SearchAction(id: 'set:bluetooth', kind: 'setting', title: 'Bluetooth & devices', subtitle: 'Windows Settings');
const chrome = SearchAction(id: 'app:0:google-chrome', kind: 'app', title: 'Google Chrome', subtitle: 'Google LLC');

void main() {
  test('what asks to open something', () {
    expect(wantsLaunch('open bluetooth'), isTrue);
    expect(wantsLaunch('turn off wifi'), isTrue);
    expect(wantsLaunch('display settings'), isTrue);
    expect(wantsLaunch('bluetooth'), isFalse);
    expect(wantsLaunch('tax pdf'), isFalse);
    expect(SearchAnswer.fromJson({'results': [], 'actions': [{'id': 'set:x', 'kind': 'setting', 'title': 'X', 'subtitle': ''}, {'kind': 'app'}]}).actions.single.id, 'set:x');
  });

  testWidgets('"open bluetooth": the setting shows, Enter opens it', (tester) async {
    final engine = FakeEngine()..searchActions = const [bt];
    await pumpApp(tester, engine);
    await type(tester, 'open bluetooth');
    await tester.pumpAndSettle();
    expect(find.byType(ActionsBlock), findsOneWidget);
    expect(find.text('Bluetooth & devices'), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(engine.actionsRun, ['set:bluetooth']);
  });

  testWidgets('"chrome" without open: the app shows and its Open button runs it, Enter still opens a file',
      (tester) async {
    final engine = FakeEngine()..searchActions = const [chrome];
    await pumpApp(tester, engine);
    await type(tester, 'chrome');
    await tester.pumpAndSettle();
    expect(find.text('Google Chrome'), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(engine.actionsRun, isEmpty);
    await tester.tap(find.text('Open  ↵'));
    await tester.pumpAndSettle();
    expect(engine.actionsRun, ['app:0:google-chrome']);
  });
}

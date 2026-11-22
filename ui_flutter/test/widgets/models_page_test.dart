import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/engine_api.dart' show RpcException;
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/models_info.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> openModels(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1180, 1400));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.textContaining('Models').last);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('every model with its facts, the recommended tier, and text models grouped by language', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    expect(find.text('Recommended for this PC: Balanced'), findsOneWidget);
    expect(find.text('multilingual-e5-small'), findsOneWidget);
    expect(find.text('LaBSE'), findsOneWidget);
    expect(find.text('SigLIP 2 base'), findsOneWidget);
    expect(find.text('MANY LANGUAGES'), findsOneWidget);
    expect(find.text('HINDI + ENGLISH'), findsOneWidget);
    expect(find.text('Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)'), findsWidgets);
    expect(find.text('80% right in the top 5'), findsOneWidget); // the measured quality, as a chip
  });

  testWidgets('the language focus changes the recommendation only', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    await tester.tap(find.text('English first'));
    await tester.pumpAndSettle();
    expect(engine.modelsInfo.languageFocus, LanguageFocus.english);
    expect(engine.modelsInfo.models.firstWhere((m) => m.recommended && m.feature == 'text').id, 'bge-small-en-v1.5');
    expect(
      engine.modelsInfo.models.firstWhere((m) => m.feature == 'text' && m.state == ModelUseState.active).id,
      'minilm-l6-v2',
    );
  });

  testWidgets('a download asks first; "Not now" downloads nothing, "Download" sends the consent', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final button = find.text('Download…').first;
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.textContaining('Download multilingual-e5-small?'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(
      engine.modelsInfo.models.firstWhere((m) => m.id == 'multilingual-e5-small').state,
      ModelUseState.notDownloaded,
    );
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    expect(
      engine.modelsInfo.models.firstWhere((m) => m.id == 'multilingual-e5-small').state,
      ModelUseState.downloading,
    );
  });

  testWidgets('an older engine: says so, and offers the older downloads', (tester) async {
    final engine = FakeEngine()..old = true;
    await openModels(tester, engine);
    expect(find.textContaining('needs a newer engine'), findsOneWidget);
    expect(find.text('Allow the one-time model download'), findsOneWidget);
    expect(find.text('multilingual-e5-small'), findsNothing);
  });

  testWidgets('0.9.0: Details show where a model is downloaded, and Open folder asks the engine to open it', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    const folder = r'C:\Users\me\AppData\Local\NOBAD\Find\photo-model';
    expect(find.text(folder), findsNothing); // folded away until Details
    final card = find.ancestor(
      of: find.text('SigLIP base'),
      matching: find.byWidgetPredicate((w) => '${w.runtimeType}' == '_ModelRow'),
    );
    final details = find.descendant(of: card, matching: find.text('Details'));
    await tester.ensureVisible(details);
    await tester.tap(details);
    await tester.pumpAndSettle();
    expect(find.text(folder), findsOneWidget);
    expect(find.textContaining('SHA-256 are checked before use'), findsWidgets);
    await tester.tap(find.text('Open folder'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('model_folder'));
  });

  testWidgets('0.9.0: Keep models loaded is a switch, off by default', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final sw = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Keep models loaded');
    expect((tester.widget(sw) as NbSwitch).value, isFalse);
    await tester.ensureVisible(sw);
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'models_stay_loaded': true});
  });

  testWidgets('2026-11-21: Your PC shows what is free right now, and a model that does not fit now says why', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    expect(engine.calls, contains('capability_state'));
    expect(find.text('Right now'), findsOneWidget);
    expect(find.text('2.1 GB'), findsOneWidget); // 2.2 GB free on the 15.7 GB demo PC
    expect(find.text('Memory free of 15.7 GB, 1.5 GB kept for Windows'), findsOneWidget);
    expect(find.text('Graphics memory free (shared with the PC)'), findsOneWidget); // Intel iGPU
    expect(find.text('4 of 7'), findsOneWidget);
    // multilingual-e5-small fits the installed PC, but not the memory free now
    expect(find.textContaining('Not now: it needs about 544 MB'), findsWidgets);
  });

  testWidgets('2026-11-21: the live part follows the status beat (not every beat)', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    engine.capability = const CapabilityState(
      canRun: {'gte-small': true},
      budget: CapabilityBudget(live: true, freeMb: 9000, reserveMb: 1500),
    );
    for (var i = 0; i < 2; i++) {
      engine.emit(const StatusEvent(EngineStatus(level: 'gentle', reason: 'Gentle: ok')));
      await tester.pumpAndSettle();
    }
    expect(find.text('8.8 GB'), findsNothing); // not on every beat
    engine.emit(const StatusEvent(EngineStatus(level: 'gentle', reason: 'Gentle: ok')));
    await tester.pumpAndSettle();
    expect(find.text('8.8 GB'), findsOneWidget);
  });

  testWidgets('2026-11-21: an older engine (no capability_state): the page works, without the live part', (
    tester,
  ) async {
    await openModels(tester, _NoCapability());
    expect(find.text('Recommended for this PC: Balanced'), findsOneWidget);
    expect(find.text('Right now'), findsNothing);
  });
}

class _NoCapability extends FakeEngine {
  @override
  Future<CapabilityState> capabilityState() =>
      Future.error(const RpcException(-32601, "This version of NOBAD Find's engine can't do that yet."));
}

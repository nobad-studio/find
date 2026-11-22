import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/models_info.dart';
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

  Finder card(String name) => find.ancestor(
    of: find.text(name),
    matching: find.byWidgetPredicate((w) => '${w.runtimeType}' == '_ModelRow'),
  );

  testWidgets('1.1: Talk about photos lists SmolVLM2, Qwen and the runtimes; Qwen says why it may not run', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    expect(find.text('Talk about photos'), findsOneWidget);
    expect(find.text('SmolVLM2 500M'), findsOneWidget);
    expect(find.text('Qwen3-VL 2B'), findsOneWidget);
    expect(find.text('llama.cpp runtime (graphics card)'), findsOneWidget);
    expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('520 MB download')), findsOneWidget);
    expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('665 MB graphics memory')), findsOneWidget);
    const why = 'Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)';
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.text(why)), findsOneWidget);
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.text('Download anyway…')), findsOneWidget);
    expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text(why)), findsNothing);
    expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('Use')), findsNothing); // no Use
  });

  testWidgets('1.1: a talk model download asks ONE consent naming the model and its runtime, then fetches both', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final button = find.descendant(of: card('SmolVLM2 500M'), matching: find.text('Download…'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.text('Download SmolVLM2 500M?'), findsOneWidget);
    expect(find.text('SmolVLM2 500M: 520 MB from huggingface.co'), findsOneWidget);
    expect(find.textContaining('llama.cpp runtime (graphics card): 37 MB from github.com'), findsOneWidget);
    expect(find.textContaining('githubusercontent.com'), findsOneWidget);
    expect(find.text('557 MB, once'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(engine.calls, isNot(contains('model_download')));
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    final state = {for (final m in engine.modelsInfo.models) m.id: m.state};
    expect(state['smolvlm2-500m'], ModelUseState.downloading);
    expect(state['llama-vulkan'], ModelUseState.downloading);
    expect(state['llama-cpu'], ModelUseState.notDownloaded); // only the runtime this PC uses
  });

  testWidgets('1.1: a downloaded talk model or runtime has Remove', (tester) async {
    final engine = FakeEngine();
    engine.modelsInfo = ModelsInfo(
      pc: engine.modelsInfo.pc,
      tierRecommended: engine.modelsInfo.tierRecommended,
      tierCurrent: engine.modelsInfo.tierCurrent,
      languageFocus: engine.modelsInfo.languageFocus,
      models: [
        for (final m in engine.modelsInfo.models)
          m.feature == 'talk' || m.feature == 'runtime' ? m.withState(ModelUseState.ready) : m,
      ],
    );
    await openModels(tester, engine);
    final remove = find.descendant(of: card('llama.cpp runtime (CPU)'), matching: find.text('Remove'));
    await tester.ensureVisible(remove);
    await tester.tap(remove);
    await tester.pumpAndSettle();
    expect(engine.calls, contains('model_remove'));
    expect(engine.modelsInfo.models.firstWhere((m) => m.id == 'llama-cpu').state, ModelUseState.notDownloaded);
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
}

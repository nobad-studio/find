import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/engine_api.dart' show RpcException;
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/models_info.dart';
import 'package:nobad_find/engine/models/setup_offer.dart' show SetupCost;
import 'package:nobad_find/features/settings/model_cost_dialog.dart';
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

  Finder card(String name) => find.ancestor(
    of: find.text(name),
    matching: find.byWidgetPredicate((w) => '${w.runtimeType}' == '_ModelRow'),
  );

  testWidgets('1.1: Talking about a photo lists SmolVLM2, Qwen and the runtimes; Qwen says why it may not run', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    expect(find.text('Talking about a photo'), findsOneWidget);
    expect(find.text('SmolVLM2 500M'), findsOneWidget);
    expect(find.text('Qwen3-VL 2B'), findsOneWidget);
    // the reference PC's built-in graphics run the Vulkan runtime: said so, not as a graphics card
    expect(find.text('llama.cpp runtime (built-in graphics, Vulkan)'), findsOneWidget);
    expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('520 MB download')), findsOneWidget);
    expect(
      find.descendant(of: card('SmolVLM2 500M'), matching: find.text('665 MB shared memory (counts as memory)')),
      findsOneWidget,
    );
    const why = 'Needs 16 GB of memory and 8 cores, or a graphics card with 2.1 GB of its own memory';
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.textContaining('DirectML')), findsNothing);
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.text(why)), findsOneWidget);
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.text('See cost…')), findsOneWidget); // above the suggestion
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
    // built-in graphics (the fake's Iris Xe): named for them, never "graphics card" (D2)
    expect(find.textContaining('llama.cpp runtime (built-in graphics, Vulkan): 37 MB from github.com'), findsOneWidget);
    expect(find.textContaining('(graphics card)'), findsNothing);
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

  testWidgets('1.1: a runtime downloaded on its own names github.com and *.githubusercontent.com', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final button = find.descendant(of: card('llama.cpp runtime (CPU)'), matching: find.text('Download…'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.text('Download the llama.cpp runtime (CPU)?'), findsOneWidget);
    expect(
      find.text('llama.cpp runtime (CPU): 24 MB from github.com (llama.cpp releases, delivered by *.githubusercontent.com)'),
      findsOneWidget,
    );
    expect(find.textContaining('Pinned release'), findsOneWidget);
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    expect(engine.modelsInfo.models.firstWhere((m) => m.id == 'llama-cpu').state, ModelUseState.downloading);
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

  _suggestionTests();
}

/// The demo catalogue with [f] applied to model [id].
void changeModel(FakeEngine engine, String id, ModelInfo Function(ModelInfo) f) {
  engine.modelsInfo = ModelsInfo(
    pc: engine.modelsInfo.pc,
    tierRecommended: engine.modelsInfo.tierRecommended,
    tierCurrent: engine.modelsInfo.tierCurrent,
    languageFocus: engine.modelsInfo.languageFocus,
    models: [for (final m in engine.modelsInfo.models) m.id == id ? f(m) : m],
  );
}

ModelInfo asOutcome(ModelInfo m, String outcome, {String? why, bool? chosen, ModelUseState? state}) => ModelInfo(
  id: m.id,
  feature: m.feature,
  name: m.name,
  tier: m.tier,
  licence: m.licence,
  source: m.source,
  sizeMb: m.sizeMb,
  ramMb: m.ramMb,
  vramMb: m.vramMb,
  runtime: m.runtime,
  languages: m.languages,
  improves: m.improves,
  state: state ?? m.state,
  recommended: m.recommended,
  outcome: outcome,
  why: why ?? m.why,
  backend: m.backend,
  cost: m.cost,
  chosen: chosen ?? m.chosen,
  vectorsChange: m.vectorsChange,
);

void _suggestionTests() {
  Finder card(String name) => find.ancestor(
    of: find.text(name),
    matching: find.byWidgetPredicate((w) => '${w.runtimeType}' == '_ModelRow'),
  );

  testWidgets('1.2: each workload is its own group and its models sit under the outcomes the floors gave them', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    for (final t in ['Meaning search', 'Searching photos', 'Talking about a photo']) {
      expect(find.text(t), findsOneWidget);
    }
    expect(find.text('Suggested for this PC'), findsOneWidget); // the first-run row's label; the headings are caps
    expect(find.text('SUGGESTED FOR THIS PC'), findsNWidgets(2)); // photos, and talking about a photo
    expect(find.text('AVAILABLE UPGRADE'), findsOneWidget); // Qwen3-VL 2B
    expect(find.text('NOT MEASURED ON A PC LIKE THIS ONE'), findsOneWidget); // SigLIP base
    // the suggested badge and the measured sentence, without the outcome's label twice
    expect(find.descendant(of: card('SigLIP 2 base'), matching: find.text('Suggested')), findsOneWidget);
    expect(
      find.descendant(
        of: card('SigLIP 2 base'),
        matching: find.text(
          'a search takes about 196 ms, it indexes 1.42 photos a second, 621 MB of memory (measured on a similar PC)',
        ),
      ),
      findsOneWidget,
    );
    expect(find.descendant(of: card('Qwen3-VL 2B'), matching: find.text('Above the suggestion')), findsOneWidget);
    expect(find.descendant(of: card('SigLIP base'), matching: find.text('Not measured')), findsOneWidget);
    // text has no floor yet: a tag, not a sentence per model
    expect(find.textContaining('not measured against a floor yet'), findsNothing);
  });

  testWidgets('1.2: an upgrade shows this PC\'s measured cost first, and Not now chooses nothing', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final see = find.descendant(of: card('Qwen3-VL 2B'), matching: find.text('See cost…'));
    await tester.ensureVisible(see);
    await tester.tap(see);
    await tester.pumpAndSettle();
    expect(find.text('Choose Qwen3-VL 2B?'), findsOneWidget);
    expect(find.textContaining('above what is suggested for this PC'), findsOneWidget);
    // only measured figures, on the runtime this PC uses, from a similar PC and said so
    expect(find.text('on a similar PC, on llama.cpp runtime (built-in graphics, Vulkan)'), findsOneWidget);
    expect(find.text('about 6.21 s'), findsOneWidget); // loading
    expect(find.text('the first word in about 12 s'), findsOneWidget);
    expect(find.textContaining('2,491 MB (2,058 MB of it is the built-in graphics'), findsOneWidget);
    expect(find.textContaining('were measured on a similar PC, not on this PC'), findsOneWidget);
    expect(find.textContaining('estimate'), findsNothing);
    expect(find.text('Choose Qwen3-VL 2B'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(engine.calls, isNot(contains('model_download')));
    expect(engine.modelUses, isEmpty);
    // Choose goes on to the download's own consent (the talk model and its runtime)
    await tester.tap(see);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Choose Qwen3-VL 2B'));
    await tester.pumpAndSettle();
    expect(find.text('Download Qwen3-VL 2B?'), findsOneWidget);
  });

  testWidgets('1.2: an upgrade for photos: the cost screen shows the time to look at the photos again; the choice '
      'keeps a note with the cost', (tester) async {
    final engine = FakeEngine();
    changeModel(engine, 'siglip-base', (m) => ModelInfo(
      id: m.id, feature: m.feature, name: m.name, tier: m.tier, licence: m.licence, source: m.source, sizeMb: m.sizeMb,
      languages: m.languages, improves: m.improves, state: m.state, outcome: 'upgrade', why: m.why, backend: 'cpu',
      cost: const SetupCost(ramMb: 600, itemsS: .9, queryMs: 420, indexH: .38, measuredOn: 'similar PC'),
      vectorsChange: true,
    ));
    await openModels(tester, engine);
    expect(find.text('AVAILABLE UPGRADE'), findsNWidgets(2));
    final see = find.descendant(of: card('SigLIP base'), matching: find.text('See cost…'));
    await tester.ensureVisible(see);
    await tester.tap(see);
    await tester.pumpAndSettle();
    expect(find.text('Choose SigLIP base?'), findsOneWidget);
    expect(find.text('on a similar PC, on the processor'), findsOneWidget);
    expect(find.text('a search takes about 420 ms'), findsOneWidget);
    expect(find.text('0.9 photos a second'), findsOneWidget);
    expect(find.textContaining('about 23 min (on a similar PC)'), findsOneWidget); // 0.38 h
    expect(find.textContaining('keep answering until the new ones are done'), findsOneWidget);
    await tester.tap(find.text('Choose SigLIP base'));
    await tester.pumpAndSettle();
    expect(engine.modelUses, [('siglip-base', true)]); // chosen after the cost screen
    final note = find.descendant(
      of: card('SigLIP base'),
      matching: find.textContaining('Above what is suggested for this PC: a search takes about 420 ms'),
    );
    expect(note, findsOneWidget);
    expect(find.textContaining('peak memory 600 MB (measured on a similar PC)'), findsOneWidget);
    // chosen already: no second cost screen
    expect(find.descendant(of: card('SigLIP base'), matching: find.text('See cost…')), findsNothing);
  });

  testWidgets('1.2: a model not recommended says why, and needs Use anyway after the same screen', (tester) async {
    final engine = FakeEngine();
    changeModel(
      engine,
      'qwen3vl-2b',
      (m) => asOutcome(
        m,
        'not_recommended',
        why: 'Not recommended: Qwen3-VL 2B: needs about 9,000 MB of memory; this PC can give it 3,900 MB',
      ),
    );
    await openModels(tester, engine);
    expect(find.text('NOT RECOMMENDED'), findsOneWidget);
    expect(
      find.descendant(
        of: card('Qwen3-VL 2B'),
        matching: find.text('needs about 9,000 MB of memory; this PC can give it 3,900 MB'),
      ),
      findsOneWidget,
    );
    final see = find.descendant(of: card('Qwen3-VL 2B'), matching: find.text('See cost…'));
    await tester.ensureVisible(see);
    await tester.tap(see);
    await tester.pumpAndSettle();
    expect(find.text('Use Qwen3-VL 2B anyway?'), findsOneWidget);
    expect(find.textContaining("doesn't recommend this one for this PC"), findsOneWidget);
    expect(find.text('Choose Qwen3-VL 2B'), findsNothing);
    await tester.tap(find.text('Use anyway'));
    await tester.pumpAndSettle();
    expect(find.text('Download Qwen3-VL 2B?'), findsOneWidget);
  });

  testWidgets('1.2: Reset to suggested asks first and shows the re-index time; Not now changes nothing', (
    tester,
  ) async {
    final engine = FakeEngine();
    changeModel(engine, 'siglip-base', (m) => asOutcome(m, m.outcome, chosen: true, state: ModelUseState.active));
    changeModel(engine, 'minilm-l6-v2', (m) => asOutcome(m, m.outcome, chosen: false, state: ModelUseState.ready));
    changeModel(engine, 'multilingual-e5-small', (m) => asOutcome(m, m.outcome, chosen: true, state: ModelUseState.active));
    await openModels(tester, engine);
    final reset = find.text('Reset to suggested');
    await tester.ensureVisible(reset);
    await tester.tap(reset);
    await tester.pumpAndSettle();
    expect(find.text('Back to the suggested models?'), findsOneWidget);
    expect(find.text('Photos by what is in them: SigLIP base to SigLIP 2 base'), findsOneWidget);
    expect(find.textContaining('Looking at your photos again takes about 14 min (measured on a similar PC)'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(engine.resets, [false]); // asked, nothing applied
    expect(engine.modelsInfo.byId('siglip-base')!.chosen, isTrue);
    await tester.tap(reset);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Reset'));
    await tester.pumpAndSettle();
    expect(engine.resets, [false, false, true]);
    expect(engine.modelsInfo.byId('siglip2-base')!.chosen, isTrue);
    expect(engine.modelsInfo.byId('siglip-base')!.chosen, isFalse);
    // the new model is not on this PC yet: the usual download consent comes next
    expect(find.text('Download SigLIP 2 base?'), findsOneWidget);
  });

  testWidgets('1.2: Reset to suggested with nothing to change says so', (tester) async {
    final engine = FakeEngine();
    changeModel(engine, 'minilm-l6-v2', (m) => asOutcome(m, m.outcome, chosen: false, state: ModelUseState.ready));
    changeModel(engine, 'multilingual-e5-small', (m) => asOutcome(m, m.outcome, chosen: true, state: ModelUseState.active));
    await openModels(tester, engine);
    final reset = find.text('Reset to suggested');
    await tester.ensureVisible(reset);
    await tester.tap(reset);
    await tester.pumpAndSettle();
    expect(find.text('Back to the suggested models?'), findsNothing);
    expect(find.text('Already on the suggested models.'), findsOneWidget);
  });

  test('1.2: whyText drops the outcome label, indexTime says how long', () {
    ModelInfo w(String why) => ModelInfo(id: 'x', why: why);
    expect(whyText(w('Upgrade: Qwen3-VL 2B: more memory (2,491 MB)')), 'more memory (2,491 MB)');
    expect(whyText(w('Lighter option: SigLIP base: finds less than SigLIP 2 base (nDCG@10 0.70 against 0.81)')),
        'finds less than SigLIP 2 base (nDCG@10 0.70 against 0.81)');
    expect(whyText(w('Not measured: SigLIP base: not measured on a PC like this one yet')),
        'not measured on a PC like this one yet');
    expect(whyText(w('something else')), 'something else');
    expect(indexTime(0.0), 'under a minute');
    expect(indexTime(0.24), 'about 14 min');
    expect(indexTime(2.25), 'about 2 h 15 min');
    expect(indexTime(3.0), 'about 3 h');
    expect(indexTime(72), 'about 3 days');
  });

  test('1.2: nothing measured: no figures at all (never a generic estimate)', () {
    expect(costFacts(const ModelInfo(id: 'x', feature: 'photo', outcome: 'upgrade'), const ModelsInfo()), isEmpty);
    expect(costLine(const ModelInfo(id: 'x', outcome: 'upgrade')), 'Nothing was measured for it on a PC like this one.');
  });
}

class _NoCapability extends FakeEngine {
  @override
  Future<CapabilityState> capabilityState() =>
      Future.error(const RpcException(-32601, "This version of NOBAD Find's engine can't do that yet."));
}

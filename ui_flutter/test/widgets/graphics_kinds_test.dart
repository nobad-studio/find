// Task D2: graphics-card options only when there is a card; built-in graphics said plainly. The same pages on a
// hybrid laptop with a graphics card, on Iris Xe only and on a PC without any adapter, and a choice the user made
// for a backend this PC no longer has.
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/engine/models/graphics.dart';
import 'package:nobad_find/engine/models/models_info.dart';
import 'package:nobad_find/engine/models/settings.dart';
import 'package:nobad_find/features/settings/pages/performance.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

const seen = {'welcome_seen': true, 'bg_notice_seen': true};
const rtx = 'NVIDIA GeForce RTX 3060 Laptop GPU';
const iris = 'Intel(R) Iris(R) Xe Graphics';
const notHere = 'Not on this PC now: NOBAD Find uses the processor.';

Future<void> openPage(WidgetTester tester, FakeEngine engine, SettingsPage page) async {
  await pumpApp(tester, engine, size: const Size(1180, 2600));
  await tester.pumpAndSettle();
  AppScope.of(tester.element(find.byType(Text).first)).nav.openSettings(page);
  await tester.pumpAndSettle();
}

/// The values a choice offers, by its label.
List<String> optionsOf(WidgetTester tester, String label) => [
  for (final (v, _)
      in tester.widget<NbSelect>(find.byWidgetPredicate((w) => w is NbSelect && w.label == label)).options)
    v,
];

/// [kind]'s made-up PC with other backends installed.
Hardware withBackends(GraphicsKind kind, {required List<String> onnx, List<String>? llama}) {
  final h = fakeHardware(kind);
  return Hardware(
    ramGb: h.ramGb,
    cores: h.cores,
    threads: h.threads,
    avx2: h.avx2,
    gpu: h.gpu,
    vramGb: h.vramGb,
    directml: onnx.contains('directml'),
    diskFreeGb: h.diskFreeGb,
    ssd: h.ssd,
    gpus: h.gpus,
    onnxBackends: onnx,
    llamacppBackends: llama ?? h.llamacppBackends,
  );
}

Finder card(String name) =>
    find.ancestor(of: find.text(name), matching: find.byWidgetPredicate((w) => '${w.runtimeType}' == '_ModelRow'));

void main() {
  setUpAll(loadWindowsFonts);

  group('Welcome: the Your PC graphics tile, and the whole column still fits the main window', () {
    for (final (kind, title, detail) in [
      (GraphicsKind.discrete, rtx, '6 GB video memory'),
      (GraphicsKind.integrated, iris, 'Built-in graphics, shares memory'),
      (GraphicsKind.none, 'No graphics card', 'Processor only'),
    ]) {
      testWidgets(kind.name, (tester) async {
        await pumpApp(
          tester,
          FakeEngine(gpu: kind, settings: const {'welcome_seen': false, 'bg_notice_seen': true}),
          size: const Size(1180, 760),
        );
        await tester.pumpAndSettle();
        expect(find.text(title), findsOneWidget);
        expect(find.text(detail), findsOneWidget);
        expect(find.textContaining('video memory'), kind == GraphicsKind.discrete ? findsOneWidget : findsNothing);
        for (final t in [title, detail]) {
          expect((tester.renderObject(find.text(t)) as RenderParagraph).didExceedMaxLines, isFalse, reason: t);
        }
        expect(tester.getBottomLeft(find.text('Software with a point of view.')).dy, lessThanOrEqualTo(760 - 16));
      });
    }
  });

  group('Settings > Performance', () {
    testWidgets('a graphics card: every graphics row, the backends it has, no built-in line', (tester) async {
      await openPage(tester, FakeEngine(gpu: GraphicsKind.discrete, settings: seen), SettingsPage.performance);
      expect(find.text('Graphics card for background work'), findsOneWidget);
      expect(find.text('Plan the graphics card as'), findsOneWidget);
      expect(find.text(OverridesGroup.reserveLabel), findsOneWidget);
      expect(find.byKey(OverridesGroup.graphicsLineKey), findsNothing);
      expect(optionsOf(tester, 'Meaning for documents runs on'), ['auto', 'cpu', 'directml']);
      expect(optionsOf(tester, 'Talk about a photo runs on'), ['auto', 'vulkan', 'cpu']);
    });

    testWidgets('built-in graphics: one plain line, no graphics-memory reserve, Vulkan kept', (tester) async {
      await openPage(tester, FakeEngine(settings: seen), SettingsPage.performance);
      expect(
        find.text("Built-in graphics ($iris): it shares your PC's memory, so NOBAD Find counts its use as memory."),
        findsOneWidget,
      );
      expect(find.text(OverridesGroup.reserveLabel), findsNothing);
      expect(find.text('Built-in graphics for background work'), findsOneWidget);
      expect(find.text('Graphics card for background work'), findsNothing);
      expect(find.text('Plan the built-in graphics as'), findsOneWidget);
      expect(optionsOf(tester, 'Talk about a photo runs on'), contains('vulkan')); // works on built-in graphics
      expect(find.textContaining('video memory'), findsNothing);
    });

    testWidgets('built-in graphics without DirectML installed: no DirectML or CUDA choice', (tester) async {
      final engine = FakeEngine(settings: seen);
      engine.pc = withBackends(GraphicsKind.integrated, onnx: ['cpu']);
      await openPage(tester, engine, SettingsPage.performance);
      expect(optionsOf(tester, 'Meaning for documents runs on'), ['auto', 'cpu']);
      expect(optionsOf(tester, 'Photos run on'), ['auto', 'cpu']);
    });

    testWidgets('no graphics adapter: no graphics rows, one line, processor-only backends', (tester) async {
      final engine = FakeEngine(gpu: GraphicsKind.none, settings: seen);
      // DirectML and the Vulkan runtime may be on disk with no adapter to use them: still not offered
      engine.pc = withBackends(GraphicsKind.none, onnx: ['cpu', 'directml'], llama: ['vulkan', 'cpu']);
      await openPage(tester, engine, SettingsPage.performance);
      expect(find.text('No graphics card: everything runs on the processor.'), findsOneWidget);
      expect(find.text('Graphics card for background work'), findsNothing);
      expect(find.text('Built-in graphics for background work'), findsNothing);
      expect(find.text('Plan the graphics card as'), findsNothing);
      expect(find.text(OverridesGroup.reserveLabel), findsNothing);
      expect(optionsOf(tester, 'Meaning for documents runs on'), ['auto', 'cpu']);
      expect(optionsOf(tester, 'Talk about a photo runs on'), ['auto', 'cpu']);
      expect(find.text(notHere), findsNothing);
    });

    testWidgets('a choice set for hardware that is gone stays, and says what is used instead', (tester) async {
      final engine = FakeEngine(
        gpu: GraphicsKind.none,
        settings: const {
          ...seen,
          'backend_text': 'directml',
          'backend_talk': 'vulkan',
          'gpu_background': 'on',
          'gpu_reserve_min_mb': 1024,
        },
      );
      await openPage(tester, engine, SettingsPage.performance);
      for (final label in [
        'Meaning for documents runs on',
        'Talk about a photo runs on',
        'Graphics card for background work',
      ]) {
        expect(find.text(label), findsOneWidget, reason: label);
      }
      expect(
        tester
            .widget<NbSelect>(
              find.byWidgetPredicate((w) => w is NbSelect && w.label == 'Meaning for documents runs on'),
            )
            .value,
        'directml',
      );
      expect(find.text(notHere), findsNWidgets(3));
      // the engine's own note on the same thing isn't said twice
      expect(find.textContaining("isn't available on this PC now"), findsNothing);
      expect(find.text(OverridesGroup.reserveLabel), findsOneWidget); // the user's own number
      // back to Auto: the row has nothing more to say
      tester
          .widget<NbSelect>(find.byWidgetPredicate((w) => w is NbSelect && w.label == 'Meaning for documents runs on'))
          .onChanged('auto');
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'backend_text': 'auto'});
      expect(find.text(notHere), findsNWidgets(2));
    });
  });

  group('Settings > Models', () {
    testWidgets('a graphics card: its name and video memory; talk models cost video memory', (tester) async {
      await openPage(tester, FakeEngine(gpu: GraphicsKind.discrete, settings: seen), SettingsPage.models);
      expect(find.text(rtx), findsOneWidget);
      expect(find.text('6 GB video memory'), findsOneWidget);
      expect(find.text('Video memory free'), findsOneWidget);
      expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('665 MB video memory')), findsOneWidget);
      expect(find.text('llama.cpp runtime (graphics card)'), findsOneWidget);
    });

    testWidgets('built-in graphics: shared memory that counts as memory, never video memory', (tester) async {
      await openPage(tester, FakeEngine(settings: seen), SettingsPage.models);
      expect(find.text(iris), findsOneWidget);
      expect(find.text('Built-in graphics, shares memory'), findsOneWidget);
      expect(find.text('Graphics memory free (shared with the PC)'), findsOneWidget);
      expect(
        find.descendant(of: card('SmolVLM2 500M'), matching: find.text('665 MB shared memory (counts as memory)')),
        findsOneWidget,
      );
      expect(find.textContaining('video memory'), findsNothing);
      expect(find.text('llama.cpp runtime (graphics card)'), findsOneWidget); // Vulkan works on built-in graphics
    });

    testWidgets('no graphics adapter: processor only, no graphics runtime or graphics memory offered', (tester) async {
      await openPage(tester, FakeEngine(gpu: GraphicsKind.none, settings: seen), SettingsPage.models);
      expect(find.text('No graphics card'), findsOneWidget);
      expect(find.text('Processor only'), findsOneWidget);
      expect(find.textContaining('Graphics memory free'), findsNothing);
      expect(find.text('llama.cpp runtime (graphics card)'), findsNothing);
      expect(find.text('llama.cpp runtime (CPU)'), findsOneWidget);
      expect(find.textContaining('graphics memory'), findsNothing);
      expect(find.textContaining('video memory'), findsNothing);
    });

    testWidgets('no graphics adapter, but the graphics runtime is already downloaded: it stays (to remove)', (
      tester,
    ) async {
      final engine = FakeEngine(gpu: GraphicsKind.none, settings: seen);
      final info = demoModels(gpu: GraphicsKind.none);
      engine.modelsInfo = ModelsInfo(
        pc: info.pc,
        tierRecommended: info.tierRecommended,
        tierCurrent: info.tierCurrent,
        languageFocus: info.languageFocus,
        models: [for (final m in info.models) m.id == 'llama-vulkan' ? m.withState(ModelUseState.ready) : m],
      );
      await openPage(tester, engine, SettingsPage.models);
      expect(find.text('llama.cpp runtime (graphics card)'), findsOneWidget);
      expect(
        find.descendant(of: card('llama.cpp runtime (graphics card)'), matching: find.text('Remove')),
        findsOneWidget,
      );
    });
  });
}

// Task D2: graphics-card options only when there is a card; built-in graphics said plainly. The same pages on a
// hybrid laptop with a graphics card, on Iris Xe only and on a PC without any adapter, and a choice the user made
// for a backend this PC no longer has.
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show Tooltip;
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
const builtInRuntime = 'llama.cpp runtime (built-in graphics, Vulkan)';

/// The fake's performance_state with some rows changed: [drop] left out (not sent yet), [rows] replaced.
class _PerfEngine extends FakeEngine {
  _PerfEngine({super.gpu, super.settings, this.drop = const [], this.rows = const {}});
  final List<String> drop;
  final Map<String, PerformanceRow> rows;

  @override
  Future<PerformanceState> performanceState() async {
    final p = await super.performanceState();
    return PerformanceState(p.goal, {
      for (final e in p.rows.entries)
        if (!drop.contains(e.key)) e.key: rows[e.key] ?? e.value,
    });
  }
}

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
        // the name in at most 2 lines (a long card name ellipsized, all of it in the tooltip); the detail in full
        final name = tester.renderObject(find.text(title)) as RenderParagraph;
        expect(tester.widget<Text>(find.text(title)).maxLines, 2);
        expect(name.didExceedMaxLines, kind == GraphicsKind.discrete, reason: title);
        expect(find.byWidgetPredicate((w) => w is Tooltip && (w.message ?? '').startsWith(title)), findsOneWidget);
        expect((tester.renderObject(find.text(detail)) as RenderParagraph).didExceedMaxLines, isFalse);
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

  group('Settings > Performance: what the page says instead of the engine', () {
    testWidgets("no adapter but DirectML and Vulkan on disk: auto is never named DirectML or Vulkan", (tester) async {
      final engine = FakeEngine(gpu: GraphicsKind.none, settings: const {...seen, 'backend_text': 'directml'});
      // the engine lists DirectML whenever its ONNX Runtime has it, adapter or not, and picks it as auto
      engine.pc = withBackends(GraphicsKind.none, onnx: ['cpu', 'directml'], llama: ['vulkan', 'cpu']);
      await openPage(tester, engine, SettingsPage.performance);
      final perf = await engine.performanceState();
      expect(perf.rows['backend_text']!.auto, 'directml');
      expect(perf.rows['backend_talk']!.auto, 'vulkan');
      expect(find.textContaining('Auto now: DirectML'), findsNothing);
      expect(find.textContaining('Auto now: Vulkan'), findsNothing);
      expect(find.text('Auto now: Processor. This PC has no graphics adapter.'), findsNWidgets(2));
      expect(find.text(notHere), findsOneWidget); // the saved DirectML, said as the processor
      expect(find.textContaining('uses DirectML'), findsNothing);
    });

    testWidgets('while a row has not come yet, no "Not on this PC now"', (tester) async {
      final engine = _PerfEngine(
        gpu: GraphicsKind.none,
        settings: const {...seen, 'backend_text': 'directml'},
        drop: const ['backend_text'],
      );
      await openPage(tester, engine, SettingsPage.performance);
      expect(find.text('Meaning for documents runs on'), findsOneWidget);
      expect(find.textContaining('Not on this PC now'), findsNothing);
    });

    testWidgets('a choice that is not about hardware keeps the engine note', (tester) async {
      const note = 'Not used yet: this version downloads only the lighter build.';
      final engine = _PerfEngine(
        gpu: GraphicsKind.none,
        settings: const {...seen, 'variant_siglip2-base': 'fp32-vision', 'profile_override_cpu': 'efficiency'},
        rows: const {
          // a saved value the engine doesn't offer now
          'variant_siglip2-base': PerformanceRow(
            value: 'fp32-vision',
            auto: 'fp16-vision',
            why: 'w.',
            options: ['auto', 'fp16-vision'],
            note: note,
          ),
        },
      );
      await openPage(tester, engine, SettingsPage.performance);
      expect(find.text(note), findsOneWidget);
      expect(find.textContaining('Not on this PC now'), findsNothing);
    });

    for (final (kind, text) in [
      (GraphicsKind.integrated, OverridesGroup.reserveBuiltIn),
      (GraphicsKind.none, OverridesGroup.reserveNone),
    ]) {
      testWidgets('${kind.name}: the reserve kept with its own number says what it means here', (tester) async {
        await openPage(
          tester,
          FakeEngine(gpu: kind, settings: const {...seen, 'gpu_reserve_min_mb': 1024}),
          SettingsPage.performance,
        );
        expect(find.text(OverridesGroup.reserveLabel), findsOneWidget);
        expect(find.text(text), findsOneWidget);
      });
    }

    testWidgets('a graphics card: the reserve has no such note', (tester) async {
      await openPage(
        tester,
        FakeEngine(gpu: GraphicsKind.discrete, settings: const {...seen, 'gpu_reserve_min_mb': 1024}),
        SettingsPage.performance,
      );
      expect(find.text(OverridesGroup.reserveBuiltIn), findsNothing);
      expect(find.text(OverridesGroup.reserveNone), findsNothing);
    });
  });

  group('Settings > Models', () {
    testWidgets('a graphics card: its name and video memory; talk models cost video memory', (tester) async {
      await openPage(tester, FakeEngine(gpu: GraphicsKind.discrete, settings: seen), SettingsPage.models);
      expect(find.text(rtx), findsOneWidget);
      expect(find.text('6 GB video memory'), findsOneWidget);
      expect(find.text('Video memory free'), findsOneWidget);
      expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('665 MB video memory')), findsOneWidget);
      expect(find.text('llama.cpp runtime (Vulkan)'), findsOneWidget);
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
      // Vulkan works on built-in graphics: offered, and said so, not as a graphics card
      expect(find.text(builtInRuntime), findsOneWidget);
      expect(find.text('Runs the talk models on the built-in graphics (Vulkan)'), findsOneWidget);
      expect(find.descendant(of: card('SmolVLM2 500M'), matching: find.text('Runs on $builtInRuntime')), findsOneWidget);
      expect(find.textContaining('graphics card)'), findsNothing);
      expect(find.textContaining('on the graphics card (Vulkan)'), findsNothing);
    });

    testWidgets('no graphics adapter: processor only, no graphics runtime or graphics memory offered', (tester) async {
      await openPage(tester, FakeEngine(gpu: GraphicsKind.none, settings: seen), SettingsPage.models);
      expect(find.text('No graphics card'), findsOneWidget);
      expect(find.text('Processor only'), findsOneWidget);
      expect(find.textContaining('Graphics memory free'), findsNothing);
      expect(find.text('llama.cpp runtime (Vulkan)'), findsNothing);
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
      expect(find.text('llama.cpp runtime (Vulkan)'), findsOneWidget);
      expect(
        find.descendant(of: card('llama.cpp runtime (Vulkan)'), matching: find.text('Remove')),
        findsOneWidget,
      );
    });
  });
}

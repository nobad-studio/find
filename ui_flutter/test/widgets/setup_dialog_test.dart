// The first-run models window (plan Task 6): after the welcome and the first scan it comes up once; each item
// shows its size, memory and why, and the total; the talk model is offered unticked; Download sends exactly the
// ticked models (the consent goes with them), Later answers it, Details opens Settings > Models. It keeps the
// look: one 32 px icon tile per card with room around it, every card one width, built-in graphics worded so.
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show Tooltip;
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/engine/engine_api.dart' show SetupItem, SetupOffer;
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/graphics.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/features/setup/setup_dialog.dart';
import 'package:nobad_find/widgets/badges.dart';
import 'package:nobad_find/widgets/controls.dart';
import 'package:nobad_find/widgets/icons.dart';

import '../support/fake_engine.dart';

const seen = {'welcome_seen': true, 'bg_notice_seen': true};

/// The app with the window brought up the way the shell does it: the engine says show, a status says the walk is
/// over.
Future<FakeEngine> openSetup(WidgetTester tester, {GraphicsKind gpu = GraphicsKind.integrated}) async {
  final engine = FakeEngine(settings: seen, gpu: gpu)..setupShow = true;
  await pumpApp(tester, engine, size: const Size(1180, 900));
  engine.emit(StatusEvent(EngineStatus(phase: 'text', files: 48210)));
  await tester.pumpAndSettle();
  return engine;
}

NbSwitch tickOf(WidgetTester tester, String name) => tester.widget<NbSwitch>(
  find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Download $name'),
);

void main() {
  setUpAll(loadWindowsFonts);

  testWidgets('it comes up once after the first scan, with each size, memory, why and the total', (tester) async {
    final engine = await openSetup(tester);
    expect(find.byType(SetupDialog), findsOneWidget);
    expect(engine.calls.where((c) => c == 'setup_offer'), hasLength(1));
    expect(find.text('This PC is like: Mid'), findsOneWidget);
    // sizes and memory, as chips
    expect(find.text('481 MB download'), findsOneWidget);
    expect(find.text('621 MB memory'), findsOneWidget);
    expect(find.text('33 MB download'), findsOneWidget);
    expect(find.text('56 MB memory'), findsOneWidget);
    expect(find.text('557 MB download'), findsOneWidget);
    // why, from the engine's measured words
    expect(find.textContaining('Suggested: SigLIP 2 base: a search takes about 196 ms'), findsOneWidget);
    expect(find.textContaining('Not a measured suggestion'), findsOneWidget);
    // a chip says the same number as the engine's sentence (196.5 ms: 196, as the engine rounds)
    expect(find.text('a search in about 196 ms'), findsOneWidget);
    expect(find.text('indexing: about 15 min for 1,240 photos (on a similar PC)'), findsOneWidget);
    // the total of the ticked one, and no download time before one was measured
    expect(find.text('481 MB, once'), findsOneWidget);
    expect(find.textContaining("Known once a download has measured this PC's speed"), findsOneWidget);
    // another status doesn't bring it up again
    engine.emit(StatusEvent(EngineStatus(phase: 'photos', files: 48210)));
    await tester.pumpAndSettle();
    expect(engine.calls.where((c) => c == 'setup_offer'), hasLength(1));
  });

  testWidgets('the talk model is offered unticked; ticking it adds it and its runtime to the total', (tester) async {
    await openSetup(tester);
    expect(tickOf(tester, 'SigLIP 2 base').value, isTrue);
    expect(tickOf(tester, 'GTE small (English)').value, isFalse); // not measured: never ticked for you
    expect(tickOf(tester, 'SmolVLM2 500M').value, isFalse);
    expect(tickOf(tester, 'Qwen3-VL 2B').value, isFalse);
    expect(find.text('More for this PC'), findsOneWidget);
    final tick = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Download SmolVLM2 500M');
    await tester.ensureVisible(tick);
    await tester.tap(tick);
    await tester.pumpAndSettle();
    expect(find.text('${481 + 557} MB, once'), findsOneWidget);
    expect(find.textContaining('github.com (llama.cpp releases'), findsOneWidget);
    // a runtime two talk models share is counted once
    final qwen = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Download Qwen3-VL 2B');
    await tester.ensureVisible(qwen);
    await tester.tap(qwen);
    await tester.pumpAndSettle();
    expect(find.text('${481 + 557 + 1518 - 37} MB, once'), findsOneWidget);
  });

  testWidgets('built-in graphics: the runtime is named for them, never "graphics card" or video memory', (
    tester,
  ) async {
    await openSetup(tester);
    expect(find.textContaining('llama.cpp runtime (built-in graphics, Vulkan)'), findsWidgets);
    expect(find.textContaining('(graphics card)'), findsNothing);
    expect(find.textContaining('video memory'), findsNothing);
    expect(find.textContaining('built-in graphics, shares memory'), findsOneWidget);
    expect(find.text('663 MB of it shared with the built-in graphics'), findsOneWidget);
  });

  testWidgets('Download sends exactly the ticked models, then shows Close', (tester) async {
    final engine = await openSetup(tester);
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    expect(engine.setupAccepted, [
      ['siglip2-base'],
    ]);
    expect(engine.calls, isNot(contains('setup_later')));
    expect(find.text('Close'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.byType(SetupDialog), findsNothing);
    expect(engine.calls, isNot(contains('setup_later')));
  });

  testWidgets('Later answers it and nothing is downloaded', (tester) async {
    final engine = await openSetup(tester);
    await tester.tap(find.text('Later'));
    await tester.pumpAndSettle();
    expect(find.byType(SetupDialog), findsNothing);
    expect(engine.calls, contains('setup_later'));
    expect(engine.setupAccepted, isEmpty);
    expect(engine.calls, isNot(contains('model_download')));
  });

  testWidgets('Details opens Settings > Models, where it can be shown again', (tester) async {
    final engine = await openSetup(tester);
    await tester.tap(find.descendant(of: find.byType(SetupDialog), matching: find.text('Details')));
    await tester.pumpAndSettle();
    expect(find.byType(SetupDialog), findsNothing);
    final nav = AppScope.of(tester.element(find.byType(Text).first)).nav;
    expect((nav.tab, nav.page), (AppTab.settings, SettingsPage.models));
    expect(engine.calls, isNot(contains('setup_later')));
    final show = find.text('Show');
    await tester.ensureVisible(show);
    await tester.tap(show);
    await tester.pumpAndSettle();
    expect(find.byType(SetupDialog), findsOneWidget);
  });

  testWidgets('a failed download says why and can be tried again', (tester) async {
    final engine = await openSetup(tester);
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    engine.emit(const DownloadEvent(id: 'siglip2-base', state: 'missing', error: 'No internet connection'));
    await tester.pumpAndSettle();
    expect(find.text("Didn't download: No internet connection"), findsOneWidget);
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(engine.setupAccepted, [
      ['siglip2-base'],
      ['siglip2-base'],
    ]);
  });

  testWidgets('every icon tile is one 32 px size with at least 12 px of room, every card one width', (tester) async {
    await openSetup(tester);
    final dialog = find.byType(SetupDialog);
    final tiles = find.descendant(of: dialog, matching: find.byType(GlyphTile));
    expect(tiles, findsNWidgets(5)); // this PC and four models
    final cards = find.descendant(of: dialog, matching: find.byType(NbCard));
    final widths = <double>{};
    for (final e in cards.evaluate()) {
      widths.add(tester.getSize(find.byWidget(e.widget)).width.roundToDouble());
    }
    expect(widths, hasLength(1), reason: 'every card one width');
    for (final e in tiles.evaluate()) {
      final f = find.byWidget(e.widget);
      final r = tester.getRect(f);
      expect(r.size, const Size(GlyphTile.size, GlyphTile.size));
      // NbCard draws its box inside its own outer padding: the box is the card's first Container
      final card = find.ancestor(of: f, matching: find.byType(NbCard)).first;
      final box = tester.getRect(find.descendant(of: card, matching: find.byType(Container)).first);
      expect(r.left - box.left, greaterThanOrEqualTo(12 - .5));
      expect(r.top - box.top, greaterThanOrEqualTo(12 - .5));
    }
  });

  testWidgets('a long why ellipsizes with the whole text in a tooltip', (tester) async {
    final engine = FakeEngine(settings: seen)..setupShow = true;
    final long = 'Suggested: SigLIP 2 base: ${'measured and plain words ' * 30}';
    engine.setup = SetupOffer(
      walked: true,
      like: 'mid',
      summary: engine.setup.summary,
      hardware: engine.pc,
      items: [
        SetupItem(model: 'siglip2-base', workload: 'photo_search', name: 'SigLIP 2 base', sizeMb: 481, why: long, checked: true),
      ],
      totalMb: 481,
    );
    await pumpApp(tester, engine, size: const Size(1180, 900));
    engine.emit(StatusEvent(EngineStatus(phase: 'text', files: 48210)));
    await tester.pumpAndSettle();
    final t = tester.widget<Text>(find.text(long));
    expect((t.maxLines, t.overflow), (2, TextOverflow.ellipsis));
    expect(find.byWidgetPredicate((w) => w is Tooltip && w.message == long), findsOneWidget);
  });
}

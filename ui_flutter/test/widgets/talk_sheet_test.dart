// Talk about a photo (1.1) on the photo detail sheet, against the fake engine: the answer streams in (replaced,
// never appended), Stop and Esc cancel, a new question replaces the old one, Deeper says its cost or why not now,
// Keep sends vision_keep, and every answer is labelled as Find's reading of the photo.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/engine/engine_api.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/features/search/talk_panel.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

/// The main window with beach.jpg's details on screen (wide: the detail pane beside the results).
Future<FakeEngine> openPhoto(WidgetTester tester, {FakeEngine? engine, String words = 'jpg'}) async {
  final e = engine ?? FakeEngine(files: demoFiles());
  await pumpApp(tester, e, size: const Size(1180, 1400));
  await type(tester, words);
  await tester.pumpAndSettle();
  expect(find.text('Describe'), findsOneWidget);
  return e;
}

void say(FakeEngine e, String state, {String text = '', String note = '', int? job, String model = 'smolvlm2-500m'}) =>
    e.emit(VisionEvent(job: job ?? e.visionJob!, state: state, text: text, model: model, note: note));

Future<void> describe(WidgetTester tester) async {
  await tester.tap(find.text('Describe'));
  await tester.pump();
}

Future<void> ask(WidgetTester tester, String q) async {
  await tester.enterText(find.widgetWithText(TextField, 'Ask about this photo'), q);
  await tester.sendKeyEvent(LogicalKeyboardKey.enter);
  await tester.pump();
}

void main() {
  testWidgets('describe streams into the answer', (tester) async {
    final e = await openPhoto(tester);
    await describe(tester);
    expect(e.visionCalls.single.$1, 'vision_describe');
    expect(e.visionCalls.single.$2, {'file_id': 3});
    say(e, 'loading', note: 'Loading SmolVLM2 500M');
    await tester.pump();
    expect(find.text('Loading SmolVLM2-500M… about 2 s'), findsOneWidget);
    say(e, 'answering', text: 'A sandy ');
    await tester.pump();
    expect(find.text('A sandy '), findsOneWidget);
    say(e, 'answering', text: 'A sandy beach.'); // the whole answer so far: replaced, not appended
    await tester.pump();
    expect(find.text('A sandy beach.'), findsOneWidget);
    expect(find.textContaining('A sandy A sandy'), findsNothing);
    expect(find.text('Stop'), findsOneWidget);
    say(e, 'done', text: 'A sandy beach.');
    await tester.pump();
    expect(find.text('Stop'), findsNothing);
    expect(find.text('Copy'), findsOneWidget);
    expect(find.text('Keep this description'), findsOneWidget);
  });

  testWidgets('stop cancels', (tester) async {
    final e = await openPhoto(tester);
    await describe(tester);
    final job = e.visionJob!;
    say(e, 'answering', text: 'Two people');
    await tester.pump();
    await tester.tap(find.text('Stop'));
    await tester.pump();
    expect(e.visionCalls.last.$1, 'vision_cancel');
    expect(find.text('Stop'), findsNothing);
    say(e, 'answering', text: 'Two people walking', job: job); // late: never shown
    await tester.pump();
    expect(find.text('Two people walking'), findsNothing);
    expect(find.text('Two people'), findsOneWidget); // what was read so far stays, with nothing extra

    // Esc stops a running answer and closes nothing
    await describe(tester);
    say(e, 'answering', text: 'Sand');
    await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump();
    expect(e.visionCalls.last.$1, 'vision_cancel');
    expect(find.text('Describe'), findsOneWidget);
    expect(e.searches.last, 'jpg'); // the words are still there

    // the engine stopping it says why
    await describe(tester);
    say(e, 'cancelled', note: 'Stopped: NOBAD Find needed the memory. Try again.');
    await tester.pump();
    expect(find.text('Stopped: NOBAD Find needed the memory. Try again.'), findsOneWidget);
  });

  testWidgets('asking again replaces the old answer', (tester) async {
    final e = await openPhoto(tester);
    await describe(tester);
    final first = e.visionJob!;
    say(e, 'answering', text: 'A beach with');
    await tester.pump();
    await ask(tester, 'How many people?');
    expect(e.visionCalls.last.$1, 'vision_ask');
    expect(e.visionCalls.last.$2, {'file_id': 3, 'question': 'How many people?'});
    expect(find.text('A beach with'), findsNothing);
    say(e, 'answering', text: 'A beach with sand', job: first); // the old job: ignored
    await tester.pump();
    expect(find.text('A beach with sand'), findsNothing);
    say(e, 'done', text: 'Two.');
    await tester.pump();
    expect(find.text('Two.'), findsOneWidget);
    expect(find.text('Keep this description'), findsNothing); // Describe only

    // an error drops the partial answer and says why
    await ask(tester, 'What colour is the sky?');
    say(e, 'answering', text: 'Blu');
    say(e, 'error', note: 'The picture model stopped unexpectedly. Try again.');
    await tester.pump();
    expect(find.text('Blu'), findsNothing);
    expect(find.text('The picture model stopped unexpectedly. Try again.'), findsOneWidget);

    // a question about writing: the text read from the photo first, then the model only if asked
    await ask(tester, 'What does the sign say?');
    say(e, 'done', text: 'SALE 50%', note: 'Text read from the photo', model: '');
    await tester.pump();
    expect(find.text('Text read from the photo'), findsOneWidget);
    await tester.tap(find.text('Ask the model too'));
    await tester.pump();
    expect(e.visionCalls.last.$2, {'file_id': 3, 'question': 'What does the sign say?', 'more': true});

    // Devanagari in an answer
    say(e, 'done', text: 'किराया', note: 'may not be exact');
    await tester.pump();
    expect(find.text('may not be exact; the text read from the photo is above'), findsOneWidget);

    // Compare with… another image result in the list (not this one)
    await tester.tap(find.text('Compare with…'));
    await tester.pumpAndSettle();
    expect(find.text('IMG_0042.jpg'), findsNWidgets(2)); // the row, and the menu
    expect(find.descendant(of: find.byType(MenuItemButton), matching: find.text('beach.jpg')), findsNothing);
    await tester.tap(find.descendant(of: find.byType(MenuItemButton), matching: find.text('IMG_0042.jpg')));
    await tester.pumpAndSettle();
    expect(e.visionCalls.last.$1, 'vision_compare');
    expect(e.visionCalls.last.$2['a'], 3);
    expect(e.visionCalls.last.$2['b'], 8);
  });

  testWidgets('deeper shows the not-now reason', (tester) async {
    final e = FakeEngine(files: demoFiles());
    await openPhoto(tester, engine: e);
    expect(find.text('Deeper analysis (Qwen3-VL-2B)'), findsOneWidget);
    expect(find.text('about 5 s, 2.4 GB while answering'), findsOneWidget); // ram_mb from vision_state
    await tester.tap(find.byType(NbSwitch));
    await tester.pump();
    await ask(tester, 'What breed is the dog?');
    expect(e.visionCalls.last.$2, {'file_id': 3, 'question': 'What breed is the dog?', 'deeper': true});
    say(e, 'loading', model: 'qwen3vl-2b', note: 'Loading Qwen3-VL 2B');
    await tester.pump();
    expect(find.text('Loading Qwen3-VL-2B… about 4 s'), findsOneWidget);

    e.vision = demoVisionState(deeperWhy: 'Not now: only 3.0 GB free, Qwen needs about 2.4 GB plus margin.');
    say(e, 'done', text: 'A beagle.', model: 'qwen3vl-2b'); // the end of a job reads vision_state again
    await tester.pumpAndSettle();
    expect(find.text('Not now: only 3.0 GB free, Qwen needs about 2.4 GB plus margin.'), findsOneWidget);
    expect(find.text('about 5 s, 2.4 GB while answering'), findsNothing);
    await ask(tester, 'And now?');
    expect(e.visionCalls.last.$2, {'file_id': 3, 'question': 'And now?'}); // deeper isn't sent while not now

    // the engine's paused sentence: nothing can start
    e.vision = demoVisionState(notNow: 'Not now: NOBAD Find is paused.');
    e.emit(const LevelEvent('paused', 'Paused: you paused NOBAD Find for 60 min'));
    await tester.pumpAndSettle();
    expect(find.text('Not now: NOBAD Find is paused.'), findsWidgets);
    final n = e.visionCalls.length;
    await tester.tap(find.text('Describe'));
    await tester.pump();
    expect(e.visionCalls.length, n);
  });

  testWidgets('keep calls vision_keep', (tester) async {
    final e = await openPhoto(tester);
    await describe(tester);
    say(e, 'done', text: 'A sandy beach under a clear sky.');
    await tester.pump();
    await tester.tap(find.text('Keep this description'));
    await tester.pump();
    expect(e.visionCalls.last.$1, 'vision_keep');
    expect(e.visionCalls.last.$2, {'file_id': 3, 'text': 'A sandy beach under a clear sky.'});
    expect(e.kept[3], 'A sandy beach under a clear sky.');
    expect(find.text('Kept'), findsOneWidget);
  });

  testWidgets('answers carry the label', (tester) async {
    final e = await openPhoto(tester);
    expect(find.text(talkLabel), findsNothing); // nothing asked yet
    await describe(tester);
    say(e, 'answering', text: '<b>bold</b> **not markdown**');
    await tester.pump();
    expect(find.text("Find's reading of this photo"), findsOneWidget);
    expect(find.text('<b>bold</b> **not markdown**'), findsOneWidget); // shown as typed: plain text
    await ask(tester, 'Is it sunny?');
    say(e, 'done', text: 'Yes.');
    await tester.pump();
    expect(find.text("Find's reading of this photo"), findsOneWidget);
  });

  testWidgets('only image results offer it', (tester) async {
    final e = FakeEngine(files: demoFiles());
    await pumpApp(tester, e, size: const Size(1180, 1400));
    await type(tester, 'tax');
    await tester.pumpAndSettle();
    expect(find.text('Describe'), findsNothing);
  });

  testWidgets('an engine without talk about a photo shows none of it', (tester) async {
    final old = FakeEngine(files: demoFiles())..old = true;
    await pumpApp(tester, old, size: const Size(1180, 1400));
    await type(tester, 'jpg');
    await tester.pumpAndSettle();
    expect(find.text('Describe'), findsNothing);
  });

  testWidgets('a refusal says why', (tester) async {
    final e = await openPhoto(tester);
    e.visionRefuse = const VisionAnswer(error: 'To talk about photos, download SmolVLM2 500M first (520 MB, once).');
    await describe(tester);
    await tester.pump();
    expect(find.text('To talk about photos, download SmolVLM2 500M first (520 MB, once).'), findsOneWidget);
    expect(find.text(talkLabel), findsNothing);
  });

  testWidgets('a deeper model not downloaded yet shows the download line and is never sent', (tester) async {
    final e = FakeEngine(files: demoFiles())..vision = demoVisionState(deeperReady: false);
    await openPhoto(tester, engine: e);
    expect(find.text('Deeper analysis (Qwen3-VL-2B)'), findsOneWidget);
    expect(find.text('Needs a one-time download (1481 MB)'), findsOneWidget);
    expect(find.text('about 5 s, 2.4 GB while answering'), findsNothing);
    final sw = tester.widget<NbSwitch>(find.byType(NbSwitch));
    expect(sw.value, isFalse); // off
    expect(sw.onChanged, isNull); // and disabled
    await tester.tap(find.byType(NbSwitch));
    await tester.pump();
    await ask(tester, 'What breed is the dog?');
    expect(e.visionCalls.last.$2, {'file_id': 3, 'question': 'What breed is the dog?'}); // no deeper
  });

  testWidgets('narrow window: the sheet lays the talk panel out, and closing it stops the answer', (tester) async {
    final e = FakeEngine(files: demoFiles());
    await pumpApp(tester, e, size: const Size(860, 900));
    await type(tester, 'jpg');
    await tester.pumpAndSettle();
    expect(find.text('Describe'), findsNothing); // no pane at this width
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.sendKeyEvent(LogicalKeyboardKey.space);
    await tester.pumpAndSettle();
    expect(find.text('Describe'), findsOneWidget);
    expect(find.text('Deeper analysis (Qwen3-VL-2B)'), findsOneWidget);
    await describe(tester);
    say(e, 'answering', text: 'Waves on a long sandy beach, people walking along the water at the edge.');
    await tester.pumpAndSettle();
    expect(find.text('Stop'), findsOneWidget);
    expect(tester.takeException(), isNull); // laid out without overflow
    await tester.tapAt(const Offset(240, 500)); // outside the sheet: it closes
    await tester.pumpAndSettle();
    expect(find.text('Describe'), findsNothing);
    expect(e.visionCalls.last.$1, 'vision_cancel');
  });
}

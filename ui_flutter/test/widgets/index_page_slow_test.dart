// 1.1.1: on a big index the engine's full status can take long. The Index page asks for it once and waits for
// that answer (or a status_full event), never asking again while it is on its way; the totals the engine is still
// counting say "Counting…".
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/status.dart';

import '../support/fake_engine.dart';

/// An engine whose status_full answers only after [wait].
class SlowFullEngine extends FakeEngine {
  SlowFullEngine({this.wait = const Duration(seconds: 10), this.answer});

  final Duration wait;
  final EngineStatus? answer;
  var asked = 0;

  @override
  Future<EngineStatus> statusFull() async {
    asked++;
    final full = await super.statusFull();
    await Future<void>.delayed(wait);
    return answer ?? full;
  }
}

Future<void> openIndex(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1080, 1600));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit2);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pump();
}

Future<void> waitFor(WidgetTester tester, Duration d) async {
  for (var i = 0; i < d.inMilliseconds ~/ 500; i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
}

void main() {
  testWidgets('a slow full status is asked for once, and the page fills when it answers', (tester) async {
    final engine = SlowFullEngine();
    await openIndex(tester, engine);
    await waitFor(tester, const Duration(seconds: 9));
    expect(find.text('Index at a glance'), findsNothing); // still on its placeholder
    expect(engine.asked, 1);
    await waitFor(tester, const Duration(seconds: 2));
    expect(find.text('Index at a glance'), findsOneWidget);
    expect(find.text('31,877'), findsOneWidget); // with readable text
    await waitFor(tester, const Duration(seconds: 20));
    expect(engine.asked, 1);
  });

  testWidgets('a status_full event that comes first fills the page; nothing is asked again', (tester) async {
    final engine = SlowFullEngine();
    final full = await FakeEngine().statusFull();
    await openIndex(tester, engine);
    await waitFor(tester, const Duration(seconds: 4));
    expect(find.text('Index at a glance'), findsNothing);
    engine.emit(StatusFullEvent(full));
    await tester.pump();
    expect(find.text('Index at a glance'), findsOneWidget);
    await waitFor(tester, const Duration(seconds: 20));
    expect(find.text('Index at a glance'), findsOneWidget);
    expect(engine.asked, 1);
  });

  testWidgets('totals the engine is still counting say Counting…, the index size is shown', (tester) async {
    final counting = EngineStatus.fromJson({
      'level': 'gentle',
      'phase': 'names',
      'files': 1200,
      'with_text': 0,
      'vectors': 0,
      'name_vectors': 0,
      'photo_vectors': 0,
      'db_bytes': 5 * 1048576,
      'counting_totals': true,
      'phases': <Object?>[],
    });
    expect(counting.details!.countingTotals, isTrue);
    final engine = SlowFullEngine(wait: Duration.zero, answer: counting);
    await openIndex(tester, engine);
    await waitFor(tester, const Duration(seconds: 1));
    expect(find.text('Counting…'), findsNWidgets(3)); // readable text, by meaning, photos
    expect(find.text('5 MB'), findsOneWidget);
    expect(find.text('1,200'), findsOneWidget); // files: the indexer's live count
  });
}

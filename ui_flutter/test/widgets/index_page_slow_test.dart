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

  EngineStatus withFreshness(Map<String, Object?> extra) => EngineStatus.fromJson({
        'level': 'gentle',
        'phase': 'watching',
        'files': 1200,
        'with_text': 10,
        'vectors': 0,
        'name_vectors': 0,
        'photo_vectors': 0,
        'db_bytes': 5 * 1048576,
        'phases': <Object?>[],
        ...extra,
      });

  double secondsAgo(int s) => DateTime.now().subtract(Duration(seconds: s)).millisecondsSinceEpoch / 1000;

  Future<void> shows(WidgetTester tester, Map<String, Object?> extra, Object expected) async {
    final engine = SlowFullEngine(wait: Duration.zero, answer: withFreshness(extra));
    await openIndex(tester, engine);
    await waitFor(tester, const Duration(seconds: 1));
    expect(find.textContaining(RegExp('Counted |Counting|Couldn')), expected);
  }

  testWidgets('a ready count says how long ago it was counted', (tester) async {
    await shows(tester, {'totals_state': 'ready', 'totals_at': secondsAgo(125), 'totals_error': ''}, findsOneWidget);
    expect(find.text('Counted 2 min ago'), findsOneWidget);
  });

  testWidgets('a first count says Counting…, a newer one says Counting again…', (tester) async {
    await shows(tester, {'totals_state': 'counting', 'totals_at': null, 'counting_totals': true}, findsNWidgets(4));
    expect(find.text('Counting…'), findsNWidgets(4)); // three totals and the line
  });

  testWidgets('a refresh in progress says Counting again…', (tester) async {
    await shows(tester, {'totals_state': 'refreshing', 'totals_at': secondsAgo(30)}, findsOneWidget);
    expect(find.text('Counting again…'), findsOneWidget);
  });

  testWidgets('a failed count names the reason and the time of the last good one', (tester) async {
    final at = secondsAgo(3000);
    final d = DateTime.fromMillisecondsSinceEpoch((at * 1000).round());
    final hm = '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
    await shows(tester, {'totals_state': 'failed', 'totals_at': at, 'totals_error': 'the index was busy'},
        findsOneWidget);
    expect(find.text("Couldn't count just now: the index was busy. Showing the last count from $hm."), findsOneWidget);
  });

  testWidgets('an older engine (no freshness fields) shows no line and nothing breaks', (tester) async {
    await shows(tester, {}, findsNothing);
    expect(find.text('Index at a glance'), findsOneWidget);
    expect(withFreshness({}).details!.totalsState, '');
    expect(freshnessLine(state: ''), isNull);
  });
}

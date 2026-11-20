// 0.9.0: a search that needs something not ready says so above the results, with one button that does it.
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/features/search/need_hint.dart';

import '../support/fake_engine.dart';

void main() {
  testWidgets('photo search off: the hint says so and Turn on switches it on, then searches again', (tester) async {
    final engine = FakeEngine()
      ..searchNeeds = const [
        SearchNeed(model: 'photo', state: 'off', id: 'siglip2-base', sizeMb: 393, text: 'Photo search is off.'),
      ];
    await pumpApp(tester, engine);
    await type(tester, 'black shirt image');
    await tester.pumpAndSettle();
    expect(find.byType(NeedHint), findsOneWidget);
    expect(find.text('Photo search is off.'), findsOneWidget);
    final before = engine.searches.length;
    await tester.tap(find.text('Turn on photo search'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'photo_meaning': true});
    expect(engine.searches.length, greaterThan(before)); // the same question again, with photos on
  });

  testWidgets('photo model missing: Download asks for consent first, and nothing downloads on Not now', (tester) async {
    final engine = FakeEngine()
      ..searchNeeds = const [
        SearchNeed(model: 'photo', state: 'missing', id: 'siglip2-base', sizeMb: 393, text: 'Needs the photo model.'),
      ];
    await pumpApp(tester, engine);
    await type(tester, 'black shirt image');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Download…'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Download SigLIP 2'), findsOneWidget); // the consent dialog, for that model
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(engine.calls, isNot(contains('model_download')));
    await tester.tap(find.text('Download…'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('model_download'));
  });

  testWidgets('photos still being looked at: the progress, and no button', (tester) async {
    final engine = FakeEngine()
      ..searchNeeds = const [
        SearchNeed(
          model: 'photo',
          state: 'analyzing',
          id: 'siglip2-base',
          done: 120,
          total: 8400,
          text: 'Still looking at your photos: 120 of 8,400 done.',
        ),
      ];
    await pumpApp(tester, engine);
    await type(tester, 'black shirt image');
    await tester.pumpAndSettle();
    expect(find.text('Still looking at your photos: 120 of 8,400 done.'), findsOneWidget);
    expect(find.text('Download…'), findsNothing);
  });

  test('needs are read from the engine, rows it can\'t use are dropped, older engines send none', () {
    final a = SearchAnswer.fromJson({
      'results': [],
      'needs': [
        {'model': 'photo', 'state': 'analyzing', 'id': 'siglip2-base', 'size_mb': 393, 'done': 5, 'total': 10, 'text': 'x'},
        {'model': 'photo'},
        'nonsense',
      ],
    });
    expect(a.needs.single.done, 5);
    expect(SearchAnswer.fromJson({'results': []}).needs, isEmpty);
  });
}

// Replays the engine's recorded contract sessions (contract/transcripts, the same files the Python
// contract test replays) through this UI's models and its pipe client. `engine` and `note` lines are the engine's side and are skipped.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/settings.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/engine/models/vision.dart';
import 'package:nobad_find/engine/rpc.dart';
import 'package:nobad_find/engine/wiring.dart';
import 'package:nobad_find/state/talk_controller.dart';

import '../engine/rpc_test.dart' show FakeTransport;

typedef Line = Map<String, Object?>;

List<Line> readTranscript(String name) => [
  for (final l in File('../contract/transcripts/$name').readAsLinesSync())
    if (l.trim().isNotEmpty) jsonDecode(l) as Line,
];

final transcripts = [
  for (final f in Directory('../contract/transcripts').listSync()..sort((a, b) => a.path.compareTo(b.path)))
    if (f.path.endsWith('.jsonl')) f.uri.pathSegments.last,
];

/// (method, result) for every answered request, in order.
List<(String, Object?)> answers() {
  final out = <(String, Object?)>[];
  for (final t in transcripts) {
    final asked = <Object?, String>{};
    for (final l in readTranscript(t)) {
      final send = l['send'];
      if (send is Map) asked[send['id']] = send['method'] as String;
      final recv = l['recv'];
      if (recv is Map && recv.containsKey('result')) out.add((asked[recv['id']]!, recv['result']));
    }
  }
  return out;
}

void main() {
  test('there are transcripts', () => expect(transcripts, hasLength(greaterThanOrEqualTo(4))));

  test('every event the engine sends parses into a typed event', () {
    final seen = <String>{};
    for (final t in transcripts) {
      for (final l in readTranscript(t)) {
        final recv = l['recv'];
        if (recv is! Map || recv.containsKey('id')) continue;
        final method = recv['method'] as String;
        final e = EngineEvent.parse(method, recv['params']);
        expect(e, isNotNull, reason: '$t: $method');
        seen.add(method);
        switch (e) {
          case DownloadEvent():
            expect(e.id, isNotEmpty); // meaning, photo, or a model id from `models` (0.8)
            expect(e.sizeMb, greaterThan(0));
          case ShowEvent():
            expect(['main', 'bar', 'settings', 'index'], contains(e.what));
          case StatusFullEvent():
            expect(e.status.details, isNotNull);
            expect(e.status.details!.phases, isNotEmpty);
          case LevelEvent():
            expect(e.reason, isNotEmpty);
          case ModelsEvent():
            expect(e.info.models, isNotEmpty);
            expect(e.info.pc, isNotNull);
          case TurboEvent():
            expect(e.state.available, isTrue);
          case UpdateEvent(:final state):
            // Install's progress: downloading (got of size, bps once measured), verifying, installing
            expect(['downloading', 'verifying', 'installing'], contains(state.state));
            expect(state.size, greaterThan(0));
            expect(state.got, inInclusiveRange(0, state.size));
            if (state.state != 'downloading') expect(state.bps, 0);
          case VisionEvent():
            expect(e.job, greaterThan(0));
            if (e.state == 'error') expect(e.note, isNotEmpty); // the message is in the note
          default:
        }
      }
    }
    expect(
      seen,
      containsAll([
        'status', 'status_full', 'level', 'activity', 'download', 'notice', 'show', 'here', 'quitting', //
        'models', 'turbo', 'update', 'vision',
      ]),
    );
  });

  test('every answer parses with the model the UI uses for it', () {
    for (final (method, r) in answers()) {
      switch (method) {
        case 'search':
          final a = SearchAnswer.fromJson(r);
          expect(a.error, isEmpty);
          for (final x in a.results) {
            expect(x.path, isNotEmpty);
          }
          // 0.8.5: every part has a label; the best guess is the first row
          for (final p in a.parts) {
            expect(p.label, isNotEmpty);
          }
          if (a.best != null) expect(a.hasGuess, isTrue);
        case 'suggest':
          final sg = Suggestions.fromJson(r);
          expect(sg.items.length, (((r as Map)['items']) as List).length); // every row the engine sends is read
          for (final i in sg.items) {
            expect(i.text, isNotEmpty);
          }
        case 'history_forget' || 'history_clear':
          expect(ActionResult.fromJson(r).error, isA<String>());
        case 'status':
          expect(EngineStatus.fromJson(r).levelLabel, isNotEmpty);
        case 'status_full':
          final d = EngineStatus.fromJson(r).details!;
          expect(d.phases.map((p) => p.id), containsAll(['names', 'text', 'watching']));
          expect(d.models.map((m) => m.id), containsAll(['meaning', 'photo', 'ocr']));
          expect(d.history, isNotEmpty);
        case 'get_settings':
          final s = Settings.fromJson(r);
          expect(s.text('theme'), anyOf('dark', 'light'));
          expect(s.values.containsKey('welcome_seen'), isTrue); // the engine keeps the welcome's state
          expect(
            Settings.fromJson(const {'theme': 'dark'}).flag('welcome_seen'),
            isTrue,
          ); // an older engine: no nagging
        case 'set_settings':
          expect(SettingsChange.fromJson(r).settings.values, isNotEmpty);
        case 'learned_apps':
          expect(LearnedApp.listFromJson(r).single.bare, 'game');
        case 'hardware':
          expect(Hardware.fromJson(r)!.threads, 16);
        case 'wsearch_state':
          expect(WsearchState.fromJson(r).start, 'delayed-auto');
        case 'open' ||
            'reveal' ||
            'forget' ||
            'wipe' ||
            'quit' ||
            'rescan' ||
            'pause_for' ||
            'resume' ||
            'reset_learned' ||
            'download_model' ||
            'download_photo_model' ||
            'wsearch_set' ||
            'use_instead_of_windows_search':
          final a = ActionResult.fromJson(r);
          if (!a.ok) expect(a.error, isA<String>());
        case 'vision_state':
          final v = VisionState.fromJson(r);
          expect(v.models.map((m) => m.deeper), [false, true]); // the quick model first
          expect(v.deeper!.canRun || v.deeper!.why.isNotEmpty, isTrue);
          expect(v.runtimeId, isNotEmpty);
        case 'vision_describe' || 'vision_ask' || 'vision_compare' || 'vision_cancel' || 'vision_keep':
          final a = VisionAnswer.fromJson(r);
          if (a.ok && method != 'vision_cancel' && method != 'vision_keep') expect(a.job, isNotNull);
          if (!a.ok) {
            expect(a.error, isNotEmpty);
            expect(a.job, isNull); // a refusal starts nothing
          }
        case 'thumbnail':
          final url = (r as Map)['url'] as String;
          expect(url.isEmpty || decodeImageDataUrl(url) != null, isTrue);
        default:
      }
    }
  });

  test('smart search (0.8.5): parts, the best guess and suggestions read as the engine sent them', () {
    final lines = readTranscript('07-smart-search.jsonl');
    final search = SearchAnswer.fromJson(((lines[2]['recv'] as Map)['result']));
    expect(search.parts.map((p) => (p.kind, p.label, p.without)), [('kind', 'PDFs', 'tax'), ('words', 'tax', 'pdf')]);
    expect(search.best!.reason, 'The only match');
    expect(search.hasGuess, isTrue);
    final sug = [
      for (final l in lines)
        if (l['recv'] is Map &&
            ((l['recv'] as Map)['result'] as Object?) is Map &&
            (((l['recv'] as Map)['result']) as Map).containsKey('complete'))
          Suggestions.fromJson((l['recv'] as Map)['result']),
    ];
    expect(sug.first.items, isEmpty);
    expect(sug[1].items.first.isHistory, isTrue);
    expect(sug[1].items[1].id, 7);
    expect(sug[1].complete, 'tax pdf');
  });

  test('the pipe client asks the way the contract says and reads what comes back', () async {
    final queue = <String, List<Object?>>{};
    for (final (m, r) in answers()) {
      (queue[m] ??= []).add(r);
    }
    Object? next(String m) {
      final q = queue[m];
      if (q == null || q.isEmpty) return null;
      return q.length == 1 ? q.first : q.removeAt(0);
    }

    final t = FakeTransport(autoReply: (m, p) => next(m));
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    expect(c.link.value, Link.connected);
    expect(c.served, containsAll(['status_full', 'pick_folder', 'set_settings', 'to_main', 'ui_hidden']));
    expect(c.enginePid, 4242);
    expect(t.sent.firstWhere((m) => m['method'] == 'ui_shown')['params'], {'window': 'main'});

    final a = await c.search('tax pdf');
    expect(a.results.single.path, r'C:\Users\me\Documents\tax 2025.pdf');
    expect(a.understood, ['pdf']);
    expect((await c.open(7)).ok, isTrue);
    expect(await c.pathOf(7), r'C:\Users\me\Documents\tax 2025.pdf');
    expect(await c.hereFolder(), r'C:\Users\me\Downloads');
    expect((await c.statusFull()).details!.plan!.cpu, 16);
    expect((await c.learnedApps()).single.exe, 'game.exe');
    expect((await c.hardware())!.ramGb, 15.7);
    final ch = await c.setSettings({'theme': 'light', 'content_max_mb': 50});
    expect(ch.changed, ['theme', 'content_max_mb']);
    expect(ch.settings.number('content_max_mb'), 50);
    final pick = await c.pickFolder();
    expect(pick.path, r'C:\Users\me\Projects');
    expect(pick.busy, isFalse);
    expect((await c.wsearchState()).running, isTrue);
    expect((await c.downloadModel('meaning')).error, 'Allow the download in Settings first.');
    expect((await c.downloadModel('photo')).error, 'Allow the photo model download in Settings first.');
    await c.search('x' * 2500);
    expect(((t.sent.last['params'] as Map)['text'] as String).length, 2000); // the engine refuses longer
    await c.wipe('DELETE');
    await c.pauseFor(const Duration(hours: 1));
    await c.resetLearned('game.exe');
    await c.toMain('tax pdf');
    await c.uiHidden('main');
    await c.quit();

    Map<String, Object?> params(String m) =>
        (t.sent.lastWhere((x) => x['method'] == m)['params'] as Map).cast<String, Object?>();
    expect(params('set_settings'), {
      'changes': {'theme': 'light', 'content_max_mb': 50},
    });
    expect(params('wipe'), {'confirm': 'DELETE'});
    expect(params('quit'), {'confirm': 'QUIT'});
    expect(params('pause_for'), {'seconds': 3600});
    expect(params('reset_learned'), {'exe': 'game.exe'});
    expect(params('to_main'), {'text': 'tax pdf'});
    expect(params('ui_hidden'), {'window': 'main'});
    expect(params('download_model'), isEmpty);

    // quitting: the client stops reconnecting
    t.push({'jsonrpc': '2.0', 'method': 'quitting', 'params': {}});
    await pumpEventQueue();
    expect(c.quitting, isTrue);
    t.drop();
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(c.link.value, Link.offline);
    c.dispose();
  });

  test('watching the Indexing page subscribes to status_full, and stops', () async {
    final t = FakeTransport(
      autoReply: (m, p) => switch (m) {
        'hello' => {
          'protocol': 1,
          'pid': 1,
          'methods': ['hello', 'subscribe', 'unsubscribe', 'status', 'status_full'],
        },
        'subscribe' || 'unsubscribe' => {'events': <String>[]},
        'status' => {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 1, 'paused': ''},
        _ => null,
      },
    );
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    unawaited(c.watchDetails(true));
    await pumpEventQueue();
    unawaited(c.watchDetails(false));
    await pumpEventQueue();
    final subs = t.sent.where((m) => m['method'] == 'subscribe' || m['method'] == 'unsubscribe').toList();
    expect(subs.last['method'], 'unsubscribe');
    expect((subs.last['params'] as Map)['events'], ['status_full']);
    expect((subs[1]['params'] as Map)['events'], ['status_full']);
    c.dispose();
  });

  test('talk about a photo (08): the controller replays the transcript over the pipe client', () async {
    final hello = readTranscript('01-connect-and-search.jsonl')
        .map((l) => l['recv'])
        .whereType<Map>()
        .firstWhere((r) => r['result'] is Map && (r['result'] as Map).containsKey('methods'))['result'];
    // every exchange of 08: what was sent, the answer, and the events the engine sent after it
    final asked = <Object?, Map>{};
    final results = <Object?, Object?>{};
    final after = <Object?, List<Object>>{};
    Object? last;
    for (final l in readTranscript('08-talk-about-a-photo.jsonl')) {
      final send = l['send'];
      if (send is Map) asked[send['id']] = send;
      final recv = l['recv'];
      if (recv is! Map) continue;
      if (recv.containsKey('id')) {
        last = recv['id'];
        results[last] = recv['result'];
      } else if (last != null) {
        (after[last] ??= []).add(recv);
      }
    }
    final used = <Object?>{};
    late FakeTransport t;
    t = FakeTransport(
      autoReply: (m, p) {
        switch (m) {
          case 'hello':
            return hello;
          case 'subscribe':
            return {'events': p['events']};
          case 'status':
            return {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 1, 'paused': ''};
          case 'vision_state':
            return results[2];
          case 'ui_shown':
            return {'ok': true};
        }
        final id = asked.keys.firstWhere(
          (k) => !used.contains(k) && asked[k]!['method'] == m && jsonEncode(asked[k]!['params']) == jsonEncode(p),
          orElse: () => fail('08 has no $m $p'),
        );
        used.add(id);
        Timer.run(() => after[id]?.forEach(t.push)); // the events come after the reply
        return results[id];
      },
    );
    final client = EngineClient(() async => t, backoff: const [Duration(seconds: 5)])..start();
    await pumpEventQueue();
    expect(client.link.value, Link.connected);
    expect((t.sent.firstWhere((x) => x['method'] == 'subscribe')['params'] as Map)['events'], contains('vision'));
    final engine = PipeEngine(client);
    final talk = TalkController(engine);
    final seen = <String>[];
    talk.addListener(() {
      if (seen.isEmpty || seen.last != talk.text) seen.add(talk.text);
    });
    Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 20));

    talk.show(7);
    await settle();
    expect(talk.state!.quick!.label, 'SmolVLM2-500M');
    expect(talk.state!.quick!.loadS, 1); // the measured seconds come over the pipe
    expect(talk.state!.deeper!.answerS, (2, 12));
    expect(talk.deeperOffer!.label, 'Deeper analysis (Qwen3-VL-2B)');
    expect(talk.deeperOffer!.available, isFalse);
    expect(talk.deeperOffer!.detail, 'Needs a one-time download (1800 MB)'); // not ready comes first

    // describe: loading, then the whole answer so far each time (replaced), then done
    await talk.describe();
    await settle();
    expect(seen, containsAllInOrder(['A red ', 'A red car.']));
    expect(seen.any((x) => x.contains('A red A red')), isFalse);
    expect(talk.phase, TalkPhase.done);
    expect(talk.text, 'A red car.');
    expect(talk.canKeep, isTrue);

    await talk.ask('What colour is the car?');
    await settle();
    expect((talk.phase, talk.text, talk.canKeep), (TalkPhase.done, 'Red.', false));

    // a question about writing: the text read from the photo, then the model too (more: true), stopped by the user
    await talk.ask('What does the sign say?');
    await settle();
    expect(talk.text, 'SALE 50%');
    expect(talk.textOnly, isTrue);
    await talk.askModelToo();
    await settle();
    expect((talk.phase, talk.text), (TalkPhase.answering, 'The sign says SALE.'));
    await talk.stop();
    await settle();
    expect((talk.phase, talk.note), (TalkPhase.stopped, '')); // the user stopped it: nothing extra

    // deeper refused: the sentence, and what to download first
    await talk.ask('Describe the house.', deeper: true);
    await settle();
    expect(talk.phase, TalkPhase.failed);
    expect(talk.error, 'To talk about photos, download Qwen3-VL 2B first (1800 MB, once).');
    expect(talk.download.single.sizeMb, 1800);

    // compare: the engine stops one (its note is shown), another fails (the message; the partial text dropped)
    await talk.compare(8, question: 'Which one is brighter?');
    await settle();
    expect((talk.phase, talk.note), (TalkPhase.stopped, 'Stopped: NOBAD Find needed the memory. Try again.'));
    await talk.compare(8);
    await settle();
    expect((talk.phase, talk.text), (TalkPhase.failed, ''));
    expect(talk.error, 'The picture model stopped unexpectedly. Try again.');
    await talk.compare(7);
    await settle();
    expect(talk.error, 'Pick a second, different photo to compare.');

    talk.show(999);
    await settle();
    await talk.describe();
    await settle();
    expect(talk.error, 'This photo is no longer there.');
    await talk.ask('   ');
    expect(t.sent.where((x) => x['method'] == 'vision_ask').length, 4); // an empty question isn't sent

    expect((await engine.visionKeep(7, 'A red car in front of a white house.')).kept, isTrue);
    expect((await engine.visionKeep(7, '')).kept, isFalse);
    expect((await engine.visionKeep(999, 'x')).error, 'This photo is no longer there.');
    talk.dispose();
    client.dispose();
  });
}

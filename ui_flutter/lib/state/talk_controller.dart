/// Talk about a photo (find 1.1) on the photo detail sheet: Describe, Ask, Compare, the streamed answer, Stop and
/// Keep. One question at a time (the engine's rule too): a new one replaces the old one.
///
/// The engine answers each call at once with the job's number; the answer itself comes as `vision` events of that
/// job. `answering` carries the WHOLE answer so far, so the shown text is replaced, never appended to. Events of any
/// other job (an older question) are ignored. `cancelled` with a note: the engine stopped it (the note is shown);
/// with no note: the user stopped it or a newer question replaced it (nothing extra is shown). `error`: the message
/// is shown and any partial answer is dropped.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import 'models_controller.dart' show TalkConsent, fetchTalkModel;
import 'settings_controller.dart' show errorText;

enum TalkKind { describe, ask, compare }

enum TalkPhase {
  /// Nothing asked about this photo yet.
  idle,

  /// Asked; waiting for the engine to name the job.
  starting,
  loading,
  answering,
  done,

  /// Stopped (by the user, a newer question, or the engine: then [TalkController.note] says why).
  stopped,

  /// Refused or failed: [TalkController.error] says why.
  failed,
}

/// The engine's note on an answer that is only the text already read from the photo (no model ran).
const textReadNote = 'Text read from the photo';

/// The engine's note on an answer with Devanagari in it (the model may have misread it).
const unverifiedNote = 'may not be exact';

final _devanagari = RegExp(r'[ऀ-ॿ]');

/// Seconds the UI says, by the model's role. vision_state has no timings, so these come from the measured rows
/// (docs/measurements.md 2026-11-22 1.1.0, reference PC, through the real worker): loading SmolVLM2-500M about
/// 1-3 s and Qwen3-VL-2B about 12-13 s (its first word came 13-15 s after the first question, 2-5 s after later
/// ones), a deeper answer about 2-7 s once loaded. The memory figure always comes from vision_state (`ram_mb`).
const loadSeconds = {false: 2, true: 13};
const deeperAnswerSeconds = 5;

/// The talk model to offer a Download for after a refusal that lists [download] (vision_* `download`): the talk
/// model it names, else (only the runtime is missing) the quick model, whose consent then names just the runtime.
String? talkDownloadId(List<VisionDownload> download, VisionState? state) {
  if (download.isEmpty || state == null) return null;
  for (final d in download) {
    if (state.byId(d.id) != null) return d.id;
  }
  return state.quick?.id;
}

class TalkController extends ChangeNotifier {
  TalkController(this.engine) {
    _sub = engine.events.listen(_event);
  }

  final EngineApi engine;
  late final StreamSubscription<EngineEvent> _sub;
  bool _disposed = false;

  VisionState? _state;
  bool _served = true;
  int? _fileId;
  int _seq = 0;
  int? _job;
  final _early = <VisionEvent>[];

  TalkKind? _kind;
  TalkPhase _phase = TalkPhase.idle;
  String _question = '';
  bool _deeper = false;
  int? _other;
  String _text = '';
  String _note = '';
  String _model = '';
  String _error = '';
  List<VisionDownload> _download = const [];
  bool _kept = false;
  bool _keeping = false;

  /// The last vision_state (null until read, or when the engine doesn't serve it).
  VisionState? get state => _state;

  /// False for an engine without talk about a photo (-32601): the sheet shows none of it.
  bool get served => _served;

  /// The photo the sheet shows (and the answer is about).
  int? get fileId => _fileId;
  TalkKind? get kind => _kind;
  TalkPhase get phase => _phase;
  String get question => _question;
  bool get deeper => _deeper;

  /// The second photo of a comparison.
  int? get other => _other;

  /// The answer so far (plain text: never read as markdown or HTML).
  String get text => _text;
  String get note => _note;
  String get model => _model;
  String get error => _error;
  List<VisionDownload> get download => _download;
  bool get kept => _kept;
  bool get keeping => _keeping;

  bool get running => _phase == TalkPhase.starting || _phase == TalkPhase.loading || _phase == TalkPhase.answering;

  /// The answer is only the text read from the photo: offer "Ask the model too".
  bool get textOnly => _phase == TalkPhase.done && _kind == TalkKind.ask && _note == textReadNote;

  /// Devanagari in the answer: "may not be exact; the text read from the photo is above".
  bool get unverified => _text.isNotEmpty && (_note == unverifiedNote || _devanagari.hasMatch(_text));

  /// "Keep this description": a finished Describe only.
  bool get canKeep => _phase == TalkPhase.done && _kind == TalkKind.describe && _text.trim().isNotEmpty;

  /// "Loading SmolVLM2-500M… about 2 s" while the model loads.
  String get loadingLine {
    final m = _state?.byId(_model) ?? (_deeper ? _state?.deeper : _state?.quick);
    if (m == null) return _note.isEmpty ? 'Loading…' : '$_note…';
    return 'Loading ${m.label}… about ${loadSeconds[m.deeper]} s';
  }

  /// Why nothing can start now (paused, the runtime downloading), or ''.
  String get notNow => _state?.notNow ?? '';

  /// The deeper model's line: its live cost, or "Not now: …"; null when the engine offers no deeper model.
  /// [download]: the model id to offer a Download for (not on this PC yet), else null.
  ({String label, bool available, String detail, String? download})? get deeperOffer {
    final d = _state?.deeper;
    if (d == null) return null;
    final label = 'Deeper analysis (${d.label})';
    if (notNow.isNotEmpty) return (label: label, available: false, detail: _notNowText(notNow), download: null);
    // not on this PC yet: the download (with its consent) comes first; asking deeper would only be refused
    if (!d.ready) {
      if (_fetching.isNotEmpty) {
        return (label: label, available: false, detail: 'Downloading…', download: null);
      }
      final rt = _state!.runtimeReady ? 0 : _state!.runtimeMissingMb; // the runtime comes with it, same consent
      final all = d.missingMb + rt;
      final mb = all > 0 ? ' ($all MB)' : '';
      return (label: label, available: false, detail: 'Needs a one-time download$mb', download: d.id);
    }
    if (!d.canRun) {
      final why = _notNowText(d.why.isEmpty ? "it doesn't fit right now." : d.why);
      return (label: label, available: false, detail: why, download: null);
    }
    final gb = (d.ramMb / 1000).toStringAsFixed(1);
    return (label: label, available: true, detail: 'about $deeperAnswerSeconds s, $gb GB while answering', download: null);
  }

  /// Talk models (and runtimes) whose download this sheet started and that haven't finished.
  final _fetching = <String>{};

  /// True while a download started here is on its way.
  bool get fetching => _fetching.isNotEmpty;

  /// Download talk model [id] (the Deeper line's or a refusal's Download): ONE consent names it and the runtime it
  /// needs (Settings → Models' dialog), then both are fetched. The Deeper switch comes on with the next
  /// vision_state after the download.
  Future<void> fetch(String id, {required TalkConsent consent}) async {
    if (_fetching.contains(id)) return;
    try {
      final info = await engine.models();
      final m = info.byId(id);
      if (m == null) return;
      final r = await fetchTalkModel(engine, info, m, consent: consent);
      if (r.error.isNotEmpty) _error = r.error;
      _fetching.addAll(r.started.map((x) => x.id));
      if (r.started.isNotEmpty && _phase == TalkPhase.failed) _download = const []; // its Download was pressed
    } catch (e) {
      _error = errorText(e);
    }
    _changed();
  }

  static String _notNowText(String why) => why.startsWith('Not now') ? why : 'Not now: $why';

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  /// The sheet shows [fileId]: a different photo stops a running answer and starts clean.
  void show(int? fileId) {
    if (fileId == _fileId) return;
    if (running) unawaited(_cancel());
    _fileId = fileId;
    _reset();
    _changed();
    if (fileId != null) unawaited(refresh());
  }

  void _reset() {
    _seq++;
    _job = null;
    _early.clear();
    _kind = null;
    _phase = TalkPhase.idle;
    _question = '';
    _deeper = false;
    _other = null;
    _text = _note = _model = _error = '';
    _download = const [];
    _kept = _keeping = false;
  }

  /// Read vision_state again (the deeper model's cost and "Not now" change with free memory and pauses).
  Future<void> refresh() async {
    try {
      _state = await engine.visionState();
      _served = true;
    } on RpcException catch (e) {
      if (e.code == -32601) _served = false;
    } catch (_) {
      // offline: keep what was known
    }
    _changed();
  }

  Future<void> describe() => _start(TalkKind.describe, () => engine.visionDescribe(_fileId!));

  /// Ask [q] about the photo; [deeper] uses the deeper model.
  Future<void> ask(String q, {bool deeper = false}) {
    final question = q.trim();
    if (question.isEmpty) return Future.value();
    return _start(
      TalkKind.ask,
      () => engine.visionAsk(_fileId!, question, deeper: deeper),
      question: question,
      deeper: deeper,
    );
  }

  /// "Ask the model too": the same question, the model this time (`more: true`).
  Future<void> askModelToo() => _start(
    TalkKind.ask,
    () => engine.visionAsk(_fileId!, _question, deeper: _deeper, more: true),
    question: _question,
    deeper: _deeper,
  );

  /// Compare this photo with [b] (another image result), with an optional question.
  Future<void> compare(int b, {String? question}) {
    final q = question?.trim() ?? '';
    return _start(
      TalkKind.compare,
      () => engine.visionCompare(_fileId!, b, question: q.isEmpty ? null : q),
      question: q,
      other: b,
    );
  }

  Future<void> _start(
    TalkKind kind,
    Future<VisionAnswer> Function() call, {
    String question = '',
    bool deeper = false,
    int? other,
  }) async {
    if (_fileId == null) return;
    final keepFile = _fileId;
    _reset();
    _fileId = keepFile;
    final seq = _seq;
    _kind = kind;
    _question = question;
    _deeper = deeper;
    _other = other;
    _phase = TalkPhase.starting;
    _changed();
    VisionAnswer a;
    try {
      a = await call();
    } catch (e) {
      a = VisionAnswer(error: errorText(e));
    }
    if (seq != _seq || _disposed) return; // a newer question (or another photo) came first
    if (!a.ok || a.job == null) {
      _phase = TalkPhase.failed;
      _error = a.error.isEmpty ? "That didn't work. Try again." : a.error;
      _download = a.download;
      _early.clear();
      _changed();
      return;
    }
    _job = a.job;
    final early = [..._early.where((e) => e.job == a.job)];
    _early.clear();
    for (final e in early) {
      _apply(e);
    }
    _changed();
  }

  /// Stop the answer being streamed (the sheet's Stop, or Esc).
  Future<void> stop() async {
    if (!running) return;
    _seq++; // a reply still on its way starts nothing on screen
    _job = null;
    _early.clear();
    _phase = TalkPhase.stopped;
    _note = '';
    _changed();
    await _cancel();
  }

  Future<void> _cancel() async {
    try {
      await engine.visionCancel();
    } catch (_) {
      // offline: nothing is running there either
    }
  }

  /// "Keep this description": searches find the photo by it.
  Future<void> keep() async {
    final id = _fileId;
    if (!canKeep || id == null || _keeping) return;
    _keeping = true;
    _changed();
    try {
      final r = await engine.visionKeep(id, _text.trim());
      if (id != _fileId) return;
      _kept = r.ok && r.kept;
      if (!r.ok) _error = r.error;
    } catch (e) {
      if (id == _fileId) _error = errorText(e);
    } finally {
      if (id == _fileId) _keeping = false;
      _changed();
    }
  }

  void _event(EngineEvent e) {
    if (e is LevelEvent) {
      if (_fileId != null) unawaited(refresh()); // a pause or its end changes "Not now"
      return;
    }
    if (e is DownloadEvent) {
      // a talk model or runtime arrived (or failed): vision_state says what can run now
      if (e.state != 'downloading' && _fetching.remove(e.id)) {
        if (e.error.isNotEmpty) {
          _fetching.clear();
          _error = 'The download stopped: ${e.error}';
        }
        unawaited(refresh());
      }
      return;
    }
    if (e is! VisionEvent) return;
    if (_job == null) {
      if (_phase == TalkPhase.starting && _early.length < 64) _early.add(e); // before the reply named its job
      return;
    }
    if (e.job != _job) return;
    _apply(e);
    _changed();
  }

  void _apply(VisionEvent e) {
    if (e.model.isNotEmpty) _model = e.model;
    switch (e.state) {
      case 'loading':
        _phase = TalkPhase.loading;
        _note = e.note;
      case 'answering':
        _phase = TalkPhase.answering;
        _note = '';
        _text = e.text; // the whole answer so far
      case 'done':
        _phase = TalkPhase.done;
        _text = e.text;
        _note = e.note;
        _job = null;
        unawaited(refresh());
      case 'error':
        _phase = TalkPhase.failed;
        _error = e.note.isNotEmpty ? e.note : (e.text.isNotEmpty ? e.text : 'The answer failed. Try again.');
        _text = ''; // a partial answer isn't shown after a failure
        _note = '';
        _job = null;
        unawaited(refresh());
      case 'cancelled':
        _phase = TalkPhase.stopped;
        _note = e.note; // empty: the user stopped it, nothing extra to say
        _job = null;
        unawaited(refresh());
    }
  }

  @override
  void dispose() {
    _disposed = true;
    if (running) unawaited(_cancel());
    unawaited(_sub.cancel());
    super.dispose();
  }
}

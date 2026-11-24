/// Settings → Models (contract 0.8): the catalogue from the engine, kept current by `models` and `download` events,
/// and the actions on it. Every download asks for consent first; an engine without these methods is said plainly
/// ("needs a newer engine"), never filled in with made-up models.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import '../engine/models/models_info.dart';
import '../platform/languages.dart';
import 'settings_controller.dart' show errorText;
import 'toast_controller.dart';

enum ModelsLoad { loading, ready, needsNewer, offline }

/// The consent for a talk model and the runtime it still needs (null: on this PC already).
typedef TalkConsent = Future<bool> Function(ModelInfo model, ModelInfo? runtime);

/// 1.1, Settings → Models and the photo talk panel: ONE consent for talk model [m] and its runtime, then a
/// `model_download` for each still missing. Returns the models whose download started, or an error sentence
/// ('' with nothing started: the user said Not now).
Future<({List<ModelInfo> started, String error})> fetchTalkModel(
  EngineApi engine,
  ModelsInfo info,
  ModelInfo m, {
  required TalkConsent consent,
}) async {
  final rt = info.runtimeToFetch(m);
  if (!await consent(m, rt)) return (started: const <ModelInfo>[], error: '');
  final started = <ModelInfo>[];
  for (final x in [if (!m.onDisk && m.state != ModelUseState.downloading) m, ?rt]) {
    final r = await engine.modelDownload(x.id);
    if (!r.ok) return (started: started, error: r.error.isNotEmpty ? r.error : 'The download did not start.');
    started.add(x);
  }
  return (started: started, error: '');
}

/// A download in progress (from `download` events).
class ModelProgress {
  const ModelProgress({this.gotMb = 0, this.sizeMb = 0, this.mbS = 0, this.error = ''});
  final double gotMb;
  final double sizeMb;
  final double mbS;
  final String error;
  double get fraction => sizeMb > 0 ? (gotMb / sizeMb).clamp(0, 1).toDouble() : 0;
}

class ModelsController extends ChangeNotifier {
  ModelsController(this.engine, {this.toasts, String? Function()? windowsFocus})
    : _windowsFocus = windowsFocus ?? windowsLanguageFocus {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_relink);
  }

  final EngineApi engine;
  final ToastController? toasts;
  final String? Function() _windowsFocus;
  late final StreamSubscription<EngineEvent> _sub;

  ModelsLoad _load = ModelsLoad.loading;
  ModelsInfo _info = const ModelsInfo();
  String _why = '';
  final _progress = <String, ModelProgress>{};
  final _busy = <String>{};
  bool _auto = false;
  bool _disposed = false;
  LanguageFocus? _suggested;
  bool _suggestedRead = false;

  CapabilityState? _cap;
  int _beats = 0;

  /// What this PC can run RIGHT NOW (`capability_state`); null from an older engine or before the first answer.
  CapabilityState? get capability => _cap;

  ModelsLoad get load => _load;
  ModelsInfo get info => _info;

  /// Why it couldn't load (the engine's own sentence for "needs a newer engine").
  String get why => _why;
  bool busy(String id) => _busy.contains(id);
  bool get autoBusy => _auto;
  ModelProgress? progress(String id) => _progress[id];

  /// The focus Windows' languages suggest (the engine's default before one is chosen): marked "Recommended".
  LanguageFocus? get suggestedFocus {
    if (!_suggestedRead) {
      _suggestedRead = true;
      _suggested = LanguageFocus.parse(_windowsFocus());
    }
    return _suggested;
  }

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _say(String s) {
    if (s.isNotEmpty) toasts?.show(s);
  }

  void _relink() {
    if (engine.link.value == Link.connected) unawaited(refresh());
  }

  Future<void> refresh() async {
    try {
      _info = await engine.models();
      _load = ModelsLoad.ready;
      unawaited(refreshCapability());
    } on EngineOffline {
      _load = ModelsLoad.offline;
    } on RpcException catch (e) {
      _load = e.code == -32601 ? ModelsLoad.needsNewer : ModelsLoad.offline;
      _why = e.message;
    } on Object {
      _load = ModelsLoad.offline;
    }
    _changed();
  }

  /// Ask the engine again what runs now. An older engine (-32601) or a dropped pipe: no live part, the installed
  /// facts stay.
  Future<void> refreshCapability() async {
    try {
      _cap = await engine.capabilityState();
    } on Object {
      _cap = null;
    }
    _changed();
  }

  /// The live part follows the engine's status beat (one `status` event every 2 s): asked again every
  /// [capabilityEveryBeats] beats, about every 6 s.
  static const capabilityEveryBeats = 3;

  void _event(EngineEvent e) {
    switch (e) {
      case StatusEvent():
        if (_load == ModelsLoad.ready && ++_beats % capabilityEveryBeats == 0) unawaited(refreshCapability());
        return;
      case ModelsEvent(:final info):
        _info = info;
        _load = ModelsLoad.ready;
        _progress.removeWhere((id, _) => info.models.any((m) => m.id == id && m.state != ModelUseState.downloading));
      case DownloadEvent():
        if (!_info.models.any((m) => m.id == e.id)) return;
        if (e.state == 'downloading') {
          _progress[e.id] = ModelProgress(gotMb: e.gotMb, sizeMb: e.sizeMb, mbS: e.mbS);
        } else {
          _progress.remove(e.id);
          if (e.error.isNotEmpty) _say('The download stopped: ${e.error}');
        }
      default:
        return;
    }
    _changed();
  }

  Future<T?> _run<T>(String id, Future<T> Function() f) async {
    if (!_busy.add(id)) return null;
    _changed();
    try {
      return await f();
    } on Object catch (e) {
      _say(errorText(e));
      return null;
    } finally {
      _busy.remove(id);
      _changed();
    }
  }

  /// Use [m] for its feature; if it isn't downloaded yet, ask for consent and download it. A model above what is
  /// suggested for this PC first shows its measured cost ([cost]; "Use anyway" for one not recommended): without
  /// the user's yes nothing is chosen, and the engine refuses it without `confirm` as well.
  Future<void> use(
    ModelInfo m, {
    required Future<bool> Function(ModelInfo) consent,
    Future<bool> Function(ModelInfo)? cost,
  }) async {
    var confirm = false;
    if (m.aboveSuggestion && !m.chosen) {
      if (cost == null || !await cost(m)) return;
      confirm = true;
    }
    final r = await _run(m.id, () => engine.modelUse(m.feature, m.id, confirm: confirm));
    if (r == null) return;
    if (!r.ok) return _say(r.error.isNotEmpty ? r.error : "That model can't be used.");
    if (r.needsDownload) {
      await download(m, consent: consent);
    } else {
      _say(m.feature == 'text' ? 'Switching to ${m.name}. Search keeps working while it rebuilds.' : 'Done.');
    }
    await refresh();
  }

  /// Download [m], only after [consent] said yes (the consent word goes with the call).
  Future<bool> download(ModelInfo m, {required Future<bool> Function(ModelInfo) consent}) async {
    if (!await consent(m)) return false;
    final r = await _run(m.id, () => engine.modelDownload(m.id));
    if (r == null) return false;
    _say(r.ok ? 'Downloading ${m.name}…' : r.error);
    if (r.ok) _progress[m.id] = ModelProgress(sizeMb: m.sizeMb);
    _changed();
    return r.ok;
  }

  /// A talk model (1.1): one consent names it and the runtime it needs; Download fetches both.
  /// A talk model above the suggestion shows its measured cost first ([cost]).
  Future<bool> downloadTalk(
    ModelInfo m, {
    required TalkConsent consent,
    Future<bool> Function(ModelInfo)? cost,
  }) async {
    if (m.aboveSuggestion && !m.onDisk && (cost == null || !await cost(m))) return false;
    final r = await _run(m.id, () => fetchTalkModel(engine, _info, m, consent: consent));
    if (r == null) return false;
    for (final x in r.started) {
      _progress[x.id] = ModelProgress(sizeMb: x.sizeMb);
    }
    if (r.error.isNotEmpty) {
      _say(r.error);
    } else if (r.started.isNotEmpty) {
      _say('Downloading ${r.started.map((x) => x.name).join(' and ')}…');
    }
    _changed();
    return r.error.isEmpty && r.started.isNotEmpty;
  }

  /// File Explorer on the folder [m] is downloaded to (the engine opens it; the UI never hands it a path).
  Future<void> openFolder(ModelInfo m) async {
    final r = await _run('folder-${m.id}', () => engine.modelFolder(m.id));
    if (r != null && !r.ok) _say(r.error.isNotEmpty ? r.error : "Couldn't open the folder.");
  }

  Future<void> remove(ModelInfo m) async {
    final r = await _run(m.id, () => engine.modelRemove(m.id));
    if (r == null) return;
    _say(r.ok ? '${m.name} removed.' : (r.error.isNotEmpty ? r.error : "It wasn't removed."));
    await refresh();
  }

  /// The recommended tier: what needs no download is applied at once; each download asks for consent.
  Future<void> autoConfigure({required Future<bool> Function(ModelInfo) consent}) async {
    if (_auto) return;
    _auto = true;
    _changed();
    try {
      final a = await engine.autoConfigure();
      await refresh();
      var asked = 0;
      for (final step in a.steps) {
        if (!step.needsDownload || step.id.isEmpty) continue;
        final m = _info.models.where((x) => x.id == step.id).firstOrNull;
        if (m == null) continue;
        asked++;
        await download(m, consent: consent);
      }
      _say(asked == 0 ? 'Set up for ${tierLabel(a.tier)}.' : '');
    } on Object catch (e) {
      _say(errorText(e));
    } finally {
      _auto = false;
      _changed();
    }
  }

  /// Back to the suggested models. When a model change looks at the files again, [ask] shows the changes with their
  /// re-index time first (nothing is changed before its yes); a model not on disk then asks for [consent] to download.
  Future<void> resetSuggested({
    required Future<bool> Function(List<ResetChange>) ask,
    required Future<bool> Function(ModelInfo) consent,
  }) async {
    final r = await _run<ResetSuggested?>('reset', () async {
      var a = await engine.resetSuggested();
      if (a.ok && !a.applied && a.changes.isNotEmpty) {
        if (!await ask(a.changes)) return null;
        a = await engine.resetSuggested(confirm: true);
      }
      return a;
    });
    if (r == null) return;
    if (!r.ok) return _say(r.error.isNotEmpty ? r.error : "The models weren't reset.");
    await refresh();
    if (r.changes.isEmpty) return _say('Already on the suggested models.');
    if (!r.applied) return;
    _say('Back on the suggested models.');
    for (final c in r.changes) {
      final m = _info.byId(c.id);
      if (c.needsDownload && m != null) await download(m, consent: consent);
    }
  }

  Future<void> setFocus(LanguageFocus f) async {
    if (_info.languageFocus == f) return;
    final r = await _run('focus', () => engine.modelLanguage(f.wire));
    if (r == null) return;
    if (!r.ok) _say(r.error);
    await refresh();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_sub.cancel());
    engine.link.removeListener(_relink);
    super.dispose();
  }
}

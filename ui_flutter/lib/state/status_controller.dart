/// The engine link and its status, from events only, never polled:
/// - `status` (short, every 2 s) and `level` for the status line and the rail;
/// - `status_full` for the Indexing page, subscribed only while it's open ([watch]);
/// - `activity` (new Recent decisions on top) and `download` (model progress).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import '../engine/models/update.dart';
import '../engine/models/format.dart';
import '../engine/models/scope_info.dart';
import '../engine/models/status.dart';

class StatusController extends ChangeNotifier {
  StatusController(this.engine) : _status = engine.lastStatus {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_linkChanged);
  }

  final EngineApi engine;
  late final StreamSubscription<EngineEvent> _sub;
  EngineStatus? _status;
  IndexDetails? _details;
  List<ActivityEntry> _activity = const [];
  final _downloads = <String, ModelState>{};
  TurboState? _turbo;
  UpdateState _update = UpdateState.unknown;
  var _watchers = 0;
  var _disposed = false;

  /// The turbo index (null: an engine without it, or not asked yet; the Index page asks).
  TurboState? get turbo => _turbo;

  /// In-app updates as the engine last said (0.9.0).
  UpdateState get update => _update;

  /// Called once per newer version found (the app shows a toast); null in tests.
  void Function(UpdateState)? onUpdateFound;

  /// Ask the engine (Settings > About opens): an older engine has none, the state stays unknown.
  /// Pause for [d] or Resume (0.9.1): the page shows it at once ("Pausing…" / "Resuming…"); the engine's level
  /// event, which now comes right away too, then says how fast it works.
  Future<void> pauseFor(Duration d) async {
    final s = _status ?? const EngineStatus();
    _status = EngineStatus(level: 'paused', reason: 'Pausing…', phase: s.phase, files: s.files, paused: 'you paused it');
    _changed();
    try {
      await engine.pauseFor(d);
    } on Object {
      _status = s;
      _changed();
    }
  }

  Future<void> resume() async {
    final s = _status ?? const EngineStatus();
    _status = EngineStatus(level: 'gentle', reason: 'Resuming…', phase: s.phase, files: s.files);
    _changed();
    try {
      await engine.resume();
    } on Object {
      _status = s;
      _changed();
    }
  }

  Future<void> loadUpdate() async {
    try {
      _update = await engine.updateState();
    } on Object {
      return;
    }
    _changed();
  }

  /// The short status (level, reason, phase, files, paused).
  EngineStatus? get status => _status;

  /// The Indexing page's details (null until the first status_full).
  IndexDetails? get details => _details;
  Link get link => engine.link.value;
  bool get connected => link == Link.connected;

  /// Recent decisions, newest first (the details plus activity events since).
  List<ActivityEntry> get activity => _activity;

  /// A model's download state: the newest download event, else the details.
  ModelState model(String id) =>
      _downloads[id] ?? (id == 'photo' ? _details?.photoModel : _details?.model) ?? const ModelState();

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _linkChanged() {
    if (connected) {
      if (_watchers > 0) unawaited(_refreshDetails(subscribe: true));
    } else {
      // no engine: nothing old is shown as if it were current
      _details = null;
      _activity = const [];
      _downloads.clear();
    }
    _changed();
  }

  /// The Indexing page opened (true) or closed (false): status_full is asked for once and then pushed while open.
  Future<void> watch(bool on) async {
    _watchers += on ? 1 : -1;
    if (_watchers < 0) _watchers = 0;
    if (on && _watchers == 1) {
      await _refreshDetails(subscribe: true);
    } else if (!on && _watchers == 0) {
      try {
        await engine.watchDetails(false);
      } on Object {
        // gone already
      }
    }
  }

  Future<void> _refreshDetails({bool subscribe = false}) async {
    try {
      // 0.9.1: the subscription and the first full status together, not one after the other
      final sub = subscribe ? engine.watchDetails(true) : Future<void>.value();
      // 1.1.1: asked once and waited for. Asking again while the answer was on its way (0.9.3) only gave a slow
      // engine the same work again: on a big index four full statuses ran at once and searches timed out behind
      // them. A status_full event that comes first fills the page meanwhile.
      try {
        _takeFull(await engine.statusFull());
      } on RpcException {
        // too slow or refused: the status_full events fill the page
      }
      _changed();
      await sub;
      try {
        _turbo = await engine.turboState();
      } on RpcException {
        _turbo = null; // an engine without the turbo index: no line
      }
      _changed();
    } on Object {
      // offline: the page says so
    }
  }

  void _takeFull(EngineStatus s) {
    _details = s.details;
    _status = EngineStatus(level: s.level, reason: s.reason, phase: s.phase, files: s.files, paused: s.paused);
    final a = s.details?.activity;
    if (a != null) _activity = a;
    // A status that knows a download finished or failed replaces the progress events.
    _downloads.removeWhere((id, d) => !d.downloading);
  }

  void _event(EngineEvent e) {
    switch (e) {
      case StatusEvent(:final status):
        if (status == _status) return;
        _status = status;
      case StatusFullEvent(:final status):
        _takeFull(status);
      case LevelEvent(:final level, :final reason, :final paused):
        final s = _status ?? const EngineStatus();
        _status = EngineStatus(level: level, reason: reason, phase: s.phase, files: s.files, paused: paused);
      case ActivityEvent(:final entry):
        if (_activity.isNotEmpty && _activity.first.t == entry.t && _activity.first.text == entry.text) return;
        _activity = [entry, ..._activity.take(49)];
      case DownloadEvent():
        _downloads[e.id] = e.asState;
      case TurboEvent(:final state):
        _turbo = state;
      case UpdateEvent(:final state):
        final was = _update;
        _update = state;
        if (state.state == 'available' && (was.state != 'available' || was.latest != state.latest)) {
          onUpdateFound?.call(state);
        }
      case ShowEvent() || NoticeEvent() || HereEvent() || QuittingEvent() || ModelsEvent() || VisionEvent() ||
          NotificationEvent():
        return;
    }
    _changed();
  }

  /// The status line: "12,345 files indexed · Working gently · Up to date", or what's wrong with the link.
  String get line => switch (link) {
    Link.connecting => 'Connecting to the engine…',
    Link.offline => "The engine isn't running. Trying again…",
    Link.incompatible => 'This window and the engine are different versions. Update NOBAD Find.',
    Link.untrusted => untrustedLine,
    Link.connected => _connectedLine(),
  };

  String _connectedLine() {
    final s = _status;
    if (s == null) return 'Connected';
    return [
      '${groupDigits(s.files)} files indexed',
      // "Paused" once: the phase already says it while paused
      if (s.levelLabel.isNotEmpty && !(s.paused.isNotEmpty && s.levelLabel == 'Paused')) s.levelLabel,
      if (s.phaseLabel.isNotEmpty) s.phaseLabel,
    ].join(' · ');
  }

  @override
  void dispose() {
    _disposed = true;
    _sub.cancel();
    engine.link.removeListener(_linkChanged);
    super.dispose();
  }
}

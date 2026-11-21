/// Settings and the actions on the Settings pages: changes go to the engine, which checks them; downloads ask for
/// consent first; the dangerous ones (wipe, forget every app) ask for confirmation. Messages are the 0.7.0 words.
library;

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/models/models_info.dart';
import '../engine/models/settings.dart';

import 'toast_controller.dart';

/// What to tell the user when a call failed: the engine is gone, it refused the request, or something else.
String errorText(Object e, {String invalid = "That wasn't accepted.", String other = "That didn't work. Try again."}) {
  if (e is EngineOffline) return "NOBAD Find's engine isn't running.";
  if (e is RpcException && e.code == -32601) return e.message;
  if (e is RpcException && e.code == -32602) return invalid;
  return other;
}

class SettingsController extends ChangeNotifier {
  SettingsController(this.engine, {this.toasts});

  final EngineApi engine;
  final ToastController? toasts;

  Settings _settings = Settings.initial;
  bool _loaded = false;
  List<LearnedApp> _learned = const [];
  Hardware? _hardware;
  WsearchState? _wsearch;
  bool _wsearchBusy = false;
  bool _disposed = false;

  Settings get settings => _settings;
  bool get loaded => _loaded;
  List<LearnedApp> get learned => _learned;
  Hardware? get hardware => _hardware;
  WsearchState? get wsearch => _wsearch;
  bool get wsearchBusy => _wsearchBusy;

  HotkeyState _hotkeys = HotkeyState.unknown;

  /// Whether each global hotkey works now (ok / taken / reserved / off), as the engine last said.
  HotkeyState get hotkeys => _hotkeys;

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _say(String s) => toasts?.show(s);

  bool _sayFalse(String s) {
    _say(s);
    return false;
  }

  Future<void> load() async {
    try {
      _settings = await engine.getSettings();
      _loaded = true;
    } on EngineOffline {
      // keeps the last known settings
    } on RpcException {
      // same
    }
    _changed();
  }

  /// The Settings pages' extra blocks: learned apps, the PC scan, Windows Search.
  Future<void> loadExtras() async {
    try {
      final r = await Future.wait([engine.learnedApps(), engine.hardware(), engine.wsearchState()]);
      _learned = r[0] as List<LearnedApp>;
      _hardware = r[1] as Hardware?;
      _wsearch = r[2] as WsearchState;
    } on Object {
      // shown as "not available"
    }
    _changed();
  }

  /// Change one setting. Shown at once; if the engine doesn't take it, says so and shows the real value again.
  Future<bool> set(String key, Object? value) async {
    final before = _settings;
    _settings = _settings.merged({key: value});
    _changed();
    SettingsChange r;
    try {
      r = await engine.setSettings({key: value});
    } on Object catch (e) {
      _say(errorText(e, invalid: "That value wasn't accepted.", other: "Couldn't save that. Try again."));
      _settings = before;
      _changed();
      return false;
    }
    _settings = r.settings;
    if (r.hotkeys != null) _hotkeys = r.hotkeys!;
    _changed();
    final now = r.settings[key];
    final took = now is List && value is List ? listEquals(now, value) : now == value;
    if (!took) _say("That value wasn't accepted.");
    return took;
  }

  Future<void> loadHotkeys() async {
    try {
      _hotkeys = await engine.hotkeyState();
    } on Object {
      return; // an older engine: no state to show
    }
    _changed();
  }

  /// Would [spec] work for [which]? null when the engine can't say (offline, older engine).
  Future<HotkeyProbe?> probeHotkey(String which, String spec) async {
    try {
      return await engine.hotkeyProbe(which, spec);
    } on Object {
      return null;
    }
  }

  /// Save a new hotkey; the engine registers it at once. Returns its state after that (null if not saved).
  Future<HotkeyOne?> setHotkey(String which, String spec) async {
    if (!await set(which, spec)) return null;
    return _hotkeys.of(which);
  }

  Future<void> addFolder(String key, String path) async {
    if (path.isEmpty) return;
    final list = _settings.list(key);
    if (list.contains(path)) return;
    await set(key, [...list, path]);
  }

  /// "Add folder": Windows' folder dialog (the engine shows it), then the folder joins the list.
  Future<void> pickAndAdd(String key) async {
    FolderPick r;
    try {
      r = await engine.pickFolder();
    } on Object {
      return;
    }
    if (r.busy) return _say('The folder window is already open.');
    await addFolder(key, r.path);
  }

  Future<void> removeFolder(String key, int index) async {
    final list = [..._settings.list(key)];
    if (index < 0 || index >= list.length) return;
    list.removeAt(index);
    await set(key, list);
  }

  /// The model Settings > Models would download for [model] ("meaning" or "photo"): the one in use while the
  /// feature is on, else the one recommended for this PC (null: the catalogue has none for it).
  static ModelInfo? modelFor(String model, ModelsInfo info, Settings settings) {
    final photo = model == 'photo';
    final all = info.byFeature(photo ? 'photo' : 'text');
    if (all.isEmpty) return null;
    if (settings.flag(photo ? 'photo_meaning' : 'semantic')) {
      final chosen = settings.text(photo ? 'photo_model' : 'text_model');
      final m = all.where((x) => x.id == chosen).firstOrNull;
      if (m != null) return m;
    }
    return all.where((x) => x.recommended).firstOrNull ??
        all.where((x) => x.state == ModelUseState.active).firstOrNull ??
        all.first;
  }

  /// [model] "meaning" or "photo": the Welcome and Index pages' Download button. Gets the same model Settings >
  /// Models would ([modelFor]) with `model_download`, after [consent] (it gets that model; null from an engine
  /// without the catalogue) said yes, then makes it the one used. Nothing is downloaded without a yes.
  Future<bool> download(String model, {required Future<bool> Function(ModelInfo?) consent}) async {
    ModelsInfo? info;
    try {
      info = await engine.models();
    } on RpcException catch (e) {
      if (e.code != -32601) return _sayFalse(errorText(e));
    } on Object catch (e) {
      return _sayFalse(errorText(e));
    }
    final m = info == null ? null : modelFor(model, info, _settings);
    if (info != null && m == null) return _sayFalse("That model isn't available. Open Settings > Models.");
    if (!await consent(m)) return false;
    if (m != null) {
      try {
        final r = await engine.modelDownload(m.id);
        if (!r.ok) return _sayFalse(r.error.isNotEmpty ? r.error : "The download didn't start.");
        final use = await engine.modelUse(m.feature, m.id); // the one used once it is here (turns the feature on)
        if (!use.ok && use.error.isNotEmpty) _say(use.error);
      } on Object catch (e) {
        return _sayFalse(errorText(e));
      }
      _say('Downloading ${m.name}…');
      await load();
      return true;
    }
    // an engine older than the catalogue: its own fixed download
    final allow = model == 'photo' ? 'allow_photo_model_download' : 'allow_model_download';
    if (!_settings.flag(allow) && !await set(allow, true)) return false;
    ActionResult r;
    try {
      r = await engine.downloadModel(model);
    } on Object {
      r = const ActionResult(false, "NOBAD Find's engine isn't running.");
    }
    _say(r.ok ? (model == 'photo' ? 'Downloading the photo model…' : 'Downloading the model…') : r.error);
    return r.ok;
  }

  Future<void> forgetApp(String? exe, {Future<bool> Function()? confirm}) async {
    if (exe == null && confirm != null && !await confirm()) return;
    try {
      if (!(await engine.resetLearned(exe)).ok) return;
      _say('Forgotten.');
    } on Object {
      return;
    }
    await loadExtras();
  }

  Future<void> toggleWindowsSearch() async {
    final ws = _wsearch;
    if (ws == null || ws.missing || _wsearchBusy) return;
    _wsearchBusy = true;
    _changed();
    try {
      final r = await engine.useInsteadOfWindowsSearch(!ws.off);
      _say(r.ok ? 'Done.' : (r.error.isNotEmpty ? r.error : 'No change.'));
    } on Object {
      _say('No change.');
    }
    _wsearchBusy = false;
    await Future.wait([loadExtras(), load()]);
  }

  /// [ask] shows "Type DELETE to confirm" and returns what was typed (null: cancelled).
  Future<bool> wipe(Future<String?> Function() ask) async {
    if (await ask() != 'DELETE') return false;
    try {
      final r = await engine.wipe('DELETE');
      if (r.ok) {
        _say('Index deleted. Rebuilding.');
        return true;
      }
      _say(r.error.isNotEmpty ? r.error : "The index wasn't deleted. Try again.");
    } on Object catch (e) {
      _say(errorText(e, other: "The index wasn't deleted. Try again."));
    }
    return false;
  }

  Future<void> rescan() async {
    try {
      final r = await engine.rescan();
      _say(r.ok ? 'Rescan started.' : (r.error.isNotEmpty ? r.error : "The rescan didn't start. Try again."));
    } on Object catch (e) {
      _say(errorText(e));
    }
  }

  /// Quit NOBAD Find completely (the engine says `quitting`, then the window closes).
  Future<void> quit() async {
    try {
      await engine.quit();
    } on Object {
      // the engine is gone already
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

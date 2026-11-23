/// Settings (const.DEFAULTS / settings.coerce in the engine) and the small records the Settings pages show:
/// learned apps (appmemory.list), the PC scan (hardware.scan), Windows Search (wsearch.state).
library;

import 'json.dart';

/// set_settings' consent word for turning `secret_app_files` on (const.APP_FILES_CONSENT in the engine).
const appFilesConsent = 'READ_APP_SECRETS';

/// The engine's settings as it sent them. Unknown keys are kept (a newer engine), missing ones read as the
/// engine's defaults. The UI never decides what a value means: set_settings sends changes and the engine checks.
class Settings {
  const Settings(this.values);
  final Map<String, Object?> values;

  /// const.DEFAULTS in nobadfind (contract `$defs/settings`), `welcome_seen` included. An older engine whose
  /// settings don't have `welcome_seen` counts as "seen" (see [fromJson]), so its users are never nagged.
  static const defaults = <String, Object?>{
    'roots': <String>[],
    'exclude': <String>[],
    'content': true,
    'content_max_mb': 25,
    'semantic': false,
    'photo_meaning': false,
    'allow_photo_model_download': false,
    'allow_model_download': false,
    'src_mail': true,
    'ocr': true,
    'index_removable': false,
    'index_network': false,
    'pause_on_battery': true,
    'pause_fullscreen': true,
    'games_mode': 'smart',
    'power': 'balanced',
    'safety_net': true,
    'keep_background': false,
    'stay_running': true,
    'bar': true,
    'bar_hotkey': 'ctrl+shift+space',
    'pause_on_call': true,
    'workers': 0,
    'hotkey': 'win+shift+f',
    'autostart': false,
    'hide_after_open': false,
    'wsearch_prev': '',
    'theme': 'dark',
    'glass': true,
    'bg_notice_seen': false,
    'welcome_seen': false,
    'search_history': true,
    // 1.1.0: read command histories, saved logins and tool tokens (Settings > Privacy, after a confirm dialog)
    'secret_app_files': false,
    'models_stay_loaded': false,
    'update_check': true,
    'notify_toasts': true,
    'notify_level': 'warning',
    'notify_quiet': true,
    'notify_show_names': false,
    // 1.2.0 Settings > Performance (spec 8b): the goal and the overrides; power mirrors the goal for older UIs
    'performance_goal': 'balanced',
    'gpu_background': 'auto',
    'backend_photos': 'auto',
    'backend_text': 'auto',
    'backend_talk': 'auto',
    'variant_siglip2-base': 'auto',
    'profile_override_gpu': 'auto',
    'profile_override_cpu': 'auto',
    'profile_override_storage': 'auto',
    'profile_override_memory': 'auto',
    'gpu_reserve_min_mb': 512,
  };

  static const initial = Settings(defaults);

  static Settings fromJson(Object? json) {
    final m = jMap(json);
    return Settings({...defaults, if (!m.containsKey('welcome_seen')) 'welcome_seen': true, ...m});
  }

  Object? operator [](String key) => values.containsKey(key) ? values[key] : defaults[key];
  bool flag(String key) => this[key] == true;
  String text(String key) => jStr(this[key]);
  int number(String key) => jInt(this[key]);
  List<String> list(String key) => jStrs(this[key]);

  /// 0.8.5 is dark only (maintainer decision 2026-11-19), whatever an older engine says.
  bool get dark => true;
  bool get glass => flag('glass');

  Settings merged(Map<String, Object?> changes) => Settings({...values, ...changes});
}

/// `set_settings` answer: what really changed, and the settings after it.
class SettingsChange {
  const SettingsChange(this.changed, this.settings, {this.hotkeys});
  final List<String> changed;
  final Settings settings;

  /// Only when hotkey, bar_hotkey or bar changed: whether each hotkey works now (0.9.0 engines).
  final HotkeyState? hotkeys;

  static SettingsChange fromJson(Object? v) {
    final m = jMap(v);
    return SettingsChange(
      jStrs(m['changed']),
      Settings.fromJson(m['settings']),
      hotkeys: m['hotkeys'] is Map ? HotkeyState.fromJson(m['hotkeys']) : null,
    );
  }
}

/// One global hotkey as the engine holds it (`hotkey_state`): [state] is ok, taken (another app has it),
/// reserved (Windows keeps it), invalid, or off (the quick find bar is off, or not known yet).
class HotkeyOne {
  const HotkeyOne(this.spec, this.state);
  final String spec;
  final String state;
  bool get ok => state == 'ok';

  static HotkeyOne fromJson(Object? v) {
    final m = jMap(v);
    final s = jStr(m['state']);
    return HotkeyOne(jStr(m['spec']), s.isEmpty ? 'off' : s);
  }
}

/// `hotkey_state`: the main hotkey and the quick find bar's.
class HotkeyState {
  const HotkeyState(this.main, this.bar);
  final HotkeyOne main;
  final HotkeyOne bar;

  /// Before the engine said anything (or an engine older than 0.9.0): nothing to show.
  static const unknown = HotkeyState(HotkeyOne('', 'off'), HotkeyOne('', 'off'));

  /// [which] is the setting's name: 'hotkey' or 'bar_hotkey'.
  HotkeyOne of(String which) => which == 'bar_hotkey' ? bar : main;

  static HotkeyState fromJson(Object? v) {
    final m = jMap(v);
    return HotkeyState(HotkeyOne.fromJson(m['hotkey']), HotkeyOne.fromJson(m['bar_hotkey']));
  }
}

/// `hotkey_probe`: would a combination work, before it's saved. [state] ok | taken | reserved | invalid | same;
/// [spec] as the engine writes it ('' when invalid); [reason] one sentence to show.
class HotkeyProbe {
  const HotkeyProbe(this.state, this.spec, this.reason);
  final String state;
  final String spec;
  final String reason;
  bool get ok => state == 'ok';

  static HotkeyProbe fromJson(Object? v) {
    final m = jMap(v);
    return HotkeyProbe(jStr(m['state']), jStr(m['spec']), jStr(m['reason']));
  }
}

class LearnedApp {
  const LearnedApp({required this.exe, this.seen = 0, this.lagEvents = 0, this.startLevel, this.reason = ''});
  final String exe;
  final int seen;
  final int lagEvents;
  final String? startLevel;
  final String reason;

  /// `learned_apps` answer: `{apps: [...]}`.
  static List<LearnedApp> listFromJson(Object? v) => jList(jMap(v)['apps'], fromJson);

  /// "game" from "game.exe": only the file name is ever stored.
  String get bare => exe.replaceAll(RegExp(r'\.exe$', caseSensitive: false), '');

  static LearnedApp? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['exe']).isEmpty) return null;
    return LearnedApp(
      exe: jStr(m['exe']),
      seen: jInt(m['seen']),
      lagEvents: jInt(m['lag_events']),
      startLevel: m['start_level'] is String ? m['start_level'] as String : null,
      reason: jStr(m['reason']),
    );
  }
}

/// One graphics adapter. [sharedMb] is system memory it may borrow, never video memory.
class GpuInfo {
  const GpuInfo({
    this.vendor = '',
    this.name = '',
    this.dedicatedMb = 0,
    this.sharedMb = 0,
    this.integrated = false,
  });
  final String vendor;
  final String name;
  final int dedicatedMb;
  final int sharedMb;
  final bool integrated;

  static GpuInfo? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return GpuInfo(
      vendor: jStr(m['vendor']),
      name: jStr(m['name']),
      dedicatedMb: jInt(m['dedicated_mb']),
      sharedMb: jInt(m['shared_mb']),
      integrated: jBool(m['integrated']),
    );
  }
}

class Hardware {
  const Hardware({
    this.ramGb = 0,
    this.cores = 0,
    this.threads = 0,
    this.avx2 = false,
    this.avx512Vnni = false,
    this.gpu = '',
    this.vramGb = 0,
    this.directml = false,
    this.diskFreeGb = 0,
    this.ssd,
    this.gpus = const [],
    this.onnxBackends = const [],
    this.llamacppBackends = const [],
  });
  final double ramGb;
  final int cores;
  final int threads;
  final bool avx2;
  final bool avx512Vnni;
  final String gpu;
  final double vramGb;
  final bool directml;
  final double diskFreeGb;
  final bool? ssd;

  /// Every graphics adapter (empty from an older engine).
  final List<GpuInfo> gpus;

  /// Backends installed per family, e.g. ['cpu', 'directml'] and ['vulkan', 'cpu'] (empty from an older engine).
  final List<String> onnxBackends;
  final List<String> llamacppBackends;

  static Hardware? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return Hardware(
      ramGb: jNum(m['ram_gb']),
      cores: jInt(m['cores']),
      threads: jInt(m['threads']),
      avx2: jBool(m['avx2']),
      avx512Vnni: jBool(m['avx512_vnni']),
      gpu: jStr(m['gpu']),
      vramGb: jNum(m['vram_gb']),
      directml: jBool(m['directml']),
      diskFreeGb: jNum(m['disk_free_gb']),
      ssd: m['ssd'] is bool ? m['ssd'] as bool : null,
      gpus: jList(m['gpus'], GpuInfo.fromJson),
      onnxBackends: jList(jMap(m['backends'])['onnx'], (x) => x is String ? x : null),
      llamacppBackends: jList(jMap(m['backends'])['llamacpp'], (x) => x is String ? x : null),
    );
  }
}

class WsearchState {
  const WsearchState({this.missing = false, this.start = '', this.running = false, this.saved = ''});
  final bool missing;

  /// How it started before NOBAD Find turned it off ('' if it didn't).
  final String saved;

  /// auto | delayed-auto | demand | disabled
  final String start;
  final bool running;
  bool get off => start == 'disabled';

  static WsearchState fromJson(Object? v) {
    final m = jMap(v);
    if (m.isEmpty || jBool(m['missing'])) return const WsearchState(missing: true);
    return WsearchState(start: jStr(m['start']), running: jBool(m['running']), saved: jStr(m['saved']));
  }
}

/// `pick_folder` answer: the folder ('' if cancelled); [busy] = a folder window was already open (not a cancel).
class FolderPick {
  const FolderPick(this.path, {this.busy = false});
  final String path;
  final bool busy;

  static FolderPick fromJson(Object? v) {
    final m = jMap(v);
    return FolderPick(jStr(m['path']), busy: jBool(m['busy']));
  }
}

/// The engine refuses longer words, folders and handed-over text (contract: at most 2000 characters).
const maxTextLength = 2000;

/// `Ok` = `{ok, error}` (open, reveal, forget, downloads, wipe, quit…); wsearch_set adds `state`.
class ActionResult {
  const ActionResult(this.ok, [this.error = '']);
  final bool ok;
  final String error;

  static ActionResult fromJson(Object? v) {
    final m = jMap(v);
    return ActionResult(jBool(m['ok']), jStr(m['error']));
  }
}

/// One Settings > Performance override as `performance_state` describes it (spec 8b rule 5): its [value], what
/// "auto" would pick on this PC right now ([auto], a string or a number) and [why], the [options] it may take here
/// (empty for numbers) and a [note] when the value isn't used now.
class PerformanceRow {
  const PerformanceRow({this.value, this.auto, this.why = '', this.options = const [], this.note = ''});
  final Object? value;
  final Object? auto;
  final String why;
  final List<String> options;
  final String note;

  static PerformanceRow fromJson(Object? v) {
    final m = jMap(v);
    return PerformanceRow(
      value: m['value'],
      auto: m['auto'],
      why: jStr(m['why']),
      options: jStrs(m['options']),
      note: jStr(m['note']),
    );
  }
}

/// `performance_state` (1.2.0 engines): the goal, and every override row by its setting name.
class PerformanceState {
  const PerformanceState(this.goal, this.rows);
  final String goal;
  final Map<String, PerformanceRow> rows;

  static PerformanceState fromJson(Object? v) {
    final m = jMap(v);
    final g = jStr(m['goal']);
    return PerformanceState(g.isEmpty ? 'balanced' : g, {
      for (final e in jMap(m['rows']).entries) e.key: PerformanceRow.fromJson(e.value),
    });
  }
}

/// `reset_safe_defaults`: whether it worked, the settings put back, and what was kept.
class ResetResult {
  const ResetResult(this.ok, this.reset, this.kept);
  final bool ok;
  final List<String> reset;
  final List<String> kept;

  static ResetResult fromJson(Object? v) {
    final m = jMap(v);
    return ResetResult(jBool(m['ok']), jStrs(m['reset']), jStrs(m['kept']));
  }
}

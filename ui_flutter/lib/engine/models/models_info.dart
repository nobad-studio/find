/// The engine's model catalogue (contract additions for 0.8: `models`, `model_use`, `model_download`,
/// `model_remove`, `auto_configure`, `model_language`, and the `models` event): this PC, the recommended tier, and every model with
/// what it does, what it costs, and whether this PC can run it.
library;

import 'json.dart';
import 'settings.dart' show Hardware;

/// Settings → Models' language choice (contract `language_focus`): it changes the recommendation only.
enum LanguageFocus {
  english('english', 'English first', 'The best English models this PC can run'),
  multilingual('multilingual', 'Many languages', 'About 100 languages, mixed ones included'),
  hindi('hindi', 'Hindi + English', 'Hindi, Hinglish and English names and text');

  const LanguageFocus(this.wire, this.label, this.help);
  final String wire;
  final String label;
  final String help;

  static LanguageFocus? parse(Object? v) => values.where((f) => f.wire == v).firstOrNull;
}

/// Retrieval scores the engine measured for a model (contract `quality`, optional): shown only when sent.
class ModelQuality {
  const ModelQuality({required this.recall5, required this.ndcg10});
  final double recall5;
  final double ndcg10;

  static ModelQuality? fromJson(Object? v) {
    if (v is! Map || v['recall5'] is! num || v['ndcg10'] is! num) return null;
    return ModelQuality(recall5: (v['recall5'] as num).toDouble(), ndcg10: (v['ndcg10'] as num).toDouble());
  }
}

String _language(String code) => switch (code.trim().toLowerCase()) {
  'en' => 'English',
  'hi' => 'Hindi',
  'multilingual' => 'many languages',
  final c when c.startsWith('multilingual (') => c.substring(14, c.length - (c.endsWith(')') ? 1 : 0)),
  _ => code.trim(),
};

enum ModelUseState { notDownloaded, downloading, ready, active, failed }

const _states = {
  'not_downloaded': ModelUseState.notDownloaded,
  'downloading': ModelUseState.downloading,
  'ready': ModelUseState.ready,
  'active': ModelUseState.active,
  'failed': ModelUseState.failed,
};

String featureLabel(String feature) =>
    const {
      'text': 'Meaning search',
      'photo': 'Photos by what is in them',
      'ocr': 'Words in pictures',
      'talk': 'Talk about photos',
      'runtime': 'Runs the photo talk models',
    }[feature] ??
    feature;

String tierLabel(String tier) =>
    const {'light': 'Light', 'balanced': 'Balanced', 'best': 'Best', 'custom': 'Custom'}[tier] ?? tier;

class ModelInfo {
  const ModelInfo({
    required this.id,
    this.feature = 'text',
    this.name = '',
    this.tier = '',
    this.licence = '',
    this.source = '',
    this.sizeMb = 0,
    this.ramMb = 0,
    this.speedNote = '',
    this.languages = const [],
    this.improves = '',
    this.builtin = false,
    this.state = ModelUseState.notDownloaded,
    this.capable = true,
    this.capableReason = '',
    this.recommended = false,
    this.focusSent,
    this.quality,
    this.dir = '',
    this.vramMb = 0,
    this.runtime = '',
  });

  /// 1.1, talk models: measured graphics memory on the Vulkan runtime (0 = not sent).
  final double vramMb;

  /// 1.1, talk models: the runtime id this PC uses for it ('' = not sent); offered in the same consent.
  final String runtime;

  /// 0.9.0: the folder its files are (or will be) downloaded to; '' when built into Windows or an older engine.
  final String dir;
  final String id;
  final String feature;
  final String name;
  final String tier;
  final String licence;
  final String source;
  final double sizeMb;
  final double ramMb;
  final String speedNote;
  final List<String> languages;
  final String improves;
  final bool builtin;
  final ModelUseState state;
  final bool capable;
  final String capableReason;
  final bool recommended;

  /// The `focus` the engine sent for the model, if any (else [focus] reads it from [languages]).
  final LanguageFocus? focusSent;
  final ModelQuality? quality;

  /// Which language group a text model belongs to: English only, Hindi first, or many languages.
  LanguageFocus get focus {
    if (focusSent != null) return focusSent!;
    final l = [for (final x in languages) x.trim().toLowerCase()];
    if (l.isEmpty || l.every((x) => x == 'en')) return LanguageFocus.english;
    return l.first == 'hi' ? LanguageFocus.hindi : LanguageFocus.multilingual;
  }

  /// "English, Hindi, about 100 languages".
  String get languageText => [for (final x in languages) _language(x)].join(', ');

  ModelInfo withState(ModelUseState s, {bool? recommended}) => ModelInfo(
    id: id,
    feature: feature,
    name: name,
    tier: tier,
    licence: licence,
    source: source,
    sizeMb: sizeMb,
    ramMb: ramMb,
    speedNote: speedNote,
    languages: languages,
    improves: improves,
    builtin: builtin,
    state: s,
    capable: capable,
    capableReason: capableReason,
    recommended: recommended ?? this.recommended,
    focusSent: focusSent,
    quality: quality,
    dir: dir,
    vramMb: vramMb,
    runtime: runtime,
  );

  bool get onDisk => builtin || state == ModelUseState.ready || state == ModelUseState.active;

  static ModelInfo? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return ModelInfo(
      id: jStr(m['id']),
      feature: jStr(m['feature']),
      name: jStr(m['name']),
      tier: jStr(m['tier']),
      licence: jStr(m['licence']),
      source: jStr(m['source']),
      sizeMb: jNum(m['size_mb']),
      ramMb: jNum(m['ram_mb']),
      speedNote: jStr(m['speed_note']),
      languages: jStrs(m['languages']),
      improves: jStr(m['improves']),
      builtin: jBool(m['builtin']),
      state: _states[m['state']] ?? ModelUseState.notDownloaded,
      capable: m['capable'] != false,
      capableReason: jStr(m['capable_reason']),
      recommended: jBool(m['recommended']),
      focusSent: LanguageFocus.parse(m['focus']),
      quality: ModelQuality.fromJson(m['quality']),
      dir: jStr(m['dir']),
      vramMb: jNum(m['vram_mb']),
      runtime: jStr(m['runtime']),
    );
  }
}

class ModelsInfo {
  const ModelsInfo({
    this.pc,
    this.tierRecommended = '',
    this.tierCurrent = '',
    this.languageFocus,
    this.models = const [],
  });
  final Hardware? pc;
  final String tierRecommended;
  final String tierCurrent;

  /// Null from an engine that doesn't send it: the language choice isn't shown.
  final LanguageFocus? languageFocus;
  final List<ModelInfo> models;

  List<ModelInfo> byFeature(String feature) => [
    for (final m in models)
      if (m.feature == feature) m,
  ];

  ModelInfo? byId(String id) => models.where((m) => m.id == id).firstOrNull;

  /// 1.1: the runtime a talk model still needs downloaded with it (null: on disk, on its way, or none named).
  ModelInfo? runtimeToFetch(ModelInfo m) {
    final rt = m.runtime.isEmpty ? null : byId(m.runtime);
    return rt == null || rt.onDisk || rt.state == ModelUseState.downloading ? null : rt;
  }

  static ModelsInfo fromJson(Object? v) {
    final m = jMap(v);
    return ModelsInfo(
      pc: Hardware.fromJson(m['pc']),
      tierRecommended: jStr(m['tier_recommended']),
      tierCurrent: jStr(m['tier_current']),
      languageFocus: LanguageFocus.parse(m['language_focus']),
      models: jList(m['models'], ModelInfo.fromJson),
    );
  }
}

/// `model_use` answer.
class ModelUse {
  const ModelUse(this.ok, {this.error = '', this.needsDownload = false});
  final bool ok;
  final String error;
  final bool needsDownload;

  static ModelUse fromJson(Object? v) {
    final m = jMap(v);
    return ModelUse(jBool(m['ok']), error: jStr(m['error']), needsDownload: jBool(m['needs_download']));
  }
}

class AutoStep {
  const AutoStep({required this.feature, required this.id, this.needsDownload = false});
  final String feature;
  final String id;
  final bool needsDownload;
}

/// `auto_configure` answer: the tier it chose and what it changes (downloads still need consent).
class AutoConfig {
  const AutoConfig({this.tier = '', this.steps = const []});
  final String tier;
  final List<AutoStep> steps;

  static AutoConfig fromJson(Object? v) {
    final m = jMap(v);
    return AutoConfig(
      tier: jStr(m['tier']),
      steps: jList(m['steps'], (s) {
        final x = jMap(s);
        if (jStr(x['id']).isEmpty) return null;
        return AutoStep(feature: jStr(x['feature']), id: jStr(x['id']), needsDownload: jBool(x['needs_download']));
      }),
    );
  }
}

/// The live numbers behind [CapabilityState] (contract `capability_state.budget`); null = unknown right now.
class CapabilityBudget {
  const CapabilityBudget({
    this.live = false,
    this.installedMb,
    this.freeMb,
    this.reserveMb = 0,
    this.usableMb,
    this.commitPct,
    this.commitFreeMb,
    this.gpuKind,
    this.gpuFreeMb,
    this.gpuBudgetMb,
    this.cpu,
    this.gpu,
    this.battery = false,
    this.batterySaver = false,
  });
  final bool live;
  final int? installedMb;
  final int? freeMb;
  final int reserveMb;
  final int? usableMb;
  final double? commitPct;
  final int? commitFreeMb;

  /// 'dedicated' (a graphics card's own memory) or 'shared' (an integrated GPU such as Intel Iris Xe), or null.
  final String? gpuKind;
  final int? gpuFreeMb;
  final int? gpuBudgetMb;
  final double? cpu;
  final double? gpu;
  final bool battery;
  final bool batterySaver;

  static CapabilityBudget fromJson(Object? v) {
    final m = jMap(v);
    final kind = jStr(m['gpu_kind']);
    return CapabilityBudget(
      live: jBool(m['live']),
      installedMb: jIntOrNull(m['installed_mb']),
      freeMb: jIntOrNull(m['free_mb']),
      reserveMb: jInt(m['reserve_mb']),
      usableMb: jIntOrNull(m['usable_mb']),
      commitPct: jNumOrNull(m['commit_pct']),
      commitFreeMb: jIntOrNull(m['commit_free_mb']),
      gpuKind: kind.isEmpty ? null : kind,
      gpuFreeMb: jIntOrNull(m['gpu_free_mb']),
      gpuBudgetMb: jIntOrNull(m['gpu_budget_mb']),
      cpu: jNumOrNull(m['cpu']),
      gpu: jNumOrNull(m['gpu']),
      battery: jBool(m['battery']),
      batterySaver: jBool(m['battery_saver']),
    );
  }
}

/// `capability_state` (2026-11-21): which models this PC can run RIGHT NOW, from free memory, commit, graphics
/// memory, load and battery, not the installed memory alone. A model the engine didn't list is unknown (null).
class CapabilityState {
  const CapabilityState({
    this.canRun = const {},
    this.why = const {},
    this.device = const {},
    this.budget = const CapabilityBudget(),
  });
  final Map<String, bool> canRun;
  final Map<String, String> why;
  final Map<String, String> device;
  final CapabilityBudget budget;

  bool? runsNow(String id) => canRun[id];

  static CapabilityState fromJson(Object? v) {
    final m = jMap(v);
    return CapabilityState(
      canRun: {
        for (final e in jMap(m['can_run']).entries)
          if (e.value is bool) e.key: e.value as bool,
      },
      why: {for (final e in jMap(m['why']).entries) e.key: jStr(e.value)},
      device: {for (final e in jMap(m['device']).entries) e.key: jStr(e.value)},
      budget: CapabilityBudget.fromJson(m['budget']),
    );
  }
}

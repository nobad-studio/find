/// Talk about a photo (find 1.1, contract "Talk about a photo"): `vision_state`, the answers of `vision_describe`,
/// `vision_ask`, `vision_compare`, `vision_cancel` and `vision_keep`. The answer itself comes as `vision` events.
library;

import 'json.dart';

/// One talk model in `vision_state.models`: the quick one first, the deeper one second.
class VisionModel {
  const VisionModel({
    required this.id,
    required this.name,
    this.deeper = false,
    this.ready = false,
    this.missingMb = 0,
    this.ramMb = 0,
    this.vramMb = 0,
    this.canRun = false,
    this.why = '',
  });

  final String id;
  final String name;
  final bool deeper;
  final bool ready;
  final int missingMb;

  /// Peak memory while it answers (measured, docs/measurements.md).
  final int ramMb;
  final int vramMb;

  /// Fits this PC right now; else [why] says why not (a sentence, maybe already "Not now: …").
  final bool canRun;
  final String why;

  /// The name as the UI writes it ("Qwen3-VL 2B" -> "Qwen3-VL-2B").
  String get label => name.trim().replaceAll(RegExp(r'\s+'), '-');

  static VisionModel? fromJson(Object? json) {
    final m = jMap(json);
    final id = jStr(m['id']);
    if (id.isEmpty) return null;
    return VisionModel(
      id: id,
      name: jStr(m['name']).isEmpty ? id : jStr(m['name']),
      deeper: jBool(m['deeper']),
      ready: jBool(m['ready']),
      missingMb: jInt(m['missing_mb']),
      ramMb: jInt(m['ram_mb']),
      vramMb: jInt(m['vram_mb']),
      canRun: jBool(m['can_run']),
      why: jStr(m['why']),
    );
  }
}

/// `vision_state`: can a question start now, the models, what is in memory, whether one is being answered.
class VisionState {
  const VisionState({
    this.ok = true,
    this.error = '',
    this.job,
    this.notNow = '',
    this.models = const [],
    this.runtimeId = '',
    this.runtimeReady = false,
    this.runtimeMissingMb = 0,
    this.loaded = '',
    this.busy = false,
    this.running = false,
  });

  final bool ok;
  final String error;
  final int? job;

  /// A sentence when nothing can start now (paused, the runtime downloading), else ''.
  final String notNow;
  final List<VisionModel> models;
  final String runtimeId;
  final bool runtimeReady;
  final int runtimeMissingMb;
  final String loaded;
  final bool busy;
  final bool running;

  VisionModel? get quick => models.where((m) => !m.deeper).firstOrNull;
  VisionModel? get deeper => models.where((m) => m.deeper).firstOrNull;
  VisionModel? byId(String id) => models.where((m) => m.id == id).firstOrNull;

  static VisionState fromJson(Object? json) {
    final m = jMap(json);
    final rt = jMap(m['runtime']);
    return VisionState(
      ok: m['ok'] != false,
      error: jStr(m['error']),
      job: jIntOrNull(m['job']),
      notNow: jStr(m['not_now']),
      models: jList(m['models'], VisionModel.fromJson),
      runtimeId: jStr(rt['id']),
      runtimeReady: jBool(rt['ready']),
      runtimeMissingMb: jInt(rt['missing_mb']),
      loaded: jStr(m['loaded']),
      busy: jBool(m['busy']),
      running: jBool(m['running']),
    );
  }
}

/// What has to be downloaded first when that is why a question can't start.
class VisionDownload {
  const VisionDownload({required this.id, required this.name, this.sizeMb = 0});
  final String id;
  final String name;
  final int sizeMb;

  static VisionDownload? fromJson(Object? json) {
    final m = jMap(json);
    final id = jStr(m['id']);
    return id.isEmpty ? null : VisionDownload(id: id, name: jStr(m['name']), sizeMb: jInt(m['size_mb']));
  }
}

/// Every vision_* call's answer: `{ok, error, job, download?}`; [job] null when no job started.
class VisionAnswer {
  const VisionAnswer({this.ok = false, this.error = '', this.job, this.download = const [], this.kept = false});
  final bool ok;
  final String error;
  final int? job;
  final List<VisionDownload> download;

  /// vision_keep only: the description is kept (false: forgotten, or not kept).
  final bool kept;

  static VisionAnswer fromJson(Object? json) {
    final m = jMap(json);
    return VisionAnswer(
      ok: jBool(m['ok']),
      error: jStr(m['error']),
      job: jIntOrNull(m['job']),
      download: jList(m['download'], VisionDownload.fromJson),
      kept: jBool(m['kept']),
    );
  }
}

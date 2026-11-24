/// The first-run models window (contract 1.2.0 `setup_offer`, `setup_accept`, `setup_later`): what this PC is
/// like, the models suggested for it with what each costs as measured, why, and how long indexing what the first
/// scan counted takes. Download in the window is the consent.
library;

import 'json.dart';
import 'settings.dart' show Hardware;

/// What a model costs, as measured (`cost_here`). Null: not measured.
class SetupCost {
  const SetupCost({
    this.ramMb,
    this.itemsS,
    this.queryMs,
    this.answerS,
    this.loadS,
    this.gpuMb,
    this.sharedMb,
    this.indexH,
    this.measuredOn = '',
  });
  final double? ramMb;
  final double? itemsS;
  final double? queryMs;
  final double? answerS;
  final double? loadS;

  /// A graphics card's own memory it needs.
  final double? gpuMb;

  /// Built-in graphics' memory it holds: the PC's memory, already in [ramMb].
  final double? sharedMb;

  /// Hours to look at the photos the first scan found (again), from the measured speed. Null: not known.
  final double? indexH;

  /// `this PC`, `similar PC` or `reference PC`.
  final String measuredOn;

  /// Nothing was measured (the engine sent `{}`).
  bool get isEmpty =>
      ramMb == null &&
      itemsS == null &&
      queryMs == null &&
      answerS == null &&
      loadS == null &&
      gpuMb == null &&
      sharedMb == null &&
      indexH == null;

  bool get here => measuredOn == 'this PC';

  /// "on this PC", "on the reference PC" or "on a similar PC".
  String get place => switch (measuredOn) {
    'this PC' => 'on this PC',
    'reference PC' => 'on the reference PC',
    _ => 'on a similar PC',
  };

  static SetupCost fromJson(Object? v) {
    final m = jMap(v);
    return SetupCost(
      ramMb: jNumOrNull(m['ram_mb']),
      itemsS: jNumOrNull(m['items_s']),
      queryMs: jNumOrNull(m['query_ms']),
      answerS: jNumOrNull(m['answer_s']),
      loadS: jNumOrNull(m['load_s']),
      gpuMb: jNumOrNull(m['gpu_mb']),
      sharedMb: jNumOrNull(m['shared_mb']),
      indexH: jNumOrNull(m['index_h']),
      measuredOn: jStr(m['measured_on']),
    );
  }
}

/// A talk model's llama.cpp runtime for this PC, fetched in the same consent.
class SetupRuntime {
  const SetupRuntime({required this.id, this.name = '', this.sizeMb = 0, this.source = ''});
  final String id;
  final String name;
  final int sizeMb;
  final String source;

  static SetupRuntime? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return SetupRuntime(
      id: jStr(m['id']),
      name: jStr(m['name']),
      sizeMb: jInt(m['size_mb']),
      source: jStr(m['source']),
    );
  }
}

class SetupItem {
  const SetupItem({
    required this.model,
    this.workload = 'text',
    this.name = '',
    this.outcome = 'suggested',
    this.group = 'suggested',
    this.sizeMb = 0,
    this.cost = const SetupCost(),
    this.why = '',
    this.estIndex = '',
    this.checked = false,
    this.onDisk = false,
    this.state = 'not_downloaded',
    this.error = '',
    this.licence = '',
    this.source = '',
    this.runtime,
  });
  final String model;

  /// text | photo_search | photo_talk
  final String workload;
  final String name;

  /// suggested | upgrade | lighter | not_measured
  final String outcome;

  /// suggested | more ("More for this PC")
  final String group;

  /// MB still to download, with the runtime for a talk model.
  final int sizeMb;
  final SetupCost cost;
  final String why;
  final String estIndex;
  final bool checked;
  final bool onDisk;

  /// not_downloaded | downloading | ready | failed
  final String state;
  final String error;
  final String licence;
  final String source;
  final SetupRuntime? runtime;

  bool get more => group == 'more';
  bool get talk => workload == 'photo_talk';

  static SetupItem? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['model']).isEmpty) return null;
    return SetupItem(
      model: jStr(m['model']),
      workload: jStr(m['workload']),
      name: jStr(m['name']),
      outcome: jStr(m['outcome']),
      group: jStr(m['group']),
      sizeMb: jInt(m['size_mb']),
      cost: SetupCost.fromJson(m['cost_here']),
      why: jStr(m['why']),
      estIndex: jStr(m['est_index']),
      checked: jBool(m['checked']),
      onDisk: jBool(m['on_disk']),
      state: jStr(m['state']),
      error: jStr(m['error']),
      licence: jStr(m['licence']),
      source: jStr(m['source']),
      runtime: SetupRuntime.fromJson(m['runtime']),
    );
  }
}

class SetupOffer {
  const SetupOffer({
    this.show = false,
    this.state = 'pending',
    this.walked = false,
    this.like = '',
    this.summary = '',
    this.hardware,
    this.items = const [],
    this.notes = const [],
    this.totalMb = 0,
    this.estDownload,
  });
  final bool show;

  /// pending | later | accepted | done
  final String state;
  final bool walked;

  /// low | mid | high: the nearest reference profile (an explanation, never a budget).
  final String like;
  final String summary;
  final Hardware? hardware;
  final List<SetupItem> items;
  final List<String> notes;
  final int totalMb;

  /// Null until a download measured this PC's speed.
  final String? estDownload;

  static SetupOffer fromJson(Object? v) {
    final m = jMap(v);
    final pc = jMap(m['pc']);
    final est = m['est_download'];
    return SetupOffer(
      show: jBool(m['show']),
      state: jStr(m['state']),
      walked: jBool(m['walked']),
      like: jStr(pc['like']),
      summary: jStr(pc['summary']),
      hardware: Hardware.fromJson(pc['hardware']),
      items: jList(m['items'], SetupItem.fromJson),
      notes: jStrs(m['notes']),
      totalMb: jInt(m['total_mb']),
      estDownload: est is String && est.isNotEmpty ? est : null,
    );
  }
}

/// `setup_accept`'s answer: the downloads it started.
class SetupAccept {
  const SetupAccept(this.ok, {this.error = '', this.started = const []});
  final bool ok;
  final String error;
  final List<String> started;

  static SetupAccept fromJson(Object? v) {
    final m = jMap(v);
    return SetupAccept(jBool(m['ok']), error: jStr(m['error']), started: jStrs(m['started']));
  }
}

/// MB to download for [checked] of [items]: each model once, a runtime two talk models share once.
int setupTotalMb(List<SetupItem> items, Set<String> checked) {
  final seen = <String>{};
  var total = 0;
  for (final i in items) {
    if (!checked.contains(i.model)) continue;
    final rt = i.runtime;
    total += i.sizeMb - (rt?.sizeMb ?? 0);
    if (rt != null && seen.add(rt.id)) total += rt.sizeMb;
  }
  return total;
}

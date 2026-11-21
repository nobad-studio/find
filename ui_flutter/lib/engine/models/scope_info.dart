/// What is indexed, and the turbo index (contract additions: `scope_info`, `turbo_state`, `turbo_set`, the `turbo`
/// event; settings `scope`, `include_system`, `include_caches`, `include_secrets`, read-only `turbo`).
/// Every name, reason and example path is untrusted text from the engine: shown as plain text.
library;

import 'json.dart';

enum IndexScope {
  wholePc('whole_pc', 'Whole PC'),
  myFiles('my_files', 'My files'),
  custom('custom', 'Custom');

  const IndexScope(this.wire, this.label);
  final String wire;
  final String label;

  static IndexScope? parse(Object? v) => values.where((s) => s.wire == v).firstOrNull;
}

/// all: only the names are indexed, the contents are never read (secrets); some: part of it is (browser profiles and
/// app databases in caches); none: read like any other file (also from an engine that doesn't say).
enum NamesOnly {
  none,
  some,
  all;

  static NamesOnly parse(Object? v) => values.where((x) => x.name == v).firstOrNull ?? none;
}

/// One kind of place, listed so nothing is skipped silently.
class ScopeCategory {
  const ScopeCategory({
    required this.id,
    this.name = '',
    this.summary = '',
    this.why = '',
    this.examples = const [],
    this.included = false,
    this.locked = false,
    this.namesOnly = NamesOnly.none,
    this.count,
  });

  /// system | caches | secrets | other_profiles | removable | network (others from a newer engine: shown, no switch).
  final String id;
  final String name;

  /// One short line for its card ('' from an older engine: [line] uses the first sentence of [why]).
  final String summary;
  final String why;
  final List<String> examples;
  final bool included;
  final bool locked;

  /// Whether its files are only listed by name (never read).
  final NamesOnly namesOnly;

  /// The card's one line: [summary], else the first sentence of [why].
  String get line {
    if (summary.isNotEmpty) return summary;
    final i = why.indexOf('. ');
    return i < 0 ? why : why.substring(0, i + 1);
  }

  /// Entries of it in the index; null when it can't be counted cheaply.
  final int? count;

  /// The setting its switch changes ('' = none this UI knows).
  String get setting =>
      const {
        'system': 'include_system',
        'caches': 'include_caches',
        'secrets': 'include_secrets',
        'removable': 'index_removable',
        'network': 'index_network',
      }[id] ??
      '';

  static ScopeCategory? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return ScopeCategory(
      id: jStr(m['id']),
      name: jStr(m['name']),
      summary: jStr(m['summary']),
      why: jStr(m['why']),
      examples: jStrs(m['examples']),
      included: jBool(m['included']),
      locked: jBool(m['locked']),
      namesOnly: NamesOnly.parse(m['names_only']),
      count: jIntOrNull(m['count']),
    );
  }
}

class ScopeInfo {
  const ScopeInfo({this.scope, this.roots = const [], this.categories = const []});
  final IndexScope? scope;
  final List<String> roots;
  final List<ScopeCategory> categories;

  static ScopeInfo fromJson(Object? v) {
    final m = jMap(v);
    return ScopeInfo(
      scope: IndexScope.parse(m['scope']),
      roots: jStrs(m['roots']),
      categories: jList(m['categories'], ScopeCategory.fromJson),
    );
  }
}

class TurboVolume {
  const TurboVolume({required this.drive, this.ntfs = false, this.files = 0, this.usnOk = false, this.lastScan});
  final String drive;

  /// "C:" (the engine may send "C:" with a backslash).
  String get label => drive.endsWith(r'\') ? drive.substring(0, drive.length - 1) : drive;
  final bool ntfs;
  final int files;

  /// Changes on the drive come from its change journal.
  final bool usnOk;

  /// Seconds since 1970, or null (not read yet).
  final double? lastScan;

  static TurboVolume? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['drive']).isEmpty) return null;
    final t = m['last_scan'];
    return TurboVolume(
      drive: jStr(m['drive']),
      ntfs: jBool(m['ntfs']),
      files: jInt(m['files']),
      usnOk: jBool(m['usn_ok']),
      lastScan: t is num ? t.toDouble() : null,
    );
  }
}

/// The turbo helper's one-time setup (2026-11-21: Windows asks once, when turbo is turned on).
enum TurboHelper {
  /// Nothing set up (always so from source, or an older engine).
  notInstalled,

  /// Set up for this account: turbo starts with no prompt.
  installed,

  /// NOBAD Find was updated (or it was set up for a NOBAD Find in another folder): the normal walk is used until the
  /// user OKs the update once.
  needsUpdate;

  static TurboHelper parse(Object? v) => switch (v) {
    'installed' => installed,
    'needs_update' => needsUpdate,
    _ => notInstalled,
  };
}

class TurboState {
  const TurboState({
    this.available = false,
    this.enabled = false,
    this.running = false,
    this.volumes = const [],
    this.error = '',
    this.helper = TurboHelper.notInstalled,
  });

  /// Whether the helper is set up and current (`installed`, `needs_update`, `not_installed`).
  final TurboHelper helper;

  /// "Update helper" is offered.
  bool get needsUpdate => helper == TurboHelper.needsUpdate;

  /// "Remove" is offered: something is set up.
  bool get removable => helper != TurboHelper.notInstalled;

  /// An NTFS fixed drive is there.
  final bool available;

  /// The `turbo` setting.
  final bool enabled;

  /// The elevated helper is connected.
  final bool running;
  final List<TurboVolume> volumes;

  /// '' or why it isn't running (the normal folder walk is used then).
  final String error;

  /// "Turbo: on (C: NTFS)", or why it is off: the Index page's line.
  String get line {
    if (running) {
      final d = [
        for (final v in volumes)
          if (v.ntfs) v.label,
      ];
      return 'Turbo: on${d.isEmpty ? '' : ' (${d.join(', ')} NTFS)'}';
    }
    if (enabled && needsUpdate) return 'Turbo: needs your OK once to update its helper (Settings → What to index)';
    if (error.isNotEmpty) return 'Turbo: off. $error';
    if (!available) return 'Turbo: not available (no NTFS fixed drive)';
    if (enabled) return 'Turbo: starting';
    return 'Turbo: off (Settings → What to index)';
  }

  static TurboState fromJson(Object? v) {
    final m = jMap(v);
    return TurboState(
      available: jBool(m['available']),
      enabled: jBool(m['enabled']),
      running: jBool(m['running']),
      volumes: jList(m['volumes'], TurboVolume.fromJson),
      error: jStr(m['error']),
      helper: TurboHelper.parse(m['helper']),
    );
  }
}

/// `turbo_set` and `turbo_helper` answer.
class TurboSet {
  const TurboSet(this.ok, {this.error = '', this.state});
  final bool ok;
  final String error;
  final TurboState? state;

  static TurboSet fromJson(Object? v) {
    final m = jMap(v);
    return TurboSet(
      jBool(m['ok']),
      error: jStr(m['error']),
      state: m['state'] is Map ? TurboState.fromJson(m['state']) : null,
    );
  }
}

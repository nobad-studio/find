/// In-app updates (0.9.0, engine update.py): `update_state` and the `update` event.
library;

import 'json.dart';

class UpdateState {
  const UpdateState({
    this.state = 'idle',
    this.current = '',
    this.latest = '',
    this.size = 0,
    this.got = 0,
    this.notesUrl = '',
    this.error = '',
    this.auto = true,
    this.checkedAt = 0,
  });

  /// idle | checking | uptodate | available | downloading | ready | installing | error.
  final String state;
  final String current;
  final String latest;
  final int size;
  final int got;
  final String notesUrl;
  final String error;
  final bool auto;
  final int checkedAt;

  static const unknown = UpdateState();

  /// A newer version can be installed now (found, or already downloaded and checked).
  bool get canInstall => latest.isNotEmpty && (state == 'available' || state == 'ready' || (state == 'error' && latest != current));
  bool get busy => state == 'checking' || state == 'downloading' || state == 'installing';
  double get fraction => size > 0 ? (got / size).clamp(0.0, 1.0) : 0.0;

  static UpdateState fromJson(Object? v) {
    final m = jMap(v);
    return UpdateState(
      state: jStr(m['state']).isEmpty ? 'idle' : jStr(m['state']),
      current: jStr(m['current']),
      latest: jStr(m['latest']),
      size: jInt(m['size']),
      got: jInt(m['got']),
      notesUrl: jStr(m['notes_url']),
      error: jStr(m['error']),
      auto: m['auto'] != false,
      checkedAt: jInt(m['checked_at']),
    );
  }
}

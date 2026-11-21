/// Recent searches (the chips under the empty box, Settings > Search): the engine's own search history
/// (`history.py`, inside the encrypted index, only while the `search_history` setting is on), asked for with
/// `suggest` on an empty box, newest first. The UI keeps no copy of its own: off means none are kept or shown, and
/// "Clear" here or in Settings > Privacy clears that one history. Up to 0.9.3 the UI kept a plain-text list in
/// `ui-recent.json`; [removeOldFile] deletes it once at start.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';

class RecentSearches extends ChangeNotifier {
  RecentSearches(this.engine) {
    engine.link.addListener(_relink);
    if (engine.link.value == Link.connected) unawaited(refresh());
  }

  final EngineApi engine;

  /// At most this many chips (the engine gives up to 6 for an empty box).
  static const max = 6;
  List<String> _items = const [];
  int _seq = 0;
  bool _disposed = false;

  List<String> get items => _items;

  void _relink() {
    if (engine.link.value == Link.connected) unawaited(refresh());
  }

  void _set(List<String> items) {
    if (_disposed || listEquals(items, _items)) return;
    _items = items;
    notifyListeners();
  }

  /// Ask the engine again (start, a used search, the box emptied, the setting switched). Offline: what is shown stays.
  Future<void> refresh() async {
    final my = ++_seq;
    List<String> got;
    try {
      final s = await engine.suggest('');
      got = [
        for (final i in s.items)
          if (i.kind == 'history' && i.text.trim().isNotEmpty) i.text,
      ].take(max).toList();
    } on Object {
      return;
    }
    if (my == _seq) _set(got);
  }

  /// The engine kept [words] (history_add said saved): first now, then as the engine has it.
  void kept(String words) {
    final w = words.trim();
    if (w.isEmpty) return;
    ++_seq; // an older answer in flight doesn't put the list back
    _set(
      [
        w,
        for (final x in _items)
          if (x.toLowerCase() != w.toLowerCase()) x,
      ].take(max).toList(),
    );
    unawaited(refresh());
  }

  /// The search_history setting went off: nothing is shown (the engine deletes what it kept).
  void off() {
    ++_seq;
    _set(const []);
  }

  /// "Clear": the engine forgets every kept question (the same as Settings > Privacy > Clear search history).
  Future<bool> clear() async {
    ++_seq;
    _set(const []);
    try {
      return (await engine.historyClear()).ok;
    } on Object {
      return false;
    }
  }

  /// `%LOCALAPPDATA%\NOBAD\Find\ui-recent.json`, the plain-text list the UI kept up to 0.9.3.
  static File? oldFile() {
    final base =
        Platform.environment['NOBAD_FIND_DATA_DIR'] ??
        (Platform.environment['LOCALAPPDATA'] == null ? null : '${Platform.environment['LOCALAPPDATA']}\\NOBAD\\Find');
    return base == null ? null : File('$base\\ui-recent.json');
  }

  /// Deletes the old plain-text list, so no copy of past searches lingers outside the encrypted index.
  static Future<void> removeOldFile([File? file]) async {
    final f = file ?? oldFile();
    try {
      if (f != null && f.existsSync()) await f.delete();
    } on Object {
      // tried again at the next start
    }
  }

  @override
  void dispose() {
    _disposed = true;
    engine.link.removeListener(_relink);
    super.dispose();
  }
}

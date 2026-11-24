/// An in-memory engine with the contract's shapes (contract, protocol 1) and a small made-up index. Used
/// only by the tests, the goldens and the explicit `NOBAD_FIND_FAKE_ENGINE=1` demo; the app never falls back to it.
///
/// With [live] it also does what the engine does on its own: `status` every 2 s, `status_full` every 2 s while
/// watched, and download progress. That's the engine's side; the UI still only listens.
library;

import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'models/graphics.dart';
import 'models/json.dart';
import 'models/models_info.dart';
import 'models/scope_info.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';
import 'models/update.dart';

/// The first-run offer on the reference PC (contract transcript 11): GTE small (the tier's pick, not measured),
/// SigLIP 2 suggested and ticked, SmolVLM2 suggested but unticked, Qwen3-VL under More for this PC.
SetupOffer demoSetupOffer(Hardware pc) {
  const rt = SetupRuntime(id: 'llama-vulkan', name: 'llama.cpp runtime (graphics card)', sizeMb: 37, source: 'github.com');
  return SetupOffer(
    walked: true,
    like: 'mid',
    summary: 'This PC is like: Mid: 16 processor threads and 15.7 GB; High needs a graphics card with 4 GB or more of '
        'its own',
    hardware: pc,
    items: const [
      SetupItem(
        model: 'gte-small',
        name: 'GTE small (English)',
        outcome: 'not_measured',
        sizeMb: 33,
        cost: SetupCost(ramMb: 56, itemsS: 54.3, measuredOn: 'reference PC'),
        why: "For this PC's 15.7 GB of memory and 8 cores: GTE small (English). Not a measured suggestion: text "
            'models have no measured floor yet.',
        estIndex: 'under a minute for 3,180 documents (on the reference PC)',
        licence: 'MIT',
        source: 'huggingface.co',
      ),
      SetupItem(
        model: 'siglip2-base',
        workload: 'photo_search',
        name: 'SigLIP 2 base',
        sizeMb: 481,
        cost: SetupCost(ramMb: 621, itemsS: 1.416, queryMs: 196.5, measuredOn: 'similar PC'),
        why: 'Suggested: SigLIP 2 base: a search takes about 196 ms, it indexes 1.42 photos a second, 621 MB of '
            'memory (measured on a similar PC)',
        estIndex: 'about 15 min for 1,240 photos (on a similar PC)',
        checked: true,
        licence: 'Apache-2.0',
        source: 'huggingface.co',
      ),
      SetupItem(
        model: 'smolvlm2-500m',
        workload: 'photo_talk',
        name: 'SmolVLM2 500M',
        sizeMb: 557,
        cost: SetupCost(ramMb: 1033, answerS: 5.77, loadS: 1.27, sharedMb: 663, measuredOn: 'similar PC'),
        why: 'Suggested: SmolVLM2 500M: first word about 6 s, 663 MB of memory, shared with the built-in graphics '
            '(measured on a similar PC)',
        licence: 'Apache-2.0',
        source: 'huggingface.co',
        runtime: rt,
      ),
      SetupItem(
        model: 'qwen3vl-2b',
        workload: 'photo_talk',
        name: 'Qwen3-VL 2B',
        outcome: 'upgrade',
        group: 'more',
        sizeMb: 1518,
        cost: SetupCost(ramMb: 2491, answerS: 12.08, loadS: 6.21, sharedMb: 2058, measuredOn: 'similar PC'),
        why: 'Upgrade: Qwen3-VL 2B: more memory (2,491 MB), longer loading and answers (12 s on a similar PC)',
        licence: 'Apache-2.0',
        source: 'huggingface.co',
        runtime: rt,
      ),
    ],
    totalMb: 481,
  );
}

class FakeEngine implements EngineApi {
  FakeEngine({
    List<FileResult>? files,
    Link link = Link.connected,
    Map<String, Object?> settings = const {'welcome_seen': true, 'bg_notice_seen': true},
    this.live = false,
    this.suggestions = false,
    DateTime Function()? clock,
    this.gpu = GraphicsKind.integrated,
  }) : files = files ?? sampleFiles(),
       _clock = clock ?? (() => DateTime(2026, 11, 19, 14, 30)) {
    _link.value = link;
    _settings = {...Settings.defaults, ...scopeDefaults, ...settings};
    _brief = const EngineStatus(level: 'gentle', reason: _gentle, phase: 'text', files: 48210);
    if (live) _ticker = Timer.periodic(const Duration(seconds: 2), (_) => _tick());
  }

  /// The find-turbo-index settings (an engine with `scope_info`); `turbo` is read-only (turbo_set changes it).
  static const scopeDefaults = <String, Object?>{
    'scope': 'my_files',
    'include_system': false,
    'include_caches': false,
    'include_secrets': false,
  };

  static const _gentle = "Gentle: you're using the PC, so NOBAD Find works with 2 of 16 threads.";

  final List<FileResult> files;
  final bool live;

  /// The made-up PC's graphics (NOBAD_FIND_FAKE_GPU in the demo): Iris Xe only by default, like the reference PC.
  final GraphicsKind gpu;

  /// `hardware` for that PC (tests may replace it, e.g. with a backend that is gone).
  late Hardware pc = fakeHardware(gpu);

  /// Answer `suggest` (0.8.5). Off: like an engine without autocomplete (the older tests count rows and texts).
  final bool suggestions;
  final DateTime Function() _clock;
  final _link = ValueNotifier(Link.connected);
  final _events = StreamController<EngineEvent>.broadcast(sync: true);
  late Map<String, Object?> _settings;
  late EngineStatus _brief;
  Timer? _ticker;
  final _downloads = <String, Timer>{};
  final _models = <String, ModelState>{'meaning': const ModelState(), 'photo': const ModelState()};
  var _watching = false;
  var _tickN = 0;

  // What the UI asked for (tests read these).
  final searches = <String>[];
  final searchFilters = <SearchFilters>[];
  final opened = <int>[];
  final revealed = <int>[];
  final thumbsAsked = <int>[];
  final forgotten = <int>[];
  final settingsSet = <Map<String, Object?>>[];

  /// The consent word sent with each set_settings (null: none).
  final consents = <String?>[];
  final calls = <String>[];
  bool openOk = true;

  /// Not empty: forget refuses with this message (the Never index list is full).
  String forgetError = '';

  /// ok with a note (1.1.0): forgotten, but the engine's protected list couldn't be saved yet.
  String forgetNote = '';
  bool pickBusy = false;
  bool offline = false;

  /// The next set_settings fails with this (tests).
  RpcException? failNext;

  /// wipe answers ok: false with this sentence (tests).
  String wipeError = '';
  String here = '';
  String pickAnswer = r'C:\Users\me\Projects';
  List<LearnedApp> learned = [
    const LearnedApp(
      exe: 'Cyberpunk2077.exe',
      seen: 6,
      lagEvents: 2,
      reason: 'Lagged twice in the last 14 days, so NOBAD Find pauses while it runs.',
    ),
    const LearnedApp(
      exe: 'Resolve.exe',
      seen: 3,
      lagEvents: 1,
      reason: 'Lagged once, so NOBAD Find works with 1 worker while it runs.',
    ),
  ];
  WsearchState wsearch = const WsearchState(start: 'delayed-auto', running: true);

  set linkState(Link l) => _link.value = l;
  bool get watching => _watching;

  void emit(EngineEvent e) {
    if (e is StatusEvent) _brief = e.status;
    if (!_events.isClosed) _events.add(e);
  }

  @override
  ValueListenable<Link> get link => _link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  EngineStatus? get lastStatus => _brief;

  Future<T> _answer<T>(String name, T Function() f) async {
    calls.add(name);
    if (offline) throw const EngineOffline();
    return f();
  }

  static const _ok = ActionResult(true);

  // ---------- search and results ----------
  /// Tests: how long an answer takes (the searching ring shows after 150 ms of it).
  Duration searchDelay = Duration.zero;

  @override
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none, String channel = 'main'}) async {
    if (searchDelay > Duration.zero) await Future<void>.delayed(searchDelay);
    return _search(text, filters, channel);
  }

  Future<SearchAnswer> _search(String text, SearchFilters filters, String channel) =>
      _answer('search', () {
        searches.add(text);
        channels.add(channel);
        searchFilters.add(filters);
        final t = text.trim().toLowerCase();
        if (t.isEmpty && !filters.narrows && filters.sort.isEmpty) return SearchAnswer.empty;
        // 1.2.0: Settings & apps: only the actions, never a file (the engine's Api._launcher_only)
        if (filters.isLauncher) return SearchAnswer(ms: 1, actions: t.isEmpty ? const [] : searchActions);
        // 1.2.0: the browsers' items, only while browser data is read (the engine's browsersearch.py)
        final reading = jStr(_settings['browser_data']).isNotEmpty && _settings['browser_data'] != 'off';
        bool browserFits(FileResult r) {
          final b = r.browser!;
          if (b.kind == 'login' && _settings['browser_data'] != 'history_logins') return false;
          if (filters.isBrowser && filters.browser.isNotEmpty && b.kind != filters.browser) return false;
          final words = t.split(RegExp(r'\s+')).where((w) => w.isNotEmpty && !_stop.contains(w));
          final hay = '${r.name} ${b.url} ${b.host}'.toLowerCase();
          return words.every(hay.contains);
        }

        final web = !reading || (!filters.isBrowser && t.isEmpty) || (filters.narrows && !filters.isBrowser)
            ? const <FileResult>[]
            : browserResults.where(browserFits).toList();
        if (filters.isBrowser) return SearchAnswer(results: web, ms: 3);
        var rows = files.where((f) {
          if (filters.kind.isNotEmpty && f.kind != filters.kind) return false;
          if (filters.folder.isNotEmpty && !f.dir.toLowerCase().startsWith(filters.folder.toLowerCase())) {
            return false;
          }
          if (t.isEmpty) return true;
          final words = t.split(RegExp(r'\s+')).where((w) => !_stop.contains(w));
          final hay = '${f.name} ${f.kind} ${f.dir}'.toLowerCase();
          return words.isNotEmpty && words.every(hay.contains);
        }).toList();
        if (filters.sort == 'newest') rows.sort((a, b) => (b.mtime ?? 0).compareTo(a.mtime ?? 0));
        if (filters.sort == 'name') rows.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
        if (filters.sort == 'largest') rows.sort((a, b) => (b.size ?? 0).compareTo(a.size ?? 0));
        if (t.isEmpty) rows = rows.where((r) => !r.weak).toList();
        final parts = fakeParts(text);
        // the best guess: an exact name, or the only match (the engine's rules, simplified)
        final exact = rows.where((r) => r.name.toLowerCase() == t || r.name.toLowerCase().split('.').first == t);
        final guess = exact.length == 1
            ? (exact.first, 'Exact name')
            : (rows.length == 1 && t.isNotEmpty ? (rows.first, 'The only match') : null);
        if (guess != null) rows = [guess.$1, ...rows.where((r) => r.id != guess.$1.id)];
        return SearchAnswer(
          results: [...rows, ...web],
          ms: 4,
          parts: parts,
          best: guess == null ? null : BestGuess(guess.$1.id, guess.$2),
          understood: [
            if (t.contains('pdf')) 'pdf',
            if (t.contains('last week')) 'changed in the last 7 days',
            if (t.contains('photo')) 'photos',
          ],
          terms: [
            for (final w in t.split(RegExp(r'\s+')))
              if (w.isNotEmpty && !_stop.contains(w)) w,
          ],
          needs: searchNeeds,
          actions: searchActions,
        );
      });

  /// 1.2.0: the browsers' items searches may show while browser_data is on (kind browser, negative ids); tests set
  /// them.
  List<FileResult> browserResults = const [];

  /// What every search offers to open (0.9.1 `actions`); tests set it.
  List<SearchAction> searchActions = const [];

  /// The action ids run_action was asked for.
  final actionsRun = <String>[];

  @override
  Future<ActionResult> runAction(String id) => _new('run_action', () {
    actionsRun.add(id);
    return searchActions.any((a) => a.id == id) ? _ok : const ActionResult(false, "That isn't something NOBAD Find can open.");
  });

  /// What every search says it needs (0.9.0 `needs`); tests and the demo set it.
  List<SearchNeed> searchNeeds = const [];

  static const _stop = {'from', 'in', 'my', 'the', 'last', 'week', 'photos', 'photo', 'pdf'};

  /// How the fake reads a question into chips (the real engine: nobadfind/understand.py). Enough for the goldens
  /// and tests: folders, kinds and times it knows, the rest is what it's about.
  static List<QueryPart> fakeParts(String text) {
    var rest = ' ${text.trim()} ';
    final out = <QueryPart>[];
    String cut(String phrase) {
      final i = rest.toLowerCase().indexOf(' $phrase ');
      if (i < 0) return '';
      final found = rest.substring(i + 1, i + 1 + phrase.length);
      rest = '${rest.substring(0, i)} ${rest.substring(i + 1 + phrase.length)}';
      return found;
    }

    String without(String phrase) =>
        text.replaceFirst(RegExp('\\s*${RegExp.escape(phrase)}', caseSensitive: false), '').trim();
    for (final (phrase, kind, label) in _fakeVocab) {
      final found = cut(phrase);
      if (found.isNotEmpty) out.add(QueryPart(kind: kind, label: label, without: without(found)));
    }
    final about = rest
        .trim()
        .replaceAll(RegExp(r'\s+'), ' ')
        .replaceAll(RegExp(r'^(an?|the|of) |( an?| the| of)$'), '');
    if (out.isNotEmpty && about.isNotEmpty) {
      var only = text;
      for (final w in about.split(' ')) {
        only = only.replaceFirst(RegExp('\\b${RegExp.escape(w)}\\b\\s*', caseSensitive: false), '');
      }
      out.add(QueryPart(kind: 'meaning', label: about, without: only.trim()));
    }
    return out;
  }

  static const _fakeVocab = [
    ('in downloads', 'folder', 'Downloads'),
    ('on desktop', 'folder', 'Desktop'),
    ('in documents', 'folder', 'Documents'),
    ('in an image', 'kind', 'Images'),
    ('photos', 'kind', 'Images'),
    ('photo', 'kind', 'Images'),
    ('pdf', 'kind', 'PDFs'),
    ('last week', 'time', 'Last week'),
    ('yesterday', 'time', 'Yesterday'),
  ];

  // ---------- 0.8.5: autocomplete and the user's own search history ----------
  /// Kept questions, newest first (the engine keeps them in the encrypted index; here in memory).
  final history = <String>[];
  final suggested = <String>[];
  bool historyOn() => _settings['search_history'] != false;

  static const _phrases = [
    ('in downloads', 'folder'),
    ('in documents', 'folder'),
    ('on desktop', 'folder'),
    ('images', 'kind'),
    ('pdf', 'kind'),
    ('last week', 'time'),
    ('last month', 'time'),
    ('yesterday', 'time'),
  ];

  @override
  Future<Suggestions> suggest(String text, {String channel = 'main'}) => _answer('suggest', () {
    suggested.add(text);
    if (!suggestions) return Suggestions.none;
    final low = text.toLowerCase();
    final items = <Suggestion>[];
    if (historyOn()) {
      for (final h in history) {
        if (h.toLowerCase().startsWith(low) && h.toLowerCase() != low.trim()) {
          items.add(Suggestion(text: h, kind: 'history', label: h));
        }
        if (items.length >= 4) break;
      }
    }
    if (low.trim().isNotEmpty && !low.endsWith(' ')) {
      final words = low.split(' ');
      for (final n in [2, 1]) {
        if (words.length < n) continue;
        final tail = words.sublist(words.length - n).join(' ');
        if (tail.length < 2) continue;
        final before = text.substring(0, text.length - tail.length);
        final hits = [
          for (final (p, k) in _phrases)
            if (p.startsWith(tail) && p != tail) Suggestion(text: '$before$p', kind: 'filter', label: p, detail: k),
        ];
        if (hits.isNotEmpty) {
          items.addAll(hits.take(3));
          break;
        }
      }
      final last = words.last;
      if (last.length >= 2) {
        final before = text.substring(0, text.length - last.length);
        // the name alone when it has the earlier words too ("tax no" -> "tax notes.txt")
        final earlier = before.toLowerCase().split(' ').where((w) => w.length >= 2);
        for (final f in files) {
          if (f.name.toLowerCase().split(RegExp(r'[\s._-]+')).any((w) => w.startsWith(last))) {
            items.add(
              Suggestion(
                text: earlier.every(f.name.toLowerCase().contains) ? f.name : '$before${f.name}',
                kind: f.kind == 'folder' ? 'folder' : 'file',
                label: f.name,
                detail: f.dir,
                id: f.id,
              ),
            );
          }
          if (items.length >= 8) break;
        }
      }
    }
    final seen = <String>{};
    final out = [
      for (final i in items)
        if (seen.add(i.text.toLowerCase())) i,
    ].take(channel == 'bar' ? 5 : 8).toList();
    final first = out.where((i) => i.text.length > text.length && i.text.toLowerCase().startsWith(low)).firstOrNull;
    return Suggestions(
      items: out,
      complete: first == null || low.trim().isEmpty ? '' : text + first.text.substring(text.length),
    );
  });

  @override
  Future<bool> historyAdd(String text) => _answer('history_add', () {
    final t = text.trim().replaceAll(RegExp(r'\s+'), ' ');
    if (!historyOn() || t.length < 2) return false;
    history.removeWhere((h) => h.toLowerCase() == t.toLowerCase());
    history.insert(0, t);
    if (history.length > 200) history.removeLast();
    return true;
  });

  @override
  Future<ActionResult> historyForget(String text) => _answer('history_forget', () {
    final n = history.length;
    history.removeWhere((h) => h.toLowerCase() == text.trim().toLowerCase());
    return ActionResult(history.length < n);
  });

  @override
  Future<ActionResult> historyClear() => _answer('history_clear', () {
    history.clear();
    return _ok;
  });

  @override
  Future<ActionResult> open(int id) => _answer('open', () {
    opened.add(id);
    return openOk ? _ok : const ActionResult(false, "That file isn't there any more.");
  });

  @override
  Future<ActionResult> reveal(int id) => _answer('reveal', () {
    revealed.add(id);
    return _ok;
  });

  @override
  Future<Uint8List?> thumbnail(int id) async {
    thumbsAsked.add(id);
    if (!live) return null;
    final f = _file(id);
    return f == null || f.kind != 'image' ? null : _picture(id);
  }

  FileResult? _file(int id) => files.where((x) => x.id == id).firstOrNull;

  @override
  Future<String> pathOf(int id) => _answer('path_of', () {
    final f = _file(id);
    return f == null ? '' : (f.path.isNotEmpty ? f.path : '${f.dir}\\${f.name}');
  });

  @override
  Future<ActionResult> forget(int id) => _answer('forget', () {
    final f = _file(id);
    if (f == null) return const ActionResult(false);
    if (forgetError.isNotEmpty) return ActionResult(false, forgetError);
    forgotten.add(id);
    files.remove(f);
    _settings['exclude'] = [...Settings(_settings).list('exclude'), '${f.dir}\\${f.name}'];
    return forgetNote.isEmpty ? _ok : ActionResult(true, forgetNote);
  });

  @override
  Future<String> hereFolder() => _answer('here_folder', () => here);

  @override
  Future<void> toMain(String text) => _answer('to_main', () => emit(ShowEvent('main', text: text)));

  // ---------- status ----------
  @override
  Future<EngineStatus> status() => _answer('status', () => _brief);

  @override
  Future<EngineStatus> statusFull() => _answer('status_full', _full);

  @override
  Future<void> watchDetails(bool on) => _answer('watch_details', () => _watching = on);

  @override
  Future<ActionResult> pauseFor(Duration d) => _answer('pause_for', () {
    _level('paused', 'Paused: you paused NOBAD Find for ${d.inMinutes} min');
    return _ok;
  });

  @override
  Future<ActionResult> resume() => _answer('resume', () {
    _level('gentle', _gentle);
    return _ok;
  });

  void _level(String level, String reason) {
    _brief = EngineStatus(
      level: level,
      reason: reason,
      phase: _brief.phase,
      files: _brief.files,
      paused: level == 'paused' ? 'for 1 hour' : '',
    );
    emit(LevelEvent(level, reason));
    emit(ActivityEvent(ActivityEntry(t: _now(), kind: 'level', text: reason)));
    emit(StatusEvent(_brief));
    if (_watching) emit(StatusFullEvent(_full()));
  }

  @override
  Future<List<LearnedApp>> learnedApps() => _answer('learned_apps', () => List.of(learned));

  @override
  Future<ActionResult> resetLearned([String? exe]) => _answer('reset_learned', () {
    learned = exe == null
        ? []
        : [
            for (final a in learned)
              if (a.exe != exe) a,
          ];
    return _ok;
  });

  /// The settings "Reset to safe defaults" puts back (const.SAFE_DEFAULTS) and the things it keeps.
  static const safeDefaults = [
    'performance_goal',
    'gpu_background',
    'backend_photos',
    'backend_text',
    'backend_talk',
    'variant_siglip2-base',
    'workers',
    'profile_override_gpu',
    'profile_override_cpu',
    'profile_override_storage',
    'profile_override_memory',
    'gpu_reserve_min_mb',
  ];
  static const safeDefaultsKept = ['index', 'models', 'privacy', 'folders', 'learned_apps'];

  /// Browser data in the demo: one Edge profile, read a few minutes ago, while the setting is on.
  int browserItems = 131;

  @override
  Future<BrowserDataState> browserDataState() => _new('browser_data_state', () {
    final setting = jStr(_settings['browser_data']).isEmpty ? 'off' : jStr(_settings['browser_data']);
    final read = DateTime.now().millisecondsSinceEpoch / 1000 - 300;
    return BrowserDataState(setting, [
      if (setting != 'off')
        BrowserProfileState('Edge', 'Work', read, '', {
          'history': browserItems,
          'bookmark': 0,
          'download': 0,
          'login': 0,
        }),
    ]);
  });

  @override
  Future<ActionResult> browserClear() => _new('browser_clear', () {
    browserItems = 0;
    return _ok;
  });

  /// `performance_state` for the demo PC (16 threads, DirectML, the Vulkan runtime), from the current settings.
  @override
  Future<PerformanceState> performanceState() => _new('performance_state', () {
    final goal = jStr(_settings['performance_goal']);
    final fast = goal == 'fast';
    const classes = ['auto', 'performance', 'balanced', 'efficiency', 'compatibility'];
    const unused = 'Not used yet: the model suggestions that plan by these classes come in a later update.';
    PerformanceRow row(String k, Object? auto, String why, [List<String> options = const [], String note = '']) =>
        PerformanceRow(value: _settings[k], auto: auto, why: why, options: options, note: note);
    // like performance.state: the backend options are the ones installed on this PC
    final onnx = pc.onnxBackends.isEmpty ? const ['cpu'] : pc.onnxBackends;
    final llama = pc.llamacppBackends.isEmpty ? const ['cpu'] : pc.llamacppBackends;
    final dml = onnx.contains('directml');
    final vulkan = llama.contains('vulkan');
    String gone(String k, List<String> avail, String instead) {
      final v = _settings[k];
      const names = {'directml': 'DirectML', 'vulkan': 'Vulkan', 'cuda': 'CUDA'};
      return v is String && v != 'auto' && !avail.contains(v)
          ? "${names[v] ?? v} isn't available on this PC now, so $instead."
          : '';
    }

    return PerformanceState(goal, {
      'gpu_background': goal == 'quiet'
          ? row('gpu_background', 'off', 'The goal is Quiet, which keeps background work off the graphics card.', [
              'auto',
              'on',
              'off',
            ])
          : !dml
          ? row('gpu_background', 'off', 'No graphics backend for background work is installed on this PC.', [
              'auto',
              'on',
              'off',
            ])
          : row(
              'gpu_background',
              'on',
              'Background work may use the graphics card at Full, not with battery saver on or a creative app in '
                  'front.',
              ['auto', 'on', 'off'],
            ),
      'backend_photos': row('backend_photos', 'cpu', 'Photos are looked at on the processor in this version.', [
        'auto',
        'cpu',
      ]),
      'backend_text': row(
        'backend_text',
        goal == 'quiet' || !dml ? 'cpu' : 'directml',
        dml
            ? 'Meaning for documents uses DirectML at Full and the processor otherwise.'
            : 'Meaning for documents runs on the processor: no graphics backend is installed on this PC.',
        ['auto', ...onnx],
        gone('backend_text', onnx, 'meaning runs on the processor'),
      ),
      'backend_talk': row(
        'backend_talk',
        vulkan ? 'vulkan' : 'cpu',
        vulkan
            ? 'Talk about a photo uses the Vulkan runtime installed here.'
            : 'Talk about a photo uses the processor runtime.',
        ['auto', ...llama],
        gone('backend_talk', llama, 'talk about a photo uses the processor'),
      ),
      'variant_siglip2-base': row(
        'variant_siglip2-base',
        fast ? 'fp32-vision' : 'fp16-vision',
        '${fast ? 'Fast takes the faster build.' : 'Quiet and Balanced take the lighter build.'} Both made the same '
            'vectors on 50 test photos.',
        ['auto', 'fp16-vision', 'fp32-vision'],
        'Not used yet: this version downloads only the lighter build.',
      ),
      'workers': row(
        'workers',
        fast ? 16 : 15,
        fast ? 'Fast uses all 16 threads.' : "15 while you're away and 8 while you use the PC, from 16 threads.",
        const [],
        fast ? "Fast uses every thread, so this number isn't used." : '',
      ),
      'profile_override_gpu': row(
        'profile_override_gpu',
        switch (gpu) {
          GraphicsKind.discrete => 'performance',
          GraphicsKind.integrated => 'efficiency',
          GraphicsKind.none => 'compatibility',
        },
        switch (gpu) {
          GraphicsKind.discrete => 'Background work: a graphics card with 6 GB of its own memory.',
          GraphicsKind.integrated => 'Background work: a built-in GPU.',
          GraphicsKind.none => 'Background work: no graphics adapter.',
        },
        classes,
        unused,
      ),
      'profile_override_cpu': row('profile_override_cpu', 'performance', '8 cores with AVX2.', classes, unused),
      'profile_override_storage': row(
        'profile_override_storage',
        'performance',
        'A solid-state drive.',
        classes,
        unused,
      ),
      'profile_override_memory': row('profile_override_memory', 'balanced', '16 GB of memory.', classes, unused),
      'gpu_reserve_min_mb': row(
        'gpu_reserve_min_mb',
        512,
        'NOBAD Find leaves the larger of this and 15% of the free graphics memory to Windows and other apps. A higher '
            'number only leaves more.',
        const [],
        'In this version it only changes the graphics-card check under Index > Running at once now.',
      ),
    });
  });

  @override
  Future<ResetResult> resetSafeDefaults() => _new('reset_safe_defaults', () {
    for (final k in safeDefaults) {
      _settings[k] = Settings.defaults[k];
    }
    _settings['power'] = 'balanced';
    return const ResetResult(true, safeDefaults, safeDefaultsKept);
  });

  @override
  Future<Hardware?> hardware() => _answer('hardware', () => pc);

  // ---------- settings ----------
  @override
  Future<Settings> getSettings() => _answer('get_settings', () => Settings(Map.of(_settings)));

  /// Like settings.coerce: a value that doesn't fit becomes the default; unknown names and wsearch_prev are ignored.
  @override
  Future<SettingsChange> setSettings(Map<String, Object?> changes, {String? consent}) => _answer('set_settings', () {
    final fail = failNext;
    if (fail != null) {
      failNext = null;
      throw fail;
    }
    settingsSet.add(changes);
    consents.add(consent);
    final changed = <String>[];
    for (final e in changes.entries) {
      final known = {...Settings.defaults, ...scopeDefaults};
      if (e.key == 'wsearch_prev' || !known.containsKey(e.key)) continue;
      // like the engine: on only with the confirm dialog's word
      if (e.key == 'secret_app_files' && e.value == true && consent != appFilesConsent) continue;
      if (e.key == 'browser_data' &&
          consent != browserConsent &&
          browserDataLevels.indexOf('${e.value}') > browserDataLevels.indexOf('${_settings['browser_data'] ?? 'off'}')) {
        continue;
      }
      final want = known[e.key];
      final fits = switch (want) {
        bool _ => e.value is bool,
        int _ => e.value is int && (e.value as int) >= 0,
        String _ => e.value is String,
        List _ => e.value is List && (e.value as List).every((x) => x is String),
        _ => false,
      };
      final v = fits ? e.value : want;
      if (!_same(_settings[e.key], v)) {
        _settings[e.key] = v;
        changed.add(e.key);
      }
    }
    // the power compatibility layer (settings.power_compat): the goal decides, power mirrors it
    if (changed.contains('performance_goal')) {
      final p = _settings['performance_goal'] == 'fast' ? 'boost' : 'balanced';
      if (_settings['power'] != p) {
        _settings['power'] = p;
        if (!changed.contains('power')) changed.add('power');
      }
    }
    final keys = changed.any((k) => k == 'hotkey' || k == 'bar_hotkey' || k == 'bar');
    return SettingsChange(changed, Settings(Map.of(_settings)), hotkeys: keys ? _hotkeyState() : null);
  });

  /// Combinations 'another app' holds (tests and the demo set it); Win+Shift+number is Windows'.
  final Set<String> takenHotkeys = {};

  HotkeyState _hotkeyState() {
    HotkeyOne one(String which) {
      final spec = '${_settings[which] ?? Settings.defaults[which]}';
      if (spec.isEmpty || (which == 'bar_hotkey' && _settings['bar'] == false)) return HotkeyOne(spec, 'off');
      if (RegExp(r'^win\+shift\+[0-9]$').hasMatch(spec)) return HotkeyOne(spec, 'reserved');
      return HotkeyOne(spec, takenHotkeys.contains(spec) ? 'taken' : 'ok');
    }

    return HotkeyState(one('hotkey'), one('bar_hotkey'));
  }

  @override
  Future<HotkeyState> hotkeyState() => _answer('hotkey_state', _hotkeyState);

  @override
  Future<HotkeyProbe> hotkeyProbe(String which, String spec) => _answer('hotkey_probe', () {
    final s = spec.toLowerCase().replaceAll(' ', '');
    final other = which == 'hotkey' ? 'bar_hotkey' : 'hotkey';
    if (!RegExp(r'^(?:(?:win|ctrl|alt|shift)\+){1,3}(?:[a-z0-9]|space|f(?:[1-9]|1[0-2]))$').hasMatch(s)) {
      return const HotkeyProbe('invalid', '', 'Use Ctrl, Alt, Shift or Win with a letter, a number, Space or F1 to F12.');
    }
    if (s == '${_settings[other]}') return HotkeyProbe('same', s, 'The other NOBAD Find shortcut already uses it.');
    if (RegExp(r'^win\+shift\+[0-9]$').hasMatch(s)) {
      return HotkeyProbe('reserved', s, 'Windows uses Win+Shift+number for the taskbar.');
    }
    if (takenHotkeys.contains(s)) return HotkeyProbe('taken', s, 'Another app on this PC already uses it.');
    return HotkeyProbe('ok', s, 'Free to use.');
  });

  static bool _same(Object? a, Object? b) => a is List && b is List ? listEquals(a, b) : a == b;

  @override
  Future<FolderPick> pickFolder() => _answer('pick_folder', () => FolderPick(pickAnswer, busy: pickBusy));

  @override
  Future<ActionResult> rescan() => _answer('rescan', () => _ok);

  @override
  Future<ActionResult> wipe(String confirm) => _answer(
    'wipe',
    () => wipeError.isNotEmpty
        ? ActionResult(false, wipeError)
        : confirm == 'DELETE'
        ? _ok
        : const ActionResult(false),
  );

  // ---------- models ----------
  @override
  Future<ActionResult> downloadModel(String model) => _answer('download_$model', () {
    final allow = model == 'photo' ? 'allow_photo_model_download' : 'allow_model_download';
    if (_settings[allow] != true) {
      return ActionResult(
        false,
        model == 'photo'
            ? 'Allow the photo model download in Settings first.'
            : 'Allow the download in Settings first.',
      );
    }
    if (_models[model]!.downloading) return _ok;
    final size = model == 'photo' ? 211.0 : 23.0;
    var got = 0.0;
    void push(String state, double mbS) {
      _models[model] = ModelState(state: state, got: (got * 1048576).round(), size: (size * 1048576).round());
      emit(DownloadEvent(id: model, state: state, gotMb: got, sizeMb: size, mbS: mbS));
    }

    push('downloading', 0);
    if (live) {
      _downloads[model]?.cancel();
      _downloads[model] = Timer.periodic(const Duration(milliseconds: 500), (t) {
        got = (got + size / 14).clamp(0, size).toDouble();
        final done = got >= size;
        push(done ? 'ready' : 'downloading', done ? 0 : 4.2);
        if (done) {
          t.cancel();
          _settings[model == 'photo' ? 'photo_meaning' : 'semantic'] = true;
        }
      });
    }
    return _ok;
  });

  // ---------- Windows Search ----------
  @override
  Future<WsearchState> wsearchState() => _answer('wsearch_state', () => wsearch);

  @override
  Future<ActionResult> useInsteadOfWindowsSearch(bool on) => _answer('use_instead_of_windows_search', () {
    wsearch = WsearchState(start: on ? 'disabled' : 'delayed-auto', running: !on, saved: on ? 'delayed-auto' : '');
    if (on) _settings['autostart'] = true;
    return _ok;
  });

  // ---------- the window ----------
  @override
  Future<void> uiShown(String window) => _answer('ui_shown', () {});
  @override
  Future<void> uiHidden(String window) => _answer('ui_hidden', () {});

  // ---------- 0.8: models and Open with ----------
  final openedWith = <int>[];

  /// The `channel` of every search, in order.
  final channels = <String>[];
  late ModelsInfo modelsInfo = demoModels(gpu: gpu);

  /// `status_full.limits` (2026-11-21); null by default, as from an older engine (tests set it).
  OpLimits? limits;

  /// Answer the 0.8 methods like an older engine: -32601 (tests of the "needs a newer engine" path).
  bool old = false;

  Future<T> _new<T>(String name, T Function() f) => old
      ? Future.error(
          const RpcException(-32601, "This version of NOBAD Find's engine can't do that yet. Update NOBAD Find."),
        )
      : _answer(name, f);

  @override
  Future<ModelsInfo> models() => _new('models', () => modelsInfo);

  /// The live capability (tests and the demo): 2.2 GB free on the 15.7 GB demo PC, so the bigger models are "not
  /// now", as the contract transcript shows.
  late CapabilityState capability = demoCapability(gpu: gpu);

  /// What `storage_use` answers (null: an engine without it). The same figures as the contract transcript.
  StorageUse? storage = const StorageUse(
    indexMb: 412.5,
    walMb: 3.2,
    models: [StorageModel('minilm-l6-v2', 23), StorageModel('siglip-base', 211)],
    totalMb: 649.7,
  );

  @override
  Future<StorageUse?> storageUse() => _answer('storage_use', () => storage);

  @override
  Future<CapabilityState> capabilityState() => _new('capability_state', () => capability);

  /// Settings → Models' language choice (`model_language`): only the recommendation changes.
  @override
  Future<ActionResult> modelLanguage(String focus) => _new('model_language', () {
    final f = LanguageFocus.parse(focus);
    if (f == null) return const ActionResult(false, 'Choose English, many languages or Hindi.');
    modelsInfo = demoModels(focus: f, from: modelsInfo, gpu: gpu);
    emit(ModelsEvent(modelsInfo));
    return _ok;
  });

  /// A text model was switched: the meaning vectors are rebuilt (status_full gets a "rebuild" phase).
  bool rebuilding = false;

  /// Each model_use call's id and confirm, in order.
  final modelUses = <(String, bool)>[];

  @override
  Future<ModelUse> modelUse(String feature, String id, {bool confirm = false}) => _new('model_use', () {
    final m = modelsInfo.models.where((x) => x.id == id).firstOrNull;
    if (m == null) return const ModelUse(false, error: 'No such model.');
    // like the engine: above the suggestion it is chosen only after the cost screen (confirm); nothing changes
    if (!confirm && m.aboveSuggestion && !m.chosen) {
      return const ModelUse(
        false,
        error: 'That is above what is suggested for this PC: its measured cost comes first.',
        needsConfirm: true,
      );
    }
    modelUses.add((id, confirm));
    if (feature == 'text' && m.onDisk) rebuilding = true;
    _setModels(
      (x) => x.feature == feature
          ? x.withState(
              x.id == id && x.onDisk
                  ? ModelUseState.active
                  : (x.id != id && x.state == ModelUseState.active ? ModelUseState.ready : x.state),
              chosen: x.id == id,
            )
          : x,
      tier: 'custom',
    );
    return ModelUse(true, needsDownload: !m.onDisk);
  });

  /// Each reset_suggested call's confirm, in order.
  final resets = <bool>[];

  @override
  Future<ResetSuggested> resetSuggested({bool confirm = false}) => _new('reset_suggested', () {
    resets.add(confirm);
    final changes = <ResetChange>[];
    for (final f in const ['text', 'photo']) {
      final have = modelsInfo.byFeature(f).where((x) => x.chosen).firstOrNull;
      final want = f == 'photo'
          ? modelsInfo.byFeature(f).where((x) => x.suggested).firstOrNull // never an unmeasured tier pick
          : modelsInfo.byFeature(f).where((x) => x.recommended).firstOrNull;
      if (have == null || want == null || have.id == want.id) continue;
      changes.add(
        ResetChange(
          feature: f,
          id: want.id,
          name: want.name,
          from: have.id,
          fromName: have.name,
          vectorsChange: true,
          indexH: want.cost.indexH,
          measuredOn: want.cost.indexH == null ? '' : want.cost.measuredOn,
          needsDownload: !want.onDisk,
        ),
      );
    }
    if (changes.isEmpty || !confirm) return ResetSuggested(applied: false, changes: changes);
    for (final c in changes) {
      _setModels(
        (x) => x.feature == c.feature
            ? x.withState(
                x.id == c.id && x.onDisk
                    ? ModelUseState.active
                    : (x.id != c.id && x.state == ModelUseState.active ? ModelUseState.ready : x.state),
                chosen: x.id == c.id,
              )
            : x,
      );
    }
    return ResetSuggested(applied: true, changes: changes);
  });

  @override
  Future<ActionResult> modelDownload(String id) => _new('model_download', () {
    final m = modelsInfo.models.where((x) => x.id == id).firstOrNull;
    if (m == null) return const ActionResult(false, 'No such model.');
    _setModels((x) => x.id == id ? x.withState(ModelUseState.downloading) : x);
    emit(DownloadEvent(id: id, state: 'downloading', sizeMb: m.sizeMb));
    if (live) {
      Timer(const Duration(seconds: 2), () {
        _setModels((x) => x.id == id ? x.withState(ModelUseState.ready) : x);
        emit(DownloadEvent(id: id, state: 'ready', gotMb: m.sizeMb, sizeMb: m.sizeMb));
      });
    }
    return _ok;
  });

  /// The update the fake 'finds' (tests and the demo set it).
  UpdateState updates = const UpdateState(state: 'uptodate', current: '0.9.0', latest: '0.9.0');

  @override
  Future<UpdateState> updateState() => _new('update_state', () => updates);

  @override
  Future<ActionResult> updateCheck() => _new('update_check', () {
    emit(UpdateEvent(updates));
    return _ok;
  });

  @override
  Future<ActionResult> updateInstall() => _new('update_install', () {
    if (!updates.canInstall) return const ActionResult(false, 'Check for updates first.');
    // like the engine: downloading (got of size), then verifying, then installing; a ready one skips the download
    updates = updates.copyWith(state: updates.state == 'ready' ? 'verifying' : 'downloading',
        got: updates.state == 'ready' ? updates.size : 0, bps: 0);
    emit(UpdateEvent(updates));
    if (live) {
      // the demo: 4 progress events a second at about 6 MB/s, as the engine sends them
      Timer.periodic(const Duration(milliseconds: 250), (t) {
        final u = updates;
        if (u.state == 'downloading') {
          final got = u.got + 1572864;
          updates = got >= u.size ? u.copyWith(state: 'verifying', got: u.size, bps: 0) : u.copyWith(got: got, bps: 6291456);
        } else if (u.state == 'verifying') {
          updates = u.copyWith(state: 'installing');
          t.cancel();
        } else {
          t.cancel();
          return;
        }
        emit(UpdateEvent(updates));
      });
    }
    return _ok;
  });

  @override
  Future<ActionResult> modelFolder(String id) => _new('model_folder', () {
    final m = modelsInfo.models.where((x) => x.id == id).firstOrNull;
    return m == null || m.builtin ? const ActionResult(false, 'That model is part of Windows.') : _ok;
  });

  @override
  Future<ActionResult> modelRemove(String id) => _new('model_remove', () {
    _setModels((x) => x.id == id && !x.builtin ? x.withState(ModelUseState.notDownloaded) : x);
    return _ok;
  });

  @override
  Future<AutoConfig> autoConfigure() => _new('auto_configure', () {
    final steps = [
      for (final m in modelsInfo.models)
        if (m.recommended) AutoStep(feature: m.feature, id: m.id, needsDownload: !m.onDisk),
    ];
    return AutoConfig(tier: modelsInfo.tierRecommended, steps: steps);
  });

  // ---------- the first-run models window (1.2.0) ----------
  /// The offer: the reference PC's (mid, Iris Xe) as the contract transcript has it. [setupShow] false by default,
  /// so the window doesn't come up in tests that aren't about it.
  late SetupOffer setup = demoSetupOffer(pc);
  bool setupShow = false;

  /// Each setup_later's remind (Details sends false).
  final laterReminds = <bool>[];

  /// What setup_accept was asked for, each call.
  final setupAccepted = <List<String>>[];

  @override
  Future<SetupOffer> setupOffer() => _new('setup_offer', () {
    final s = setup;
    return SetupOffer(
      show: setupShow,
      state: s.state,
      walked: s.walked,
      like: s.like,
      summary: s.summary,
      hardware: s.hardware,
      items: s.items,
      notes: s.notes,
      totalMb: s.totalMb,
      estDownload: s.estDownload,
    );
  });

  @override
  Future<SetupAccept> setupAccept(List<String> models) => _new('setup_accept', () {
    setupAccepted.add([...models]);
    setupShow = false;
    final started = <String>[];
    for (final id in models) {
      final i = setup.items.where((x) => x.model == id).firstOrNull;
      if (i == null) return const SetupAccept(false, error: "That model isn't one suggested for this PC.");
      for (final x in [id, ?i.runtime?.id]) {
        if (modelsInfo.byId(x)?.onDisk ?? false) continue;
        unawaited(modelDownload(x));
        started.add(x);
      }
    }
    return SetupAccept(true, started: started);
  });

  @override
  Future<ActionResult> setupLater({bool remind = true}) => _new('setup_later', () {
    setupShow = false;
    laterReminds.add(remind);
    return _ok;
  });

  // ---------- what is indexed, and the turbo index ----------
  /// The categories as the engine lists them (nobadfind, find-turbo-index), switched by the settings.
  ScopeInfo get scope {
    final sc = IndexScope.parse(_settings['scope']) ?? IndexScope.myFiles;
    bool on(String k, {bool d = false}) => _settings[k] is bool ? _settings[k] as bool : d;
    return ScopeInfo(
      scope: sc,
      roots: sc == IndexScope.custom
          ? [for (final r in jStrs(_settings['roots'])) r]
          : (sc == IndexScope.wholePc ? const [r'C:\', r'D:\'] : const [r'C:\Users\me']),
      categories: [
        ScopeCategory(
          id: 'system',
          name: 'Windows and programs',
          summary: 'Windows itself and installed programs.',
          why: "Windows' own files and installed programs: rarely what you look for, and many of them.",
          examples: const [r'C:\Windows', r'C:\Program Files', r'C:\ProgramData'],
          included: sc == IndexScope.wholePc && on('include_system'),
          locked: sc != IndexScope.wholePc,
          count: sc == IndexScope.wholePc && on('include_system') ? 412880 : 0,
        ),
        ScopeCategory(
          id: 'caches',
          name: 'App data and caches',
          summary: 'What apps keep for themselves, temp folders and developer folders.',
          namesOnly: NamesOnly.some,
          why: 'Settings, temporary files and build folders apps keep for themselves.',
          examples: const [r'C:\Users\me\AppData', r'C:\Users\me\AppData\Local\Temp', r'…\node_modules', r'…\.git'],
          included: on('include_caches'),
          count: on('include_caches') ? 96214 : 0,
        ),
        ScopeCategory(
          id: 'secrets',
          name: 'Keys and password stores',
          summary: 'Keys, saved browser passwords, sign-in tokens, password vaults and wallets.',
          namesOnly: NamesOnly.all,
          why: 'SSH keys, password databases, wallets. Names only if you turn it on; their contents are never read.',
          examples: const [r'C:\Users\me\.ssh', r'…\*.kdbx', r'…\wallet.dat'],
          included: on('include_secrets'),
          count: on('include_secrets') ? 14 : 0,
        ),
        const ScopeCategory(
          id: 'other_profiles',
          name: "Other people's files",
          summary: 'Other accounts on this PC, recycle bins and restore points.',
          why: "Other accounts on this PC, recycle bins and System Volume Information: never indexed.",
          examples: [r'C:\Users\guest', r'C:\$Recycle.Bin', r'C:\System Volume Information'],
          locked: true,
        ),
        ScopeCategory(
          id: 'removable',
          name: 'USB and external drives',
          summary: 'Drives you plug in, while they are connected.',
          why: 'Indexed while plugged in; their files stay findable, marked "not connected", when you unplug them.',
          examples: const [r'E:\'],
          included: on('index_removable'),
          locked: sc == IndexScope.custom,
          count: on('index_removable') ? 2210 : null,
        ),
        ScopeCategory(
          id: 'network',
          name: 'Network drives',
          summary: 'Mapped network drives.',
          why: 'Mapped network drives. Big shares take a while and use your network.',
          examples: const [r'Z:\'],
          included: on('index_network'),
          locked: sc == IndexScope.custom,
        ),
      ],
    );
  }

  late TurboState turbo = const TurboState(
    available: true,
    volumes: [
      TurboVolume(drive: 'C:', ntfs: true, files: 0),
      TurboVolume(drive: 'D:', ntfs: true, files: 0),
      TurboVolume(drive: 'E:', files: 0),
    ],
  );

  /// The answer at Windows' permission prompt (tests: false = "No").
  bool turboPromptYes = true;

  /// Tests: scope_info answers only after this completes (an engine still counting).
  Future<void>? scopeWait;

  @override
  Future<ScopeInfo> scopeInfo() async {
    final w = scopeWait;
    if (w != null && !old) await w;
    return _new('scope_info', () => scope);
  }

  @override
  Future<TurboState> turboState() => _new('turbo_state', () => turbo);

  @override
  Future<TurboSet> turboSet(bool on) => _new('turbo_set', () {
    if (on && !turboPromptYes) {
      return TurboSet(false, error: "Windows didn't give permission, so the normal folder walk is used.", state: turbo);
    }
    turbo = TurboState(
      available: true,
      enabled: on,
      running: on,
      helper: on ? TurboHelper.installed : TurboHelper.notInstalled, // off removes it (the prompt said yes)
      volumes: [
        TurboVolume(drive: 'C:', ntfs: true, files: on ? 612408 : 0, usnOk: on, lastScan: on ? 1795500000 : null),
        TurboVolume(drive: 'D:', ntfs: true, files: on ? 88120 : 0, usnOk: on, lastScan: on ? 1795500000 : null),
        const TurboVolume(drive: 'E:', files: 0),
      ],
    );
    _settings['turbo'] = on;
    emit(TurboEvent(turbo));
    return TurboSet(true, state: turbo);
  });

  /// The `turbo_helper` actions asked for (tests).
  final List<String> turboHelperCalls = [];

  @override
  Future<TurboSet> turboHelper(String action) => _new('turbo_helper', () {
    turboHelperCalls.add(action);
    if (!turboPromptYes) {
      return TurboSet(false, error: "Windows didn't give permission, so the normal folder walk is used.", state: turbo);
    }
    if (action == 'remove') {
      turbo = TurboState(available: turbo.available, volumes: turbo.volumes);
      _settings['turbo'] = false;
    } else {
      turbo = TurboState(
        available: turbo.available,
        enabled: turbo.enabled,
        running: turbo.enabled,
        helper: TurboHelper.installed,
        volumes: turbo.volumes,
      );
    }
    emit(TurboEvent(turbo));
    return TurboSet(true, state: turbo);
  });

  @override
  Future<ActionResult> openWith(int id) => _new('open_with', () {
    openedWith.add(id);
    return _ok;
  });

  void _setModels(ModelInfo Function(ModelInfo) f, {String? tier}) {
    modelsInfo = ModelsInfo(
      pc: modelsInfo.pc,
      tierRecommended: modelsInfo.tierRecommended,
      tierCurrent: tier ?? modelsInfo.tierCurrent,
      languageFocus: modelsInfo.languageFocus,
      models: [for (final m in modelsInfo.models) f(m)],
    );
    emit(ModelsEvent(modelsInfo));
  }

  @override
  Future<ActionResult> quit() => _answer('quit', () {
    emit(const QuittingEvent());
    return _ok;
  });

  // ---------- 1.1: talk about a photo ----------
  /// What vision_state answers (tests change it): the engine's two talk models, as a PC with room for both.
  VisionState vision = demoVisionState();

  /// Every vision_* call: (method, params), in order.
  final visionCalls = <(String, Map<String, Object?>)>[];

  /// The next describe / ask / compare answers this instead of starting a job (a refusal).
  VisionAnswer? visionRefuse;

  /// What vision_keep kept, by file id.
  final kept = <int, String>{};
  int _job = 0;
  int? _visionJob;
  Timer? _visionTimer;

  @override
  Future<VisionState> visionState() => _new('vision_state', () => vision);

  Future<VisionAnswer> _visionStart(String m, Map<String, Object?> p, List<int> ids, {String? answer}) =>
      _new(m, () {
        visionCalls.add((m, p));
        final r = visionRefuse;
        if (r != null) {
          visionRefuse = null;
          return r;
        }
        if (ids.any((id) => _file(id) == null)) return const VisionAnswer(error: 'This photo is no longer there.');
        if (ids.length == 2 && ids[0] == ids[1]) {
          return const VisionAnswer(error: 'Pick a second, different photo to compare.');
        }
        final old = _visionJob;
        if (old != null) emit(VisionEvent(job: old, state: 'cancelled', model: 'smolvlm2-500m'));
        final job = _visionJob = ++_job;
        if (live) _stream(job, answer ?? 'A photo.');
        return VisionAnswer(ok: true, job: job);
      });

  /// The demo (live): the answer streams in a few words at a time, as the engine sends it.
  void _stream(int job, String answer) {
    _visionTimer?.cancel();
    final words = answer.split(' ');
    var n = 0;
    _visionTimer = Timer.periodic(const Duration(milliseconds: 160), (t) {
      if (_visionJob != job) return t.cancel();
      n++;
      if (n > words.length) {
        _visionJob = null;
        t.cancel();
        emit(VisionEvent(job: job, state: 'done', text: answer, model: 'smolvlm2-500m'));
        return;
      }
      emit(VisionEvent(job: job, state: 'answering', text: words.take(n).join(' '), model: 'smolvlm2-500m'));
    });
  }

  /// The job being answered (tests emit its events), or null.
  int? get visionJob => _visionJob;

  @override
  Future<VisionAnswer> visionDescribe(int fileId) => _visionStart(
    'vision_describe',
    {'file_id': fileId},
    [fileId],
    answer: 'A sandy beach under a clear sky, with small waves and two people walking by the water.',
  );

  @override
  Future<VisionAnswer> visionAsk(int fileId, String question, {bool deeper = false, bool more = false}) =>
      _visionStart('vision_ask', {
        'file_id': fileId,
        'question': question,
        if (deeper) 'deeper': true,
        if (more) 'more': true,
      }, [fileId]);

  @override
  Future<VisionAnswer> visionCompare(int a, int b, {String? question}) =>
      _visionStart('vision_compare', {'a': a, 'b': b, 'question': ?question}, [a, b]);

  @override
  Future<VisionAnswer> visionCancel() => _new('vision_cancel', () {
    visionCalls.add(('vision_cancel', const {}));
    final job = _visionJob;
    _visionJob = null;
    _visionTimer?.cancel();
    if (job != null) emit(VisionEvent(job: job, state: 'cancelled', model: 'smolvlm2-500m'));
    return const VisionAnswer(ok: true);
  });

  @override
  Future<VisionAnswer> visionKeep(int fileId, String text) => _new('vision_keep', () {
    visionCalls.add(('vision_keep', {'file_id': fileId, 'text': text}));
    if (_file(fileId) == null) return const VisionAnswer(error: 'This photo is no longer there.');
    if (text.trim().isEmpty) {
      kept.remove(fileId);
      return const VisionAnswer(ok: true);
    }
    kept[fileId] = text;
    return const VisionAnswer(ok: true, kept: true);
  });

  // ---------- notifications: the bell ----------
  /// Newest first, as the engine keeps them (tests add some with [notify]).
  final notifications = <AppNotification>[];
  int get _unread => notifications.where((n) => !n.read).length;

  /// The engine posted one: it goes on top and the `notification` event goes out.
  void notify(AppNotification n) {
    notifications.insert(0, n);
    emit(NotificationEvent(n, unread: _unread));
  }

  @override
  Future<NotificationList> notificationsList() =>
      _answer('notifications_list', () => NotificationList(List.of(notifications), _unread));

  @override
  Future<int> notificationsRead({List<int> ids = const [], bool all = false}) => _answer('notifications_read', () {
    for (var i = 0; i < notifications.length; i++) {
      if (all || ids.contains(notifications[i].id)) notifications[i] = notifications[i].asRead();
    }
    return _unread;
  });

  @override
  Future<ActionResult> notificationsClear() => _answer('notifications_clear', () {
    notifications.clear();
    return _ok;
  });

  @override
  void dispose() {
    _visionTimer?.cancel();
    _ticker?.cancel();
    for (final t in _downloads.values) {
      t.cancel();
    }
    _events.close();
  }

  // ---------- the made-up index ----------
  double _now() => _clock().millisecondsSinceEpoch / 1000;

  void _tick() {
    _tickN++;
    emit(StatusEvent(_brief));
    if (_watching) emit(StatusFullEvent(_full()));
  }

  EngineStatus _full() {
    final now = _now();
    final shift = _tickN;
    final history = [
      for (var i = 0; i < 150; i++)
        HistoryPoint(
          t: now - (149 - i) * 2,
          findCpu: _cpuAt(i + shift),
          findMb: 410 + 60 * _wave(i + shift, 37) + (i + shift > 95 ? 90.0 : 0),
        ),
    ];
    final meaning = _models['meaning']!, photoM = _models['photo']!;
    return EngineStatus(
      level: _brief.level,
      reason: _brief.reason,
      phase: _brief.phase,
      files: _brief.files,
      paused: _brief.paused,
      details: IndexDetails(
        version: '0.9.3',
        withText: 31877,
        memoryMb: 186,
        rate: 2140,
        dbBytes: 214 * 1048576,
        plan: const WorkPlan(cpu: 16, textWorkers: 2, textWorkersIdle: 6, ssd: true),
        limits: limits,
        speed: "gentle (you're using the PC)",
        ocrOn: true,
        roots: const [r'C:\Users\me', r'D:\'],
        drives: const [
          Drive(root: r'C:\', label: 'Windows', type: 'fixed'),
          Drive(root: r'D:\', label: 'Data', type: 'fixed'),
          Drive(root: r'E:\', label: 'SANDISK', type: 'removable', present: false),
        ],
        encrypted: true,
        model: meaning,
        photoModel: photoM,
        history: history,
        resources: Resources(
          cpu: history.last.findCpu,
          memoryMb: history.last.findMb,
          readMbS: 3.4,
          processes: [
            const ProcessUse(
              name: 'NOBAD Find engine',
              role: 'engine',
              about: 'The main process: the index, searching, watching folders and choosing the pace.',
              pid: 11240,
              cpu: 1.2,
              memoryMb: 186,
              privateMb: 204,
              ageS: 2402,
            ),
            const ProcessUse(
              name: 'The window',
              role: 'window',
              about: "NOBAD Find's window. Closing it ends this process.",
              pid: 15436,
              cpu: .4,
              memoryMb: 96,
              privateMb: 122,
              ageS: 871,
            ),
            ProcessUse(
              name: 'Text reader worker',
              role: 'text',
              about: 'Reads the words inside documents, and inside pictures with Windows OCR.',
              pid: 15012,
              cpu: history.last.findCpu * .6,
              memoryMb: 142,
              privateMb: 118,
              ageS: 40,
            ),
            ProcessUse(
              name: 'Text reader worker',
              role: 'text',
              about: 'Reads the words inside documents, and inside pictures with Windows OCR.',
              pid: 15876,
              cpu: history.last.findCpu * .4,
              memoryMb: 131,
              privateMb: 109,
              ageS: 38,
            ),
            const ProcessUse(
              name: 'Meaning worker',
              role: 'meaning',
              about: 'Runs the AI model for text, so you can search by what files mean.',
              pid: 16592,
              memoryMb: 194,
              privateMb: 177,
              ageS: 300,
              note: 'Idle: waiting for work',
            ),
          ],
        ),
        phases: [
          const PhaseRow(id: 'names', label: 'Finding file names', state: PhaseState.done, done: 48210),
          PhaseRow(
            id: 'text',
            label: 'Reading documents',
            state: PhaseState.running,
            done: 31877 + shift * 29,
            total: 40112,
            rate: 14.6,
            etaS: 564 - shift * 2,
          ),
          const PhaseRow(
            id: 'ocr',
            label: 'Reading words in pictures',
            state: PhaseState.waiting,
            done: 120,
            total: 2304,
          ),
          PhaseRow(
            id: 'meaning',
            label: 'Learning what files mean',
            state: meaning.ready ? PhaseState.waiting : PhaseState.off,
          ),
          PhaseRow(id: 'photos', label: 'Looking at photos', state: photoM.ready ? PhaseState.waiting : PhaseState.off),
          if (rebuilding)
            PhaseRow(
              id: 'rebuild',
              label: 'Rebuilding meaning for the new model (the old one works until it is done)',
              state: PhaseState.running,
              done: 9120 + shift * 40,
              total: 48210,
              rate: 38,
              etaS: 1030 - shift * 2,
            ),
          const PhaseRow(id: 'watching', label: 'Watching for changes', state: PhaseState.waiting),
        ],
        models: [
          _card('meaning', 'Meaning search (all-MiniLM-L6-v2)', 23, meaning),
          _card('photo', 'Photo search (SigLIP base)', 211, photoM),
          const ModelCard(
            id: 'ocr',
            name: 'Windows OCR',
            license: 'Windows',
            onDisk: true,
            device: 'Windows',
            items: 120,
          ),
        ],
        activity: [
          ActivityEntry(t: now - 60, kind: 'level', text: _gentle),
          ActivityEntry(t: now - 840, kind: 'info', text: 'Finished finding file names: 48,210 files and folders.'),
          ActivityEntry(
            t: now - 1500,
            kind: 'level',
            text: 'Paused: Cyberpunk2077 is running and lagged before, so NOBAD Find waits until it closes.',
          ),
          ActivityEntry(t: now - 2700, kind: 'level', text: "Full speed: you're away from the PC."),
        ],
      ),
    );
  }

  static ModelCard _card(String id, String name, double size, ModelState m) => ModelCard(
    id: id,
    name: name,
    license: 'Apache-2.0',
    sizeMb: size,
    onDisk: m.ready,
    device: 'CPU',
    download: m.downloading ? DownloadProgress(gotMb: m.got / 1048576, sizeMb: m.size / 1048576, mbS: 4.2) : null,
  );

  static double _wave(int i, int period) {
    final x = (i % period) / period;
    return x < .5 ? x * 2 : (1 - x) * 2;
  }

  static double _cpuAt(int i) {
    final base = 3 + 5 * _wave(i, 23) + 3 * _wave(i, 7);
    return i % 50 > 40 ? base + 9 : base;
  }

  /// A preview for a made-up photo: a soft two-colour gradient (only with [live], for screenshots).
  static Future<Uint8List?> _picture(int id) async {
    final rec = ui.PictureRecorder();
    final c = ui.Canvas(rec);
    const palettes = [
      [ui.Color(0xFF1B3A5C), ui.Color(0xFFE9B872)],
      [ui.Color(0xFF2E4B3C), ui.Color(0xFFB8D4C8)],
      [ui.Color(0xFF5B2A3A), ui.Color(0xFFF2A07B)],
    ];
    final p = palettes[id % palettes.length];
    c.drawRect(
      const ui.Rect.fromLTWH(0, 0, 96, 96),
      ui.Paint()..shader = ui.Gradient.linear(const ui.Offset(0, 0), const ui.Offset(0, 96), p),
    );
    c.drawCircle(const ui.Offset(68, 30), 12, ui.Paint()..color = const ui.Color(0xCCFFF4D6));
    final img = await rec.endRecording().toImage(96, 96);
    final data = await img.toByteData(format: ui.ImageByteFormat.png);
    img.dispose();
    return data?.buffer.asUint8List();
  }
}

/// The made-up index: a few files of every kind, with folders and ages that read like a real profile.
List<FileResult> sampleFiles() => [
  const FileResult(
    id: 1,
    name: 'tax return 2025.pdf',
    dir: r'C:\Users\me\Documents\Taxes',
    kind: 'pdf',
    size: 482113,
    ago: '3 days ago',
    mtime: 1763200000,
    why: ['name matches'],
    snippet: 'your \x02tax\x03 refund for 2025 is expected within six weeks of filing',
  ),
  const FileResult(
    id: 2,
    name: 'tax notes.txt',
    dir: r'C:\Users\me\Desktop',
    kind: 'text',
    size: 912,
    ago: '1 h ago',
    mtime: 1763500000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 3,
    name: 'beach.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 3400000,
    ago: 'March',
    mtime: 1742000000,
    why: ['the picture may show it'],
  ),
  const FileResult(
    id: 4,
    name: '<b>tax</b> & "quotes".docx',
    dir: r'D:\Work',
    kind: 'document',
    size: 20000,
    ago: '2 weeks ago',
    mtime: 1762300000,
    why: ['text inside matches'],
  ),
  const FileResult(
    id: 5,
    name: 'old tax scan.pdf',
    dir: r'C:\Users\me\Scans',
    kind: 'pdf',
    size: 1200000,
    ago: 'last year',
    mtime: 1730000000,
    weak: true,
    why: ['text has a loose meaning'],
  ),
];

/// A bigger made-up index for screenshots (NOBAD_FIND_FAKE_ENGINE).
List<FileResult> demoFiles() => [
  ...sampleFiles(),
  const FileResult(
    id: 6,
    name: 'rent agreement 2026.pdf',
    dir: r'C:\Users\me\Documents\Home',
    kind: 'pdf',
    size: 228400,
    ago: 'yesterday',
    mtime: 1763450000,
    why: ['name matches', 'changed last week'],
    snippet: 'the monthly \x02rent\x03 of 1,450 is due on the first day of each month',
  ),
  const FileResult(
    id: 7,
    name: 'budget 2026.xlsx',
    dir: r'C:\Users\me\Documents\Money',
    kind: 'spreadsheet',
    size: 48210,
    ago: '5 days ago',
    mtime: 1763100000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 8,
    name: 'IMG_0042.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 4100000,
    ago: 'March',
    mtime: 1742100000,
    why: ['the picture may show it'],
  ),
  const FileResult(
    id: 9,
    name: 'quarterly review.pptx',
    dir: r'D:\Work\Reviews',
    kind: 'slides',
    size: 5600000,
    ago: '2 weeks ago',
    mtime: 1762200000,
    why: ['text inside matches'],
  ),
  const FileResult(
    id: 10,
    name: 'invoice-march.pdf',
    dir: r'C:\Users\me\Downloads',
    kind: 'pdf',
    size: 88000,
    ago: 'March',
    mtime: 1742500000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 11,
    name: 'trip video.mp4',
    dir: r'C:\Users\me\Videos',
    kind: 'video',
    size: 412000000,
    ago: '4 months ago',
    mtime: 1752000000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 12,
    name: 'notes.md',
    dir: r'C:\Users\me\Documents',
    kind: 'text',
    size: 3200,
    ago: 'today',
    mtime: 1763520000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 13,
    name: 'IMG_0107.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 3900000,
    ago: 'March',
    mtime: 1742200000,
    why: ['the picture may show it'],
  ),
];

/// vision_state as the engine answers on a PC with room for both talk models (nobadfind/models.py's measured memory
/// and timings at Full: Vulkan on the reference PC's Iris Xe, or its processor with [cpu]; [veryLight] with [cpu]:
/// the processor at Very light, slower, with the engine's "Slower now" note).
VisionState demoVisionState({
  String deeperWhy = '',
  String notNow = '',
  bool deeperReady = true,
  bool cpu = false,
  bool veryLight = false,
}) {
  // Very light on the processor: the 15 % CPU cap and efficiency mode, measured slower, with the engine's note
  final slow = cpu && veryLight;
  final slowNote = slow ? 'Slower now: NOBAD Find is in Very light mode.' : '';
  return VisionState(
      notNow: notNow,
      models: [
        VisionModel(
          id: 'smolvlm2-500m',
          name: 'SmolVLM2 500M',
          ready: true,
          ramMb: 1031,
          vramMb: 665,
          loadS: cpu && !slow ? 3 : 1,
          answerS: slow ? (5, 15) : (cpu ? (3, 11) : (1, 3)),
          slowNote: slowNote,
          canRun: true,
        ),
        VisionModel(
          id: 'qwen3vl-2b',
          name: 'Qwen3-VL 2B',
          deeper: true,
          ready: deeperReady,
          missingMb: deeperReady ? 0 : 1481,
          ramMb: 2483,
          vramMb: 2062,
          loadS: slow ? 10 : (cpu ? 12 : 13),
          answerS: slow ? (7, 32) : (cpu ? (4, 22) : (1, 12)),
          slowNote: slowNote,
          canRun: deeperWhy.isEmpty,
          why: deeperWhy,
        ),
      ],
      runtimeId: cpu ? 'llama-cpu' : 'llama-vulkan',
      runtimeReady: true,
    );
}

List<FileResult> manyFiles(int n) => [
  for (var i = 0; i < n; i++)
    FileResult(id: 100 + i, name: 'report $i.pdf', dir: r'C:\Users\me\Reports\Quarterly\Archive', kind: 'pdf'),
];

/// The engine's 0.8 catalogue (nobadfind/models.py) as a made-up 6-core laptop would see it: Balanced is
/// recommended, the Best models need more than it has. [focus] picks the recommended text model like the engine's
/// TEXT_CHOICE; [from] keeps the download and use states of an earlier catalogue.
ModelsInfo demoModels({
  LanguageFocus focus = LanguageFocus.multilingual,
  ModelsInfo? from,
  GraphicsKind gpu = GraphicsKind.integrated,
}) {
  // like models.talk_runtime: the graphics runtime when Windows lists an adapter, else the processor one
  final talkRuntime = gpu == GraphicsKind.none ? 'llama-cpu' : 'llama-vulkan';
  const best = 'Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)';
  final text = focus == LanguageFocus.english ? 'bge-small-en-v1.5' : 'multilingual-e5-small';
  const hiEn = ['hi', 'en', 'multilingual'];
  const many = ['en', 'hi', 'multilingual (about 100 languages)'];
  final all = <ModelInfo>[
    const ModelInfo(
      id: 'minilm-l6-v2',
      name: 'all-MiniLM-L6-v2',
      tier: 'light',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2',
      sizeMb: 87,
      ramMb: 60,
      speedNote: 'fast: about 40 pieces of text a second on this PC',
      languages: ['en'],
      improves: 'Finds files by what they mean, in English',
      state: ModelUseState.active,
      quality: ModelQuality(recall5: .71, ndcg10: .62),
      chosen: true,
    ),
    const ModelInfo(
      id: 'bge-small-en-v1.5',
      name: 'BGE small (English) v1.5',
      tier: 'light',
      licence: 'MIT',
      source: 'https://huggingface.co/BAAI/bge-small-en-v1.5 (ONNX: Xenova/bge-small-en-v1.5)',
      sizeMb: 33,
      languages: ['en'],
      quality: ModelQuality(recall5: .78, ndcg10: .69),
      outcome: 'not_measured',
      why: 'Not measured: BGE small (English) v1.5: not measured against a floor yet',
      vectorsChange: true,
    ),
    const ModelInfo(
      id: 'bge-base-en-v1.5',
      name: 'BGE base (English) v1.5',
      tier: 'balanced',
      licence: 'MIT',
      source: 'https://huggingface.co/BAAI/bge-base-en-v1.5 (ONNX: Xenova/bge-base-en-v1.5)',
      sizeMb: 106,
      languages: ['en'],
    ),
    const ModelInfo(
      id: 'multilingual-e5-small',
      name: 'multilingual-e5-small',
      tier: 'balanced',
      licence: 'MIT',
      source: 'https://huggingface.co/intfloat/multilingual-e5-small (ONNX: Xenova/multilingual-e5-small)',
      sizeMb: 129,
      languages: many,
      improves: 'Finds files by meaning in Hindi, mixed Hindi and English, and about 100 other languages',
      quality: ModelQuality(recall5: .80, ndcg10: .70),
      outcome: 'not_measured',
      why: 'Not measured: multilingual-e5-small: not measured against a floor yet',
      vectorsChange: true,
    ),
    const ModelInfo(
      id: 'multilingual-e5-base',
      name: 'multilingual-e5-base',
      tier: 'best',
      licence: 'MIT',
      source: 'https://huggingface.co/intfloat/multilingual-e5-base (ONNX: Xenova/multilingual-e5-base)',
      sizeMb: 282,
      languages: many,
      improves: 'The most accurate meaning search, in Hindi, mixed Hindi and English and about 100 languages',
      capable: false,
      capableReason: best,
    ),
    const ModelInfo(
      id: 'paraphrase-multilingual-minilm',
      name: 'paraphrase-multilingual-MiniLM-L12-v2',
      tier: 'balanced',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
      sizeMb: 122,
      languages: hiEn,
    ),
    const ModelInfo(
      id: 'labse',
      name: 'LaBSE',
      tier: 'best',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/LaBSE (ONNX: Xenova/LaBSE)',
      sizeMb: 463,
      languages: hiEn,
      capable: false,
      capableReason: best,
    ),
    const ModelInfo(
      id: 'siglip-base',
      feature: 'photo',
      name: 'SigLIP base',
      tier: 'balanced',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/google/siglip-base-patch16-224 (ONNX: Xenova/siglip-base-patch16-224)',
      sizeMb: 211,
      languages: ['en'],
      improves: "Finds photos by what's in them (English questions)",
      dir: r'C:\Users\me\AppData\Local\NOBAD\Find\photo-model',
      outcome: 'not_measured',
      why: 'Not measured: SigLIP base: not measured on a PC like this one yet',
      backend: 'cpu',
      vectorsChange: true,
    ),
    const ModelInfo(
      id: 'siglip2-base',
      feature: 'photo',
      name: 'SigLIP 2 base',
      tier: 'best',
      licence: 'Apache-2.0',
      source:
          'https://huggingface.co/google/siglip2-base-patch16-224 (ONNX: onnx-community/siglip2-base-patch16-224-ONNX)',
      sizeMb: 393,
      languages: ['en', 'hi', 'multilingual'],
      improves: 'Finds photos more accurately, and with questions in many languages',
      outcome: 'suggested',
      why: 'Suggested: SigLIP 2 base: a search takes about 196 ms, it indexes 1.42 photos a second, 621 MB of memory '
          '(measured on a similar PC)',
      backend: 'cpu',
      cost: SetupCost(ramMb: 621, itemsS: 1.416, queryMs: 196.5, indexH: .24, measuredOn: 'similar PC'),
      vectorsChange: true,
    ),
    const ModelInfo(
      id: 'windows-ocr',
      feature: 'ocr',
      name: 'Windows OCR',
      tier: 'light',
      licence: 'Windows',
      source: 'Windows (Windows.Media.Ocr)',
      speedNote: 'built into Windows',
      languages: ['the Windows language packs'],
      improves: 'Reads words in photos, screenshots and scans',
      builtin: true,
      state: ModelUseState.active,
    ),
    // 1.1: talk about a photo and the llama.cpp runtimes (nobadfind/models.py, measured memory)
    ModelInfo(
      id: 'smolvlm2-500m',
      feature: 'talk',
      name: 'SmolVLM2 500M',
      tier: 'balanced',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/ggml-org/SmolVLM2-500M-Video-Instruct-GGUF',
      sizeMb: 520,
      ramMb: 1031,
      vramMb: 665,
      runtime: talkRuntime,
      speedNote:
          "an answer in about 1-3 s on the reference PC's graphics (Iris Xe), 3-11 s on its processor "
          '(5-15 s while NOBAD Find runs very light)',
      languages: ['en'],
      improves: 'Answers questions about a photo, on this PC',
      outcome: 'suggested',
      why: 'Suggested: SmolVLM2 500M: first word about 6 s, 663 MB of memory, shared with the built-in graphics '
          '(measured on a similar PC)',
      backend: 'vulkan',
      cost: SetupCost(ramMb: 1033, loadS: 1.27, answerS: 5.77, sharedMb: 663, measuredOn: 'similar PC'),
    ),
    ModelInfo(
      id: 'qwen3vl-2b',
      feature: 'talk',
      name: 'Qwen3-VL 2B',
      tier: 'best',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF',
      sizeMb: 1481,
      ramMb: 2483,
      vramMb: 2062,
      runtime: talkRuntime,
      languages: ['en', 'multilingual'],
      improves: 'Deeper answers about a photo, on this PC',
      outcome: 'upgrade',
      why: 'Upgrade: Qwen3-VL 2B: more memory (2,491 MB), longer loading and answers (12 s on a similar PC)',
      backend: 'vulkan',
      cost: SetupCost(ramMb: 2491, loadS: 6.21, answerS: 12.08, sharedMb: 2058, measuredOn: 'similar PC'),
      // the hybrid laptop's 6 GB card can run it
      capable: gpu == GraphicsKind.discrete,
      // talk models never use DirectML: their own check (models._talk_capable)
      capableReason: gpu == GraphicsKind.discrete
          ? ''
          : 'Needs 16 GB of memory and 8 cores, or a graphics card with 2.1 GB of its own memory',
    ),
    const ModelInfo(
      id: 'llama-cpu',
      feature: 'runtime',
      name: 'llama.cpp runtime (CPU)',
      tier: 'light',
      licence: 'MIT',
      source: 'https://github.com/ggml-org/llama.cpp/releases/tag/b12602',
      sizeMb: 24,
      improves: 'Runs the talk models on the processor',
    ),
    const ModelInfo(
      id: 'llama-vulkan',
      feature: 'runtime',
      name: 'llama.cpp runtime (graphics card)',
      tier: 'light',
      licence: 'MIT',
      source: 'https://github.com/ggml-org/llama.cpp/releases/tag/b12602',
      sizeMb: 37,
      improves: 'Runs the talk models on the graphics card (Vulkan)',
    ),
  ];
  final was = {for (final m in from?.models ?? const <ModelInfo>[]) m.id: m.state};
  final wasChosen = {for (final m in from?.models ?? const <ModelInfo>[]) m.id: m.chosen};
  return ModelsInfo(
    pc: from?.pc ?? fakeHardware(gpu, cores: 6, threads: 12),
    tierRecommended: 'balanced',
    tierCurrent: from?.tierCurrent ?? 'light',
    languageFocus: focus,
    models: [
      for (final m in all)
        m.withState(
          was[m.id] ?? m.state,
          recommended: m.id == text || m.id == 'siglip-base' || m.id == 'windows-ocr',
          chosen: wasChosen[m.id] ?? m.chosen,
        ),
    ],
  );
}

/// The demo PC right now: 2.2 GB of its 15.7 GB free (contract transcript 06).
CapabilityState demoCapability({GraphicsKind gpu = GraphicsKind.integrated}) {
  const fits = 'Fits now: needs about 56 MB, 2.1 GB free';
  const notNow = 'Not now: it needs about 544 MB plus 392 MB to spare, and 2.1 GB of memory is free (NOBAD Find '
      'leaves 1.5 GB to Windows)';
  return CapabilityState(
    canRun: const {'minilm-l6-v2': true, 'gte-small': true, 'multilingual-e5-small': false,
      'multilingual-e5-base': false, 'siglip-base': true, 'siglip2-base': false, 'windows-ocr': true},
    why: const {'minilm-l6-v2': fits, 'gte-small': fits, 'multilingual-e5-small': notNow,
      'multilingual-e5-base': notNow, 'siglip-base': fits, 'siglip2-base': notNow, 'windows-ocr': 'Built into Windows'},
    budget: switch (gpu) {
      GraphicsKind.discrete => const CapabilityBudget(live: true, installedMb: 16076, freeMb: 2200, reserveMb: 1500,
          usableMb: 700, commitPct: 62, commitFreeMb: 9000, gpuKind: 'dedicated', gpuFreeMb: 5400, gpuBudgetMb: 6144,
          cpu: 20, gpu: 3),
      GraphicsKind.integrated => const CapabilityBudget(live: true, installedMb: 16076, freeMb: 2200, reserveMb: 1500,
          usableMb: 700, commitPct: 62, commitFreeMb: 9000, gpuKind: 'shared', gpuFreeMb: 7300, gpuBudgetMb: 8000,
          cpu: 20, gpu: 3),
      GraphicsKind.none => const CapabilityBudget(live: true, installedMb: 16076, freeMb: 2200, reserveMb: 1500,
          usableMb: 700, commitPct: 62, commitFreeMb: 9000, cpu: 20),
    },
  );
}

/// The made-up PC per graphics kind: a hybrid laptop (Iris Xe and an RTX 3060 with 6 GB of its own), Iris Xe only
/// (the reference PC), or no adapter at all; the backends are what such a PC would have installed.
Hardware fakeHardware(GraphicsKind gpu, {int cores = 12, int threads = 16}) {
  const iris = GpuInfo(
    vendor: 'intel',
    name: 'Intel(R) Iris(R) Xe Graphics',
    dedicatedMb: 128,
    sharedMb: 8038,
    integrated: true,
  );
  const rtx = GpuInfo(vendor: 'nvidia', name: 'NVIDIA GeForce RTX 3060 Laptop GPU', dedicatedMb: 6144, sharedMb: 8038);
  return switch (gpu) {
    GraphicsKind.discrete => Hardware(
      ramGb: 15.7,
      cores: cores,
      threads: threads,
      avx2: true,
      gpu: rtx.name,
      vramGb: 6,
      directml: true,
      diskFreeGb: 211.4,
      ssd: true,
      gpus: const [iris, rtx],
      onnxBackends: const ['cpu', 'directml'],
      llamacppBackends: const ['vulkan', 'cpu'],
    ),
    GraphicsKind.integrated => Hardware(
      ramGb: 15.7,
      cores: cores,
      threads: threads,
      avx2: true,
      gpu: iris.name,
      vramGb: 0.1,
      directml: true,
      diskFreeGb: 211.4,
      ssd: true,
      gpus: const [iris],
      onnxBackends: const ['cpu', 'directml'],
      llamacppBackends: const ['vulkan', 'cpu'],
    ),
    GraphicsKind.none => Hardware(
      ramGb: 15.7,
      cores: cores,
      threads: threads,
      avx2: true,
      diskFreeGb: 211.4,
      ssd: true,
      onnxBackends: const ['cpu'],
      llamacppBackends: const ['cpu'],
    ),
  };
}

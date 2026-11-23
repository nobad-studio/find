/// The first-run models window (plan Task 6): after the first scan, what this PC is like and the models suggested
/// for it, each with its download size, the memory it needs, why, and how long indexing what the scan counted
/// takes, then the total, the sources and the download time once it is known. Download here is the consent (one
/// click names every model, its runtime, sizes, total and sources); Later leaves a reminder; Details opens
/// Settings > Models. Only suggested models are ticked, never talk about a photo. It never blocks the window:
/// Close keeps the downloads going in the background, and a failed one can be tried again here.
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../engine/events.dart';
import '../../engine/models/format.dart';
import '../../engine/models/graphics.dart';
import '../../engine/models/settings.dart' show Hardware;
import '../../widgets/badges.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/icons.dart';
import '../../widgets/panels.dart';
import '../consent/download_consent_dialog.dart';
import '../settings/pages/models.dart' show ModelTag, runtimeName;

/// Show the window for [offer]. Closing it before answering (Escape, outside it) counts as Later.
Future<void> showSetupDialog(BuildContext context, SetupOffer offer) async {
  final s = AppScope.of(context);
  final run = SetupRun();
  final r = await showDialog<SetupAnswer>(
    context: context,
    builder: (context) => SetupDialog(offer: offer, engine: s.engine, run: run),
  );
  if (r == SetupAnswer.details) {
    s.nav.openSettings(SettingsPage.models);
  } else if (!run.started) {
    try {
      await s.engine.setupLater();
    } on Object {
      // the engine is gone: it asks again next time
    }
  }
}

/// The window for [offer] with nothing sent when it closes (the screenshot tour).
Future<void> previewSetupDialog(BuildContext context, SetupOffer offer, EngineApi engine) => showDialog<SetupAnswer>(
  context: context,
  builder: (context) => SetupDialog(offer: offer, engine: engine, run: SetupRun()),
);

enum SetupAnswer { later, details, closed }

/// What happened in the window ([started]: Download was pressed and something began or was set).
class SetupRun {
  bool started = false;
}

class SetupDialog extends StatefulWidget {
  const SetupDialog({super.key, required this.offer, required this.engine, required this.run});
  final SetupOffer offer;
  final EngineApi engine;
  final SetupRun run;

  @override
  State<SetupDialog> createState() => _SetupDialogState();
}

class _SetupDialogState extends State<SetupDialog> {
  late final Set<String> _ticked = {
    for (final i in widget.offer.items)
      if (i.checked) i.model,
  };
  final _progress = <String, DownloadEvent>{};
  final _mine = <String>{};
  StreamSubscription<EngineEvent>? _sub;
  bool _busy = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _sub = widget.engine.events.listen((e) {
      if (e is DownloadEvent && mounted) setState(() => _progress[e.id] = e);
    });
  }

  @override
  void dispose() {
    unawaited(_sub?.cancel());
    super.dispose();
  }

  SetupOffer get _offer => widget.offer;
  Hardware? get _pc => _offer.hardware;
  bool get _started => widget.run.started;

  Future<void> _download([List<String>? only]) async {
    final ids = only ?? [for (final i in _offer.items) if (_ticked.contains(i.model)) i.model];
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final r = await widget.engine.setupAccept(ids);
      if (!mounted) return;
      setState(() {
        widget.run.started = r.ok || r.started.isNotEmpty;
        _mine.addAll(r.started);
        for (final id in r.started) {
          _progress.remove(id);
        }
        _error = r.ok ? '' : (r.error.isNotEmpty ? r.error : 'The download did not start.');
      });
    } on Object {
      if (mounted) setState(() => _error = "NOBAD Find's engine didn't answer. Try again in a moment.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// The ids (models and runtimes) this window started that ended with an error.
  List<String> get _failedItems => [
    for (final i in _offer.items)
      if ([i.model, ?i.runtime?.id].any((x) => _mine.contains(x) && _progress[x]?.error.isNotEmpty == true)) i.model,
  ];

  String? _timeLeft() {
    var left = 0.0, rate = 0.0;
    for (final id in _mine) {
      final p = _progress[id];
      if (p == null || p.state != 'downloading') continue;
      left += (p.sizeMb - p.gotMb).clamp(0, double.infinity);
      rate += p.mbS;
    }
    if (rate <= 0 || left <= 0) return null;
    return '${_duration(left / rate)} left (at ${rate.toStringAsFixed(1)} MB/s)';
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final items = _offer.items;
    final main = [for (final i in items) if (!i.more) i];
    final more = [for (final i in items) if (i.more) i];
    final total = setupTotalMb(items, _ticked);
    final failed = _started ? _failedItems : const <String>[];
    final maxH = (MediaQuery.sizeOf(context).height - 230).clamp(240.0, 900.0);
    return NbDialog(
      title: 'Set up NOBAD Find for this PC',
      width: 680,
      body: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxH),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _PcLine(offer: _offer),
              const SizedBox(height: NbSpace.x3),
              Text(
                'The first scan is done. These models add search by meaning, photos by what is in them and talk '
                'about a photo. They run on this PC only. Tick what to download; you can change it later in '
                'Settings > Models.',
                style: NbType.text(13, c.muted, height: 1.5),
              ),
              const SizedBox(height: NbSpace.x2),
              for (final i in main) _row(i),
              for (final n in _offer.notes)
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
                  child: Text(n, style: NbType.text(12.5, c.warn, height: 1.4)),
                ),
              if (more.isNotEmpty) ...[
                const SectionTitle('More for this PC', top: NbSpace.x4),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    'Upgrades and lighter options. Each says what it costs, as measured.',
                    style: NbType.text(12.5, c.dim, height: 1.4),
                  ),
                ),
                for (final i in more) _row(i),
              ],
              const SizedBox(height: NbSpace.x3),
              ConsentFacts(_facts(total)),
              if (_error.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: NbSpace.x2),
                  child: Text(_error, style: NbType.text(12.5, c.danger, height: 1.4)),
                ),
              const SizedBox(height: NbSpace.x3),
              const OnlyConnectionNote(),
            ],
          ),
        ),
      ),
      actions: [
        NbButton('Details', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context, SetupAnswer.details)),
        if (!_started) ...[
          // no download by pressing Enter: Later has the focus
          NbButton(
            'Later',
            kind: NbButtonKind.ghost,
            autofocus: true,
            onPressed: () => Navigator.pop(context, SetupAnswer.later),
          ),
          NbButton(
            _busy ? 'Starting…' : (total > 0 || _ticked.isEmpty ? 'Download' : 'Use these'),
            onPressed: _busy || _ticked.isEmpty ? null : _download,
          ),
        ] else ...[
          if (failed.isNotEmpty) NbButton('Try again', onPressed: _busy ? null : () => _download(failed)),
          NbButton(
            'Close',
            kind: failed.isEmpty ? NbButtonKind.primary : NbButtonKind.ghost,
            autofocus: true,
            onPressed: () => Navigator.pop(context, SetupAnswer.closed),
          ),
        ],
      ],
    );
  }

  List<(String, String)> _facts(int total) {
    final ticked = [for (final i in _offer.items) if (_ticked.contains(i.model)) i];
    final hosts = <String>{
      for (final i in ticked)
        if (i.sizeMb - (i.runtime?.sizeMb ?? 0) > 0) i.source,
    };
    final runtimes = <String>{
      for (final i in ticked)
        if (i.runtime != null && i.runtime!.sizeMb > 0) i.runtime!.id,
    };
    final live = _timeLeft();
    return [
      ('Total', total > 0 ? '$total MB, once' : 'Nothing to download'),
      if (hosts.isNotEmpty || runtimes.isNotEmpty)
        (
          'From',
          [
            ...hosts,
            if (runtimes.isNotEmpty) 'github.com (llama.cpp releases, delivered by *.githubusercontent.com)',
          ].join('; '),
        ),
      (
        'Time',
        live ??
            (_offer.estDownload != null
                ? '${_offer.estDownload} at the speed this PC measured'
                : 'Known once a download has measured this PC\'s speed'),
      ),
      ('Checked', 'Pinned revision, exact size and SHA-256'),
    ];
  }

  Widget _row(SetupItem i) => SetupRow(
    item: i,
    pc: _pc,
    ticked: _ticked.contains(i.model),
    onTick: _started || _busy
        ? null
        : (on) => setState(() => on ? _ticked.add(i.model) : _ticked.remove(i.model)),
    progress: [for (final x in [i.model, ?i.runtime?.id]) ?_progress[x]],
  );
}

/// This PC in one line: the nearest reference profile and its parts (graphics as [graphicsOf] words them).
class _PcLine extends StatelessWidget {
  const _PcLine({required this.offer});
  final SetupOffer offer;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final hw = offer.hardware;
    final cut = offer.summary.indexOf(': ', offer.summary.indexOf(': ') + 2);
    final title = cut > 0 ? offer.summary.substring(0, cut) : offer.summary;
    final why = cut > 0 ? offer.summary.substring(cut + 2) : '';
    final parts = hw == null
        ? ''
        : '${hw.threads} processor threads · ${gb(hw.ramGb)} memory · ${graphicsOf(hw).line}';
    return NbCard(
      child: Row(
        children: [
          const GlyphTile(NbGlyph.pc),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: NbType.text(14, c.text, weight: FontWeight.w600, height: 1.3)),
                if (parts.isNotEmpty) _Line(parts, style: NbType.text(12.5, c.muted, height: 1.4)),
                if (why.isNotEmpty) _Line(why, style: NbType.text(12, c.dim, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// One line that ellipsizes, with the whole text in a tooltip.
class _Line extends StatelessWidget {
  const _Line(this.text, {required this.style, this.lines = 1});
  final String text;
  final TextStyle style;
  final int lines;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: text,
    waitDuration: const Duration(milliseconds: 500),
    child: Text(text, maxLines: lines, overflow: TextOverflow.ellipsis, style: style),
  );
}

/// One model: its tile, name and outcome, the facts (download, memory, speed, time to index, where measured), why,
/// the runtime a talk model brings, the download's progress, and the tick.
class SetupRow extends StatelessWidget {
  const SetupRow({
    super.key,
    required this.item,
    required this.pc,
    required this.ticked,
    required this.onTick,
    this.progress = const [],
  });
  final SetupItem item;
  final Hardware? pc;
  final bool ticked;
  final ValueChanged<bool>? onTick;

  /// The download events of the model and its runtime.
  final List<DownloadEvent> progress;

  static NbGlyph glyphOf(String workload) => switch (workload) {
    'photo_search' => NbGlyph.image,
    'photo_talk' => NbGlyph.chat,
    _ => NbGlyph.textDoc,
  };

  static String outcomeLabel(String outcome) => switch (outcome) {
    'suggested' => 'Suggested',
    'upgrade' => 'Upgrade',
    'lighter' => 'Lighter',
    _ => 'Not measured',
  };

  static String featureOf(String workload) => switch (workload) {
    'photo_search' => 'Photos by what is in them',
    'photo_talk' => 'Talk about a photo',
    _ => 'Search by meaning',
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final i = item;
    final cost = i.cost;
    final kind = pc == null ? null : graphicsOf(pc!).kind;
    final rt = i.runtime;
    final facts = <(NbGlyph, String)>[
      (NbGlyph.download, i.onDisk ? 'On this PC' : '${i.sizeMb} MB download'),
      if (cost.ramMb != null) (NbGlyph.memory, '${cost.ramMb!.round()} MB memory'),
      if (cost.sharedMb != null && kind == GraphicsKind.integrated)
        (NbGlyph.graphics, '${cost.sharedMb!.round()} MB of it shared with the built-in graphics'),
      if (cost.gpuMb != null && kind == GraphicsKind.discrete) (NbGlyph.graphics, '${cost.gpuMb!.round()} MB video memory'),
      if (cost.queryMs != null) (NbGlyph.search, 'a search in about ${roundEven(cost.queryMs!)} ms'),
      if (cost.answerS != null) (NbGlyph.chat, 'first word in about ${roundEven(cost.answerS!)} s'),
      if (i.estIndex.isNotEmpty) (NbGlyph.clock, 'indexing: ${i.estIndex}'),
      if (cost.measuredOn.isNotEmpty && i.estIndex.isEmpty) (NbGlyph.gauge, 'measured ${cost.place}'),
    ];
    final failed = progress.where((p) => p.error.isNotEmpty).firstOrNull;
    final running = progress.where((p) => p.state == 'downloading').toList();
    final gotMb = running.fold<double>(0, (a, p) => a + p.gotMb);
    final sizeMb = running.fold<double>(0, (a, p) => a + p.sizeMb);
    final done = progress.isNotEmpty && progress.every((p) => p.state == 'ready');
    return NbCard(
      active: ticked,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GlyphTile(glyphOf(i.workload), accent: ticked),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: _Line(
                        '${featureOf(i.workload)}: ${i.name}',
                        style: NbType.text(14, c.text, weight: FontWeight.w600, height: 1.3),
                      ),
                    ),
                    const SizedBox(width: 6),
                    ModelTag(outcomeLabel(i.outcome), strong: i.outcome == 'suggested'),
                  ],
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [for (final (g, t) in facts) NbFact(g, t)],
                ),
                const SizedBox(height: 6),
                _Line(i.why, style: NbType.text(12, c.muted, height: 1.4), lines: 2),
                if (rt != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: _Line(
                      rt.sizeMb > 0
                          ? 'With the ${runtimeName(rt.id, rt.name, pc)}: ${rt.sizeMb} MB from github.com'
                          : 'Runs on the ${runtimeName(rt.id, rt.name, pc)}, already on this PC',
                      style: NbType.text(12, c.dim, height: 1.4),
                    ),
                  ),
                if (running.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  NbMeter(fraction: sizeMb > 0 ? (gotMb / sizeMb).clamp(0, 1).toDouble() : 0, busy: sizeMb == 0),
                  const SizedBox(height: 2),
                  Text('Downloading… ${gotMb.round()} of ${sizeMb.round()} MB', style: NbType.data(11, c.dim)),
                ] else if (failed != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: _Line(
                      "Didn't download: ${failed.error}",
                      style: NbType.text(12, c.danger, weight: FontWeight.w600, height: 1.4),
                    ),
                  )
                else if (done)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text('Downloaded and checked.', style: NbType.text(12, c.orange, height: 1.4)),
                  )
                else if (i.state == 'failed' && i.error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: _Line(
                      "The last download didn't finish: ${i.error}",
                      style: NbType.text(12, c.danger, height: 1.4),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          NbSwitch(value: ticked, onChanged: onTick, label: 'Download ${i.name}'),
        ],
      ),
    );
  }
}

/// Rounded as the engine rounds (Python's round: halves to even), so a chip and the engine's sentence agree.
int roundEven(double x) {
  final f = x.floor();
  final d = x - f;
  if (d > .5) return f + 1;
  if (d < .5) return f;
  return f.isEven ? f : f + 1;
}

String _duration(double seconds) {
  if (seconds < 60) return 'Under a minute';
  final m = (seconds / 60).round();
  if (m < 60) return 'About $m min';
  final h = m ~/ 60, r = m % 60;
  return 'About $h h${r > 0 ? ' $r min' : ''}';
}

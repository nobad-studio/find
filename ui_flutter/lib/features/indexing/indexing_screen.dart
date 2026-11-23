/// Index: what NOBAD Find is doing, what it costs, and why. The level and its reason (the page's one loud
/// element), the pipeline with times to go, its own processor/memory/disk/graphics use per process with the last
/// five minutes, the models, recent decisions, the index at a glance, folders, drives and the encryption note.
///
/// Subscribes to `status_full` while open (StatusController.watch) and drops it when closed. No timers.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/format.dart';
import '../../engine/models/status.dart';
import '../../widgets/badges.dart';
import '../../widgets/smooth_scroll.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/panels.dart';
import '../../widgets/resources_chart.dart';
import '../consent/download_consent_dialog.dart';

class IndexingScreen extends StatefulWidget {
  const IndexingScreen({super.key});

  @override
  State<IndexingScreen> createState() => _IndexingScreenState();
}

class _IndexingScreenState extends State<IndexingScreen> {
  AppScope? _s;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_s != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _s = s;
    unawaited(s.status.watch(true));
  }

  @override
  void dispose() {
    unawaited(_s?.status.watch(false));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: Listenable.merge([s.status, s.settings]),
      builder: (context, _) {
        final st = s.status.status;
        final d = s.status.details;
        return LayoutBuilder(
          builder: (context, box) {
            final wide = box.maxWidth >= NbSpace.wide;
            final body = SmoothScroll(builder: (sc) => SingleChildScrollView(controller: sc, 
              padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, NbSpace.x6),
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: wide ? NbSpace.maxContent : NbSpace.column),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!s.settings.settings.flag('bg_notice_seen')) ...[
                        NoticeBar(
                          text:
                              'Closing the window now stops indexing. Turn on Keep indexing in the background in '
                              'Settings → Performance to keep it going.',
                          action: 'Got it',
                          onAction: () => s.settings.set('bg_notice_seen', true),
                        ),
                        const SizedBox(height: NbSpace.x4),
                      ],
                      _Now(status: st, connected: s.status.connected),
                      if (s.status.turbo != null && s.status.connected)
                        Padding(
                          padding: const EdgeInsets.only(top: 8, left: 2),
                          child: Text(
                            s.status.turbo!.line,
                            style: NbType.data(11.5, s.status.turbo!.running ? c.orange : c.dim),
                          ),
                        ),
                      if (!s.status.connected)
                        Padding(
                          padding: const EdgeInsets.only(top: NbSpace.x4),
                          child: Text(s.status.line, style: NbType.text(13, c.warn)),
                        ),
                      // no engine: no numbers at all (old ones would look current)
                      if (d != null && s.status.connected) ..._layout(_details(context, s, d), wide),
                      if (d == null && s.status.connected) const _Loading(),
                    ],
                  ),
                ),
              ),
            ));
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PageHeader(
                  'Index',
                  crumb: 'Status',
                  trailing: s.status.connected
                      ? NbButton('Rescan now', kind: NbButtonKind.ghost, small: true, onPressed: s.settings.rescan)
                      : null,
                ),
                Expanded(child: body),
              ],
            );
          },
        );
      },
    );
  }

  /// Narrow: one column. Wide: a dashboard, what it is doing, the models and the index on the left; what it
  /// uses, recent decisions, folders and drives on the right.
  /// How many sections at the top span the width on a wide window (doing, uses, processes).
  static const _spanning = 3;

  List<Widget> _layout(List<Widget> flat, bool wide) {
    if (!wide) return flat;
    final sections = <List<Widget>>[];
    for (final w in flat) {
      if (w is SectionTitle || sections.isEmpty) sections.add([]);
      sections.last.add(w);
    }
    // what it is doing, what it uses and the processes span the width (their rows need room); the rest in two
    // columns
    final first = <Widget>[];
    for (var i = 0; i < _spanning && sections.isNotEmpty; i++) {
      first.addAll(sections.removeAt(0));
    }
    final left = <Widget>[], right = <Widget>[];
    for (var i = 0; i < sections.length; i++) {
      (i.isEven ? left : right).addAll(sections[i]);
    }
    return [
      ...first,
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: left),
          ),
          const SizedBox(width: 28),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: right),
          ),
        ],
      ),
    ];
  }

  List<Widget> _details(BuildContext context, AppScope s, IndexDetails d) {
    final r = d.resources;
    final phaseLabel = s.status.status?.phaseLabel ?? '';
    // 1.1.1: the engine counts the index totals in the background; until the first count is in, it says so
    String total(int n) => d.countingTotals ? 'Counting…' : groupDigits(n);
    return [
      const SectionTitle('What it is doing', top: NbSpace.x4),
      TileGrid(min: 270, children: [for (final p in d.phases) _PhaseCard(p)]),
      const SectionTitle('What NOBAD Find uses'),
      TileGrid(
        min: 150,
        children: [
          NbStat(hue: NbHue.use, glyph: NbGlyph.gauge, value: pct(r.cpu), label: 'Processor'),
          NbStat(hue: NbHue.use, glyph: NbGlyph.chip, value: r.memoryMb != null ? mb(r.memoryMb) : '–',
              label: 'Memory'),
          NbStat(
            hue: NbHue.use,
            glyph: NbGlyph.drive,
            value: r.readMbS != null ? '${r.readMbS!.toStringAsFixed(r.readMbS! < 10 ? 1 : 0)} MB/s' : '–',
            label: 'Disk reading',
          ),
          NbStat(hue: NbHue.use, glyph: NbGlyph.media, value: r.gpu == null ? 'Not used' : pct(r.gpu),
              label: 'Graphics card'),
        ],
      ),
      const SizedBox(height: 10),
      NbPanel(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: ResourcesChart(history: d.history),
      ),
      const SectionTitle('Processes'),
      _ProcessTable(r.processes),
      const SectionTitle('Models'),
      TileGrid(min: 250, children: [for (final m in d.models) _ModelCardView(m)]),
      const SectionTitle('Recent decisions'),
      _Activity(s.status.activity),
      const SectionTitle('Index at a glance'),
      TileGrid(
        min: 200,
        children: [
          NbStat(hue: NbHue.library, glyph: NbGlyph.rings, value: phaseLabel, label: 'Status',
              live: s.status.status?.phase != 'watching'),
          NbStat(hue: NbHue.folder, glyph: NbGlyph.folder, value: groupDigits(s.status.status?.files ?? 0),
              label: 'Files and folders'),
          NbStat(hue: NbHue.text, glyph: NbGlyph.doc, value: total(d.withText), label: 'With readable text'),
          NbStat(hue: NbHue.meaning, glyph: NbGlyph.search, value: total(d.vectors + d.nameVectors),
              label: 'Understood by meaning'),
          NbStat(hue: NbHue.photo, glyph: NbGlyph.image, value: total(d.photoVectors),
              label: 'Photos understood'),
          NbStat(
            hue: NbHue.use,
            glyph: NbGlyph.chip,
            value: d.memoryMb != null ? '${d.memoryMb!.round()} MB' : '–',
            label: d.modelsLoaded.isNotEmpty ? 'Memory · ${d.modelsLoaded.join(', ')} loaded' : 'Memory · no models loaded',
          ),
          NbStat(
            hue: NbHue.folder,
            glyph: NbGlyph.clock,
            value: d.rate > 0 ? '${groupDigits(d.rate.round())}/s' : 'Not yet',
            label: s.status.status?.phase == 'names' ? 'Scan speed' : 'Last scan speed',
          ),
          NbStat(hue: NbHue.library, glyph: NbGlyph.drive, value: '${(d.dbBytes / 1048576).toStringAsFixed(0)} MB',
              label: 'Index size'),
          NbStat(
            hue: NbHue.use,
            glyph: NbGlyph.sliders,
            value: d.plan != null && d.plan!.cpu > 0
                ? '${d.plan!.textWorkers}–${d.plan!.textWorkersIdle} of ${d.plan!.cpu}'
                : '–',
            label: 'Workers / CPU threads',
          ),
          NbStat(hue: NbHue.library, glyph: NbGlyph.gauge, value: d.speed.isNotEmpty ? d.speedLabel : '–',
              label: d.speedHelp),
          NbStat(hue: NbHue.page, glyph: NbGlyph.doc, value: d.ocrOn ? 'On' : 'Off',
              label: d.ocrOn ? 'Words in pictures (OCR)' : 'OCR: ${d.ocrWhy.isNotEmpty ? d.ocrWhy : 'not available'}'),
          NbStat(hue: NbHue.use, glyph: NbGlyph.drive,
              value: d.plan?.ssd == null ? '–' : (d.plan!.ssd! ? 'SSD' : 'Hard disk'), label: 'Drive type'),
        ],
      ),
      const SectionTitle('Folders being searched'),
      _PlainList([for (final r in d.roots) (r, '')]),
      const SectionTitle('Drives'),
      _PlainList([
        for (final dr in d.drives)
          ('${dr.root} ${dr.label}'.trim(), '${dr.typeLabel}${dr.present ? '' : ' · not connected'}'),
      ]),
      const SizedBox(height: NbSpace.x5),
      _Encryption(encrypted: d.encrypted),
    ];
  }
}

/// The level, its reason, and Pause / Resume: the page's one loud element.
class _Now extends StatelessWidget {
  const _Now({required this.status, required this.connected});
  final EngineStatus? status;
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final st = status ?? const EngineStatus();
    final lv = connected ? st.levelKey : 'paused';
    final paused = lv == 'paused';
    final label = connected ? EngineStatus.levelLabels[lv]! : 'Not connected';
    return NbPanel(
      live: lv == 'full',
      padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
      child: Row(
        children: [
          LevelGlyph(level: lv, color: c.orange, dim: c.dim, size: 14),
          const SizedBox(width: 14),
          Expanded(
            child: Semantics(
              liveRegion: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: NbType.text(15, paused ? c.muted : c.text, weight: FontWeight.w700, height: 1.3)),
                  if (st.reason.isNotEmpty && connected) ...[
                    const SizedBox(height: 2),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 600),
                      child: Text(st.reason, style: NbType.text(12.5, c.muted, height: 1.4)),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(width: 16),
          if (connected)
            NbButton(
              paused ? 'Resume' : 'Pause for 1 hour',
              kind: paused ? NbButtonKind.primary : NbButtonKind.ghost,
              icon: paused ? NbGlyph.play : NbGlyph.pause,
              onPressed: () => paused ? s.status.resume() : s.status.pauseFor(const Duration(hours: 1)),
            ),
        ],
      ),
    );
  }
}

/// One step of indexing as a card: what it is (a coloured tile), its state, a meter and its numbers as chips.
class _PhaseCard extends StatelessWidget {
  const _PhaseCard(this.p);
  final PhaseRow p;

  static (NbHue, NbGlyph, String?) look(String id) => switch (id) {
    'names' => (NbHue.folder, NbGlyph.folder, null),
    'text' => (NbHue.text, NbGlyph.doc, null),
    'ocr' => (NbHue.page, NbGlyph.doc, null),
    'meaning' || 'names_meaning' => (NbHue.meaning, NbGlyph.search, 'Aa'),
    'rebuild' => (NbHue.library, NbGlyph.rings, null),
    'photos' => (NbHue.photo, NbGlyph.image, null),
    _ => (NbHue.library, NbGlyph.info, null),
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final off = p.state == PhaseState.off;
    final run = p.state == PhaseState.running;
    final done = p.state == PhaseState.done;
    final (hue, glyph, text) = look(p.id);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 11),
      decoration: BoxDecoration(
        color: run ? c.orange.withValues(alpha: .06) : c.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: run ? c.orange.withValues(alpha: .45) : c.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              NbAvatar(hue: hue, glyph: glyph, text: text, size: 36, dim: off),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  p.label,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: NbType.text(13.5, off ? c.dim : c.text, weight: FontWeight.w600, height: 1.3),
                ),
              ),
              const SizedBox(width: 8),
              NbFact(done ? NbGlyph.check : (run ? NbGlyph.play : NbGlyph.clock), p.stateLabel, strong: run),
            ],
          ),
          const SizedBox(height: 10),
          NbMeter(fraction: p.fraction, busy: p.busy, muted: p.state == PhaseState.waiting || off),
          if (p.count.isNotEmpty || p.extra.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                if (p.count.isNotEmpty) NbFact(NbGlyph.rings, p.count),
                if (p.extra.isNotEmpty) NbFact(NbGlyph.clock, p.extra),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// Every process of NOBAD Find's own, as Task Manager lists them under it: what each one is in plain words, a line
/// on what it does, its PID, processor, memory (working set and private) and how long it has run, with a short
/// note when it is idle, starting or ending. The engine names them; this only lays them out.
class _ProcessTable extends StatelessWidget {
  const _ProcessTable(this.rows);
  final List<ProcessUse> rows;

  /// "0.4%" under 10, "12%" above: an idle worker isn't "0%" when it isn't.
  static String cpu(double v) => !v.isFinite ? '–' : (v < 10 ? '${v.toStringAsFixed(1)}%' : '${v.round()}%');

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget cell(String t, {bool head = false}) => Expanded(
      flex: 2,
      child: Text(
        t,
        textAlign: TextAlign.right,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: head ? NbType.text(NbSize.small, c.dim) : NbType.data(NbSize.caption + .5, c.muted),
      ),
    );
    if (rows.isEmpty) {
      return NbPanel(
        padding: const EdgeInsets.all(14),
        child: Text('No process list from the engine yet.', style: NbType.text(13, c.dim)),
      );
    }
    final mem = rows.fold<double>(0, (a, p) => a + (p.readable ? p.memoryMb : 0));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 2, bottom: 8),
          child: Text(
            '${rows.length} ${rows.length == 1 ? 'process' : 'processes'} of NOBAD Find\'s own, ${mb(mem)} in '
            'memory together. Memory is the working set, as Task Manager shows it; private is what each one has '
            'committed.',
            style: NbType.text(12.5, c.muted, height: 1.4),
          ),
        ),
        NbPanel(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    Expanded(flex: 7, child: Text('Process', style: NbType.text(NbSize.small, c.dim))),
                    cell('PID', head: true),
                    cell('Processor', head: true),
                    cell('Memory', head: true),
                    cell('Private', head: true),
                    cell('Running', head: true),
                  ],
                ),
              ),
              Container(height: 1, color: c.line2),
              for (var i = 0; i < rows.length; i++)
                Container(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: BoxDecoration(
                    border: i == rows.length - 1 ? null : Border(bottom: BorderSide(color: c.line)),
                  ),
                  child: _row(c, rows[i], cell),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _row(NbColors c, ProcessUse p, Widget Function(String, {bool head}) cell) {
    final busy = p.readable && p.cpu >= 1;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          flex: 7,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(p.name, style: NbType.text(13, c.text, weight: FontWeight.w600, height: 1.3)),
              if (p.about.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 1, right: 12),
                  child: Text(p.about, style: NbType.text(NbSize.small, c.dim, height: 1.35)),
                ),
              if (p.note.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 2, right: 12),
                  child: Text(p.note, style: NbType.text(NbSize.small, c.orange, height: 1.35)),
                ),
            ],
          ),
        ),
        cell('${p.pid}'),
        Expanded(
          flex: 2,
          child: Text(
            p.readable ? cpu(p.cpu) : '–',
            textAlign: TextAlign.right,
            style: NbType.data(NbSize.caption + .5, busy ? c.orange : c.muted),
          ),
        ),
        cell(p.readable ? mb(p.memoryMb) : '–'),
        cell(p.readable && p.privateMb != null ? mb(p.privateMb) : '–'),
        cell(runningFor(p.ageS)),
      ],
    );
  }
}

class _ModelCardView extends StatelessWidget {
  const _ModelCardView(this.m);
  final ModelCard m;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    // A download event is newer than the card in the last status_full.
    final live = m.id == 'ocr' ? null : s.status.model(m.id);
    final downloading = live?.downloading ?? m.download != null;
    final state = live != null && live.downloading
        ? 'Downloading ${mb(live.got / 1048576)} of ${mb(live.size / 1048576)}'
              '${live.mbS > 0 ? ' at ${live.mbS.toStringAsFixed(1)} MB/s' : ''}'
        : m.stateLine;
    final canGet = m.id != 'ocr' && !m.onDisk && !downloading && !(live?.ready ?? false);
    final (hue, glyph, text) = switch (m.id) {
      'photo' => (NbHue.photo, NbGlyph.image, null),
      'ocr' => (NbHue.page, NbGlyph.doc, null),
      _ => (NbHue.text, NbGlyph.doc, 'Aa'),
    };
    final facts = [for (final f in m.facts.split('·')) if (f.trim().isNotEmpty) f.trim()];
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: m.loaded ? c.orange.withValues(alpha: .06) : c.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: m.loaded ? c.orange.withValues(alpha: .45) : c.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              NbAvatar(hue: hue, glyph: glyph, text: text, size: 36, dim: !m.onDisk && m.id != 'ocr'),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(m.name, style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.3)),
                    Text(state, style: NbType.text(12, m.loaded || downloading ? c.orange : c.muted, height: 1.35)),
                  ],
                ),
              ),
            ],
          ),
          if (facts.isNotEmpty) ...[
            const SizedBox(height: 9),
            Wrap(spacing: 6, runSpacing: 6, children: [for (final f in facts) NbFact(NbGlyph.info, f)]),
          ],
          if (downloading && live != null) ...[
            const SizedBox(height: 10),
            NbMeter(fraction: live.size > 0 ? live.got / live.size : (m.download?.fraction ?? 0)),
          ],
          if (canGet) ...[
            const SizedBox(height: 10),
            NbButton(
              'Download…',
              kind: NbButtonKind.ghost,
              small: true,
              onPressed: () {
                unawaited(s.settings.download(m.id, consent: (x) => askConsentFor(context, m.id, x)));
              },
            ),
          ],
        ],
      ),
    );
  }
}

class _Activity extends StatelessWidget {
  const _Activity(this.items);
  final List<ActivityEntry> items;

  /// About six lines: the newest at the top, older ones scroll inside (0.9.1: it no longer pushes the page down).
  static const _boxHeight = 246.0;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbPanel(
      padding: EdgeInsets.zero,
      child: items.isEmpty
          ? Padding(
              padding: const EdgeInsets.all(14),
              child: Text(
                'Nothing yet. NOBAD Find adds a line here whenever it changes pace, pauses or finishes something.',
                style: NbType.text(13, c.dim),
              ),
            )
          : SizedBox(
              height: _boxHeight,
              child: ListView(
                padding: EdgeInsets.zero,
                primary: false,
                children: [
                for (var i = 0; i < items.length; i++)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 64,
                          child: Text(clock(items[i].t), style: NbType.data(NbSize.caption, c.dim, height: 1.6)),
                        ),
                        Expanded(child: Text(items[i].text, style: NbType.text(13, c.muted, height: 1.5))),
                      ],
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

class _PlainList extends StatelessWidget {
  const _PlainList(this.rows);
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (rows.isEmpty) return Text('–', style: NbType.data(12, c.dim));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (a, b) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: a, style: NbType.data(12.5, c.muted)),
                  if (b.isNotEmpty) TextSpan(text: '   $b', style: NbType.text(NbSize.small, c.dim)),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _Encryption extends StatelessWidget {
  const _Encryption({required this.encrypted});
  final bool encrypted;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Text(
      encrypted
          ? 'The index is encrypted on disk (SQLCipher). Its key is protected by your Windows sign-in, and nothing '
                'leaves this PC.'
          : "The index is NOT encrypted: SQLCipher isn't installed in this build. It stays in your own profile folder.",
      style: NbType.text(13, encrypted ? c.muted : c.warn, height: 1.5),
    );
  }
}

/// While the first full status is on its way: the page's shape, quietly.
class _Loading extends StatelessWidget {
  const _Loading();

  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.only(top: NbSpace.x8),
    child: Shimmer(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Skeleton(width: 160, height: 14),
          SizedBox(height: NbSpace.x3),
          Skeleton(height: 230, radius: NbRadius.panel),
          SizedBox(height: NbSpace.x8),
          Skeleton(width: 190, height: 14),
          SizedBox(height: NbSpace.x3),
          Skeleton(height: 150, radius: NbRadius.panel),
        ],
      ),
    ),
  );
}

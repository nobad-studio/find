/// What to index: the scope (Whole PC, My files, Custom) and its folders, then every category of place as a card
/// like the Models page's (a tile for what it is, its name and one line, the facts as chips: in or out, how many
/// files of it are in the index, names only; its switch; the full explanation and example paths under Details), how
/// files are read, and the optional turbo index. Nothing is skipped silently: every category the engine lists is
/// shown. The page opens at once: the parts read from the settings are drawn straight away, the categories and
/// their counts when `scope_info` answers. An engine without `scope_info` keeps the older folder rows and says why.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/engine_api.dart';
import '../../../engine/events.dart';
import '../../../engine/models/format.dart';
import '../../../engine/models/scope_info.dart';
import '../../../state/settings_controller.dart' show errorText;
import '../../../widgets/badges.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/icons.dart';
import '../../../widgets/motion.dart';
import '../settings_parts.dart';

class IndexingPage extends StatefulWidget {
  const IndexingPage({super.key});

  @override
  State<IndexingPage> createState() => _IndexingPageState();
}

enum _Load { loading, ready, needsNewer, offline }

class _IndexingPageState extends State<IndexingPage> {
  AppScope? _s;
  StreamSubscription<EngineEvent>? _sub;
  _Load _load = _Load.loading;
  String _why = '';
  ScopeInfo _scope = const ScopeInfo();
  TurboState? _turbo;
  bool _turboBusy = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_s != null) return;
    _s = AppScope.of(context);
    _sub = _s!.engine.events.listen((e) {
      if (e is TurboEvent && mounted) setState(() => _turbo = e.state);
    });
    unawaited(_refresh());
  }

  @override
  void dispose() {
    unawaited(_sub?.cancel());
    super.dispose();
  }

  Future<void> _refresh() async {
    final e = _s!.engine;
    try {
      final scope = await e.scopeInfo();
      TurboState? turbo;
      try {
        turbo = await e.turboState();
      } on RpcException {
        turbo = null;
      }
      if (!mounted) return;
      setState(() {
        _scope = scope;
        _turbo = turbo;
        _load = _Load.ready;
      });
    } on RpcException catch (x) {
      if (!mounted) return;
      setState(() {
        _load = x.code == -32601 ? _Load.needsNewer : _Load.offline;
        _why = x.message;
      });
    } on Object {
      if (mounted) setState(() => _load = _Load.offline);
    }
  }

  /// A scope or category switch: the engine walks again, and the list is read again.
  Future<void> _set(String key, Object value) async {
    await _s!.settings.set(key, value);
    await _refresh();
  }

  Future<void> _setTurbo(bool on) async {
    if (_turboBusy) return;
    setState(() => _turboBusy = true);
    try {
      final r = await _s!.engine.turboSet(on);
      if (!r.ok) _s!.toasts.show(r.error.isNotEmpty ? r.error : 'The turbo index stayed off.');
      if (mounted && r.state != null) setState(() => _turbo = r.state);
    } on Object catch (e) {
      _s!.toasts.show(errorText(e));
    }
    if (mounted) setState(() => _turboBusy = false);
  }

  /// "Update helper" / "Remove": Windows asks once.
  Future<void> _turboHelper(String action) async {
    if (_turboBusy) return;
    setState(() => _turboBusy = true);
    try {
      final r = await _s!.engine.turboHelper(action);
      if (!r.ok || r.error.isNotEmpty) {
        _s!.toasts.show(r.error.isNotEmpty ? r.error : "The turbo index's helper wasn't changed.");
      }
      if (mounted && r.state != null) setState(() => _turbo = r.state);
    } on Object catch (e) {
      _s!.toasts.show(errorText(e));
    }
    if (mounted) setState(() => _turboBusy = false);
  }

  @override
  Widget build(BuildContext context) {
    return switch (_load) {
      _Load.loading || _Load.ready => _page(context),
      _Load.needsNewer => _Older(note: 'Choosing what to index needs a newer engine. $_why'.trim()),
      _Load.offline => const _Older(),
    };
  }

  Widget _page(BuildContext context) {
    final c = NbColors.of(context);
    final ready = _load == _Load.ready;
    // before the answer: the scope as saved in the settings, so the switches are there at once
    final scope = ready ? _scope.scope : IndexScope.parse(_s!.settings.settings.text('scope'));
    final roots = _scope.roots;
    final turbo = _turbo;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'Where',
          icon: NbGlyph.folderShut,
          rows: [
            SettingRow(
              label: 'What to index',
              help: switch (scope) {
                IndexScope.wholePc =>
                  'Every fixed drive. Windows, programs and app data stay out unless you add them below.',
                IndexScope.myFiles => 'Your profile folder: Documents, Desktop, Downloads, Pictures and the rest.',
                IndexScope.custom => 'Only the folders you choose.',
                null => '',
              },
              below: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  NbSegmented<IndexScope>(
                    value: scope,
                    options: [for (final x in IndexScope.values) (x, x.label)],
                    onChanged: (x) => unawaited(_set('scope', x.wire)),
                  ),
                  if (scope != IndexScope.custom && roots.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Semantics(
                      label: 'Folders the walk starts from: ${roots.join(', ')}',
                      excludeSemantics: true,
                      child: Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [for (final r in roots) NbFact(NbGlyph.folder, r)],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (scope == IndexScope.custom)
              const FoldersSetting('roots', 'Folders', 'NOBAD Find indexes these folders and what is inside them.'),
            const FoldersSetting(
              'exclude',
              'Never index',
              'These folders and files are skipped and removed from the index.',
            ),
          ],
        ),
        SettingsGroup(
          'What is included',
          icon: NbGlyph.list,
          rows: [
            Container(
              alignment: Alignment.centerLeft,
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 4),
              child: Text(
                'Each kind of place, whether it is indexed and how many of its files are in the index now.',
                style: NbType.text(12.5, c.muted, height: 1.4),
              ),
            ),
            if (!ready)
              const _Counting()
            else
              for (final k in _scope.categories)
                _CategoryCard(k, scope: scope, onSet: (on) => unawaited(_set(k.setting, on))),
          ],
        ),
        const SettingsGroup(
          'Reading files',
          icon: NbGlyph.textDoc,
          rows: [
            SwitchSetting(
              'content',
              'Read the text inside files',
              'Documents, PDFs, code, notes and e-mail files. Off: names only.',
            ),
            TextSetting(
              'content_max_mb',
              'Largest file to read (MB)',
              'Bigger files are still found by name.',
              number: true,
            ),
            SwitchSetting(
              'ocr',
              'Words in photos and scans',
              'Read with the OCR built into Windows (offline). Slower, so it runs after everything else.',
            ),
            SwitchSetting('src_mail', 'E-mail files', '.eml and .mbox files found on your drives.'),
          ],
        ),
        if (turbo != null)
          SettingsGroup(
            'Turbo index',
            icon: NbGlyph.bolt,
            rows: [
              _TurboCard(
                turbo,
                busy: _turboBusy,
                onSet: (v) => unawaited(_setTurbo(v)),
                onHelper: (a) => unawaited(_turboHelper(a)),
              ),
            ],
          ),
      ],
    );
  }
}

/// While `scope_info` is on its way: placeholder cards and what is happening (no moving shimmer, nothing to settle).
class _Counting extends StatelessWidget {
  const _Counting();

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget card() => NbCard(
      child: Row(
        children: [
          const Skeleton(width: 40, height: 40),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [Skeleton(width: 180, height: 13), SizedBox(height: 8), Skeleton(width: 300)],
            ),
          ),
        ],
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 2),
          child: Semantics(
            liveRegion: true,
            child: Text('Counting what is in the index…', style: NbType.text(12, c.dim, height: 1.4)),
          ),
        ),
        card(),
        card(),
        card(),
      ],
    );
  }
}

/// One category as a card: its tile, name and one line, its switch (or "Always out"), the facts the engine gives
/// as chips, and the full explanation with example paths under Details.
class _CategoryCard extends StatelessWidget {
  const _CategoryCard(this.k, {required this.scope, required this.onSet});
  final ScopeCategory k;
  final IndexScope? scope;
  final ValueChanged<bool> onSet;

  static (NbHue, NbGlyph) look(String id) => switch (id) {
    'system' => (NbHue.page, NbGlyph.settings),
    'caches' => (NbHue.text, NbGlyph.code),
    'secrets' => (NbHue.meaning, NbGlyph.shield),
    'other_profiles' => (NbHue.library, NbGlyph.close),
    'removable' => (NbHue.folder, NbGlyph.drive),
    'network' => (NbHue.use, NbGlyph.drive),
    _ => (NbHue.library, NbGlyph.info),
  };

  /// Why a locked category can't be switched here: a chip, and a sentence under Details.
  (String, String) get lockedWhy => switch (k.id) {
    'system' => ('Whole PC only', 'My files and Custom cover only your own folders. Choose Whole PC to include it.'),
    'removable' || 'network' => (
      'Custom: use Folders',
      'With Custom, only the folders you add are indexed: add the drive under Folders above.',
    ),
    'other_profiles' => ('Never indexed', "They aren't yours to search, so this can't be changed."),
    _ => ("Can't be changed here", ''),
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final canSwitch = !k.locked && k.setting.isNotEmpty;
    final (hue, glyph) = look(k.id);
    final (lockChip, lockLine) = lockedWhy;
    return NbCard(
      active: k.included,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ExcludeSemantics(child: NbAvatar(hue: hue, glyph: glyph, dim: !k.included)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(k.name, style: NbType.text(14, c.text, weight: FontWeight.w600, height: 1.3)),
                    if (k.line.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(k.line, style: NbType.text(12.5, c.muted, height: 1.4)),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              if (canSwitch)
                NbSwitch(value: k.included, label: k.name, onChanged: onSet)
              else
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    k.included ? 'Always in' : 'Always out',
                    style: NbType.text(12.5, c.dim, weight: FontWeight.w600),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              // a locked one says "Always in / out" beside it already
              if (!k.locked && k.included)
                const NbFact(NbGlyph.check, 'Included', strong: true)
              else if (!k.locked)
                const NbFact(NbGlyph.close, 'Left out'),
              NbFact(NbGlyph.rings, k.count == null ? 'Not counted' : '${groupDigits(k.count!)} in the index'),
              if (k.namesOnly == NamesOnly.all)
                const NbFact(NbGlyph.shield, 'Names only, never read')
              else if (k.namesOnly == NamesOnly.some)
                const NbFact(NbGlyph.shield, 'App databases: names only'),
              if (k.locked) NbFact(NbGlyph.info, lockChip),
            ],
          ),
          if (k.id == 'secrets' && (k.included || canSwitch))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'Names only: the contents of these files are never read.',
                style: NbType.text(12, c.warn, weight: FontWeight.w600, height: 1.4),
              ),
            ),
          const SizedBox(height: 6),
          NbDetails(
            about: k.name,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(4, 2, 4, 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (k.why.isNotEmpty) NbDetailLine('What it is', NbDetailLine.text(context, k.why)),
                  if (k.examples.isNotEmpty)
                    NbDetailLine(
                      'For example',
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          for (final e in k.examples) Text(e, style: NbType.data(12, c.text, height: 1.45)),
                        ],
                      ),
                    ),
                  if (k.locked && lockLine.isNotEmpty) NbDetailLine('Why it is fixed', NbDetailLine.text(context, lockLine)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The turbo index as a card: what it reads, its switch (Windows asks once to set it up), its state, the helper's
/// "Update helper" / "Remove" and each drive as chips; the full explanation and the per-drive table under Details.
class _TurboCard extends StatelessWidget {
  const _TurboCard(this.t, {required this.busy, required this.onSet, required this.onHelper});
  final TurboState t;
  final bool busy;
  final ValueChanged<bool> onSet;
  final ValueChanged<String> onHelper;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final on = t.enabled || t.running;
    return NbCard(
      active: t.running,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ExcludeSemantics(child: NbAvatar(hue: NbHue.use, glyph: NbGlyph.gauge, dim: !on)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Turbo index', style: NbType.text(14, c.text, weight: FontWeight.w600, height: 1.3)),
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(
                        "Lists NTFS drives from Windows' own file list and sees changes at once.",
                        style: NbType.text(12.5, c.muted, height: 1.4),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              if (busy)
                Text('Waiting for Windows…', style: NbType.text(12, c.dim))
              else
                NbSwitch(value: on, label: 'Turbo index', onChanged: t.available ? onSet : null),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              const NbFact(NbGlyph.shield, 'Names, sizes and dates only'),
              NbFact(NbGlyph.info, switch (t.helper) {
                TurboHelper.installed => 'Helper set up: starts without asking',
                TurboHelper.needsUpdate => 'Helper needs your OK once to update',
                TurboHelper.notInstalled => 'Asks for administrator once, to set up',
              }),
              for (final v in t.volumes)
                NbFact(
                  NbGlyph.drive,
                  [
                    v.label,
                    v.ntfs ? 'NTFS' : 'not NTFS',
                    if (v.files > 0) '${groupDigits(v.files)} files',
                  ].join(' · '),
                ),
            ],
          ),
          // its state, unless simply off (the Index page's "off" line points to this page)
          if (t.running || t.enabled || t.error.isNotEmpty || !t.available)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Semantics(
                liveRegion: true,
                child: Text(t.line, style: NbType.text(12, t.running ? c.orange : c.muted, weight: FontWeight.w600)),
              ),
            ),
          if (t.needsUpdate || (t.removable && !on))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  if (t.needsUpdate)
                    NbButton(
                      'Update helper',
                      small: true,
                      semanticLabel: "Update the turbo index's helper (Windows asks once)",
                      onPressed: busy ? null : () => onHelper('update'),
                    ),
                  if (t.removable && !on)
                    NbButton(
                      'Remove',
                      small: true,
                      kind: NbButtonKind.ghost,
                      semanticLabel: "Remove the turbo index's helper (Windows asks once)",
                      onPressed: busy ? null : () => onHelper('remove'),
                    ),
                ],
              ),
            ),
          const SizedBox(height: 6),
          NbDetails(
            about: 'Turbo index',
            child: Padding(
              padding: const EdgeInsets.fromLTRB(4, 2, 4, 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  NbDetailLine(
                    'What it is',
                    NbDetailLine.text(
                      context,
                      "Reads NTFS's own list of files and its change journal: file names, sizes and dates, so a whole "
                      'drive is listed in seconds and changes show up at once. Never file contents, and never other '
                      "people's files. Windows asks for administrator permission (UAC) once, when you turn it on: "
                      'NOBAD Find then sets up a small helper in Program Files that only your account can start, '
                      'and starts it without asking. When NOBAD Find is updated, the helper needs your OK once more. '
                      'Turning turbo off removes the helper (Windows asks once).',
                    ),
                  ),
                  if (t.volumes.isNotEmpty) NbDetailLine('Drives', _TurboTable(t)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Per drive: NTFS or not, files read, whether changes come from the change journal, when it was read.
class _TurboTable extends StatelessWidget {
  const _TurboTable(this.t);
  final TurboState t;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget cell(String s, {bool head = false, double w = 90}) => SizedBox(
      width: w,
      child: Text(s, style: head ? NbType.text(11, c.dim, weight: FontWeight.w600) : NbType.data(11.5, c.muted)),
    );
    String when(double? t) {
      if (t == null) return '—';
      final d = DateTime.now().difference(DateTime.fromMillisecondsSinceEpoch((t * 1000).round()));
      return d.inSeconds < 60 ? 'just now' : '${span(d.inSeconds)} ago';
    }

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              cell('Drive', head: true, w: 60),
              cell('File system', head: true),
              cell('Files', head: true),
              cell('Changes', head: true, w: 120),
              cell('Read', head: true),
            ],
          ),
          for (final v in t.volumes)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Row(
                children: [
                  cell(v.label, w: 60),
                  cell(v.ntfs ? 'NTFS' : 'Not NTFS'),
                  cell(v.files > 0 ? groupDigits(v.files) : '—'),
                  cell(v.usnOk ? 'Change journal' : (v.ntfs ? 'Folder walk' : '—'), w: 120),
                  cell(when(v.lastScan)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// The 0.7.0 rows, for an engine without `scope_info`.
class _Older extends StatelessWidget {
  const _Older({this.note = ''});
  final String note;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Text(note, style: NbType.text(13, c.muted, height: 1.45)),
          ),
        const SettingsGroup(
          'What to search',
          icon: NbGlyph.search,
          rows: [
            FoldersSetting(
              'roots',
              'Folders to search',
              "Empty: your profile folder and every fixed drive (never other people's profiles or Windows itself).",
            ),
            FoldersSetting(
              'exclude',
              'Never search',
              'These folders and files are skipped and removed from the index.',
            ),
            SwitchSetting(
              'content',
              'Read the text inside files',
              'Documents, PDFs, code, notes and e-mail files. Off: names only.',
            ),
            TextSetting(
              'content_max_mb',
              'Largest file to read (MB)',
              'Bigger files are still found by name.',
              number: true,
            ),
            SwitchSetting(
              'ocr',
              'Words in photos and scans',
              'Screenshots, photos of documents and scanned PDFs, read with the OCR built into Windows (offline). '
                  'Slower, so it runs after everything else.',
            ),
            SwitchSetting('src_mail', 'E-mail files', '.eml and .mbox files found on your drives.'),
            SwitchSetting(
              'index_removable',
              'USB and external drives',
              'Indexed while plugged in. Their files stay findable (marked “not connected”) when you unplug them. '
                  'Turning this off removes their files from the index.',
            ),
            SwitchSetting(
              'index_network',
              'Network drives',
              'Mapped network drives (Z: and so on). Big shares take a while and use your home or office network.',
            ),
          ],
        ),
      ],
    );
  }
}

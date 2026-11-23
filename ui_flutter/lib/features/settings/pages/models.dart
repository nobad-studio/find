/// Models & languages: this PC, the tier recommended for it, the language focus, and every model the engine
/// offers, with what it does, what it costs and whether this PC can run it. Use, Download (consent first), Remove,
/// Auto-configure. An engine without the 0.8 model methods gets the older page and says why, never made-up models.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/engine_api.dart' show RpcException;
import '../../../engine/models/format.dart';
import '../../../engine/models/graphics.dart';
import '../../../engine/models/models_info.dart';
import '../../../engine/models/settings.dart';
import '../../../state/models_controller.dart';
import '../../../widgets/badges.dart';
import '../../../widgets/common.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/glass.dart';
import '../../../widgets/icons.dart';
import '../../../widgets/panels.dart';
import '../../consent/download_consent_dialog.dart';
import '../../setup/setup_dialog.dart';
import '../settings_parts.dart';

class ModelsPage extends StatefulWidget {
  const ModelsPage({super.key, this.windowsFocus});

  /// Tests: the focus Windows' languages suggest (else read from Windows).
  final String? Function()? windowsFocus;

  @override
  State<ModelsPage> createState() => _ModelsPageState();
}

class _ModelsPageState extends State<ModelsPage> {
  ModelsController? _m;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_m != null) return;
    final s = AppScope.of(context);
    _m = ModelsController(s.engine, toasts: s.toasts, windowsFocus: widget.windowsFocus);
    unawaited(_m!.refresh());
  }

  @override
  void dispose() {
    _m?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: _m!,
    builder: (context, _) {
      final m = _m!;
      return switch (m.load) {
        ModelsLoad.loading => SizedBox(
          height: 120,
          child: Center(child: Text('Loading the models…', style: NbType.text(13, NbColors.of(context).muted))),
        ),
        ModelsLoad.ready => _Catalogue(m),
        ModelsLoad.needsNewer => _Legacy(note: 'Choosing between models needs a newer engine. ${m.why}'.trim()),
        ModelsLoad.offline => const _Legacy(),
      };
    },
  );
}

Future<bool> _consent(BuildContext context, ModelInfo m) => askModelConsent(context, m);

class _Catalogue extends StatelessWidget {
  const _Catalogue(this.m);
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final info = m.info;
    final focus = info.languageFocus;
    final text = info.byFeature('text');
    // the chosen focus's group first, then the others
    final order = [?focus, ...LanguageFocus.values.where((f) => f != focus)];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PcAndTier(m),
        const SettingsGroup(
          'Memory',
          icon: NbGlyph.memory,
          rows: [
            SwitchSetting(
              'models_stay_loaded',
              'Keep models loaded',
              'Searches by meaning and in photos answer at once, but the models use memory all the time. '
                  'Off (recommended): they leave memory a few minutes after the last use and load again when needed.',
            ),
          ],
        ),
        if (focus != null)
          SettingsGroup(
            'Languages',
            icon: NbGlyph.translate,
            rows: [
              SettingRow(
                label: 'What your files are in',
                help: '${focus.help}. This changes what is recommended; nothing is downloaded or switched by itself.',
                below: Align(
                  alignment: Alignment.centerLeft,
                  child: NbSegmented<LanguageFocus>(
                    value: focus,
                    badge: m.suggestedFocus,
                    badgeText: 'Matches Windows',
                    options: [for (final f in LanguageFocus.values) (f, f.label)],
                    onChanged: m.busy('focus') ? null : (f) => unawaited(m.setFocus(f)),
                  ),
                ),
              ),
            ],
          ),
        _FeatureGroup(
          title: 'Meaning search',
          icon: NbGlyph.textDoc,
          switchKey: 'semantic',
          switchLabel: 'Search by meaning',
          switchHelp: 'Finds “lease agreement” when you type “rent”. Runs on this PC only.',
          groups: focus == null
              ? [('', text)]
              : [
                  for (final f in order)
                    if (text.any((x) => x.focus == f))
                      (
                        f.label,
                        [
                          for (final x in text)
                            if (x.focus == f) x,
                        ],
                      ),
                ],
          m: m,
        ),
        _FeatureGroup(
          title: 'Photos by what is in them',
          icon: NbGlyph.image,
          switchKey: 'photo_meaning',
          switchLabel: "Find photos by what's in them",
          switchHelp: '“Dog on a beach” finds IMG_0042.jpg. The first pass is slow, in the background.',
          groups: [('', info.byFeature('photo'))],
          m: m,
        ),
        _FeatureGroup(
          title: 'Words in pictures',
          icon: NbGlyph.scan,
          switchKey: 'ocr',
          switchLabel: 'Read words in screenshots and scans',
          switchHelp: 'Uses Windows OCR, after everything else is indexed.',
          groups: [('', info.byFeature('ocr'))],
          m: m,
        ),
        // 1.1: not part of a tier; a photo's Describe / Ask / Compare offers the same download
        _FeatureGroup(
          title: 'Talk about photos',
          icon: NbGlyph.chat,
          about:
              'Describe a photo, ask about it, or compare two, on its detail pane. The models run on this PC only, '
              'on the llama.cpp runtime; each download asks first.',
          groups: [('', info.byFeature('talk')), ('Runtime', info.byFeature('runtime'))],
          m: m,
        ),
      ],
    );
  }
}

/// Your PC, the tier recommended for it, the tier in use, and Auto-configure.
class _PcAndTier extends StatelessWidget {
  const _PcAndTier(this.m);
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final info = m.info;
    final rec = info.tierRecommended;
    final now = info.tierCurrent;
    final matches = rec.isNotEmpty && rec == now;
    return SettingsGroup(
      'Your PC',
      icon: NbGlyph.pc,
      rows: [
        Padding(padding: const EdgeInsets.all(12), child: HardwareTiles(info.pc)),
        if (m.capability != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            child: LiveTiles(
              m.capability!,
              models: info.models.length,
              graphics: info.pc == null ? null : graphicsOf(info.pc!),
            ),
          ),
        if (rec.isNotEmpty)
          SettingRow(
            label: 'Recommended for this PC: ${tierLabel(rec)}',
            helpWidget: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: tierWhy(rec)),
                  if (now.isNotEmpty)
                    TextSpan(
                      text: '  Now: ${tierLabel(now)}.',
                      style: NbType.text(12, matches ? c.orange : c.text, weight: FontWeight.w600),
                    ),
                ],
              ),
              style: NbType.text(12, c.dim, height: 1.4),
            ),
            control: NbButton(
              m.autoBusy ? 'Setting up…' : (matches ? 'Set up again' : 'Auto-configure'),
              small: true,
              kind: matches ? NbButtonKind.ghost : NbButtonKind.primary,
              onPressed: m.autoBusy ? null : () => unawaited(m.autoConfigure(consent: (x) => _consent(context, x))),
            ),
          ),
        const _SuggestedRow(),
      ],
    );
  }
}

/// 1.2.0: the first-run models window again (setting `setup_offer`: what was answered), any time.
class _SuggestedRow extends StatefulWidget {
  const _SuggestedRow();

  @override
  State<_SuggestedRow> createState() => _SuggestedRowState();
}

class _SuggestedRowState extends State<_SuggestedRow> {
  bool _busy = false;
  String _error = '';

  static String help(String state) => switch (state) {
    'later' => 'You chose Later in the first-run window; nothing was downloaded.',
    'accepted' => 'Downloading what you chose in the first-run window.',
    'done' => 'Answered in the first-run window.',
    _ => 'Comes up once after the first scan.',
  };

  Future<void> _show() async {
    final s = AppScope.of(context);
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final offer = await s.engine.setupOffer();
      if (!mounted) return;
      setState(() => _busy = false);
      await showSetupDialog(context, offer);
    } on Object catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e is RpcException && e.code == -32601 ? 'This needs a newer engine.' : "The engine didn't answer.";
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final state = s.settings.settings.text('setup_offer');
    return SettingRow(
      label: 'Suggested for this PC',
      help: [
        'The models measured to suit this PC, with sizes, memory and why; each download asks first.',
        help(state),
        if (_error.isNotEmpty) _error,
      ].join(' '),
      control: NbButton(_busy ? 'Opening…' : 'Show', small: true, kind: NbButtonKind.ghost, onPressed: _busy ? null : _show),
    );
  }
}

/// What a tier is for (the engine's table, nobadfind/models.py).
String tierWhy(String tier) => switch (tier) {
  'light' => 'Small, fast models for under 8 GB of memory or few cores.',
  'balanced' => 'Many languages and photos, for 8 to 16 GB of memory and 4+ cores.',
  'best' => 'The most accurate models, for 16 GB+ and 8+ cores or a graphics card that can run them.',
  _ => '',
};

/// One feature: its on/off switch, then its models (text models in language groups).
class _FeatureGroup extends StatelessWidget {
  const _FeatureGroup({
    required this.title,
    required this.icon,
    this.switchKey,
    this.switchLabel = '',
    this.switchHelp = '',
    this.about = '',
    required this.groups,
    required this.m,
  });
  final String title;
  final NbGlyph icon;

  /// The feature's setting (null: a feature with no switch, talk about photos).
  final String? switchKey;
  final String switchLabel;
  final String switchHelp;

  /// A line on what the group is, for a feature with no switch.
  final String about;
  final List<(String, List<ModelInfo>)> groups;
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (groups.every((g) => g.$2.isEmpty)) return const SizedBox.shrink();
    final key = switchKey;
    return SettingsGroup(
      title,
      icon: icon,
      rows: [
        if (key != null) SwitchSetting(key, switchLabel, switchHelp),
        if (about.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Text(about, style: NbType.text(12.5, c.muted, height: 1.4)),
          ),
        for (final (label, models) in groups) ...[
          if (label.isNotEmpty && models.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(label.toUpperCase(), style: NbType.data(12, c.dim, weight: FontWeight.w600)),
              ),
            ),
          for (final x in models)
            if (modelOffered(x, m.info.pc)) _ModelRow(x, m),
        ],
      ],
    );
  }
}

/// Whether the page offers [x] on this PC: a graphics runtime (llama.cpp Vulkan) only when Windows lists a
/// graphics adapter, unless it is already downloaded, downloading or in use (a choice made is never hidden).
bool modelOffered(ModelInfo x, Hardware? pc) {
  if (pc == null || x.feature != 'runtime' || !x.id.endsWith('-vulkan')) return true;
  if (x.onDisk || x.state != ModelUseState.notDownloaded) return true;
  return graphicsOf(pc).kind != GraphicsKind.none;
}

/// A talk model's measured graphics memory, as this PC has it: a card's own (video) memory, the shared memory
/// built-in graphics borrow (it counts as memory), nothing without an adapter.
String graphicsCost(double vramMb, Hardware? pc) {
  final n = '${vramMb.round()} MB';
  return switch (pc == null ? null : graphicsOf(pc).kind) {
    null => '$n graphics memory',
    GraphicsKind.discrete => '$n video memory',
    GraphicsKind.integrated => '$n shared memory (counts as memory)',
    GraphicsKind.none => '',
  };
}

/// The Vulkan runtime on built-in graphics: it runs there, but not on a graphics card (display only; the engine's
/// catalogue keeps its name).
bool _builtInVulkan(ModelInfo x, Hardware? pc) =>
    pc != null && x.feature == 'runtime' && x.id.endsWith('-vulkan') && graphicsOf(pc).kind == GraphicsKind.integrated;

/// [x]'s name as this PC has it.
String modelName(ModelInfo x, Hardware? pc) => _builtInVulkan(x, pc) ? builtInVulkanName : x.name;

const builtInVulkanName = 'llama.cpp runtime (built-in graphics, Vulkan)';

/// A runtime's name ([id], the engine's [name]) as this PC has it: the same mapping as [modelName].
String runtimeName(String id, String name, Hardware? pc) =>
    pc != null && id.endsWith('-vulkan') && graphicsOf(pc).kind == GraphicsKind.integrated ? builtInVulkanName : name;

/// What [x] does, as this PC has it.
String modelImproves(ModelInfo x, Hardware? pc) =>
    _builtInVulkan(x, pc) ? 'Runs the talk models on the built-in graphics (Vulkan)' : x.improves;

String _runtimeName(String id, ModelsInfo info) {
  final rt = info.byId(id);
  return rt == null ? id : modelName(rt, info.pc);
}

/// One model as a card: an avatar for what it does, its name and tags, one line on what it improves, the facts as
/// chips (download, memory, licence, languages, measured quality), and Details: speed, the measurement, where it
/// comes from and the folder it's downloaded to (with Open folder), so nothing about it is hidden.
class _ModelRow extends StatelessWidget {
  const _ModelRow(this.x, this.m);
  final ModelInfo x;
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final p = m.progress(x.id);
    final downloading = x.state == ModelUseState.downloading || p != null;
    final q = x.quality;
    final active = x.state == ModelUseState.active;
    return NbCard(
        active: active,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Avatar(x),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text(
                            modelName(x, m.info.pc),
                            style: NbType.text(14, c.text, weight: FontWeight.w600, height: 1.3),
                          ),
                          if (x.tier.isNotEmpty) ModelTag(tierLabel(x.tier)),
                          if (x.recommended) const ModelTag('Recommended', strong: true),
                        ],
                      ),
                      if (x.improves.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(modelImproves(x, m.info.pc), style: NbType.text(12.5, c.muted, height: 1.4)),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                _Actions(x: x, m: m, busy: m.busy(x.id) || downloading),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                if (x.builtin)
                  const NbFact(NbGlyph.check, 'Built into Windows')
                else if (x.sizeMb > 0)
                  NbFact(NbGlyph.download, '${x.sizeMb.round()} MB download'),
                if (x.ramMb > 0) NbFact(NbGlyph.chip, '${x.ramMb.round()} MB memory'),
                if (x.vramMb > 0 && graphicsCost(x.vramMb, m.info.pc).isNotEmpty)
                  NbFact(NbGlyph.chip, graphicsCost(x.vramMb, m.info.pc)),
                if (x.runtime.isNotEmpty)
                  NbFact(NbGlyph.gauge, 'Runs on ${_runtimeName(x.runtime, m.info)}'),
                if (x.licence.isNotEmpty) NbFact(NbGlyph.shield, x.licence),
                if (x.languages.isNotEmpty) NbFact(NbGlyph.info, x.languageText),
                if (q != null) NbFact(NbGlyph.gauge, '${(q.recall5 * 100).round()}% right in the top 5'),
              ],
            ),
            if (!x.capable && x.capableReason.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(x.capableReason, style: NbType.text(12, c.warn, weight: FontWeight.w600, height: 1.4)),
              )
            else if (x.capable && m.capability?.runsNow(x.id) == false)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  m.capability!.why[x.id] ?? 'Not now.',
                  style: NbType.text(12, c.warn, weight: FontWeight.w600, height: 1.4),
                ),
              ),
            if (x.state == ModelUseState.failed && p == null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('The last download failed.', style: NbType.text(12, c.danger, height: 1.4)),
              ),
            if (downloading) ...[
              const SizedBox(height: 8),
              NbMeter(fraction: p?.fraction ?? 0, busy: p == null || p.sizeMb == 0),
              const SizedBox(height: 2),
              Text(
                p == null || p.sizeMb == 0
                    ? 'Downloading…'
                    : 'Downloading… ${p.gotMb.round()} of ${p.sizeMb.round()} MB'
                          '${p.mbS > 0 ? ' · ${p.mbS.toStringAsFixed(1)} MB/s' : ''}',
                style: NbType.data(11, c.dim),
              ),
            ],
            const SizedBox(height: 6),
            NbDetails(about: x.name, child: _Details(x: x, m: m)),
          ],
        ),
    );
  }
}

/// What the model does, as a glyph in a frosted tile: a page of text (meaning), a photo, a scan (words in
/// pictures), a chat bubble (talk), a processor (the runtime). Orange for the one in use or recommended.
class _Avatar extends StatelessWidget {
  const _Avatar(this.x);
  final ModelInfo x;

  static NbGlyph glyphOf(String feature) => switch (feature) {
    'photo' => NbGlyph.image,
    'ocr' => NbGlyph.scan,
    'talk' => NbGlyph.chat,
    'runtime' => NbGlyph.processor,
    _ => NbGlyph.textDoc,
  };

  @override
  Widget build(BuildContext context) =>
      GlyphTile(glyphOf(x.feature), accent: x.state == ModelUseState.active || x.recommended);
}

/// Everything else about the model, plainly: how fast, how it measured, where it comes from, where it lives.
class _Details extends StatelessWidget {
  const _Details({required this.x, required this.m});
  final ModelInfo x;
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final q = x.quality;
    Widget line(String label, Widget value) => NbDetailLine(label, value);
    Widget val(String s) => NbDetailLine.text(context, s);
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 2, 4, 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (x.speedNote.isNotEmpty) line('Speed', val(x.speedNote)),
          if (q != null)
            line(
              'Measured',
              val(
                '${(q.recall5 * 100).round()}% of test questions found in the top 5; ranking ${q.ndcg10.toStringAsFixed(2)} '
                '(nDCG@10, 1.00 is perfect)',
              ),
            ),
          if (x.source.isNotEmpty)
            line(
              'Comes from',
              TailText(
                x.source.replaceFirst(RegExp(r'^https?://'), ''),
                style: NbType.data(12, c.text),
                textAlign: TextAlign.left,
              ),
            ),
          if (x.builtin)
            line('Where it is', val('Part of Windows: nothing is downloaded.'))
          else if (x.dir.isNotEmpty)
            line(
              'Download folder',
              Wrap(
                spacing: 8,
                runSpacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(x.dir, style: NbType.data(12, c.text)),
                  NbButton(
                    'Open folder',
                    small: true,
                    kind: NbButtonKind.ghost,
                    onPressed: () => unawaited(m.openFolder(x)),
                  ),
                ],
              ),
            ),
          if (x.feature == 'runtime')
            line(
              'Checked',
              val(
                'Downloaded over HTTPS from that exact release; its size and SHA-256 are checked, and only its '
                'pinned files are kept (each checked by size and SHA-256).',
              ),
            )
          else if (!x.builtin)
            line(
              'Checked',
              val('Downloaded over HTTPS from that exact revision; its size and SHA-256 are checked before use.'),
            ),
        ],
      ),
    );
  }
}

class _Actions extends StatelessWidget {
  const _Actions({required this.x, required this.m, required this.busy});
  final ModelInfo x;
  final ModelsController m;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (x.state == ModelUseState.active) {
      return Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('In use', style: NbType.text(12.5, c.orange, weight: FontWeight.w600)),
      );
    }
    void use() => unawaited(m.use(x, consent: (y) => _consent(context, y)));
    // talk models and runtimes have no Use: they are fetched (one consent with the runtime) and used on a photo
    final talk = x.feature == 'talk' || x.feature == 'runtime';
    void fetch() => unawaited(
      x.feature == 'talk'
          ? m.downloadTalk(x, consent: (y, rt) => askTalkConsent(context, y, rt, pc: m.info.pc))
          : m.download(x, consent: (y) => askRuntimeConsent(context, y, pc: m.info.pc)),
    );
    final List<Widget> buttons;
    if (busy) {
      buttons = const [];
    } else if (talk) {
      buttons = [
        if (x.onDisk)
          NbButton(
            'Remove',
            small: true,
            kind: NbButtonKind.quiet,
            icon: NbGlyph.remove,
            onPressed: () => unawaited(m.remove(x)),
          )
        else
          NbButton(
            x.capable ? 'Download…' : 'Download anyway…',
            small: true,
            kind: NbButtonKind.ghost,
            icon: NbGlyph.download,
            onPressed: fetch,
          ),
      ];
    } else if (x.onDisk) {
      buttons = [
        NbButton('Use', small: true, onPressed: use),
        if (!x.builtin)
          NbButton(
            'Remove',
            small: true,
            kind: NbButtonKind.quiet,
            icon: NbGlyph.remove,
            onPressed: () => unawaited(m.remove(x)),
          ),
      ];
    } else {
      buttons = [
        NbButton(
          x.capable ? 'Download…' : 'Download anyway…',
          small: true,
          kind: x.capable && x.recommended ? NbButtonKind.primary : NbButtonKind.ghost,
          icon: NbGlyph.download,
          onPressed: use,
        ),
      ];
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.end, spacing: 6, children: buttons);
  }
}

class ModelTag extends StatelessWidget {
  const ModelTag(this.text, {super.key, this.strong = false});
  final String text;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final color = strong ? c.orange : c.dim;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: color.withValues(alpha: strong ? .12 : .06),
        border: Border.all(color: color.withValues(alpha: .35)),
        borderRadius: NbRadius.pillAll,
      ),
      child: Text(text, style: NbType.text(10.5, color, weight: FontWeight.w600, height: 1.3)),
    );
  }
}

/// An engine without the 0.8 model methods (or none yet): the meaning and photo models as before, and why.
class _Legacy extends StatelessWidget {
  const _Legacy({this.note = ''});
  final String note;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: NbSpace.x4),
            child: Glass(
              radius: NbRadius.card,
              padding: const EdgeInsets.all(12),
              child: Text(note, style: NbType.text(13, c.muted, height: 1.45)),
            ),
          ),
        SettingsGroup(
          'Your PC',
          icon: NbGlyph.pc,
          rows: [Padding(padding: const EdgeInsets.all(12), child: HardwareTiles(s.settings.hardware))],
        ),
        const SettingsGroup(
          'Meaning search',
          icon: NbGlyph.textDoc,
          rows: [
            SwitchSetting(
              'allow_model_download',
              'Allow the one-time model download',
              "23 MB from Hugging Face (all-MiniLM-L6-v2, pinned and checked by SHA-256). This is NOBAD Find's only "
                  'internet connection.',
            ),
            SwitchSetting(
              'semantic',
              'Search by meaning',
              'Finds “lease agreement” when you type “rent”, and photos or bills by what their names mean. Runs on '
                  'this PC only.',
            ),
            _LegacyModelRow('meaning', 'Model'),
          ],
        ),
        const SettingsGroup(
          'Photo meaning',
          icon: NbGlyph.image,
          rows: [
            SwitchSetting(
              'allow_photo_model_download',
              'Allow the one-time photo model download',
              'About 211 MB from Hugging Face (SigLIP base by Google, Apache-2.0; pinned and checked by SHA-256). '
                  'Only needed for this feature.',
            ),
            SwitchSetting(
              'photo_meaning',
              "Find photos by what's in them",
              '“Dog on a beach” finds IMG_0042.jpg even with no words in it. Runs on this PC only. The first pass '
                  'is slow (a few photos per second), in the background.',
            ),
            _LegacyModelRow('photo', 'Photo model'),
          ],
        ),
      ],
    );
  }
}

class _LegacyModelRow extends StatelessWidget {
  const _LegacyModelRow(this.id, this.label);
  final String id;
  final String label;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([AppScope.of(context).status, AppScope.of(context).settings]),
    builder: (context, _) => _build(context),
  );

  Widget _build(BuildContext context) {
    final s = AppScope.of(context);
    final m = s.status.model(id);
    final photos = s.status.details?.photoVectors ?? 0;
    final counting = s.status.details?.countingTotals ?? false;
    final help = m.ready
        ? (id == 'photo'
              ? (counting
                    ? 'Downloaded and verified. Counting the photos understood so far…'
                    : 'Downloaded and verified. ${groupDigits(photos)} photos understood so far.')
              : 'Downloaded and verified.')
        : m.downloading
        ? 'Downloading… ${m.percent}%'
        : (m.error.isNotEmpty ? 'Last try failed: ${m.error}' : 'Not downloaded.');
    return SettingRow(
      label: label,
      help: help,
      control: m.ready || m.downloading
          ? null
          : NbButton(
              'Download',
              small: true,
              icon: NbGlyph.download,
              onPressed: () {
                unawaited(s.settings.download(id, consent: (x) => askConsentFor(context, id, x)));
              },
            ),
      below: m.downloading ? NbMeter(fraction: m.percent / 100) : null,
    );
  }
}

/// "Your PC, now" (capability_state, 2026-11-21): free memory, commit, graphics memory and power right now, and how
/// many models can run now. Live: the page asks again every few seconds. Unknown readings show a dash.
class LiveTiles extends StatelessWidget {
  const LiveTiles(this.cap, {super.key, required this.models, this.graphics});
  final CapabilityState cap;
  final int models;

  /// This PC's graphics (null: not known): no graphics tile without an adapter; built-in graphics' memory is
  /// shared, never called video memory.
  final Graphics? graphics;

  static String mb(int? v) => v == null ? '–' : (v >= 1024 ? '${(v / 1024).toStringAsFixed(1)} GB' : '$v MB');

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final b = cap.budget;
    final runs = cap.canRun.values.where((v) => v).length;
    final kind = graphics?.kind;
    final shared = kind == GraphicsKind.integrated || (kind == null && b.gpuKind == 'shared');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(
            b.live ? 'Right now' : 'Right now: not measured yet',
            style: NbType.text(12.5, c.muted, weight: FontWeight.w600),
          ),
        ),
        TileGrid(
          min: 130,
          children: [
            StatTile(
              icon: NbGlyph.memory,
              value: mb(b.freeMb),
              label: 'Memory free${b.installedMb != null ? ' of ${mb(b.installedMb)}' : ''}, '
                  '${mb(b.reserveMb)} kept for Windows',
            ),
            StatTile(
              icon: NbGlyph.pulse,
              value: b.commitPct == null ? '–' : '${b.commitPct!.round()}%',
              label: 'Of the memory Windows can promise programs',
            ),
            if (kind != GraphicsKind.none)
              StatTile(
                icon: NbGlyph.graphics,
                value: mb(b.gpuFreeMb),
                label: shared
                    ? 'Graphics memory free (shared with the PC)'
                    : (kind == GraphicsKind.discrete || b.gpuKind == 'dedicated'
                          ? 'Video memory free'
                          : 'Graphics memory free'),
              ),
            StatTile(
              icon: NbGlyph.battery,
              value: b.batterySaver ? 'Battery saver' : (b.battery ? 'On battery' : 'Plugged in'),
              label: 'Power',
            ),
            StatTile(
              icon: NbGlyph.processor,
              value: '$runs of ${cap.canRun.isEmpty ? models : cap.canRun.length}',
              label: 'Models that can run now',
            ),
          ],
        ),
      ],
    );
  }
}

/// "Your PC": memory, cores, graphics, processor speed-ups, drive (0.7.0 hardwareBlock).
class HardwareTiles extends StatelessWidget {
  const HardwareTiles(this.h, {super.key, this.compact = false});
  final Hardware? h;

  /// The welcome's column: a graphics card's name takes at most 2 lines (ellipsis, the whole name in the tooltip).
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final h = this.h;
    if (h == null) return Text('Not available here.', style: NbType.text(13, c.dim));
    final fast = [if (h.avx2) 'AVX2', if (h.avx512Vnni) 'AVX-512 VNNI'].join(' + ');
    final g = graphicsOf(h);
    final drive = h.ssd == true
        ? 'SSD'
        : h.ssd == false
        ? 'Hard disk'
        : 'Disk';
    return TileGrid(
      min: 130,
      children: [
        StatTile(value: gb(h.ramGb), label: 'Memory', icon: NbGlyph.memory),
        StatTile(
          value: '${groupDigits(h.cores)} cores',
          label: '${groupDigits(h.threads)} threads',
          icon: NbGlyph.processor,
        ),
        StatTile(
          icon: NbGlyph.graphics,
          value: g.title,
          label: g.detail[0].toUpperCase() + g.detail.substring(1),
          valueMaxLines: compact ? 2 : null,
        ),
        StatTile(value: fast.isEmpty ? 'Standard' : fast, label: 'Processor speed-ups', icon: NbGlyph.bolt),
        StatTile(
          value: drive,
          label: h.diskFreeGb > 0 ? '${gb(h.diskFreeGb)} free' : 'Drive type',
          icon: NbGlyph.drive,
        ),
      ],
    );
  }
}

/// Performance: the goal, the choices that beat "auto" (each with what auto would pick now and why), "Reset to
/// safe defaults", staying out of your way, and the apps NOBAD Find has learned.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/models/format.dart';
import '../../../engine/models/settings.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/dialogs.dart';
import '../../../widgets/icons.dart';
import '../settings_parts.dart';

class PerformancePage extends StatelessWidget {
  const PerformancePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final learned = s.settings.learned;
    final perf = s.settings.performance; // null: an engine before 1.2.0 (only power, no overrides)
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'Speed',
          icon: NbGlyph.gauge,
          rows: [
            if (perf != null)
              const ChoiceSetting(
                'performance_goal',
                'Goal',
                'Quiet slows its disk work earlier when the disk is busy, steps down earlier when other apps or heat '
                    'keep the PC busy, and keeps background work off the graphics card. Balanced leaves threads free for you. Fast uses every thread, even '
                    'while you use the PC, and still steps down when the PC needs it. Changes apply at once.',
                [('quiet', 'Quiet'), ('balanced', 'Balanced (recommended)'), ('fast', 'Fast: every thread')],
              )
            else
              const ChoiceSetting(
                'power',
                'How hard NOBAD Find works',
                'Balanced leaves threads free for you. Boost uses every thread for reading, photos and meaning, even '
                    'while you use the PC. Changes apply at once.',
                [('balanced', 'Balanced (recommended)'), ('boost', 'Boost: every thread')],
              ),
            SwitchSetting(
              'safety_net',
              'Safety net',
              'Even at ${perf != null ? 'Fast' : 'Boost'}, NOBAD Find steps down when other apps need the processor '
                  'or memory gets tight, and pauses before the PC struggles. Off: only a frozen app or very low memory '
                  'pause it.',
            ),
            const WorkersSetting(),
          ],
        ),
        if (perf != null) const OverridesGroup(),
        const SettingsGroup(
          'Staying out of your way',
          icon: NbGlyph.moon,
          rows: [
            ChoiceSetting(
              'games_mode',
              'Games and presentations',
              'Smart slows down or pauses only for the apps that really need your PC, and learns which ones. Always '
                  "pause stops whenever a game is running. Don't change never reacts to games. Presentations always "
                  'pause NOBAD Find.',
              [('smart', 'Smart (recommended)'), ('always', 'Always pause'), ('off', "Don't change")],
            ),
            NamesSetting(
              'creative_apps',
              'Creative apps',
              'Video, 3D and music apps (program file names, separated by commas). While one is in front, NOBAD Find '
                  'uses 1 worker and leaves the graphics card to it.',
            ),
            SwitchSetting('pause_on_battery', 'Pause on battery', ''),
            SwitchSetting('pause_on_call', 'Pause during calls', 'While an app uses the microphone or camera.'),
            SwitchSetting(
              'stay_running',
              'Keep running after closing the window',
              'Off: closing NOBAD Find quits it completely, nothing stays running. On: it stays in the notification '
                  'area so the hotkey keeps working.',
            ),
            SwitchSetting(
              'keep_background',
              'Keep indexing in the background',
              'Closing the window stops indexing and every worker; NOBAD Find stays as one small idle process so the '
                  'hotkey works. On: keeps indexing after closing.',
            ),
            SwitchSetting(
              'tray',
              'Show NOBAD Find in the notification area',
              'The icon works with the window closed: open NOBAD Find, pause and quit.',
            ),
          ],
        ),
        SettingsGroup(
          'Apps NOBAD Find has learned',
          icon: NbGlyph.apps,
          rows: [
            SettingRow(
              label: 'Apps that slowed your PC down',
              help:
                  'When an app lagged while NOBAD Find was working, NOBAD Find remembers the app\'s file name '
                  '(nothing else) and starts gentler next time.',
              control: learned.isEmpty
                  ? null
                  : NbButton(
                      'Reset all',
                      kind: NbButtonKind.ghost,
                      small: true,
                      onPressed: () {
                        unawaited(
                          s.settings.forgetApp(
                            null,
                            confirm: () => confirmDialog(
                              context,
                              title: 'Reset all',
                              question: 'Forget every app NOBAD Find has learned?',
                              yes: 'Forget all',
                              danger: true,
                            ),
                          ),
                        );
                      },
                    ),
              below: learned.isEmpty
                  ? Text(
                      'None yet. When an app lags while NOBAD Find works, it shows up here.',
                      style: NbType.text(13, c.dim),
                    )
                  : Column(
                      children: [
                        for (final a in learned)
                          Container(
                            margin: const EdgeInsets.only(bottom: 6),
                            padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
                            decoration: BoxDecoration(
                              border: Border.all(color: c.line),
                              borderRadius: NbRadius.rowAll,
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(a.bare, style: NbType.text(13.5, c.text, weight: FontWeight.w600)),
                                      Text(
                                        '${a.reason} Seen ${groupDigits(a.seen)} ${a.seen == 1 ? 'time' : 'times'}.',
                                        style: NbType.text(NbSize.small, c.dim, height: 1.45),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 12),
                                NbButton(
                                  'Forget',
                                  kind: NbButtonKind.ghost,
                                  small: true,
                                  onPressed: () => unawaited(s.settings.forgetApp(a.exe)),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
            ),
          ],
        ),
      ],
    );
  }
}

/// What each override value is called on the page.
const _names = {
  'auto': 'Auto',
  'on': 'On',
  'off': 'Off',
  'cpu': 'Processor',
  'directml': 'DirectML',
  'vulkan': 'Vulkan',
  'cuda': 'CUDA',
  'fp16-vision': 'Lighter (fp16)',
  'fp32-vision': 'Faster (fp32)',
  'performance': 'Performance',
  'balanced': 'Balanced',
  'efficiency': 'Efficiency',
  'compatibility': 'Compatibility',
};

String _name(Object? v) => v is String ? (_names[v] ?? v) : '${v ?? ''}';

/// The row's help, then "Auto now: X. Why." and its note (spec 8b rule 5): what the user is overriding.
class _AutoNow extends StatelessWidget {
  const _AutoNow(this.help, this.row, {this.unit = ''});
  final String help;
  final PerformanceRow? row;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = row;
    final style = NbType.text(NbSize.small, c.dim, height: 1.4);
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 560),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (help.isNotEmpty) Text(help, style: style),
          if (r != null && r.auto != null) Text('Auto now: ${_name(r.auto)}$unit. ${r.why}', style: style),
          if (r != null && r.note.isNotEmpty) Text(r.note, style: NbType.text(NbSize.small, c.orange, height: 1.4)),
        ],
      ),
    );
  }
}

/// The text reading workers. While the goal is Fast the number isn't used (every thread): the field is greyed
/// out and the row says why.
class WorkersSetting extends StatelessWidget {
  const WorkersSetting({super.key});

  static const label = 'Text reading workers';
  static const fastReason =
      'Not used while the goal is Fast: Fast uses every thread. Choose Balanced or Quiet to '
      'set a number.';

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    final fast = s.performance != null && s.settings.text('performance_goal') == 'fast';
    return SettingRow(
      label: label,
      helpWidget: _AutoNow(
        fast ? fastReason : '0 = auto, chosen from your processor. Applies at once.',
        fast ? null : s.performance?.rows['workers'],
      ),
      control: NbField(
        label: label,
        number: true,
        enabled: !fast,
        value: '${s.settings.number('workers')}',
        onSubmit: (v) => s.set('workers', int.tryParse(v) ?? -1),
      ),
    );
  }
}

/// One choice that beats auto (spec 8b): only the values the engine offers on this PC, and what auto would pick.
class _OverrideChoice extends StatelessWidget {
  const _OverrideChoice(this.k, this.label, [this.help = '']);
  final String k;
  final String label;
  final String help;

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    final row = s.performance?.rows[k];
    final value = s.settings.text(k);
    final options = [...?row?.options];
    if (options.isEmpty) options.add('auto');
    if (!options.contains(value)) options.add(value); // a forced choice not available now: its note says so
    return SettingRow(
      label: label,
      helpWidget: _AutoNow(help, row),
      control: NbSelect(
        label: label,
        value: value,
        options: [for (final o in options) (o, _name(o))],
        maxWidth: 230,
        onChanged: (v) => s.set(k, v),
      ),
    );
  }
}

/// Settings > Performance's overrides and "Reset to safe defaults" (1.2.0 engines).
class OverridesGroup extends StatelessWidget {
  const OverridesGroup({super.key});

  static const reserveLabel = 'Graphics memory left free (MB)';

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    return SettingsGroup(
      'Your choices',
      icon: NbGlyph.sliders,
      rows: [
        const _OverrideChoice(
          'gpu_background',
          'Graphics card for background work',
          'On beats the goal. Off also beats a graphics backend chosen below. Battery saver, a creative app in front '
          'and the graphics memory left free still decide.',
        ),
        const _OverrideChoice('backend_photos', 'Photos run on'),
        const _OverrideChoice('backend_text', 'Meaning for documents runs on'),
        const _OverrideChoice('backend_talk', 'Talk about a photo runs on'),
        const _OverrideChoice('variant_siglip2-base', 'SigLIP 2 build'),
        const _OverrideChoice('profile_override_gpu', 'Plan the graphics card as'),
        const _OverrideChoice('profile_override_cpu', 'Plan the processor as'),
        const _OverrideChoice('profile_override_storage', 'Plan the storage as'),
        const _OverrideChoice('profile_override_memory', 'Plan the memory as'),
        SettingRow(
          label: reserveLabel,
          helpWidget: _AutoNow('512 to 4096.', s.performance?.rows['gpu_reserve_min_mb'], unit: ' MB'),
          control: NbField(
            label: reserveLabel,
            number: true,
            value: '${s.settings.number('gpu_reserve_min_mb')}',
            onSubmit: (v) => s.set('gpu_reserve_min_mb', int.tryParse(v) ?? -1),
          ),
        ),
        SettingRow(
          label: 'Reset to safe defaults',
          help:
              'The goal back to Balanced, every choice on this page back to Auto (text reading workers too) and the '
              'graphics memory left free back to 512 MB. Keeps the index, your models, privacy settings, folders and '
              'the apps NOBAD Find has learned.',
          control: NbButton(
            'Reset',
            kind: NbButtonKind.ghost,
            small: true,
            onPressed: () {
              unawaited(
                s.resetSafeDefaults(
                  confirm: () => confirmDialog(
                    context,
                    title: 'Reset to safe defaults',
                    question: 'Put the goal and every choice on this page back to the safe defaults?',
                    yes: 'Reset',
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

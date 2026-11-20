/// One global hotkey in Settings: the combination as key caps, whether it works right now, and a way to change
/// it by pressing the new keys (or typing them). Every new combination is checked by the engine first
/// (`hotkey_probe`: free, used by another app, kept by Windows, or NOBAD Find's other hotkey) and only a free
/// one is saved; the engine registers it at once, no restart.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/settings.dart';
import '../../widgets/controls.dart';
import 'settings_parts.dart';

/// 'win+shift+f' -> ['Win', 'Shift', 'F'].
List<String> hotkeyCaps(String spec) => [
  for (final p in spec.split('+'))
    if (p.isNotEmpty)
      switch (p) {
        'win' => 'Win',
        'ctrl' => 'Ctrl',
        'alt' => 'Alt',
        'shift' => 'Shift',
        'space' => 'Space',
        _ => p.toUpperCase(),
      },
];

/// The combination being held, as the engine writes it (win, ctrl, alt, shift, then the key), or null while only
/// modifiers are down or the key isn't one a hotkey can use (a letter, a digit, Space, F1 to F12).
String? hotkeyFromKeys(
  LogicalKeyboardKey key,
  Set<LogicalKeyboardKey> pressed,
) {
  bool any(List<LogicalKeyboardKey> ks) => ks.any(pressed.contains);
  final mods = [
    if (any([
      LogicalKeyboardKey.metaLeft,
      LogicalKeyboardKey.metaRight,
      LogicalKeyboardKey.meta,
    ]))
      'win',
    if (any([
      LogicalKeyboardKey.controlLeft,
      LogicalKeyboardKey.controlRight,
      LogicalKeyboardKey.control,
    ]))
      'ctrl',
    if (any([
      LogicalKeyboardKey.altLeft,
      LogicalKeyboardKey.altRight,
      LogicalKeyboardKey.alt,
    ]))
      'alt',
    if (any([
      LogicalKeyboardKey.shiftLeft,
      LogicalKeyboardKey.shiftRight,
      LogicalKeyboardKey.shift,
    ]))
      'shift',
  ];
  String? k;
  final label = key.keyLabel.toLowerCase();
  if (key == LogicalKeyboardKey.space) {
    k = 'space';
  } else if (RegExp(r'^[a-z0-9]$').hasMatch(label)) {
    k = label;
  } else {
    final f = RegExp(r'^f([1-9]|1[0-2])$').firstMatch(label);
    if (f != null) k = 'f${f.group(1)}';
  }
  if (k == null || mods.isEmpty) return null;
  return [...mods, k].join('+');
}

enum _Mode { show, record, type }

class HotkeySetting extends StatefulWidget {
  const HotkeySetting(this.which, this.label, {super.key});

  /// The setting: 'hotkey' (open NOBAD Find) or 'bar_hotkey' (the quick find bar).
  final String which;
  final String label;

  @override
  State<HotkeySetting> createState() => _HotkeySettingState();
}

class _HotkeySettingState extends State<HotkeySetting> {
  _Mode _mode = _Mode.show;
  final _focus = FocusNode(debugLabel: 'hotkey-record');
  String? _held; // what is being pressed right now (recording)
  HotkeyProbe? _probe; // the engine's answer for the new combination
  bool _busy = false;
  bool _asked = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_asked) {
      _asked = true;
      AppScope.of(context).settings.loadHotkeys();
    }
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  void _start(_Mode m) {
    setState(() {
      _mode = m;
      _held = null;
      _probe = null;
    });
    if (m == _Mode.record) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _focus.requestFocus());
    }
  }

  void _cancel() => setState(() {
    _mode = _Mode.show;
    _held = null;
    _probe = null;
  });

  Future<void> _check(String spec) async {
    setState(() {
      _busy = true;
      _held = spec;
    });
    final p = await AppScope.of(context).settings
        .probeHotkey(widget.which, spec);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _probe =
          p ??
          const HotkeyProbe(
            'invalid',
            '',
            "NOBAD Find's engine didn't answer. Try again.",
          );
    });
  }

  Future<void> _save() async {
    final p = _probe;
    if (p == null || !p.ok) return;
    setState(() => _busy = true);
    await AppScope.of(context).settings.setHotkey(widget.which, p.spec);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _mode = _Mode.show;
      _probe = null;
      _held = null;
    });
  }

  /// No shortcut at all (0.9.1): the Start menu and the notification-area icon still open NOBAD Find.
  Future<void> _clear() async {
    setState(() => _busy = true);
    await AppScope.of(context).settings.setHotkey(widget.which, '');
    if (mounted) setState(() => _busy = false);
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent e) {
    if (e is! KeyDownEvent) return KeyEventResult.handled;
    if (e.logicalKey == LogicalKeyboardKey.escape) {
      _cancel();
      return KeyEventResult.handled;
    }
    final spec = hotkeyFromKeys(
      e.logicalKey,
      HardwareKeyboard.instance.logicalKeysPressed,
    );
    if (spec == null) {
      setState(() {
        _probe = null;
        _held = null;
      });
      return KeyEventResult.handled;
    }
    _check(spec);
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: AppScope.of(context).settings,
    builder: (context, _) {
      final s = AppScope.of(context).settings;
      final spec = s.settings.text(widget.which);
      final state = s.hotkeys.of(widget.which);
      return SettingRow(
        label: widget.label,
        helpWidget: _StateLine(
          state: state,
          spec: spec,
          bar: widget.which == 'bar_hotkey',
        ),
        control: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final cap in hotkeyCaps(spec)) ...[
              Kbd(cap),
              const SizedBox(width: 4),
            ],
            const SizedBox(width: 6),
            if (_mode == _Mode.show) ...[
              NbButton(
                spec.isEmpty ? 'Set' : 'Change',
                small: true,
                kind: NbButtonKind.ghost,
                onPressed: () => _start(_Mode.record),
              ),
              if (spec.isNotEmpty) ...[
                const SizedBox(width: 6),
                NbButton('Clear', small: true, kind: NbButtonKind.quiet, onPressed: _clear),
              ],
            ],
          ],
        ),
        below: _mode == _Mode.show ? null : _editor(context),
      );
    },
  );

  Widget _editor(BuildContext context) {
    final c = NbColors.of(context);
    final p = _probe;
    final held = _held;
    final Widget input = _mode == _Mode.record
        ? Focus(
            focusNode: _focus,
            onKeyEvent: _onKey,
            child: Semantics(
              label: 'Press the new shortcut',
              child: Container(
                height: 44,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: c.orange.withValues(alpha: .7)),
                  color: c.orange.withValues(alpha: .06),
                ),
                child: held == null
                    ? Text(
                        'Press the new shortcut now: Ctrl, Alt, Shift or Win with a letter, a number, Space or F1 to F12',
                        style: NbType.text(12.5, c.muted),
                      )
                    : Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          for (final cap in hotkeyCaps(held)) ...[
                            Kbd(cap),
                            const SizedBox(width: 4),
                          ],
                        ],
                      ),
              ),
            ),
          )
        : NbField(
            label: 'Type the shortcut',
            value: '',
            width: 260,
            onSubmit: (v) {
              final t = v.trim();
              if (t.isNotEmpty) _check(t);
            },
          );
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          input,
          const SizedBox(height: 8),
          if (_busy)
            Text('Checking…', style: NbType.text(12.5, c.muted))
          else if (p != null)
            Text(
              p.ok
                  ? '${hotkeyCaps(p.spec).join('+')} is free to use.'
                  : p.reason,
              style: NbType.text(12.5, p.ok ? c.text : c.warn),
            ),
          const SizedBox(height: 8),
          Row(
            children: [
              NbButton(
                'Use it',
                small: true,
                onPressed: (p != null && p.ok && !_busy) ? _save : null,
              ),
              const SizedBox(width: 8),
              NbButton(
                _mode == _Mode.record
                    ? 'Type it instead'
                    : 'Press keys instead',
                small: true,
                kind: NbButtonKind.ghost,
                onPressed: () =>
                    _start(_mode == _Mode.record ? _Mode.type : _Mode.record),
              ),
              const SizedBox(width: 8),
              NbButton(
                'Cancel',
                small: true,
                kind: NbButtonKind.quiet,
                onPressed: _cancel,
              ),
            ],
          ),
          if (_mode == _Mode.record)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Some combinations never reach an app because Windows keeps them; type those instead.',
                style: NbType.text(11.5, c.dim),
              ),
            ),
        ],
      ),
    );
  }
}

class _StateLine extends StatelessWidget {
  const _StateLine({
    required this.state,
    required this.spec,
    required this.bar,
  });
  final HotkeyOne state;
  final String spec;
  final bool bar;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final (String text, Color color) = switch (state.state) {
      'ok' => ('Works now, anywhere in Windows.', c.muted),
      'taken' => (
        'Not working: another app on this PC uses it. Change it.',
        c.warn,
      ),
      'reserved' => (
        'Not working: Windows keeps it for itself. Change it.',
        c.warn,
      ),
      'invalid' => (
        'Not working: not a combination NOBAD Find can use. Change it.',
        c.warn,
      ),
      _ when spec.isEmpty => (
        'No shortcut. Open NOBAD Find from the Start menu or its icon in the notification area.',
        c.muted,
      ),
      _ when bar => ('Works while the quick find bar is on.', c.muted),
      _ => ('Changes take effect at once.', c.muted),
    };
    return Text(text, style: NbType.text(12, color, height: 1.3));
  }
}

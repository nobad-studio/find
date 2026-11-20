/// Shortcuts: the two global hotkeys (the engine owns them) and the keys inside the window.
library;

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../widgets/controls.dart';
import '../hotkey_setting.dart';
import '../settings_parts.dart';

const _keys = [
  (['Ctrl', '1'], 'Search'),
  (['Ctrl', '2'], 'Index'),
  (['Ctrl', '3'], 'Settings'),
  (['↑', '↓'], 'Move through the results'),
  (['PgUp', 'PgDn'], 'A page of results'),
  (['Home', 'End'], 'First or last result'),
  (['Tab'], 'Use the suggested filter'),
  (['Enter'], 'Open'),
  (['Ctrl', 'Enter'], 'Show in folder'),
  (['Ctrl', 'Shift', 'Enter'], 'Open with…'),
  (['Ctrl', 'C'], 'Copy path'),
  (['Shift', 'Del'], 'Forget…'),
  (['Space'], 'Details (narrow window)'),
  (['Shift', 'F10'], 'Actions menu'),
  (['Esc'], 'Clear the box, then hide'),
];

class ShortcutsPage extends StatelessWidget {
  const ShortcutsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListenableBuilder(
          listenable: AppScope.of(context).settings,
          builder: (context, _) => SettingsGroup(
            'Anywhere in Windows',
            rows: [
              const HotkeySetting('hotkey', 'Open NOBAD Find'),
              // 0.9.3: the search bar, like Spotlight: the shortcut opens it when the window isn't open
              const SwitchSetting(
                'bar',
                'Search bar',
                "With NOBAD Find's window closed, the shortcut opens a small search bar over any app: files, Windows "
                    "settings and apps. With the window open, it goes to the window's search box.",
              ),
              if (AppScope.of(context).settings.settings.flag('bar'))
                const HotkeySetting('bar_hotkey', 'Search bar only (a second shortcut)'),
            ],
          ),
        ),
        SettingsGroup(
          'In this window',
          rows: [
            for (final (keys, what) in _keys)
              SizedBox(
                height: 36,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: Row(
                    children: [
                      Expanded(child: Text(what, style: NbType.text(13, c.text, height: 1.2))),
                      for (final k in keys) ...[const SizedBox(width: 4), Kbd(k)],
                    ],
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

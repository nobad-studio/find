/// General: how the window looks and when NOBAD Find starts.
library;

import 'package:flutter/widgets.dart';

import '../settings_parts.dart';

class GeneralPage extends StatelessWidget {
  const GeneralPage({super.key});

  @override
  Widget build(BuildContext context) => const Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      SettingsGroup(
        'Look',
        rows: [
          SwitchSetting(
            'glass',
            'See-through window',
            "Windows 11 Mica behind the window, while Windows' own Transparency effects switch is on "
                '(Settings > Personalization > Colors). With that off the window stays solid.',
          ),
        ],
      ),
      SettingsGroup(
        'Start',
        rows: [SwitchSetting('autostart', 'Start with Windows', 'Starts hidden; the hotkey opens it.')],
      ),
    ],
  );
}

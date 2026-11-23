/// General: how the window looks, when NOBAD Find starts, and how it tells you things (notifications).
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
      SettingsGroup(
        'Notifications',
        rows: [
          SwitchSetting(
            'notify_toasts',
            'Windows notifications',
            'Also show them as Windows notifications, made on this PC (nothing is sent anywhere). Windows can show '
                'them on the lock screen and keeps them in its notification center. The bell keeps every one '
                'either way.',
          ),
          ChoiceSetting(
            'notify_level',
            'Which ones go to Windows',
            'The rest stay in the bell only.',
            [('error', 'Errors only'), ('warning', 'Warnings and errors'), ('info', 'All of them')],
          ),
          SwitchSetting(
            'notify_quiet',
            'Quiet during games and calls',
            'No Windows notification while a game, a call (microphone or camera in use) or a presentation is on. '
                'They wait in the bell.',
          ),
        ],
      ),
    ],
  );
}

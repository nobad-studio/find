/// Privacy: the Windows Search switch (elevated helper, undoable), your own search history (0.8.5) and deleting
/// the whole index.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/models/settings.dart' show appFilesConsent, browserConsent, browserDataLevels;
import '../../../widgets/controls.dart';
import '../../../widgets/dialogs.dart';
import '../../../widgets/icons.dart';
import '../settings_parts.dart';

/// The one exception to "names only" (setting `secret_app_files`, 1.1.0, off by default; const.APP_SECRET_* in
/// the engine): what other programs record and developer tools' plain-text sign-ins. Turning it on asks once.
class AppFilesSetting extends StatelessWidget {
  const AppFilesSetting({super.key});

  static const label = 'Read command histories, saved logins and tool tokens';
  static const help =
      'Off (the default): NOBAD Find doesn\'t read these files; with "Keys and password stores" on in What to '
      'index it lists only their names. On: it reads what\'s inside them, in the folders it indexes: command '
      'histories (PowerShell, bash, zsh, Python, database clients), saved-site and login files of FTP/SSH tools '
      '(FileZilla, WinSCP, .netrc), developer tool tokens (GitHub CLI, npm, PyPI, git credentials, Maven, Cargo, '
      'Terraform, Vault, PostgreSQL, S3 tools) and .env files (until then listed by name only). SSH and GPG keys, '
      'browser passwords, password vaults, wallets, Windows\' saved credentials and Recent items are never read. '
      'Turning it off removes what was read from the index.';
  static const askTitle = 'Read these files?';
  static const ask =
      'Their contents may include passwords and tokens. They stay in NOBAD Find\'s encrypted index on this PC, '
      'and they can appear in search results. Turn this off to remove them from the index again.\n\n'
      'PowerShell, FileZilla and GitHub CLI keep their files in AppData: those are read only while "App data, '
      'caches and code folders" is on in What to index.';

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    return SettingRow(
      label: label,
      help: help,
      control: NbSwitch(
        value: s.settings.flag('secret_app_files'),
        label: label,
        onChanged: (v) async {
          if (v && !await confirmDialog(context, title: askTitle, question: ask, yes: 'Read them')) return;
          await s.set('secret_app_files', v, consent: v ? appFilesConsent : null);
        },
      ),
    );
  }
}

/// Browser data (setting `browser_data`, 1.2.0, off by default; browserdata.py in the engine): the browsers'
/// history, bookmarks and downloads, and saved logins' site and user name. Reading more asks once.
class BrowserDataSetting extends StatelessWidget {
  const BrowserDataSetting({super.key});

  static const label = 'Search my browsers';
  static const help =
      "Off (the default): NOBAD Find doesn't read your browsers. On: it reads Chrome, Edge, Brave, Vivaldi, Opera "
      'and Firefox, every profile of this Windows account: history (page title, address, site, last visit, '
      'visits), bookmarks (title, address, folder) and downloads (file path, source site, date); with saved logins '
      'also the site and user name of each saved login (Firefox: the site only). Never passwords (they are not '
      'decrypted, kept or shown), page contents, cookies or open tabs. It reads a copy, so your browser keeps '
      'running. Turning it off removes everything it read.';
  static const options = [
    ('off', 'Off'),
    ('history', 'History, bookmarks and downloads'),
    ('history_logins', 'Also saved logins (no passwords)'),
  ];
  static const askTitle = 'Read your browsers?';
  static const ask =
      'NOBAD Find will read the history, bookmarks and downloads of your browsers on this PC, and with saved '
      "logins the site and user name of each one. Passwords are never read. It all stays in NOBAD Find's "
      'encrypted index on this PC and can appear in search results. Turn this off to remove it again.';

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    final now = s.settings.text('browser_data');
    return SettingRow(
      label: label,
      help: help,
      control: NbSelect(
        label: label,
        value: now,
        options: options,
        maxWidth: 260,
        onChanged: (v) async {
          final more = browserDataLevels.indexOf(v) > browserDataLevels.indexOf(now);
          if (more && !await confirmDialog(context, title: askTitle, question: ask, yes: 'Read them')) return;
          await s.set('browser_data', v, consent: more ? browserConsent : null);
        },
      ),
    );
  }
}

class PrivacyPage extends StatelessWidget {
  const PrivacyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final ws = s.settings.wsearch;
    Widget wsHelp;
    Widget? wsControl;
    if (ws == null || ws.missing) {
      wsHelp = Text(
        ws == null ? '' : "Windows Search isn't installed on this PC.",
        style: NbType.text(12.5, c.dim, height: 1.5),
      );
    } else {
      final off = ws.off;
      wsHelp = Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: off
                  ? 'Done: Windows Search indexing is off and NOBAD Find starts with Windows. '
                  : 'Windows Search indexing is on (${ws.start}${ws.running ? ', running' : ''}). One click turns it '
                        'off and starts NOBAD Find with Windows. ',
            ),
            TextSpan(
              text:
                  'With it off, the Start menu, Explorer and Outlook stop finding files by their content (NOBAD '
                  'Find does that instead). Windows asks for permission once; going back restores exactly the '
                  'setting it had before.',
              style: TextStyle(color: c.warn),
            ),
          ],
        ),
        style: NbType.text(12.5, c.dim, height: 1.5),
      );
      wsControl = NbButton(
        s.settings.wsearchBusy ? 'Waiting for Windows…' : (off ? 'Go back to Windows Search' : 'Switch to NOBAD Find'),
        kind: off ? NbButtonKind.ghost : NbButtonKind.primary,
        onPressed: s.settings.wsearchBusy ? null : () => unawaited(s.settings.toggleWindowsSearch()),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'Windows Search',
          icon: NbGlyph.search,
          rows: [SettingRow(label: 'Use NOBAD Find instead of Windows Search', helpWidget: wsHelp, control: wsControl)],
        ),
        SettingsGroup(
          'Search history',
          icon: NbGlyph.clock,
          rows: [
            const SwitchSetting(
              'search_history',
              'Remember my searches',
              'Keeps the questions you type here, for suggestions and the recent searches. Only what you search in NOBAD '
                  'Find: nothing from Windows or other programs. Encrypted with the index, at most 200; turning it '
                  'off deletes them.',
            ),
            SettingRow(
              label: 'Clear search history',
              help: 'Forgets every question kept for suggestions. One at a time: the x next to it in the list.',
              control: NbButton(
                'Clear history',
                kind: NbButtonKind.ghost,
                onPressed: () async {
                  try {
                    final r = await s.engine.historyClear();
                    unawaited(s.find.recent?.refresh()); // the recent searches are that history too
                    s.toasts.show(r.ok ? 'Search history cleared.' : "Couldn't clear the search history.");
                  } on Object {
                    s.toasts.show("NOBAD Find's engine isn't running.");
                  }
                },
              ),
            ),
          ],
        ),
        const SettingsGroup('Files other programs keep', icon: NbGlyph.archive, rows: [AppFilesSetting()]),
        const SettingsGroup('Browsers', icon: NbGlyph.external, rows: [BrowserDataSetting()]),
        const SettingsGroup(
          'Notifications',
          icon: NbGlyph.bell,
          rows: [
            SwitchSetting(
              'notify_show_names',
              'Show file names in notifications',
              'Off: notifications never name a file or show where it is. On: the name of the file involved (not '
                  'its folder), also in Windows notifications, which can show on the lock screen. Turning it off '
                  'removes the names kept so far. Notifications are kept encrypted with the index, at most 100.',
            ),
          ],
        ),
        SettingsGroup(
          'Your data',
          icon: NbGlyph.shield,
          rows: [
            SettingRow(
              label: 'Delete the whole index',
              help:
                  'Removes everything NOBAD Find has stored about your files: the index, its log, and the list of '
                  'files you forgot (they can be indexed again). Your settings and Never index folders stay. It '
                  'starts again from scratch.',
              control: NbButton(
                'Delete index',
                kind: NbButtonKind.danger,
                onPressed: () => unawaited(s.settings.wipe(() => typeDeleteDialog(context))),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

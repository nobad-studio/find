/// About: the version, what NOBAD Find is, the licence and source, and Quit.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../widgets/common.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/panels.dart';
import '../settings_parts.dart';

const sourceLink = 'github.com/nobad-studio/find';

class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final v = s.status.details?.version ?? '';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'NOBAD Find',
          rows: [
            Padding(
              padding: const EdgeInsets.all(NbSpace.x5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const NbMark(size: 52),
                  const SizedBox(width: NbSpace.x5),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Version ${v.isNotEmpty ? v : s.version}'.toUpperCase(),
                          style: NbType.text(20, c.text, weight: FontWeight.w600),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Private, offline file search for Windows. Your files, your index and your searches stay on '
                          'this PC.',
                          style: NbType.text(14, c.muted, height: 1.55),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Open source under the MIT licence. Source and releases: $sourceLink',
                          style: NbType.data(12, c.dim, height: 1.6),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          'NOBAD. Software with a point of view.',
                          style: NbType.text(13, c.text, weight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: NbSpace.x4),
                  NbButton(
                    'Copy link',
                    kind: NbButtonKind.ghost,
                    small: true,
                    onPressed: () async {
                      try {
                        await Clipboard.setData(const ClipboardData(text: 'https://$sourceLink'));
                        s.toasts.show('Link copied.');
                      } on Object {
                        s.toasts.show("Couldn't copy the link.");
                      }
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
        const UpdatesGroup(),
        SettingsGroup(
          'Quit',
          rows: [
            SettingRow(
              label: 'Quit NOBAD Find',
              help:
                  'Closing the window stops indexing and leaves NOBAD Find as one small idle process so the hotkey '
                  'still works (unless Keep indexing in the background is on). This stops it completely until you '
                  'start it again.',
              control: NbButton('Quit', kind: NbButtonKind.ghost, onPressed: () => unawaited(s.settings.quit())),
            ),
          ],
        ),
      ],
    );
  }
}

/// Updates (0.9.0): whether NOBAD Find looks for a newer version by itself, Check now, and Install, which
/// downloads the new installer, checks it and installs it over this version (NOBAD Find closes and starts again).
class UpdatesGroup extends StatefulWidget {
  const UpdatesGroup({super.key});

  @override
  State<UpdatesGroup> createState() => _UpdatesGroupState();
}

class _UpdatesGroupState extends State<UpdatesGroup> {
  bool _asked = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_asked) {
      _asked = true;
      unawaited(AppScope.of(context).status.loadUpdate());
    }
  }

  Future<void> _check() async {
    final s = AppScope.of(context);
    final r = await s.engine.updateCheck();
    if (!r.ok && r.error.isNotEmpty) s.toasts.show(r.error);
  }

  Future<void> _install() async {
    final s = AppScope.of(context);
    final r = await s.engine.updateInstall();
    if (!r.ok) s.toasts.show(r.error.isNotEmpty ? r.error : "The update didn't start.");
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: s.status,
      builder: (context, _) {
        final u = s.status.update;
        final mb = u.size > 0 ? ' (${(u.size / 1048576).round()} MB)' : '';
        final (String line, Color color) = switch (u.state) {
          'checking' => ('Looking for a newer version…', c.muted),
          'uptodate' => ('NOBAD Find is up to date${u.current.isNotEmpty ? ' (${u.current})' : ''}.', c.muted),
          'available' => ('NOBAD Find ${u.latest} is available$mb.', c.orange),
          'downloading' => ('Downloading ${u.latest}… ${(u.got / 1048576).round()} of ${(u.size / 1048576).round()} MB', c.muted),
          'ready' => ('NOBAD Find ${u.latest} is downloaded and checked.', c.orange),
          'installing' => ('Installing ${u.latest}: NOBAD Find closes and starts again in a moment.', c.orange),
          'error' => (u.error.isNotEmpty ? u.error : "Couldn't check for updates.", c.warn),
          _ => ('Press Check now to look for a newer version.', c.muted),
        };
        return SettingsGroup(
          'Updates',
          rows: [
            const SwitchSetting(
              'update_check',
              'Check for updates automatically',
              'Once a day NOBAD Find asks GitHub for its newest release. Nothing about your PC or files is sent, '
                  'and nothing is downloaded until you choose Install.',
            ),
            SettingRow(
              label: 'NOBAD Find updates',
              helpWidget: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(line, style: NbType.text(12.5, color, height: 1.4)),
                  if (u.state == 'downloading') ...[
                    const SizedBox(height: 6),
                    NbMeter(fraction: u.fraction, busy: u.size == 0),
                  ],
                  if (u.canInstall)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        'Install downloads the new installer from GitHub, checks its size and SHA-256 against the '
                        'release, and installs it over this version. The installer isn\'t code-signed yet: that '
                        'checksum is the check. Your index and settings are kept.',
                        style: NbType.text(11.5, c.dim, height: 1.4),
                      ),
                    ),
                ],
              ),
              control: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (u.canInstall) ...[
                    NbButton(u.state == 'ready' ? 'Install now' : 'Install', small: true, onPressed: u.busy ? null : _install),
                    const SizedBox(width: 8),
                  ],
                  NbButton(
                    'Check now',
                    small: true,
                    kind: NbButtonKind.ghost,
                    onPressed: u.busy ? null : () => unawaited(_check()),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}


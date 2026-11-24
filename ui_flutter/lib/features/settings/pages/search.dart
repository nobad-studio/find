/// Search: what happens when you open a file, and the recent searches (from the engine's search history).
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/icons.dart';
import '../settings_parts.dart';

class SearchSettingsPage extends StatelessWidget {
  const SearchSettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final recent = s.find.recent;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SettingsGroup(
          'Opening files',
          icon: NbGlyph.openFile,
          rows: [
            SwitchSetting(
              'hide_after_open',
              'Hide after opening a file',
              'Off: the window stays up after Enter opens a file. On: it hides, like a launcher.',
            ),
          ],
        ),
        if (recent != null)
          SettingsGroup(
            'Recent searches',
            icon: NbGlyph.clock,
            rows: [
              ListenableBuilder(
                listenable: Listenable.merge([recent, s.settings]),
                builder: (context, _) => SettingRow(
                  label: 'Recent searches',
                  help: !s.settings.settings.flag('search_history')
                      ? 'None kept: "Remember my searches" is off in Privacy & data.'
                      : recent.items.isEmpty
                      ? 'None yet. Searches you open a file from show under the empty box.'
                      : 'The last ${recent.items.length} from your search history (encrypted with the index, on '
                            'this PC only), shown under the empty box. Clear forgets the whole history.',
                  control: NbButton(
                    'Clear',
                    small: true,
                    kind: NbButtonKind.ghost,
                    onPressed: recent.items.isEmpty ? null : () => unawaited(recent.clear()),
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }
}

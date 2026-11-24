/// 1.2.0 (browser spec §4): the filter bar's Browser choices. With Kind = Browser: which kind of browser item
/// (History, Bookmarks, Saved logins, Downloads), and with History only, when it was visited (today, yesterday,
/// the last 7 or 30 days, or picked days). The engine reads the values (contract `Filters.browser` / `visited`).
library;

import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';

/// The Browser and Visited menus for [f] (only when [f] is the Browser filter). [logins]: saved logins are read
/// (browser_data history_logins), so they can be asked for.
List<Widget> browserChoices(
  BuildContext context,
  SearchFilters f, {
  required bool logins,
  required void Function(SearchFilters) set,
}) {
  if (!f.isBrowser) return const [];
  final kinds = [
    for (final o in FilterChoices.browserKinds)
      if (o.$1 != 'login' || logins || f.browser == 'login') o,
  ];
  final range = visitedRange(f.visited);
  return [
    NbSelect(
      label: 'Browser',
      compact: true,
      value: f.browser,
      options: kinds,
      highlight: f.browser.isNotEmpty,
      onChanged: (v) => set(f.copyWith(browser: v, visited: v == 'history' ? f.visited : '')),
    ),
    if (f.browser == 'history')
      NbSelect(
        label: 'Visited',
        compact: true,
        value: f.visited,
        options: [
          ...FilterChoices.visited,
          if (range != null) (f.visited, range),
        ],
        highlight: f.visited.isNotEmpty,
        onChanged: (v) async {
          if (v != FilterChoices.pick) {
            set(f.copyWith(visited: v));
            return;
          }
          final days = await pickDays(context);
          if (days != null) set(f.copyWith(visited: days));
        },
      ),
  ];
}

/// "2026-11-01 to 2026-11-20" for a picked `visited` range, null for anything else.
String? visitedRange(String v) {
  final parts = v.split('..');
  if (parts.length != 2 || _day(parts[0]) == null || _day(parts[1]) == null) return null;
  return parts[0] == parts[1] ? parts[0] : '${parts[0]} to ${parts[1]}';
}

/// A real day written YYYY-MM-DD ("2026-02-30" is not one), or null.
DateTime? _day(String s) {
  final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(s.trim());
  if (m == null) return null;
  final y = int.parse(m[1]!), mo = int.parse(m[2]!), d = int.parse(m[3]!);
  final t = DateTime(y, mo, d);
  return t.year == y && t.month == mo && t.day == d ? t : null;
}

String _iso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// Two days (either order), as the engine's `visited` range "YYYY-MM-DD..YYYY-MM-DD"; null when cancelled.
Future<String?> pickDays(BuildContext context) =>
    showDialog<String>(context: context, builder: (context) => const _PickDays());

class _PickDays extends StatefulWidget {
  const _PickDays();
  @override
  State<_PickDays> createState() => _PickDaysState();
}

class _PickDaysState extends State<_PickDays> {
  final _from = TextEditingController();
  final _to = TextEditingController();
  bool _wrong = false;

  @override
  void dispose() {
    _from.dispose();
    _to.dispose();
    super.dispose();
  }

  void _done() {
    final a = _day(_from.text), b = _day(_to.text.isEmpty ? _from.text : _to.text);
    if (a == null || b == null) return setState(() => _wrong = true);
    final (lo, hi) = a.isAfter(b) ? (b, a) : (a, b);
    Navigator.pop(context, '${_iso(lo)}..${_iso(hi)}');
  }

  Widget _field(String label, TextEditingController ctl, {bool first = false}) {
    final c = NbColors.of(context);
    OutlineInputBorder edge(Color col) =>
        OutlineInputBorder(borderRadius: NbRadius.controlAll, borderSide: BorderSide(color: col));
    return Semantics(
      label: label,
      textField: true,
      child: SizedBox(
        width: 150,
        child: TextField(
          controller: ctl,
          autofocus: first,
          onSubmitted: (_) => _done(),
          style: NbType.data(13.5, c.text),
          cursorColor: c.orange,
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: c.raised,
            hintText: 'YYYY-MM-DD',
            hintStyle: NbType.data(13.5, c.dim),
            contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            enabledBorder: edge(c.line2),
            focusedBorder: edge(c.orange),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbDialog(
      key: const ValueKey('pick-dates'),
      title: 'Pick the days',
      width: 480,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('History visited on these days, both included. Leave "To" empty for one day.'),
          const SizedBox(height: NbSpace.x3),
          Wrap(
            spacing: NbSpace.x3,
            runSpacing: NbSpace.x2,
            children: [
              for (final (label, ctl) in [('From', _from), ('To', _to)])
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(width: 38, child: Text(label, style: NbType.text(12.5, c.muted))),
                    _field(label, ctl, first: label == 'From'),
                  ],
                ),
            ],
          ),
          if (_wrong) ...[
            const SizedBox(height: NbSpace.x2),
            Text('Write each day as YYYY-MM-DD, for example 2026-11-20.', style: NbType.text(12.5, c.warn)),
          ],
        ],
      ),
      actions: [
        NbButton('Cancel', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context)),
        NbButton('Search these days', kind: NbButtonKind.primary, onPressed: _done),
      ],
    );
  }
}

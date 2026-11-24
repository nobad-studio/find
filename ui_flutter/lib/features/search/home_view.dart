/// Home, shown while the box and the filters are empty: the categories as one row of equal tiles, then the files
/// changed lately, on the same edges as the search box.
///
/// "Recently changed" is asked for when Home appears, when the engine connects, and again when the index grows
/// (status events, at most every 15 s) or after a failed try. The engine sends its usual answer; 8 are shown.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart' show Link, untrustedLine;
import '../../engine/models/result.dart';
import '../../state/categories.dart';
import '../../widgets/smooth_scroll.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';

class HomeView extends StatefulWidget {
  const HomeView({super.key, required this.onTile});
  final void Function(String words, SearchFilters filters) onTile;

  /// The category row and the recent files card (their edges match the search box's; tested).
  static const tilesKey = ValueKey('home-tiles');
  static const listKey = ValueKey('home-list');

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView> {
  List<FileResult>? _recent;
  DateTime _asked = DateTime.fromMillisecondsSinceEpoch(0);
  int _files = -1;
  AppScope? _scope;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_scope != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _scope?.status.removeListener(_statusChanged);
    _scope = s;
    s.status.addListener(_statusChanged);
    s.engine.link.addListener(_linkChanged);
    _files = s.status.status?.files ?? -1;
    unawaited(_load());
  }

  bool _failed = false;

  void _linkChanged() {
    if (mounted) setState(() {}); // the list says what the link is
    if (_scope!.engine.link.value == Link.connected) unawaited(_load());
  }

  void _statusChanged() {
    final n = _scope!.status.status?.files ?? -1;
    if (_failed) {
      unawaited(_load());
      return;
    }
    if (n == _files) return;
    _files = n;
    if (DateTime.now().difference(_asked) > const Duration(seconds: 15)) unawaited(_load());
  }

  Future<void> _load() async {
    _asked = DateTime.now();
    try {
      final a = await _scope!.engine.search(
        '',
        filters: const SearchFilters(sort: 'newest'),
        channel: 'home',
      );
      if (a.cancelled) return; // a newer one on this channel is coming
      _failed = false;
      if (!mounted) return;
      setState(
        () => _recent = [
          for (final r in a.results)
            if (r.kind != 'folder') r,
        ].take(8).toList(),
      );
    } on Object {
      _failed = true; // tried again on the next status or when the engine comes back
      if (mounted) setState(() => _recent ??= const []);
    }
  }

  @override
  void dispose() {
    _scope?.status.removeListener(_statusChanged);
    _scope?.engine.link.removeListener(_linkChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = AppScope.of(context);
    // the categories as one row of equal tiles, then what changed lately; on the search box's edges, and all of
    // it visible at 1180 x 760 without scrolling
    return SmoothScroll(
      builder: (sc) => SingleChildScrollView(
        controller: sc,
        padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, NbSpace.x5),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              label: 'Browse by category',
              container: true,
              child: CategoryTiles(
                key: HomeView.tilesKey,
                tiles: [for (final k in SearchCategory.values.skip(1)) (k.label, categoryBadges[k]!, k.filters)],
                onTile: (f) => widget.onTile('', f),
              ),
            ),
            const SizedBox(height: NbSpace.x4),
            Glass(
              key: HomeView.listKey,
              padding: const EdgeInsets.fromLTRB(6, 10, 6, 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(10, 0, 10, 6),
                    child: Row(
                      children: [
                        Semantics(header: true, child: Text('Recently changed', style: sectionStyle(c))),
                        const Spacer(),
                        Pressable(
                          onTap: () => widget.onTile('', SearchCategory.recent.filters),
                          semanticLabel: 'All recent files',
                          builder: (context, p) => Text(
                            'Show all',
                            style: NbType.text(12, p.lit ? c.orange : c.dim, weight: FontWeight.w600),
                          ),
                        ),
                      ],
                    ),
                  ),
                  _RecentList(
                    files: _recent,
                    link: s.engine.link.value,
                    failed: _failed,
                    onOpen: (r) async {
                      final res = await s.engine.open(r.id);
                      if (!res.ok) {
                        s.toasts.show(res.error.isNotEmpty ? res.error : "That file isn't there any more.");
                      } else if (s.settings.settings.flag('hide_after_open')) {
                        s.window.hide();
                        unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
                      }
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The badges of the categories on Home's tiles.
const categoryBadges = {
  SearchCategory.documents: 'DOC',
  SearchCategory.photos: 'IMG',
  SearchCategory.media: 'VID',
  SearchCategory.code: 'SRC',
  SearchCategory.downloads: 'DL',
  SearchCategory.recent: 'NEW',
};

/// The icon of a tile: its kind, else a time, a size, or the folder it narrows to.
NbGlyph tileGlyph(SearchFilters f) => switch (f) {
  SearchFilters(folder: 'downloads', kind: '') => NbGlyph.download,
  SearchFilters(kind: 'pdf' || 'document' || 'spreadsheet' || 'slides' || 'text' || 'email' || 'ebook') => NbGlyph.doc,
  SearchFilters(kind: 'image') => NbGlyph.image,
  SearchFilters(kind: 'video' || 'audio') => NbGlyph.media,
  SearchFilters(kind: 'code' || 'archive' || 'app') => NbGlyph.code,
  SearchFilters(modified: != '') => NbGlyph.clock,
  _ => NbGlyph.grid,
};

/// A row of starting tiles (Home's categories, a category's narrower searches): every tile the same width, the
/// row spanning the search box's width (full rows of equal tiles when the window is narrow).
class CategoryTiles extends StatelessWidget {
  const CategoryTiles({super.key, required this.tiles, required this.onTile, this.current});
  final List<CategoryTile> tiles;
  final ValueChanged<SearchFilters> onTile;

  /// The filters in use: the tile with them is lit.
  final SearchFilters? current;

  static const _gap = 8.0, _min = 140.0;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      // the most columns that fit and divide the tiles evenly (6, 3, 2 or 1 for six), so every row spans the box
      final fit = ((box.maxWidth + _gap) / (_min + _gap)).floor().clamp(1, tiles.isEmpty ? 1 : tiles.length);
      var cols = fit;
      while (cols > 1 && tiles.length % cols != 0) {
        cols--;
      }
      final w = (box.maxWidth - _gap * (cols - 1)) / cols;
      return Wrap(
        spacing: _gap,
        runSpacing: _gap,
        children: [
          for (final (label, _, f) in tiles)
            SizedBox(
              width: w,
              child: _Tile(filters: f, label: label, on: current == f, onTap: () => onTile(f)),
            ),
        ],
      );
    },
  );
}

/// A category's narrower searches above its files: one slim row of chips (28 px), scrolling sideways when the
/// window is narrow, so the results keep their room. Home keeps the big [CategoryTiles].
class CategoryChips extends StatelessWidget {
  const CategoryChips({super.key, required this.tiles, required this.onTile, this.current});
  final List<CategoryTile> tiles;
  final ValueChanged<SearchFilters> onTile;

  /// The filters in use: the chip with them is lit.
  final SearchFilters? current;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    child: Row(
      children: [
        for (final (i, (label, _, f)) in tiles.indexed) ...[
          if (i > 0) const SizedBox(width: NbSpace.x2),
          NbChipButton(label, icon: tileGlyph(f), on: current == f, onTap: () => onTile(f)),
        ],
      ],
    ),
  );
}

class _Tile extends StatelessWidget {
  const _Tile({required this.filters, required this.label, required this.onTap, this.on = false});
  final SearchFilters filters;
  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      selected: on,
      semanticLabel: label,
      ringRadius: NbRadius.rowAll,
      builder: (context, p) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        curve: NbMotion.curve,
        // room around the icon tile: 8 px above, below and on its left
        height: GlyphTile.size + 2 * NbSpace.x2,
        padding: const EdgeInsets.fromLTRB(NbSpace.x2, 0, NbSpace.x1, 0),
        decoration: BoxDecoration(
          color: on ? c.orangeA(c.isDark ? .12 : .09) : (p.lit ? c.cardLift : c.card),
          border: Border.all(color: on || p.lit ? c.orangeA(.55) : c.line),
          borderRadius: NbRadius.rowAll,
        ),
        // fills its grid cell; the icon in the one icon treatment (Classic: its hue; Minimal ice: plain)
        child: Row(
          children: [
            GlyphTile(tileGlyph(filters), accent: on),
            const SizedBox(width: NbSpace.x3),
            Expanded(
              child: Text(
                label,
                // a long label wraps to a second line inside the pill rather than being cut
                maxLines: 2,
                style: NbType.text(12, c.text, weight: FontWeight.w600, height: 1.2),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentList extends StatelessWidget {
  const _RecentList({required this.files, required this.onOpen, required this.link, required this.failed});
  final List<FileResult>? files;
  final ValueChanged<FileResult> onOpen;
  final Link link;

  /// The last try failed (the engine was busy or gone): say so instead of "nothing yet".
  final bool failed;

  Widget _say(NbColors c, String text) => Padding(
    padding: const EdgeInsets.fromLTRB(10, 8, 10, 12),
    child: Text(text, style: NbType.text(13, c.dim, height: 1.4)),
  );

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final list = files;
    return ClipRRect(
      borderRadius: NbRadius.rowAll,
      child: link == Link.offline
          ? _say(c, "NOBAD Find's engine isn't running, so there is nothing to show. It comes back with the engine.")
          : link == Link.incompatible
          ? _say(c, 'This window and the engine are different versions. Update NOBAD Find.')
          : link == Link.untrusted
          ? _say(c, untrustedLine)
          : list == null
          ? _say(c, link == Link.connecting ? 'Connecting to the engine…' : 'Looking for what changed…')
          : list.isEmpty && failed
          ? _say(c, "Couldn't ask the engine just now. Trying again with the next update.")
          : list.isEmpty
          ? _say(c, 'Files you change will show up here once they are indexed.')
          : Column(
              children: [
                for (var i = 0; i < list.length; i++) ...[
                  if (i > 0) Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 12), color: c.line),
                  Pressable(
                    onTap: () => onOpen(list[i]),
                    semanticLabel: list[i].name,
                    focusRing: false,
                    builder: (context, p) => AnimatedContainer(
                      duration: NbMotion.of(context, NbMotion.fast),
                      color: p.lit ? c.orangeA(.07) : const Color(0x00000000),
                      height: 40,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      child: Row(
                        children: [
                          KindBadge(list[i].kind, size: 26),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Row(
                              children: [
                                Flexible(
                                  child: Text(
                                    list[i].name,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: NbType.text(13, p.focus ? c.orange : c.text, weight: FontWeight.w600),
                                  ),
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: TailText(
                                    list[i].dir,
                                    textAlign: TextAlign.left,
                                    style: NbType.data(11, c.dim),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 12),
                          Text(list[i].ago, style: NbType.data(11, c.dim)),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
    );
  }
}

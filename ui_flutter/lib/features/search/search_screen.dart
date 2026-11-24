/// Search: the box, the filter bar, what the question was understood as, the results (or Home), the status line.
///
/// Keys (0.7.0): ↑/↓ choose, Enter opens, Ctrl+Enter shows in folder, Ctrl+C copies the path (when no text is
/// selected in the box), Shift+Delete forgets, Esc clears the box and, when it's empty, hides the window.
/// 0.8.5 smart search: while the suggestions are open ↑/↓ move in them and Enter takes one; Tab or → (at the end)
/// takes the dim inline completion; Esc closes the suggestions first. With no suggestion highlighted Enter opens
/// the best guess (the first result).
library;

import 'dart:async';

import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/rendering.dart' show RenderAbstractViewport;
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart' show maxTextLength;
import '../../engine/events.dart';
import '../../engine/models/result.dart';
import '../../state/categories.dart';
import '../../state/search_controller.dart';
import '../../state/suggest_controller.dart';
import '../../state/talk_controller.dart';
import '../../platform/demo.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/menu_glass.dart';
import '../../widgets/motion.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';
import '../../widgets/smooth_scroll.dart';
import 'filter_bar.dart';
import 'actions_block.dart';
import 'need_hint.dart';
import 'home_view.dart';
import '../../platform/timing.dart';
import '../../state/typed_filters.dart';
import '../../widgets/controls.dart';
import 'result_actions.dart';
import 'preview_strip.dart';
import 'result_tile.dart';
import 'searching_ring.dart';
import 'smart_search.dart';
import 'status_line.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  /// The search box, Home's category row and list, and the status line share the same left and right edges
  /// (test/widgets/alignment_test.dart).
  static const boxKey = ValueKey('search-box');
  static const statusKey = ValueKey('search-status');

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  late AppScope s;
  late final box = GhostTextController(text: AppScope.of(context).find.text);

  /// Autocomplete (the engine's `suggest`), shown under the box.
  late final SuggestController sug = SuggestController(AppScope.of(context).engine);

  /// Talk about a photo (1.1) on the detail pane or sheet: one question at a time, about the selected photo.
  late final TalkController talk = TalkController(AppScope.of(context).engine);
  final _boxLink = LayerLink();
  final _dropdown = OverlayPortalController();
  double _boxWidth = 600;

  /// The box's text is being set by the screen (a suggestion taken, a chip removed): not typing.
  bool _quiet = false;
  final focus = FocusNode(debugLabel: 'search box');

  /// The results' scroll: wheel notches glide (smooth_scroll.dart); the Scrollbar and the keys use it too.
  final scroll = SmoothScrollController();

  /// One key per row for the answer on screen, so the selected row can be scrolled to without rebuilding rows.
  final _rowKeys = <int, GlobalKey>{};
  int _keysFor = -1;

  /// List or cards (cards: a grid of 1 to 4 columns as the window allows).
  bool _cards = false;
  StreamSubscription<EngineEvent>? _shows;
  int _lastSel = -1;
  bool _wired = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    s = AppScope.of(context);
    if (_wired) return;
    _wired = true;
    Demo.mainBox = box;
    box.addListener(() {
      final changed = box.text != s.find.text;
      if (changed) _navigating = false;
      s.find.setText(box.text);
      if (changed && !_quiet) sug.typed(box.text);
      box.ghost = sug.ghostFor(box.text);
    });
    sug.addListener(() => box.ghost = sug.ghostFor(box.text));
    focus.addListener(() {
      if (!focus.hasFocus) sug.close();
    });
    _dropdown.show();
    s.find.addListener(_follow);
    s.find.addListener(_followPhoto);
    s.find.addListener(_measure);
    s.find.addListener(_takeHandOver);
    _takeHandOver();
    _shows = s.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'main' && e.text == null) {
        focus.requestFocus();
        box.selection = TextSelection(baseOffset: 0, extentOffset: box.text.length);
      }
    });
  }

  /// The bar's words (Alt+Enter), held by the controller until this screen is there to take them.
  void _takeHandOver() {
    final t = s.find.takeHandOver();
    if (t == null) return;
    box.text = t;
    box.selection = TextSelection.collapsed(offset: t.length);
    focus.requestFocus();
  }

  GlobalKey rowKey(int id) {
    if (_rowKeys.length > 2000) _rowKeys.clear(); // kept across answers: a row that stays keeps its preview
    return _rowKeys.putIfAbsent(id, GlobalKey.new);
  }

  /// Measurement (NOBAD_FIND_UI_TIMING): keystroke → the frame with the new answer on screen.
  void _measure() {
    if (s.find.serial == _keysFor) return;
    _keysFor = s.find.serial;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      recordTiming('keystroke-to-paint ms=${s.find.sinceKeystroke.inMilliseconds} results=${s.find.results.length}');
    });
  }

  /// The photo the detail pane shows now (talk follows it: another selection stops a running answer).
  void _followPhoto() {
    final cur = s.find.showingResults ? s.find.current : null;
    talk.show(cur != null && cur.kind == 'image' ? cur.id : null);
  }

  /// The image results in the list now (Compare with…).
  List<FileResult> get _photos => [
    for (final r in s.find.results)
      if (r.kind == 'image') r,
  ];

  void _follow() {
    if (s.find.selected == _lastSel) return;
    _lastSel = s.find.selected;
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: true));
  }

  /// Scroll the selected row into view. Rows have different heights, so a row that isn't built yet (the selection
  /// jumped far, e.g. wrapping from the first to the last) is first reached by an estimate, then aligned.
  void _reveal({required bool retry}) {
    if (!mounted) return;
    final cur = s.find.current;
    final ctx = cur == null ? null : _rowKeys[cur.id]?.currentContext;
    if (ctx != null && ctx.mounted) {
      final ro = ctx.findRenderObject();
      final viewport = ro == null ? null : RenderAbstractViewport.maybeOf(ro);
      final above =
          viewport != null &&
          scroll.hasClients &&
          viewport.getOffsetToReveal(ro!, 0).offset < scroll.offset; // the row starts above the top edge
      Scrollable.ensureVisible(
        ctx,
        duration: NbMotion.of(context, NbMotion.fast),
        alignmentPolicy: s.find.selected == 0 || above
            ? ScrollPositionAlignmentPolicy.keepVisibleAtStart
            : ScrollPositionAlignmentPolicy.keepVisibleAtEnd,
      );
      return;
    }
    if (!retry || !scroll.hasClients || s.find.results.isEmpty) return;
    final p = scroll.position;
    p.jumpTo((p.maxScrollExtent * s.find.selected / s.find.results.length).clamp(0, p.maxScrollExtent));
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: false));
    WidgetsBinding.instance.scheduleFrame();
  }

  @override
  void dispose() {
    if (identical(Demo.mainBox, box)) Demo.mainBox = null;
    _shows?.cancel();
    _clickedFor?.cancel();
    s.find.removeListener(_follow);
    s.find.removeListener(_followPhoto);
    talk.dispose();
    s.find.removeListener(_measure);
    s.find.removeListener(_takeHandOver);
    sug.dispose();
    box.dispose();
    focus.dispose();
    scroll.dispose();
    super.dispose();
  }

  Future<void> _open({bool reveal = false}) async {
    if (reveal) {
      await s.find.revealSelected();
      return;
    }
    final ok = await s.find.openSelected();
    if (ok && s.settings.settings.flag('hide_after_open')) {
      s.window.hide();
      unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
    }
  }

  void _copy() {
    final sel = box.selection;
    if (sel.isValid && !sel.isCollapsed) {
      // text selected in the box: a normal copy
      Clipboard.setData(ClipboardData(text: sel.textInside(box.text)));
      return;
    }
    unawaited(s.find.copySelected());
  }

  Future<void> _forget() async {
    await s.find.forgetSelected(
      (q) => confirmDialog(context, title: 'Forget this file?', question: q, yes: 'Forget', danger: true),
    );
    if (mounted) focus.requestFocus();
  }

  /// Esc clears the words, then the filters, and only then hides the window.
  /// The selection was moved with the keys since the last typing: Space then opens the details (below the
  /// detail pane's width), and Home / End jump in the results instead of moving the caret.
  bool _navigating = false;
  bool _sheet = false;

  /// Narrow window (no detail pane): a click opened the preview strip under the results (preview_strip.dart).
  bool _strip = false;
  bool _wide = false;
  final _menu = MenuController();
  final _menuAnchor = GlobalKey();
  static const _page = 8;

  void _nav(VoidCallback f) {
    _navigating = true;
    f();
  }

  /// Keys that only mean something to the results while the selection is being moved (else they edit the words).
  KeyEventResult _navKeys(FocusNode node, KeyEvent e) {
    // the inline completion: Tab, or → with the caret at the end
    if (e is KeyDownEvent &&
        (e.logicalKey == LogicalKeyboardKey.tab && !HardwareKeyboard.instance.isShiftPressed ||
            e.logicalKey == LogicalKeyboardKey.arrowRight && box.atEnd && box.ghost.isNotEmpty) &&
        box.acceptGhost()) {
      return KeyEventResult.handled;
    }
    if (e is KeyDownEvent && e.logicalKey == LogicalKeyboardKey.tab && !HardwareKeyboard.instance.isShiftPressed) {
      final typed = suggestFilters(box.text);
      if (typed.isNotEmpty) {
        _acceptSuggestion(typed.first);
        return KeyEventResult.handled;
      }
    }
    if (e is! KeyDownEvent || !_navigating || s.find.results.isEmpty) return KeyEventResult.ignored;
    final k = e.logicalKey;
    if (k == LogicalKeyboardKey.space && !HardwareKeyboard.instance.isShiftPressed && !_wide) {
      setState(() => _sheet = !_sheet);
      return KeyEventResult.handled;
    }
    if (k == LogicalKeyboardKey.home) {
      s.find.select(0);
      return KeyEventResult.handled;
    }
    if (k == LogicalKeyboardKey.end) {
      s.find.select(s.find.results.length - 1);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  void _acceptSuggestion(TypedFilter t) {
    final (text, filters) = t.accept(box.text, s.find.filters);
    s.find.setFilters(filters);
    box.text = text;
    box.selection = TextSelection.collapsed(offset: text.length);
    focus.requestFocus();
  }

  void _setWords(String t) {
    _quiet = true;
    box.text = t;
    box.selection = TextSelection.collapsed(offset: t.length);
    _quiet = false;
    sug.close();
    focus.requestFocus();
  }

  /// A suggestion taken (Enter on it, a click): its whole question goes in the box and is kept in history.
  void _pick(Suggestion x) {
    _setWords(x.text);
    s.find.remember(x.text);
  }

  void _down() {
    if (sug.down(noResults: s.find.results.isEmpty)) return;
    if (box.text.isEmpty && s.find.results.isEmpty) {
      sug.showRecent(); // ↓ in an empty box: your recent questions
      return;
    }
    _nav(() => s.find.move(1));
  }

  void _up() {
    if (sug.up(atTop: s.find.results.isEmpty || s.find.selected == 0)) return;
    _nav(() => s.find.move(-1));
  }

  void _enter() {
    final x = sug.current;
    if (x != null) {
      _pick(x);
      return;
    }
    sug.close();
    unawaited(s.find.settle().then((_) {        // 0.9.5: act on the answer to what is typed now
      if (!mounted) return;
      final act = s.find.launchAction;          // "open bluetooth": Enter opens the setting, not the first file
      if (act != null) {
        unawaited(s.find.runAction(act));
        return;
      }
      _open();
    }));
  }

  /// A second plain click on the same result within this time is a double-click.
  static const _doubleClick = Duration(milliseconds: 450);
  int _clickedId = -1;
  Timer? _clickedFor;

  /// A click on a result (1.2): it selects and previews, it never opens. The preview is the detail pane, or, in a
  /// window too narrow for the pane, the strip under the results (nothing covers the list). A double-click opens;
  /// Ctrl+click shows the file in its folder (Enter, Ctrl+Enter and the preview's buttons do the same for the
  /// selected result). The click takes effect at once: nothing waits to find out whether a second one follows.
  void _clicked(int i, bool reveal) {
    s.find.select(i);
    focus.requestFocus();
    _clickedFor?.cancel();
    if (reveal) {
      _clickedId = -1;
      unawaited(_open(reveal: true));
      return;
    }
    final id = s.find.results[i].id;
    if (id == _clickedId) {
      _clickedId = -1;
      unawaited(_open());
      return;
    }
    _clickedId = id;
    _clickedFor = Timer(_doubleClick, () => _clickedId = -1);
    if (!_wide && !_strip) setState(() => _strip = true);
  }

  void _action(ResultAction a) {
    switch (a) {
      case ResultAction.open:
        _open();
      case ResultAction.openWith:
        unawaited(s.find.openWithSelected());
      case ResultAction.reveal:
        _open(reveal: true);
      case ResultAction.copyPath:
        unawaited(s.find.copySelected());
      case ResultAction.copyName:
        unawaited(s.find.copyNameSelected());
      case ResultAction.details:
        setState(() => _sheet = true);
      case ResultAction.forget:
        unawaited(_forget());
    }
  }

  /// The actions menu at [global] (right-click, "⋯").
  void _menuAt(Offset global) {
    final box = _menuAnchor.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return;
    _menu.open(position: MenuGlass.at(box.globalToLocal(global)));
  }

  /// The menu key / Shift+F10: the menu under the selected result.
  void _menuAtSelection() {
    final cur = s.find.current;
    final row = cur == null ? null : _rowKeys[cur.id]?.currentContext?.findRenderObject() as RenderBox?;
    if (row == null) return;
    _menuAt(row.localToGlobal(Offset(24, row.size.height - 8)));
  }

  void _escape() {
    if (sug.close()) return;
    if (talk.running) {
      unawaited(talk.stop()); // Esc stops an answer before it closes anything
      return;
    }
    if (_sheet) {
      setState(() => _sheet = false);
      return;
    }
    if (_strip && !_wide) {
      setState(() => _strip = false); // the preview strip closes before the box is cleared
      return;
    }
    if (box.text.isNotEmpty) {
      box.clear();
      return;
    }
    if (s.find.clearOne()) return;
    s.window.hide();
    unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
  }

  /// The suggestions, floating under the search field over the page (they never push the results down).
  Widget _dropdownLayer(BuildContext context) => Positioned(
    width: _boxWidth,
    child: CompositedTransformFollower(
      link: _boxLink,
      targetAnchor: Alignment.bottomLeft,
      offset: const Offset(0, 4),
      child: TextFieldTapRegion(
        child: SuggestionList(ctl: sug, onPick: _pick),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    box.ghostColor = NbColors.of(context).dim;
    scroll.glide = !reduceMotion(context);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.arrowDown): _down,
        const SingleActivator(LogicalKeyboardKey.arrowUp): _up,
        const SingleActivator(LogicalKeyboardKey.pageDown): () => _nav(() => s.find.move(_page)),
        const SingleActivator(LogicalKeyboardKey.pageUp): () => _nav(() => s.find.move(-_page)),
        const SingleActivator(LogicalKeyboardKey.enter, control: true, shift: true): () =>
            _action(ResultAction.openWith),
        const SingleActivator(LogicalKeyboardKey.contextMenu): _menuAtSelection,
        // the action panel on the selected result, as in a command palette
        const SingleActivator(LogicalKeyboardKey.keyK, control: true): _menuAtSelection,
        const SingleActivator(LogicalKeyboardKey.f10, shift: true): _menuAtSelection,
        const SingleActivator(LogicalKeyboardKey.enter): _enter,
        const SingleActivator(LogicalKeyboardKey.numpadEnter): _enter,
        const SingleActivator(LogicalKeyboardKey.enter, control: true): () => _open(reveal: true),
        const SingleActivator(LogicalKeyboardKey.keyC, control: true): _copy,
        const SingleActivator(LogicalKeyboardKey.delete, shift: true): _forget,
        const SingleActivator(LogicalKeyboardKey.escape): _escape,
      },
      child: LayoutBuilder(
        builder: (context, box2) {
          final wide = box2.maxWidth >= NbSpace.wide;
          _wide = wide;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // the page header: Search, and the category (the sidebar's lit entry)
              ListenableBuilder(
                listenable: s.find,
                builder: (context, _) {
                  final cat = SearchCategory.of(s.find.filters);
                  return PageHeader(cat == SearchCategory.all ? 'All files' : cat.label, crumb: 'Search');
                },
              ),
              // the toolbar: the box and its filters, on the page gutter
              // the same box as the list under it (max width, then the inset), so their edges line up
              Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, NbSpace.x2),
                    // Space, Home and End go to the results while the selection is being moved with the keys
                    child: Focus(
                      canRequestFocus: false,
                      skipTraversal: true,
                      onKeyEvent: _navKeys,
                      child: _SearchBox(
                        controller: box,
                        focus: focus,
                        link: _boxLink,
                        onWidth: (w) => _boxWidth = w,
                        dropdown: _dropdown,
                        searching: s.find.searching,
                        overlay: (context) => _dropdownLayer(context),
                        filters: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            _Suggestions(box: box, onAccept: _acceptSuggestion, onRecent: _setWords),
                            FilterBar(onDone: focus.requestFocus),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              ListenableBuilder(
                listenable: s.find,
                builder: (context, _) =>
                    _Meta(find: s.find, onWords: _setWords, cards: _cards, onCards: (v) => setState(() => _cards = v)),
              ),
              Expanded(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: MenuAnchor(
                        controller: _menu,
                        menuChildren: MenuGlass.wrap(resultMenuItems(context, _action, details: !wide)),
                        child: KeyedSubtree(
                          key: _menuAnchor,
                          child: Align(
                            alignment: Alignment.topLeft,
                            child: ConstrainedBox(
                              constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
                              child: ListenableBuilder(
                                listenable: s.find,
                                builder: (context, _) => AnimatedSwitcher(
                                  duration: NbMotion.of(context, NbMotion.fast),
                                  layoutBuilder: (current, previous) =>
                                      Stack(alignment: Alignment.topCenter, children: [...previous, ?current]),
                                  child:
                                      s.find.showingResults &&
                                          s.find.busy &&
                                          s.find.results.isEmpty &&
                                          s.find.notice.isEmpty
                                      ? const Align(
                                          key: ValueKey('loading'),
                                          alignment: Alignment.topCenter,
                                          child: Padding(
                                            padding: EdgeInsets.symmetric(horizontal: NbSpace.x5),
                                            child: SkeletonResults(),
                                          ),
                                        )
                                      : s.find.showingResults &&
                                            !s.find.busy &&
                                            s.find.results.isEmpty &&
                                            s.find.answer.actions.isEmpty &&
                                            s.find.askedFor.isNotEmpty
                                      ? _NoResults(
                                          key: const ValueKey('none'),
                                          words: s.find.askedFor,
                                          hasFilters: !s.find.filters.isEmpty,
                                          onClearFilters: s.find.clearFilters,
                                          onWords: _setWords,
                                        )
                                      : s.find.showingResults &&
                                            !s.find.busy &&
                                            s.find.results.isEmpty &&
                                            s.find.askedFor.isEmpty
                                      ? _EmptyCategory(
                                          key: ValueKey(('empty', SearchCategory.of(s.find.filters))),
                                          category: SearchCategory.of(s.find.filters),
                                          current: s.find.filters,
                                          onTile: s.find.setFilters,
                                        )
                                      : !s.find.showingResults
                                      ? HomeView(
                                          key: const ValueKey('home'),
                                          onTile: (words, f) {
                                            s.find.setFilters(f);
                                            box.text = words;
                                            focus.requestFocus();
                                          },
                                        )
                                      : Row(
                                          key: const ValueKey('results'),
                                          crossAxisAlignment: CrossAxisAlignment.stretch,
                                          children: [
                                            Expanded(
                                              child: _Results(
                                                tiles: s.find.text.trim().isEmpty
                                                    ? SearchCategory.of(s.find.filters).tiles
                                                    : null,
                                                scroll: scroll,
                                                rowKey: rowKey,
                                                cards: _cards,
                                                onTap: _clicked,
                                                onSecondary: (i, pos) {
                                                  s.find.select(i);
                                                  _menuAt(pos);
                                                },
                                                onAction: (i, a) {
                                                  s.find.select(i);
                                                  _action(a);
                                                  focus.requestFocus();
                                                },
                                              ),
                                            ),
                                            if (wide && s.find.results.isNotEmpty)
                                              Padding(
                                                padding: const EdgeInsets.fromLTRB(4, 2, NbSpace.gutter, NbSpace.x3),
                                                child: SizedBox(
                                                  width: box2.maxWidth >= 1100 ? 360 : 320,
                                                  child: DetailPane(
                                                    engine: s.engine,
                                                    result: s.find.current,
                                                    onOpen: _open,
                                                    onOpenWith: () => _action(ResultAction.openWith),
                                                    onReveal: () => _action(ResultAction.reveal),
                                                    onCopy: _copy,
                                                    onForget: _forget,
                                                    talk: talk,
                                                    otherPhotos: _photos,
                                                  ),
                                                ),
                                              ),
                                          ],
                                        ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    // below the detail pane's width: the details as a sheet sliding over the results
                    if (!wide)
                      Positioned.fill(
                        child: ListenableBuilder(
                          listenable: s.find,
                          builder: (context, _) => _DetailSheet(
                            open: _sheet && s.find.showingResults && s.find.current != null,
                            onClose: () {
                              unawaited(talk.stop()); // closing the sheet stops an answer nobody would see
                              setState(() => _sheet = false);
                            },
                            child: DetailPane(
                              engine: s.engine,
                              result: s.find.current,
                              onOpen: _open,
                              onOpenWith: () => _action(ResultAction.openWith),
                              onReveal: () => _action(ResultAction.reveal),
                              onCopy: _copy,
                              onForget: _forget,
                              talk: talk,
                              otherPhotos: _photos,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
              // narrow window: the preview of the selected result, under the results (never over them)
              if (!wide)
                Align(
                  alignment: Alignment.topLeft,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
                    child: ListenableBuilder(
                      listenable: s.find,
                      builder: (context, _) {
                        final r = s.find.current;
                        final show = _strip && !_sheet && s.find.showingResults && r != null;
                        return AnimatedSize(
                          duration: NbMotion.size(context, NbMotion.base),
                          curve: NbMotion.curve,
                          alignment: Alignment.topCenter,
                          child: show
                              ? PreviewStrip(
                                  key: const ValueKey('preview-strip'),
                                  result: r,
                                  onOpen: _open,
                                  onReveal: () => _open(reveal: true),
                                  onClose: () {
                                    setState(() => _strip = false);
                                    focus.requestFocus();
                                  },
                                )
                              : const SizedBox(width: double.infinity),
                        );
                      },
                    ),
                  ),
                ),
              // on the same edges as the search box and Home's tiles and list
              Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
                  child: ListenableBuilder(
                    listenable: s.find,
                    builder: (context, _) =>
                        StatusLine(key: SearchScreen.statusKey, keys: s.find.results.isNotEmpty),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _SearchBox extends StatefulWidget {
  const _SearchBox({
    required this.controller,
    required this.focus,
    required this.filters,
    required this.link,
    required this.onWidth,
    required this.dropdown,
    required this.overlay,
    required this.searching,
  });
  final TextEditingController controller;
  final FocusNode focus;
  final Widget filters;

  /// The suggestions hang from the field (smart_search.dart).
  final LayerLink link;
  final ValueChanged<double> onWidth;
  final OverlayPortalController dropdown;
  final WidgetBuilder overlay;

  /// A search is on its way (the ring shows after 150 ms of it).
  final ValueListenable<bool> searching;

  @override
  State<_SearchBox> createState() => _SearchBoxState();
}

class _SearchBoxState extends State<_SearchBox> with SingleTickerProviderStateMixin {
  // the palette settles in when the window opens: 280 ms, a FadeTransition (one layer, nothing rebuilt per frame)
  late final _in = AnimationController(vsync: this, duration: const Duration(milliseconds: 280));
  late final _fade = CurvedAnimation(parent: _in, curve: NbMotion.curve);
  late final _rise = Tween(begin: const Offset(0, .06), end: Offset.zero).animate(_fade);

  @override
  void initState() {
    super.initState();
    widget.focus.addListener(_changed);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_in.isDismissed) {
      if (reduceMotion(context)) {
        _in.value = 1;
      } else {
        _in.forward();
      }
    }
  }

  void _changed() => setState(() {});

  @override
  void dispose() {
    widget.focus.removeListener(_changed);
    _in.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final on = widget.focus.hasFocus;
    return FadeTransition(
      opacity: _fade,
      child: SlideTransition(
        position: _rise,
        child: Glass(
          key: SearchScreen.boxKey,
          level: GlassLevel.panel,
          radius: NbRadius.card,
          rim: on && !c.smoke ? c.orangeA(.6) : null,
          padding: c.smoke ? const EdgeInsets.fromLTRB(10, 10, 10, 12) : const EdgeInsets.fromLTRB(4, 2, 4, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // its own layer: the blinking caret repaints only the field, not the glass around it
              LayoutBuilder(
                builder: (context, cons) {
                  widget.onWidth(cons.maxWidth);
                  return OverlayPortal(
                    controller: widget.dropdown,
                    overlayChildBuilder: widget.overlay,
                    child: CompositedTransformTarget(link: widget.link, child: _field(context, c, on)),
                  );
                },
              ),
              Container(
                height: 1,
                margin: c.smoke ? const EdgeInsets.fromLTRB(4, 8, 4, 10) : const EdgeInsets.fromLTRB(10, 0, 10, 8),
                color: c.line,
              ),
              Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: widget.filters),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field(BuildContext context, NbColors c, bool on) => RepaintBoundary(
    child: TextField(
      controller: widget.controller,
      focusNode: widget.focus,
      autofocus: true,
      cursorColor: c.orange,
      inputFormatters: [LengthLimitingTextInputFormatter(maxTextLength)],
      style: NbType.text(NbSize.field, c.text),
      textInputAction: TextInputAction.search,
      decoration: InputDecoration(
        isDense: true,
        border: InputBorder.none,
        hintText: 'Describe it: “rent pdf from last week”, “budget.xlsx”',
        hintStyle: NbType.text(NbSize.field, c.dim),
        prefixIcon: c.smoke
            // Nocturne: the reference's round button on the left
            ? Padding(
                padding: const EdgeInsets.only(right: 14),
                child: Container(
                  width: 44,
                  height: 44,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(shape: BoxShape.circle, color: c.raised, border: Border.all(color: c.line)),
                  child: SearchingRing(
                    searching: widget.searching,
                    color: c.text,
                    size: 18,
                    child: NbIcon(NbGlyph.search, size: 18, color: on ? c.text : c.muted),
                  ),
                ),
              )
            : Padding(
                padding: const EdgeInsets.only(left: 12, right: 10),
                child: SearchingRing(
                  searching: widget.searching,
                  color: c.orange,
                  size: 17,
                  child: NbIcon(NbGlyph.search, size: 17, color: on ? c.orange : c.dim),
                ),
              ),
        prefixIconConstraints: c.smoke
            ? const BoxConstraints(minWidth: 58, minHeight: 44)
            : const BoxConstraints(minWidth: 40, minHeight: 18),
        // a way to clear the box with the mouse; Esc does the same
        suffixIcon: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) => widget.controller.text.isEmpty
              ? SizedBox(width: c.smoke ? 44 : 8, height: c.smoke ? 44 : null)
              : Padding(
                  padding: EdgeInsets.only(right: c.smoke ? 0 : 10),
                  child: Pressable(
                    onTap: () {
                      widget.controller.clear();
                      widget.focus.requestFocus();
                    },
                    semanticLabel: 'Clear',
                    tooltip: 'Clear (Esc)',
                    canRequestFocus: false,
                    ringRadius: NbRadius.pillAll,
                    builder: (context, p) => c.smoke
                        // Nocturne: the white round button on the right
                        ? Container(
                            width: 44,
                            height: 44,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: p.lit ? Color.lerp(c.action, c.onAction, .06) : c.action,
                              shape: BoxShape.circle,
                              boxShadow: [
                                BoxShadow(color: c.float, blurRadius: 16, offset: const Offset(0, 6), spreadRadius: -6),
                              ],
                            ),
                            child: NbIcon(NbGlyph.close, size: 16, color: c.onAction),
                          )
                        : Container(
                            padding: const EdgeInsets.all(5),
                            decoration: BoxDecoration(color: p.lit ? c.cardHover : null, shape: BoxShape.circle),
                            child: NbIcon(NbGlyph.close, size: 13, color: p.lit ? c.text : c.dim),
                          ),
                  ),
                ),
        ),
        contentPadding: c.smoke ? const EdgeInsets.fromLTRB(0, 12, 8, 12) : const EdgeInsets.fromLTRB(0, 12, 12, 11),
      ),
    ),
  );
}

class _Meta extends StatelessWidget {
  const _Meta({required this.find, required this.cards, required this.onCards, required this.onWords});
  final FindController find;
  final ValueChanged<String> onWords;
  final bool cards;
  final ValueChanged<bool> onCards;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final f = find;
    final a = f.answer;
    if (!f.showingResults) return const SizedBox(height: NbSpace.x1);
    final spans = <InlineSpan>[];
    if (f.notice.isNotEmpty) {
      spans.add(TextSpan(text: f.notice, style: NbType.text(NbSize.small, c.warn)));
    } else if (f.askedFor.isNotEmpty || f.filters.narrows) {
      spans.add(
        TextSpan(
          text: f.filters.isLauncher && a.actions.isNotEmpty
              ? '${a.actions.length} ${a.actions.length == 1 ? 'setting or app' : 'settings and apps'} · ${a.ms} ms'
              : a.results.isEmpty
              ? 'Nothing found. Try fewer or other words, or fewer filters.'
              : '${a.results.length}${a.more ? '+' : ''} ${a.results.length == 1 && !a.more ? 'result' : 'results'} · ${a.ms} ms',
        ),
      );
      for (final n in a.notes) {
        spans.add(TextSpan(text: ' · $n', style: NbType.text(NbSize.small, c.warn)));
      }
    }
    final acts = f.showingResults ? a.actions : const <SearchAction>[];
    final header = Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(NbSpace.gutter + 2, 0, NbSpace.gutter, 6),
          child: Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    // 0.8.5: the engine's parts, each removable (it says what the question is without it)
                    for (final p in a.parts) PartChip(p, onRemove: () => onWords(p.without)),
                    if (a.parts.isEmpty)
                      for (final u in a.understood)
                        _Understood(
                          u,
                          onRemove: removeUnderstood(find.text, u) == null
                              ? null
                              : () => onWords(removeUnderstood(find.text, u)!),
                        ),
                    if (spans.isNotEmpty)
                      Padding(
                        padding: EdgeInsets.only(left: a.understood.isEmpty && a.parts.isEmpty ? 0 : 6),
                        child: Text.rich(TextSpan(children: spans), style: NbType.data(NbSize.caption, c.dim)),
                      ),
                  ],
                ),
              ),
              if (a.results.isNotEmpty) _ViewSwitch(cards: cards, onChanged: onCards),
            ],
          ),
        ),
      ),
    );
    if (a.needs.isEmpty && acts.isEmpty) return header;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        header,
        if (acts.isNotEmpty)
          Align(
            alignment: Alignment.topLeft,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, 8),
                child: ActionsBlock(acts, max: f.filters.isLauncher ? acts.length : 3),
              ),
            ),
          ),
        if (a.needs.isNotEmpty)
        Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: NbSpace.maxContent),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, 8),
              child: NeedHint(a.needs.first, key: ValueKey('${a.needs.first.model}-${a.needs.first.state}'),
                  onChanged: () => unawaited(f.run())),
            ),
          ),
        ),
      ],
    );
  }
}

/// List or cards: a two-segment switch, the lit segment a small glass pill.
class _ViewSwitch extends StatelessWidget {
  const _ViewSwitch({required this.cards, required this.onChanged});
  final bool cards;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget seg(String label, bool on, VoidCallback tap) => Pressable(
      onTap: tap,
      selected: on,
      semanticLabel: label,
      ringRadius: NbRadius.pillAll,
      builder: (context, p) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.base),
        curve: NbMotion.curve,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
        decoration: BoxDecoration(color: on ? c.cardHover : null, borderRadius: NbRadius.pillAll),
        child: Text(
          label,
          style: NbType.text(
            NbSize.small,
            on ? c.text : (p.lit ? c.muted : c.dim),
            weight: on ? FontWeight.w600 : FontWeight.w500,
            height: 1.2,
          ),
        ),
      ),
    );
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: c.card,
        border: Border.all(color: c.line),
        borderRadius: NbRadius.pillAll,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [seg('List', !cards, () => onChanged(false)), seg('Cards', cards, () => onChanged(true))],
      ),
    );
  }
}

class _Results extends StatelessWidget {
  const _Results({
    this.tiles,
    required this.scroll,
    required this.rowKey,
    required this.cards,
    required this.onTap,
    required this.onSecondary,
    required this.onAction,
  });
  final ScrollController scroll;
  final GlobalKey Function(int id) rowKey;
  final bool cards;
  final void Function(int index, bool reveal) onTap;
  final void Function(int index, Offset globalPosition) onSecondary;
  final void Function(int index, ResultAction action) onAction;

  /// A category's narrower searches, shown above its files while the box is empty.
  final List<CategoryTile>? tiles;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final List<FileResult> rows = s.find.results;
    final head = tiles == null
        ? null
        : Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
            child: CategoryChips(tiles: tiles!, current: s.find.filters, onTile: s.find.setFilters),
          );
    final firstWeak = rows.indexWhere((r) => r.weak);
    final divider = firstWeak > 0;
    if (cards) {
      // 1 to 4 (or more) columns of cards, as wide as the space allows
      return Scrollbar(
        controller: scroll,
        child: GridView.builder(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 4, NbSpace.x2, NbSpace.x4),
          gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
            maxCrossAxisExtent: 300,
            mainAxisExtent: ResultCard.height,
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
          ),
          itemCount: rows.length,
          itemBuilder: (context, i) => Appear(
            key: ValueKey((s.find.revealSerial, rows[i].id)),
            delay: Appear.stagger(i),
            child: ResultCard(
              key: rowKey(rows[i].id),
              engine: s.engine,
              result: rows[i],
              selected: i == s.find.selected,
              onTap: (reveal) => onTap(i, reveal),
              onSecondary: (pos) => onSecondary(i, pos),
              onAction: (a) => onAction(i, a),
            ),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.x2, NbSpace.x3),
      child: Glass(
        level: GlassLevel.panel,
        radius: NbRadius.card,
        padding: const EdgeInsets.fromLTRB(4, 2, 4, 2),
        child: Scrollbar(
          controller: scroll,
          child: ListView.builder(
            controller: scroll,
            padding: EdgeInsets.zero,
            itemCount: rows.length + (divider ? 1 : 0) + (head == null ? 0 : 1),
            itemBuilder: (context, at) {
              if (head != null && at == 0) return head;
              final i = head == null ? at : at - 1;
              if (divider && i == firstWeak) return const LessSure();
              final idx = divider && i > firstWeak ? i - 1 : i;
              final sel = idx == s.find.selected;
              final best = s.find.answer.best;
              final guess = idx == 0 && s.find.answer.hasGuess && best != null;
              // each new answer comes in as a short cascade; moving the selection doesn't replay it
              final tile = ResultTile(
                key: rowKey(rows[idx].id), // stable: moving the selection only repaints two rows
                engine: s.engine,
                result: rows[idx],
                selected: sel,
                onTap: (reveal) => onTap(idx, reveal),
                onSecondary: (pos) => onSecondary(idx, pos),
                onAction: (a) => onAction(idx, a),
                terms: s.find.answer.terms,
              );
              return Appear(
                key: ValueKey((s.find.revealSerial, rows[idx].id)),
                delay: Appear.stagger(i),
                child: guess ? BestGuessCard(reason: best.reason, selected: sel, child: tile) : tile,
              );
            },
          ),
        ),
      ),
    );
  }
}

/// The detail view below 1100 px: a frosted sheet sliding in from the right over the results (Space, "Details").
class _DetailSheet extends StatelessWidget {
  const _DetailSheet({required this.open, required this.onClose, required this.child});
  final bool open;
  final VoidCallback onClose;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final d = NbMotion.of(context, const Duration(milliseconds: 220));
    return IgnorePointer(
      ignoring: !open,
      child: Stack(
        children: [
          Positioned.fill(
            child: GestureDetector(
              onTap: onClose,
              child: AnimatedOpacity(
                opacity: open ? 1 : 0,
                duration: d,
                child: const ColoredBox(color: Color(0x33000000)),
              ),
            ),
          ),
          Positioned(
            top: 4,
            right: NbSpace.x4,
            bottom: NbSpace.x4,
            child: LayoutBuilder(
              builder: (context, box) => AnimatedSlide(
                offset: open ? Offset.zero : const Offset(1.1, 0),
                duration: d,
                curve: const SpringCurve(damping: .82),
                // built only while open: nothing hidden behind the results
                child: SizedBox(
                  width: 420.0.clamp(0, MediaQuery.sizeOf(context).width - 140).toDouble(),
                  child: open ? child : null,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Under the box: recent searches while it is empty, the filters the words mean while typing (Tab takes one).
class _Suggestions extends StatelessWidget {
  const _Suggestions({required this.box, required this.onAccept, required this.onRecent});
  final TextEditingController box;
  final ValueChanged<TypedFilter> onAccept;
  final ValueChanged<String> onRecent;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final recent = s.find.recent;
    return ListenableBuilder(
      listenable: Listenable.merge([box, ?recent]),
      builder: (context, _) {
        final text = box.text;
        final List<Widget> chips;
        if (text.trim().isEmpty) {
          final items = recent?.items ?? const <String>[];
          if (items.isEmpty) return const SizedBox.shrink();
          chips = [
            Text('Recent', style: NbType.text(NbSize.small, c.dim, weight: FontWeight.w600)),
            for (final r in items) NbChipButton(r, onTap: () => onRecent(r), icon: NbGlyph.search),
            NbChipButton(
              'Clear',
              dashed: true,
              onTap: () => unawaited(recent!.clear()),
              tooltip: 'Clear your search history',
            ),
          ];
        } else {
          final sug = suggestFilters(text);
          if (sug.isEmpty) return const SizedBox.shrink();
          chips = [
            for (var i = 0; i < sug.length; i++)
              NbChipButton(
                i == 0 ? '${sug[i].label}   Tab' : sug[i].label,
                on: true,
                icon: NbGlyph.plus,
                onTap: () => onAccept(sug[i]),
                tooltip: 'Use it as a filter',
              ),
          ];
        }
        return Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: chips),
        );
      },
    );
  }
}

/// How the question was read: a chip, removable when this UI knows which words it came from.
class _Understood extends StatelessWidget {
  const _Understood(this.text, {required this.onRemove});
  final String text;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: EdgeInsets.fromLTRB(10, 3, onRemove == null ? 10 : 4, 3),
      decoration: BoxDecoration(
        color: c.orangeA(.07),
        border: Border.all(color: c.orangeA(.5)),
        borderRadius: NbRadius.pillAll,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(text, style: NbType.text(NbSize.small, c.orange, weight: FontWeight.w600, height: 1.3)),
          if (onRemove != null)
            Pressable(
              onTap: onRemove,
              semanticLabel: 'Remove $text',
              tooltip: 'Search without this',
              canRequestFocus: false,
              ringRadius: NbRadius.pillAll,
              builder: (context, p) => Padding(
                padding: const EdgeInsets.only(left: 4),
                child: NbIcon(NbGlyph.close, size: 12, color: p.lit ? c.text : c.orange),
              ),
            ),
        ],
      ),
    );
  }
}

/// Nothing found: say so plainly, and offer the ways on.
class _NoResults extends StatelessWidget {
  const _NoResults({
    super.key,
    required this.words,
    required this.hasFilters,
    required this.onClearFilters,
    required this.onWords,
  });
  final String words;
  final bool hasFilters;
  final VoidCallback onClearFilters;
  final ValueChanged<String> onWords;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final parts = words.trim().split(RegExp(r'\s+'));
    final fewer = parts.length > 1 ? parts.sublist(0, parts.length - 1).join(' ') : '';
    return Align(
      alignment: Alignment.topLeft,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(NbSpace.gutter, NbSpace.x2, NbSpace.gutter, 0),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: Glass(
            radius: NbRadius.card,
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text.rich(
                  TextSpan(
                    children: [
                      const TextSpan(text: 'Nothing matches '),
                      TextSpan(
                        text: words.trim(),
                        style: NbType.text(16, c.text, weight: FontWeight.w600),
                      ),
                    ],
                  ),
                  style: NbType.text(14, c.muted),
                ),
                const SizedBox(height: 8),
                Text(
                  'Try fewer or other words, a different kind, or search without the filters.',
                  style: NbType.text(13.5, c.dim, height: 1.5),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    if (hasFilters) NbButton('Search without filters', onPressed: onClearFilters),
                    if (fewer.isNotEmpty)
                      NbButton('Search “$fewer”', kind: NbButtonKind.ghost, onPressed: () => onWords(fewer)),
                    NbButton(
                      'Search names only: “${parts.first}”',
                      kind: NbButtonKind.quiet,
                      onPressed: () => onWords(parts.first),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A category with nothing in it yet (or nothing for its filters): says so, with its narrower searches.
class _EmptyCategory extends StatelessWidget {
  const _EmptyCategory({super.key, required this.category, required this.current, required this.onTile});
  final SearchCategory category;
  final SearchFilters current;
  final ValueChanged<SearchFilters> onTile;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Align(
      alignment: Alignment.topLeft,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CategoryTiles(tiles: category.tiles, current: current, onTile: onTile),
            const SizedBox(height: NbSpace.x4),
            Text(
              current.isLauncher
                  ? 'Type the name of a setting or an app.'
                  : category == SearchCategory.all
                  ? 'Nothing matches these filters.'
                  : 'Nothing here yet in ${category.label}. Files show up as they are indexed.',
              style: NbType.text(13, c.muted, weight: FontWeight.w600),
            ),
            const SizedBox(height: 4),
            Text('Try another tile, or type a few words.', style: NbType.text(12, c.dim)),
          ],
        ),
      ),
    );
  }
}

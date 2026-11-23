/// The app: the dark theme (the only one since 0.8.5; the old theme setting is ignored), glass when Windows takes
/// it and its Transparency effects switch is on, the controllers, and either the main window (splash → first-run
/// welcome → rail + Search / Index / Settings) or the quick find bar.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../engine/engine_api.dart';
import '../features/bar/bar_window.dart';
import '../features/shell/shell.dart';
import '../platform/demo.dart';
import '../platform/window.dart';
import '../state/notifications_controller.dart';
import '../state/recent_searches.dart';
import '../state/search_controller.dart';
import '../state/settings_controller.dart';
import '../state/status_controller.dart';
import '../state/toast_controller.dart';
import 'scope.dart';
import 'theme/colors.dart';
import 'theme/theme.dart';

enum AppMode { main, bar }

const appVersion = '0.9.3';

class NobadFindApp extends StatefulWidget {
  const NobadFindApp({
    super.key,
    required this.engine,
    this.mode = AppMode.main,
    this.window = const NoWindow(),
    this.demo,
    this.splash = true,
    this.reduceMotion,
    this.startPage = AppTab.search,
    this.recent,
  });

  /// Recent searches from the engine's search history (main.dart gives one to the main window; tests none, or
  /// their own).
  final RecentSearches? recent;

  /// The page the window opens on (`--page`).
  final AppTab startPage;
  final EngineApi engine;

  /// Animations off: Windows' "Animation effects" switch (read at start and when the window comes back), or
  /// forced by tests.
  final bool? reduceMotion;
  final AppMode mode;
  final WindowControl window;
  final Demo? demo;

  /// Show the splash while the engine connects (tests turn it off).
  final bool splash;

  @override
  State<NobadFindApp> createState() => _NobadFindAppState();
}

class _NobadFindAppState extends State<NobadFindApp> {
  late final toasts = ToastController(engine: widget.engine);
  late final settings = SettingsController(widget.engine, toasts: toasts);
  late final status = StatusController(widget.engine)
    ..onUpdateFound = (u) => toasts.show('NOBAD Find ${u.latest} is available. Settings > About installs it.');
  late final find = FindController(widget.engine, toasts: toasts, recent: widget.recent);
  late final nav = AppNav(widget.startPage);
  late final notifications = widget.mode == AppMode.main ? NotificationsController(widget.engine) : null;
  bool _glass = false;
  (bool, bool, bool)? _applied;
  late bool _motionOff = widget.reduceMotion ?? systemAnimationsOff();

  /// On screen (not hidden or minimized): animations only run while it is.
  bool _onScreen = true;
  late final AppLifecycleListener _life;

  String get _windowName => widget.mode == AppMode.bar ? 'bar' : 'main';

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onStateChange: _lifecycle);
    settings.addListener(_restyle);
    settings.addListener(_historySetting);
    unawaited(settings.load());
    widget.engine.link.addListener(_relink);
    WidgetsBinding.instance.addPostFrameCallback((_) => _restyle());
  }

  bool? _historyOn;

  /// "Remember my searches" switched: off shows no recent searches at once (the engine deletes them), on asks.
  void _historySetting() {
    final r = widget.recent;
    if (r == null || !settings.loaded) return;
    final on = settings.settings.flag('search_history');
    if (on == _historyOn) return;
    final was = _historyOn;
    _historyOn = on;
    if (!on) {
      r.off();
    } else if (was != null) {
      unawaited(r.refresh());
    }
  }

  /// Settings come back with the engine (it may start after the window).
  void _relink() {
    if (widget.engine.link.value == Link.connected) unawaited(settings.load());
  }

  /// Windows' Transparency effects switch (read at start and when the window comes back): off keeps it solid.
  late bool _transparencyOff = systemTransparencyOff();

  void _restyle() {
    final s = settings.settings;
    final glass = s.glass && !_transparencyOff;
    // the style (Classic or Minimal ice) picks Mica or Acrylic, so a change re-applies the look at once
    final want = (s.dark, glass, s.ice);
    if (want == _applied) return;
    _applied = want;
    final base = s.dark ? NbColors.dark : NbColors.light;
    final took = widget.window.look(dark: s.dark, glass: glass, canvasRgb: base.bg.toARGB32() & 0xFFFFFF, ice: s.ice);
    setState(() => _glass = took);
  }

  /// Minimized or hidden: tell the engine (it stops indexing when the main window goes, unless asked to keep on)
  /// and stop every animation; back on screen: the same the other way, and look at the animation setting again.
  void _lifecycle(AppLifecycleState state) {
    final on = state == AppLifecycleState.resumed || state == AppLifecycleState.inactive;
    if (on == _onScreen) return;
    if (widget.mode == AppMode.main) {
      final f = on ? widget.engine.uiShown(_windowName) : widget.engine.uiHidden(_windowName);
      unawaited(f.catchError((Object _) {}));
    }
    setState(() {
      _onScreen = on;
      if (on && widget.reduceMotion == null) _motionOff = systemAnimationsOff();
    });
    if (on) {
      _transparencyOff = systemTransparencyOff();
      _restyle();
    }
  }

  @override
  void dispose() {
    _life.dispose();
    settings.removeListener(_restyle);
    settings.removeListener(_historySetting);
    widget.engine.link.removeListener(_relink);
    find.dispose();
    status.dispose();
    notifications?.dispose();
    settings.dispose();
    toasts.dispose();
    nav.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: settings,
      builder: (context, _) {
        final c = (settings.settings.dark ? NbColors.dark : NbColors.light).withGlass(
          _glass,
          iceStyle: settings.settings.ice,
        );
        final bar = widget.mode == AppMode.bar;
        return MaterialApp(
          title: bar ? 'NOBAD Find bar' : 'NOBAD Find',
          debugShowCheckedModeBanner: false,
          theme: nbTheme(c),
          themeAnimationDuration: const Duration(milliseconds: 180),
          color: c.orange,
          navigatorKey: appNavigator,
          builder: (context, child) => RepaintBoundary(
            key: shotBoundary,
            child: AppScope(
              engine: widget.engine,
              find: find,
              status: status,
              settings: settings,
              toasts: toasts,
              nav: nav,
              window: widget.window,
              version: appVersion,
              notifications: notifications,
              child: MediaQuery(
                data: MediaQuery.of(context).copyWith(disableAnimations: _motionOff),
                child: TickerMode(
                  enabled: _onScreen,
                  child: DefaultTextStyle(
                    style: TextStyle(color: c.text, fontSize: 14),
                    child: child!,
                  ),
                ),
              ),
            ),
          ),
          home: Material(
            type: MaterialType.transparency,
            child: bar
                ? BarWindow(engine: widget.engine, window: widget.window, demo: widget.demo)
                : _Keys(
                    nav: nav,
                    window: widget.window,
                    engine: widget.engine,
                    child: Shell(splash: widget.splash, demo: widget.demo),
                  ),
          ),
        );
      },
    );
  }
}

/// Window-wide keys: Ctrl+1 / Ctrl+2 / Ctrl+3 for Search, Index, Settings; Esc on Index and Settings hides the
/// window (0.7.0). Holds the keyboard focus when a page has nothing focused, so the keys always work.
class _Keys extends StatefulWidget {
  const _Keys({required this.nav, required this.window, required this.engine, required this.child});
  final AppNav nav;
  final WindowControl window;
  final EngineApi engine;
  final Widget child;

  @override
  State<_Keys> createState() => _KeysState();
}

class _KeysState extends State<_Keys> {
  final _focus = FocusNode(debugLabel: 'window keys');

  @override
  void initState() {
    super.initState();
    widget.nav.addListener(_moved);
  }

  /// Search focuses its own box; the other pages start with the window keys focused.
  void _moved() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (mounted && widget.nav.tab != AppTab.search) _focus.requestFocus();
  });

  @override
  void dispose() {
    widget.nav.removeListener(_moved);
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CallbackShortcuts(
    bindings: {
      const SingleActivator(LogicalKeyboardKey.digit1, control: true): () => widget.nav.go(AppTab.search),
      const SingleActivator(LogicalKeyboardKey.digit2, control: true): () => widget.nav.go(AppTab.indexing),
      const SingleActivator(LogicalKeyboardKey.digit3, control: true): () => widget.nav.go(AppTab.settings),
      const SingleActivator(LogicalKeyboardKey.escape): () {
        if (widget.nav.tab == AppTab.search) return;
        widget.window.hide();
        unawaited(widget.engine.uiHidden('main').catchError((Object _) {}));
      },
    },
    child: Focus(focusNode: _focus, child: widget.child),
  );
}

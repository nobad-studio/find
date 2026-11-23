/// The main window: the rail on the left, the open page, the toast, and over them the splash (while the engine
/// connects) and the first-run welcome. After the welcome and the first scan, the first-run models window once.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/tokens.dart';
import '../../engine/engine_api.dart';
import '../../engine/events.dart';
import '../../engine/models/status.dart';
import '../../platform/demo.dart';
import '../../widgets/glass.dart';
import '../../widgets/panels.dart';
import '../indexing/indexing_screen.dart';
import '../search/search_screen.dart';
import '../settings/settings_screen.dart';
import '../setup/setup_dialog.dart';
import '../splash/splash.dart';
import '../welcome/welcome.dart';
import 'sidebar.dart';

class Shell extends StatefulWidget {
  const Shell({super.key, this.splash = true, this.demo});
  final bool splash;
  final Demo? demo;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  StreamSubscription<EngineEvent>? _shows;
  bool _splashDone = false;
  AppScope? _scope;

  /// The first-run models window was asked for this session (the engine decides whether it shows).
  bool _offerAsked = false;

  /// After the welcome, once the first scan is done (the status says the walk is over): ask the engine whether to
  /// show the first-run models window, and show it. Once a session; an engine without it (-32601) is left alone.
  Future<void> _maybeOffer([EngineStatus? st]) async {
    final s = _scope;
    if (s == null || _offerAsked || !mounted) return;
    final phase = (st ?? s.engine.lastStatus)?.phase ?? '';
    if (!s.settings.loaded || !s.settings.settings.flag('welcome_seen') || s.engine.link.value != Link.connected) {
      return;
    }
    if (const {'', 'starting', 'names', 'error'}.contains(phase)) return;
    _offerAsked = true;
    try {
      final offer = await s.engine.setupOffer();
      if (!offer.walked) _offerAsked = false; // the walk's count isn't in yet: ask again on a later status
      final ctx = appNavigator.currentContext;
      if (offer.show && mounted && ctx != null && ctx.mounted) await showSetupDialog(ctx, offer);
    } on Object {
      // an older engine, or the pipe went away: nothing to show
    }
  }

  void _settingsChanged() => unawaited(_maybeOffer());

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_scope != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _scope = s;
    _shows?.cancel();
    _shows = s.engine.events.listen((e) {
      // the engine's tray menu: open the window on a page
      if (e is ShowEvent && (e.what == 'settings' || e.what == 'index')) {
        s.window.front();
        s.nav.go(e.what == 'settings' ? AppTab.settings : AppTab.indexing);
        unawaited(s.engine.uiShown('main').catchError((Object _) {}));
      }
      if (e is ShowEvent && e.what == 'main') {
        final t = e.text;
        if (t != null) s.find.handOver(t); // kept until the search screen takes it
        s.window.front();
        unawaited(s.engine.uiShown('main').catchError((Object _) {})); // the engine starts idle until a window shows
        s.nav.go(AppTab.search);
        unawaited(s.find.loadHere());
      }
      if (e is QuittingEvent) s.window.close(); // the engine is ending: this window goes with it
      if (e is StatusEvent) unawaited(_maybeOffer(e.status));
    });
    s.settings.addListener(_settingsChanged);
    _splashDone = !widget.splash || s.engine.link.value != Link.connecting;
    if (!_splashDone) s.engine.link.addListener(_linkChanged);
    unawaited(s.find.loadHere());
    widget.demo?.start(s);
  }

  void _linkChanged() {
    final s = _scope!;
    if (s.engine.link.value == Link.connecting) return;
    s.engine.link.removeListener(_linkChanged);
    if (mounted) setState(() => _splashDone = true);
  }

  @override
  void dispose() {
    _shows?.cancel();
    _scope?.engine.link.removeListener(_linkChanged);
    _scope?.settings.removeListener(_settingsChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return ColoredBox(
      color: const Color(0x00000000),
      child: Stack(
        children: [
          const Positioned.fill(child: Backdrop()), // painted once; Windows' Acrylic shows through it
          Positioned.fill(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Sidebar(),
                Expanded(
                  child: ListenableBuilder(
                    listenable: s.nav,
                    builder: (context, _) => AnimatedSwitcher(
                      duration: NbMotion.of(context, NbMotion.base),
                      switchInCurve: NbMotion.curve,
                      transitionBuilder: (child, a) => FadeTransition(
                        opacity: a,
                        child: SlideTransition(
                          position: Tween(begin: const Offset(0, .012), end: Offset.zero).animate(a),
                          child: child,
                        ),
                      ),
                      child: switch (s.nav.tab) {
                        AppTab.search => const SearchScreen(key: ValueKey('search')),
                        AppTab.indexing => const IndexingScreen(key: ValueKey('index')),
                        AppTab.settings => const SettingsScreen(key: ValueKey('settings')),
                      },
                    ),
                  ),
                ),
              ],
            ),
          ),
          Positioned(
            left: Sidebar.room,
            right: 0,
            bottom: 52,
            child: Center(child: ToastHost(toasts: s.toasts)),
          ),
          ListenableBuilder(
            listenable: s.settings,
            builder: (context, _) => s.settings.loaded && !s.settings.settings.flag('welcome_seen')
                ? const Positioned.fill(child: Welcome())
                : const SizedBox.shrink(),
          ),
          Positioned.fill(
            child: IgnorePointer(
              ignoring: _splashDone,
              child: AnimatedSwitcher(
                duration: NbMotion.of(context, NbMotion.slow),
                child: _splashDone ? const SizedBox.expand() : const Splash(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

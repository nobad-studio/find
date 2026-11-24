/// NOBAD Find UI. No arguments: the main window. `--bar`: the quick find bar.
/// Talks only to the NOBAD Find engine (`python -m nobadfind --engine`) over the user's private named pipe.
/// NOBAD_FIND_FAKE_ENGINE=1 runs against the in-memory FakeEngine instead (screenshots, design work).
library;

import 'dart:io' show Platform;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'app/scope.dart';
import 'state/recent_searches.dart';
import 'app/theme/typography.dart';
import 'engine/engine_api.dart';
import 'engine/events.dart';
import 'engine/fake_engine.dart';
import 'engine/models/graphics.dart';
import 'engine/pipe_client.dart';
import 'engine/rpc.dart';
import 'engine/wiring.dart';
import 'platform/demo.dart';
import 'platform/timing.dart';
import 'platform/window.dart';
import 'widgets/glass.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await loadDisplayFont(); // one 170 KB file from C:\Windows\Fonts, a millisecond
  // Skia keeps up to 256 MB of GPU resources by default; this UI redraws text and a few paths, so a small cache is
  // plenty and keeps the window's memory down (docs/measurements.md).
  final cacheMb = int.tryParse(Platform.environment['NOBAD_FIND_SKIA_CACHE_MB'] ?? '') ?? 12;
  Win32Window.shownCacheBytes = cacheMb << 20;
  SystemChannels.skia.invokeMethod<void>('Skia.setResourceCacheMaxBytes', cacheMb << 20);
  final mode = args.contains('--bar') ? AppMode.bar : AppMode.main;
  // recent searches come from the engine's encrypted history: the plain-text copy older UIs kept goes
  if (mode == AppMode.main) await RecentSearches.removeOldFile();
  Win32Window.acrylic = mode == AppMode.bar;
  Glass.noBlur = Platform.environment['NOBAD_FIND_NO_BLUR'] == '1';
  final EngineApi engine;
  if (Platform.environment['NOBAD_FIND_FAKE_ENGINE'] == '1') {
    engine = FakeEngine(
      files: demoFiles(),
      live: true,
      // the made-up PC's graphics: discrete | integrated (default, like the reference PC) | none
      gpu: GraphicsKind.values.asNameMap()[Platform.environment['NOBAD_FIND_FAKE_GPU']] ?? GraphicsKind.integrated,
      settings: {
        'welcome_seen': Platform.environment['NOBAD_FIND_FAKE_WELCOME'] == '0',
        if (Platform.environment['NOBAD_FIND_FAKE_GLASS'] == '0') 'glass': false,
        // screenshots of the Minimal ice style (the fake engine starts in Classic, like a real one)
        if (const {'ice', 'nocturne'}.contains(Platform.environment['NOBAD_FIND_FAKE_STYLE']))
          'theme_style': Platform.environment['NOBAD_FIND_FAKE_STYLE']!,
      },
    );
  } else {
    final pipe = EngineClient(
      PipeTransport.connect,
      subscribeTo: mode == AppMode.bar ? EngineEvent.bar : EngineEvent.mainWindow,
      window: mode == AppMode.bar ? 'bar' : 'main',
    )..start();
    engine = PipeEngine(pipe, beforeDialog: allowSetForeground); // never the fake: offline is shown as offline
  }
  runApp(
    NobadFindApp(
      engine: engine,
      mode: mode,
      window: Win32Window.create(),
      demo: Demo.fromEnvironment(),
      startPage: AppPage.parse(args),
      recent: mode == AppMode.main ? RecentSearches(engine) : null,
    ),
  );
  startFrameLog();
  WidgetsBinding.instance.waitUntilFirstFrameRasterized.then((_) => recordTiming('first-frame ${mode.name}'));
}

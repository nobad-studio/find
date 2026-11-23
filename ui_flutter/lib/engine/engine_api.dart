/// Everything the screens can ask the engine, typed after contract (protocol 1). Controllers depend on
/// this interface only.
///
/// Implementations:
/// - [PipeEngine] (wiring.dart): the app's engine, over the pipe only. Offline: [EngineOffline]; a method the
///   engine doesn't serve: [RpcException] -32601. Never made-up answers.
/// - [FakeEngine] (fake_engine.dart): an in-memory engine with the contract's shapes, only for tests, goldens and
///   the explicit `NOBAD_FIND_FAKE_ENGINE=1` demo.
///
/// Files are always named by result id, never by a path from the UI (the engine looks the path up).
library;

import 'package:flutter/foundation.dart';

import 'events.dart';
import 'models/models_info.dart';
import 'models/notification.dart';
import 'models/scope_info.dart';
import 'models/setup_offer.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';
import 'models/update.dart';
import 'models/vision.dart';

export 'models/notification.dart';
export 'models/setup_offer.dart';
export 'models/settings.dart' show ActionResult, FolderPick, maxTextLength;
export 'models/vision.dart';

/// untrusted: something answers on the engine's pipe that isn't NOBAD Find's engine (pipe_client.dart checks the
/// process at the other end); this window sends it nothing and keeps trying for the real one.
enum Link { connecting, connected, offline, incompatible, untrusted }

/// What the window says while [Link.untrusted].
const untrustedLine =
    "Another program is answering in place of NOBAD Find's engine, so this window won't talk to it. "
    'Quit NOBAD Find and start it again; if this stays, restart the PC.';

/// The pipe is served by a process that isn't NOBAD Find's engine (another account, a sandboxed or low-integrity
/// process, another program): nothing is sent to it. [reason] is for the log.
class EngineUntrusted implements Exception {
  const EngineUntrusted(this.reason);
  final String reason;
  @override
  String toString() => "Not connecting: the pipe's server isn't NOBAD Find's engine ($reason).";
}

/// The engine answered with a JSON-RPC error; [message] is plain language for the user.
class RpcException implements Exception {
  const RpcException(this.code, this.message);
  final int code;
  final String message;
  @override
  String toString() => 'RpcException($code, $message)';
}

/// No engine to talk to (not running, or the connection dropped).
class EngineOffline implements Exception {
  const EngineOffline();
}

abstract class EngineApi {
  ValueListenable<Link> get link;
  Stream<EngineEvent> get events;

  /// The newest short status seen (from `status` or its event), or null before the first one.
  EngineStatus? get lastStatus;

  // ---- search and results ----
  /// [channel]: "main" (what the user typed) or "home" (Home's recently changed list). The engine cancels a stale
  /// search only within the same connection and channel; a cancelled one answers `cancelled: true` (ignore it).
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none, String channel = 'main'});
  Future<ActionResult> open(int id);
  Future<ActionResult> reveal(int id);

  /// A small preview (PNG/JPEG/BMP bytes) from Windows' thumbnail cache, or null.
  Future<Uint8List?> thumbnail(int id);
  Future<String> pathOf(int id);

  /// Remove from the index and keep it out (adds it to Never index).
  Future<ActionResult> forget(int id);

  /// The File Explorer folder the hotkey was pressed in, or ''.
  Future<String> hereFolder();

  /// The bar's Alt+Enter: the engine brings the main window up with [text] in its box.
  Future<void> toMain(String text);

  // ---- 0.8.5 smart search: autocomplete and the user's own search history (an older engine: no suggestions) ----
  /// Suggestions for what's typed so far: past questions, names, phrases search understands; [channel] "bar"
  /// gets at most 5. Never throws for an engine that doesn't serve it (no suggestions then).
  Future<Suggestions> suggest(String text, {String channel = 'main'});

  /// A question was used: kept for autocomplete while the `search_history` setting is on. True if it was kept.
  Future<bool> historyAdd(String text);

  /// The x on a history suggestion.
  Future<ActionResult> historyForget(String text);

  /// Settings > Privacy: "Clear search history".
  Future<ActionResult> historyClear();

  // ---- status and the governor ----
  Future<EngineStatus> status();

  /// Everything the Indexing page shows (`status_full`).
  Future<EngineStatus> statusFull();

  /// The Indexing page is open: get `status_full` events (they cost the engine work, so only then).
  Future<void> watchDetails(bool on);
  Future<ActionResult> pauseFor(Duration d);
  Future<ActionResult> resume();
  Future<List<LearnedApp>> learnedApps();

  /// One app, or every app when [exe] is null.
  Future<ActionResult> resetLearned([String? exe]);
  Future<Hardware?> hardware();

  /// Settings > Performance (1.2.0 engines): every override with what "auto" would pick now and why. An older
  /// engine answers -32601.
  Future<PerformanceState> performanceState();

  /// "Reset to safe defaults" (1.2.0): the goal to balanced, every override to auto. Only after the user's yes.
  Future<ResetResult> resetSafeDefaults();

  /// Settings > Privacy (1.2.0 engines): each browser profile read, its items and its last problem
  /// (`browser_data_state`). An older engine answers -32601.
  Future<BrowserDataState> browserDataState();

  /// "Clear browser data" (`browser_clear`, 1.2.0): every browser item out of the index. Only after the user's yes.
  Future<ActionResult> browserClear();

  // ---- settings and the index ----
  Future<Settings> getSettings();

  /// [consent]: `appFilesConsent` after the user's yes in the confirm dialog; the engine turns `secret_app_files`
  /// on only with it; `browserConsent` likewise for making `browser_data` read more.
  Future<SettingsChange> setSettings(Map<String, Object?> changes, {String? consent});

  /// Whether each global hotkey is registered and working now (`hotkey_state`).
  Future<HotkeyState> hotkeyState();

  /// Would [spec] work for [which] ('hotkey' or 'bar_hotkey')? Asked before saving (`hotkey_probe`).
  Future<HotkeyProbe> hotkeyProbe(String which, String spec);

  /// Windows' folder dialog, shown by the engine: path '' if cancelled; busy if one is already open.
  Future<FolderPick> pickFolder();
  Future<ActionResult> rescan();

  /// The engine only wipes with "DELETE".
  Future<ActionResult> wipe(String confirm);

  // ---- models (progress comes as download events) ----
  /// [model] is "meaning" or "photo".
  Future<ActionResult> downloadModel(String model);

  // ---- Windows Search ----
  Future<WsearchState> wsearchState();
  Future<ActionResult> useInsteadOfWindowsSearch(bool on);

  // ---- the window and quitting ----
  /// [window] is "main" or "bar".
  Future<void> uiShown(String window);
  Future<void> uiHidden(String window);

  /// End NOBAD Find completely (the engine sends `quitting`, then closes).
  Future<ActionResult> quit();

  // ---- 0.8: models and Open with (an engine that doesn't list them answers -32601: "needs a newer engine") ----
  /// This PC, the recommended tier, and every model with its facts.
  Future<ModelsInfo> models();

  /// Which models this PC can run RIGHT NOW (`capability_state`, 2026-11-21 engines): free memory, commit, graphics
  /// memory, load and battery. An older engine answers -32601.
  Future<CapabilityState> capabilityState();

  /// Use [id] for [feature] (it may need a download first).
  Future<ModelUse> modelUse(String feature, String id);

  /// Download [id]. Only call after the consent dialog said yes: it sends the consent word.
  Future<ActionResult> modelDownload(String id);
  Future<ActionResult> modelRemove(String id);

  /// Open the folder model [id] is downloaded to in File Explorer (`model_folder`).
  Future<ActionResult> modelFolder(String id);

  /// Open a Windows Settings page, tool or app a search offered (`run_action`, by its id).
  Future<ActionResult> runAction(String id);

  // ---- in-app updates (0.9.0) ----
  Future<UpdateState> updateState();

  /// Look for a newer version now; the `update` event says how it went.
  Future<ActionResult> updateCheck();

  /// Download, check and install the newer version (the consent word goes with the call).
  Future<ActionResult> updateInstall();
  Future<AutoConfig> autoConfigure();

  // ---- the first-run models window (1.2.0; an older engine: -32601) ----
  /// What to offer this PC after the first scan, and whether to show it now (`setup_offer`).
  Future<SetupOffer> setupOffer();

  /// The window's Download, which is the consent: the consent word goes with exactly [models] (`setup_accept`).
  Future<SetupAccept> setupAccept(List<String> models);

  /// The window's Later: one reminder ([remind]; Details sends false), then it is on Settings > Models
  /// (`setup_later`).
  Future<ActionResult> setupLater({bool remind = true});

  /// "English first", "Many languages" or "Hindi + English": changes the recommendation only.
  Future<ActionResult> modelLanguage(String focus);

  // ---- what is indexed, and the turbo index (an older engine: -32601) ----
  Future<ScopeInfo> scopeInfo();
  Future<TurboState> turboState();

  /// On: Windows asks for administrator permission once if the helper isn't set up (no time limit); after that it
  /// starts with no prompt. Off: the helper ends and Windows asks once to remove it.
  Future<TurboSet> turboSet(bool on);

  /// The helper: `update` (Windows asks once) or `remove` (turbo off, one prompt).
  Future<TurboSet> turboHelper(String action);

  /// Windows' "Open with" dialog for the result.
  Future<ActionResult> openWith(int id);

  // ---- talk about a photo (1.1; an older engine: -32601). Photos by result id; the answer comes as VisionEvents,
  // after the reply that names its job. One job at a time: a new question cancels the old one. ----
  Future<VisionState> visionState();
  Future<VisionAnswer> visionDescribe(int fileId);

  /// [more]: run the model even when the text read from the photo answered a question about writing.
  Future<VisionAnswer> visionAsk(int fileId, String question, {bool deeper = false, bool more = false});
  Future<VisionAnswer> visionCompare(int a, int b, {String? question});
  Future<VisionAnswer> visionCancel();

  /// Keep [text] as the photo's description so searches find it ('' forgets it); [VisionAnswer.kept] says which.
  Future<VisionAnswer> visionKeep(int fileId, String text);

  // ---- notifications: the bell (an older engine has none: an empty list, never an error) ----
  /// Everything kept, newest first, with the unread count.
  Future<NotificationList> notificationsList();

  /// Mark [ids] read, or all of them; the engine's unread count after it.
  Future<int> notificationsRead({List<int> ids = const [], bool all = false});

  /// The panel's Clear: every notification goes.
  Future<ActionResult> notificationsClear();

  void dispose();
}

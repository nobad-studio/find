/// What graphics this PC has, in one word, for every place that shows it (task D2): a graphics card with its own
/// memory, built-in graphics that share the PC's memory (Intel Iris Xe and the like), or none. Built-in graphics
/// report a small dedicated carve-out (Iris Xe: 128 MB); that is not video memory and is never called so.
library;

import 'format.dart';
import 'settings.dart';

enum GraphicsKind { discrete, integrated, none }

/// Less dedicated memory than this: built-in graphics (the engine's `hardware.INTEGRATED_MB`).
const integratedMb = 512;

/// The backends that need a graphics adapter.
const graphicsBackends = {'directml', 'vulkan', 'cuda'};

class Graphics {
  const Graphics(this.kind, {this.name = '', this.dedicatedMb = 0});
  final GraphicsKind kind;

  /// The adapter's name as Windows gives it ('' for none).
  final String name;

  /// A graphics card's own memory (0 unless [kind] is discrete).
  final int dedicatedMb;

  bool get hasCard => kind == GraphicsKind.discrete;

  /// "NVIDIA GeForce RTX 3060", "Intel(R) Iris(R) Xe Graphics", "No graphics card".
  String get title => switch (kind) {
    GraphicsKind.none => 'No graphics card',
    _ when name.isNotEmpty => name,
    GraphicsKind.discrete => 'Graphics card',
    GraphicsKind.integrated => 'Built-in graphics',
  };

  /// "6 GB video memory", "built-in graphics, shares memory", "processor only".
  String get detail => switch (kind) {
    GraphicsKind.discrete => '${gb(dedicatedMb / 1024)} video memory',
    GraphicsKind.integrated => 'built-in graphics, shares memory',
    GraphicsKind.none => 'processor only',
  };

  String get line => '$title · $detail';

  /// Whether [backend] may be offered on this PC, given the backends installed for its family ([installed] empty:
  /// an older engine that doesn't list them, so the engine's own options stand).
  bool offers(String backend, List<String> installed) {
    if (!graphicsBackends.contains(backend)) return true; // auto, cpu, on/off, classes
    if (kind == GraphicsKind.none) return false;
    return installed.isEmpty || installed.contains(backend);
  }
}

/// The graphics of [hw]: any non-built-in adapter with at least [integratedMb] of its own memory makes it a
/// graphics card (the biggest one is named, also on hybrid laptops); only built-in adapters make it built-in
/// graphics. An older engine without `gpus`: its one `gpu` / `vram_gb`, under [integratedMb] built-in.
Graphics graphicsOf(Hardware hw) {
  if (hw.gpus.isNotEmpty) {
    final cards = [
      for (final g in hw.gpus)
        if (!g.integrated && g.dedicatedMb >= integratedMb) g,
    ]..sort((a, b) => b.dedicatedMb.compareTo(a.dedicatedMb));
    if (cards.isNotEmpty) {
      return Graphics(GraphicsKind.discrete, name: cards.first.name.trim(), dedicatedMb: cards.first.dedicatedMb);
    }
    final built = hw.gpus.where((g) => g.integrated).firstOrNull ?? hw.gpus.first;
    return Graphics(GraphicsKind.integrated, name: built.name.trim());
  }
  final name = hw.gpu.trim();
  if (name.isEmpty) return const Graphics(GraphicsKind.none);
  final mb = (hw.vramGb * 1024).round();
  return mb >= integratedMb
      ? Graphics(GraphicsKind.discrete, name: name, dedicatedMb: mb)
      : Graphics(GraphicsKind.integrated, name: name);
}

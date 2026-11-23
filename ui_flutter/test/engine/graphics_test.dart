import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/graphics.dart';
import 'package:nobad_find/engine/models/settings.dart';

const irisXe = GpuInfo(
  vendor: 'intel',
  name: 'Intel(R) Iris(R) Xe Graphics',
  dedicatedMb: 128,
  sharedMb: 8038,
  integrated: true,
);
const rtx = GpuInfo(vendor: 'nvidia', name: 'NVIDIA GeForce RTX 3060 Laptop GPU', dedicatedMb: 6144, sharedMb: 8038);

void main() {
  test('a hybrid laptop (built-in graphics and a card) is a graphics card, named with its own memory', () {
    final g = graphicsOf(const Hardware(gpu: 'NVIDIA GeForce RTX 3060 Laptop GPU', vramGb: 6, gpus: [irisXe, rtx]));
    expect(g.kind, GraphicsKind.discrete);
    expect(g.name, 'NVIDIA GeForce RTX 3060 Laptop GPU');
    expect(g.dedicatedMb, 6144);
    expect(g.title, 'NVIDIA GeForce RTX 3060 Laptop GPU');
    expect(g.detail, '6 GB video memory');
    expect(g.line, 'NVIDIA GeForce RTX 3060 Laptop GPU · 6 GB video memory');
    expect(g.hasCard, isTrue);
  });

  test('the biggest card wins when there are two', () {
    const small = GpuInfo(vendor: 'amd', name: 'Radeon RX 6500M', dedicatedMb: 4096);
    final g = graphicsOf(const Hardware(gpus: [small, rtx, irisXe]));
    expect(g.name, rtx.name);
  });

  test('Iris Xe only is built-in graphics: its 128 MB carve-out is never called video memory', () {
    final g = graphicsOf(const Hardware(gpu: 'Intel(R) Iris(R) Xe Graphics', vramGb: 0.1, gpus: [irisXe]));
    expect(g.kind, GraphicsKind.integrated);
    expect(g.name, 'Intel(R) Iris(R) Xe Graphics');
    expect(g.detail, 'built-in graphics, shares memory');
    expect(g.line, 'Intel(R) Iris(R) Xe Graphics · built-in graphics, shares memory');
    expect(g.line, isNot(contains('video memory')));
    expect(g.hasCard, isFalse);
  });

  test('no adapter at all: processor only', () {
    final g = graphicsOf(const Hardware(onnxBackends: ['cpu'], llamacppBackends: ['cpu']));
    expect(g.kind, GraphicsKind.none);
    expect(g.line, 'No graphics card · processor only');
  });

  test('an older engine without gpus: today\'s vram fields, under 512 MB is built-in graphics', () {
    final iris = graphicsOf(const Hardware(gpu: 'Intel(R) Iris(R) Xe Graphics', vramGb: 0.1));
    expect(iris.kind, GraphicsKind.integrated);
    expect(iris.line, isNot(contains('0.1 GB')));
    expect(iris.line, isNot(contains('video memory')));
    final card = graphicsOf(const Hardware(gpu: 'NVIDIA GeForce GTX 1650', vramGb: 4));
    expect(card.kind, GraphicsKind.discrete);
    expect(card.line, 'NVIDIA GeForce GTX 1650 · 4 GB video memory');
    expect(graphicsOf(const Hardware()).kind, GraphicsKind.none);
  });

  test('graphics backends are offered only when this PC has them', () {
    final none = graphicsOf(const Hardware(onnxBackends: ['cpu', 'directml'], llamacppBackends: ['vulkan', 'cpu']));
    // no adapter: DirectML or Vulkan on disk can't use one
    expect(none.offers('directml', const ['cpu', 'directml']), isFalse);
    expect(none.offers('vulkan', const ['vulkan', 'cpu']), isFalse);
    expect(none.offers('cpu', const ['cpu']), isTrue);
    expect(none.offers('auto', const ['cpu']), isTrue);
    final iris = graphicsOf(const Hardware(gpus: [irisXe]));
    expect(iris.offers('vulkan', const ['vulkan', 'cpu']), isTrue); // Vulkan works on built-in graphics
    expect(iris.offers('directml', const ['cpu']), isFalse); // not installed
    expect(iris.offers('cuda', const ['cpu', 'directml']), isFalse);
    expect(iris.offers('directml', const ['cpu', 'directml']), isTrue);
    // an older engine lists no backends: the engine's own options stand
    expect(iris.offers('directml', const []), isTrue);
  });
}

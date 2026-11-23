import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/settings.dart';

const base = {
  'ram_gb': 15.7,
  'cores': 8,
  'threads': 16,
  'avx2': true,
  'avx512_vnni': false,
  'gpu': 'Intel(R) Iris(R) Xe Graphics',
  'vram_gb': 0.1,
  'directml': false,
  'disk_free_gb': 120.5,
  'ssd': true,
};

void main() {
  test('hardware reads every adapter and the backends per family', () {
    final h = Hardware.fromJson({
      ...base,
      'gpus': [
        {'vendor': 'intel', 'name': 'Iris Xe', 'dedicated_mb': 128, 'shared_mb': 8038, 'integrated': true},
        {'vendor': 'nvidia', 'name': 'RTX 3060', 'dedicated_mb': 6144, 'shared_mb': 8000, 'integrated': false},
      ],
      'backends': {
        'onnx': ['cpu', 'directml'],
        'llamacpp': ['vulkan', 'cpu'],
      },
    })!;
    expect(h.gpus.length, 2);
    expect(h.gpus[1].vendor, 'nvidia');
    expect(h.gpus[1].dedicatedMb, 6144);
    expect(h.gpus[1].sharedMb, 8000);
    expect(h.gpus[0].integrated, true);
    expect(h.onnxBackends, ['cpu', 'directml']);
    expect(h.llamacppBackends, ['vulkan', 'cpu']);
  });

  test('hardware from an older engine has no adapters or backends', () {
    final h = Hardware.fromJson(base)!;
    expect(h.cores, 8);
    expect(h.gpus, isEmpty);
    expect(h.onnxBackends, isEmpty);
    expect(h.llamacppBackends, isEmpty);
  });
}

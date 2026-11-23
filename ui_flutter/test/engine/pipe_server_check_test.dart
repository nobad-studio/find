// Security review 2026-11-22 (M1): the window talks only to NOBAD Find's engine, not to whatever took the pipe's
// name first. engineProblem decides from what Windows says about the serving process (faked here).
import 'dart:ffi';
import 'dart:io' show Directory, File, Platform;

import 'package:ffi/ffi.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/pipe_client.dart';

const ui = r'C:\Users\me\AppData\Local\Programs\NOBAD Find\nobad_find.exe';
const engine = r'C:\Users\me\AppData\Local\Programs\NOBAD Find\NobadFind.exe';

ServerProcess proc({
  String image = engine,
  int integrity = integrityMedium,
  bool appContainer = false,
  bool sameUser = true,
}) => ServerProcess(image: image, integrity: integrity, appContainer: appContainer, sameUser: sameUser);

bool installed(String p) => p.toLowerCase() == engine.toLowerCase();
bool fromSource(String p) => false;

void main() {
  test('the installed engine next to this window is accepted', () {
    expect(engineProblem(proc(), uiExe: ui, exists: installed), isNull);
    expect(engineProblem(proc(image: engine.toUpperCase()), uiExe: ui, exists: installed), isNull);
    expect(engineProblem(proc(image: '\\\\?\\$engine'), uiExe: ui, exists: installed), isNull);
    expect(engineProblem(proc(integrity: 0x2100), uiExe: ui, exists: installed), isNull); // medium plus
  });

  test('a low-integrity squatter is refused, even one named NobadFind.exe', () {
    expect(engineProblem(proc(integrity: 0x1000), uiExe: ui, exists: installed), contains('low integrity'));
    expect(engineProblem(proc(integrity: 0), uiExe: ui, exists: installed), contains('low integrity'));
  });

  test('a sandboxed (AppContainer), elevated or other-account server is refused', () {
    expect(engineProblem(proc(appContainer: true), uiExe: ui, exists: installed), contains('AppContainer'));
    expect(engineProblem(proc(integrity: integrityHigh), uiExe: ui, exists: installed), contains('administrator'));
    expect(engineProblem(proc(sameUser: false), uiExe: ui, exists: installed), contains('another account'));
  });

  test('another program at medium integrity is refused when the app is installed', () {
    expect(
      engineProblem(proc(image: r'C:\Users\me\Downloads\NobadFind.exe'), uiExe: ui, exists: installed),
      contains('next to this window'),
    );
    expect(
      engineProblem(proc(image: r'C:\Python311\python.exe'), uiExe: ui, exists: installed),
      contains('next to this window'),
    );
  });

  test('from source the engine is Python running the source tree', () {
    const devUi = r'C:\src\find\ui_flutter\build\windows\x64\runner\Release\nobad_find.exe';
    expect(engineProblem(proc(image: r'C:\Python311\python.exe'), uiExe: devUi, exists: fromSource), isNull);
    expect(engineProblem(proc(image: r'C:\src\find\.venv\Scripts\pythonw.exe'), uiExe: devUi, exists: fromSource),
        isNull);
    expect(engineProblem(proc(image: r'C:\Temp\evil.exe'), uiExe: devUi, exists: fromSource), isNotNull);
    expect(
      engineProblem(proc(image: r'C:\Python311\python.exe', integrity: 0x1000), uiExe: devUi, exists: fromSource),
      contains('low integrity'),
    );
  });

  test("when Windows can't say who serves the pipe, nothing is sent", () {
    expect(engineProblem(ServerProcess.unknown, uiExe: ui, exists: installed), isNotNull);
  });

  test('the installed engine is matched by file identity, so a short 8.3 image path is still the engine', () {
    const short = r'C:\Users\me\AppData\Local\Programs\NOBADF~1\NobadFind.exe';
    expect(engineProblem(proc(image: short), uiExe: ui, exists: installed), isNotNull); // by text: refused
    bool sameFile(String a, String b) => {a.toLowerCase(), b.toLowerCase()}.difference({short.toLowerCase(), engine.toLowerCase()}).isEmpty;
    expect(engineProblem(proc(image: short), uiExe: ui, exists: installed, sameFile: sameFile), isNull);
    expect(
      engineProblem(proc(image: r'C:\Temp\NobadFind.exe'), uiExe: ui, exists: installed, sameFile: sameFile),
      contains('next to this window'),
    );
  });

  test('sameFileOnDisk compares the files, not the spelling', () {
    final dir = Directory.systemTemp.createTempSync('nbf long folder name ');
    try {
      final f = File('${dir.path}\\NobadFind engine.exe')..writeAsStringSync('x');
      final other = File('${dir.path}\\other.exe')..writeAsStringSync('x');
      final k32 = DynamicLibrary.open('kernel32.dll');
      final getShort = k32
          .lookupFunction<Uint32 Function(Pointer<Utf16>, Pointer<Utf16>, Uint32), int Function(Pointer<Utf16>, Pointer<Utf16>, int)>(
            'GetShortPathNameW',
          );
      final src = f.path.toNativeUtf16();
      final buf = calloc<Uint16>(1024).cast<Utf16>();
      final n = getShort(src, buf, 1024);
      final shortPath = n > 0 ? buf.toDartString(length: n) : f.path;
      calloc.free(src);
      calloc.free(buf);
      expect(sameFileOnDisk(shortPath, f.path), isTrue);
      expect(sameFileOnDisk(f.path.toUpperCase(), f.path), isTrue);
      expect(sameFileOnDisk(other.path, f.path), isFalse);
      expect(sameFileOnDisk(r'C:\no\such\file.exe', r'C:\no\such\file.exe'), isTrue); // unopenable: text decides
      expect(sameFileOnDisk(r'C:\no\such\a.exe', f.path), isFalse);
    } finally {
      dir.deleteSync(recursive: true);
    }
  });

  test('the installed engine path is NobadFind.exe next to the window', () {
    expect(installedEngine(ui), engine);
  });

  test('serverProcess reads the real answers Windows gives for a pipe this test serves itself', () {
    // a real, unelevated pipe: this test process is both ends, so the server is this very process
    final k32 = DynamicLibrary.open('kernel32.dll');
    final createPipe = k32
        .lookupFunction<
          IntPtr Function(Pointer<Utf16>, Uint32, Uint32, Uint32, Uint32, Uint32, Uint32, Pointer<Void>),
          int Function(Pointer<Utf16>, int, int, int, int, int, int, Pointer<Void>)
        >('CreateNamedPipeW');
    final createFile = k32
        .lookupFunction<
          IntPtr Function(Pointer<Utf16>, Uint32, Uint32, Pointer<Void>, Uint32, Uint32, IntPtr),
          int Function(Pointer<Utf16>, int, int, Pointer<Void>, int, int, int)
        >('CreateFileW');
    final close = k32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('CloseHandle');
    final name = '\\\\.\\pipe\\NOBADFind-test-${DateTime.now().microsecondsSinceEpoch}'.toNativeUtf16();
    final server = createPipe(name, 3, 0, 1, 4096, 4096, 0, nullptr); // duplex, byte mode, one instance
    expect(server, isNot(-1));
    final client = createFile(name, 0xC0000000, 0, nullptr, 3, 0, 0);
    expect(client, isNot(-1));
    try {
      final p = serverProcess(client);
      expect(p.sameUser, isTrue);
      expect(p.appContainer, isFalse);
      expect(p.integrity, greaterThanOrEqualTo(integrityMedium)); // a test run is never low integrity
      expect(p.image.toLowerCase(), Platform.resolvedExecutable.toLowerCase());
    } finally {
      close(client);
      close(server);
      calloc.free(name);
    }
  });
}

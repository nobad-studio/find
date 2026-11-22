/// The Windows named pipe to the engine: `\\.\pipe\NOBADFind-<user SID>` (dart:ffi, overlapped I/O).
///
/// - Connects with identification-level impersonation only (SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION), so
///   whatever is at the other end can't act as this user.
/// - Checks the pipe's owner is this user before sending anything: another account on the PC that created the name
///   first gets no search words.
/// - Checks the process serving it is NOBAD Find's engine (security review 2026-11-22, M1): this user, medium
///   integrity, no AppContainer, and NobadFind.exe next to this window (from source: Python). A sandboxed or
///   low-integrity process that took the name first gets nothing either ([engineProblem], [Link.untrusted]).
/// - Reads in a small background isolate (blocking on its own OVERLAPPED), writes from the UI isolate; the handle is
///   overlapped so both can be in flight at once. Lines are capped at [maxMessage].
library;

import 'dart:async';
import 'dart:convert';
import 'dart:ffi';
import 'dart:io' show File, Platform;
import 'dart:isolate';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

import 'rpc.dart';

// ---------- the few Win32 calls needed (kernel32, advapi32) ----------
final class _OVERLAPPED extends Struct {
  @IntPtr()
  external int internal;
  @IntPtr()
  external int internalHigh;
  @Uint32()
  external int offset;
  @Uint32()
  external int offsetHigh;
  @IntPtr()
  external int hEvent;
}

final _k32 = DynamicLibrary.open('kernel32.dll');
final _adv = DynamicLibrary.open('advapi32.dll');

final _createFile = _k32
    .lookupFunction<
      IntPtr Function(Pointer<Utf16>, Uint32, Uint32, Pointer<Void>, Uint32, Uint32, IntPtr),
      int Function(Pointer<Utf16>, int, int, Pointer<Void>, int, int, int)
    >('CreateFileW');
final _waitNamedPipe = _k32.lookupFunction<Int32 Function(Pointer<Utf16>, Uint32), int Function(Pointer<Utf16>, int)>(
  'WaitNamedPipeW',
);
final _readFile = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<Uint8>, Uint32, Pointer<Uint32>, Pointer<_OVERLAPPED>),
      int Function(int, Pointer<Uint8>, int, Pointer<Uint32>, Pointer<_OVERLAPPED>)
    >('ReadFile');
final _writeFile = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<Uint8>, Uint32, Pointer<Uint32>, Pointer<_OVERLAPPED>),
      int Function(int, Pointer<Uint8>, int, Pointer<Uint32>, Pointer<_OVERLAPPED>)
    >('WriteFile');
final _getOverlappedResult = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<_OVERLAPPED>, Pointer<Uint32>, Int32),
      int Function(int, Pointer<_OVERLAPPED>, Pointer<Uint32>, int)
    >('GetOverlappedResult');
final _createEvent = _k32
    .lookupFunction<
      IntPtr Function(Pointer<Void>, Int32, Int32, Pointer<Utf16>),
      int Function(Pointer<Void>, int, int, Pointer<Utf16>)
    >('CreateEventW');
final _cancelIoEx = _k32
    .lookupFunction<Int32 Function(IntPtr, Pointer<_OVERLAPPED>), int Function(int, Pointer<_OVERLAPPED>)>(
      'CancelIoEx',
    );
final _closeHandle = _k32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('CloseHandle');
final _localFree = _k32.lookupFunction<IntPtr Function(Pointer<Void>), int Function(Pointer<Void>)>('LocalFree');
final _getCurrentProcess = _k32.lookupFunction<IntPtr Function(), int Function()>('GetCurrentProcess');
final _openProcessToken = _adv
    .lookupFunction<Int32 Function(IntPtr, Uint32, Pointer<IntPtr>), int Function(int, int, Pointer<IntPtr>)>(
      'OpenProcessToken',
    );
final _getTokenInformation = _adv
    .lookupFunction<
      Int32 Function(IntPtr, Int32, Pointer<Void>, Uint32, Pointer<Uint32>),
      int Function(int, int, Pointer<Void>, int, Pointer<Uint32>)
    >('GetTokenInformation');
final _convertSidToStringSid = _adv
    .lookupFunction<
      Int32 Function(Pointer<Void>, Pointer<Pointer<Utf16>>),
      int Function(Pointer<Void>, Pointer<Pointer<Utf16>>)
    >('ConvertSidToStringSidW');
final _equalSid = _adv
    .lookupFunction<Int32 Function(Pointer<Void>, Pointer<Void>), int Function(Pointer<Void>, Pointer<Void>)>(
      'EqualSid',
    );
final _getSecurityInfo = _adv
    .lookupFunction<
      Uint32 Function(
        IntPtr,
        Int32,
        Uint32,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
      ),
      int Function(
        int,
        int,
        int,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
      )
    >('GetSecurityInfo');

const _genericReadWrite = 0xC0000000;
const _openExisting = 3;
const _fileFlagOverlapped = 0x40000000;
const _securitySqosPresent = 0x00100000;
const _securityIdentification = 0x00010000;
const _invalidHandle = -1;
const _tokenQuery = 0x8;
const _tokenUser = 1;
const _seKernelObject = 6;
const _ownerSecurityInformation = 1;
const _bufSize = 64 * 1024;

/// Runs [body] with this process's user SID (a pointer valid only inside [body]).
T _withUserSid<T>(T Function(Pointer<Void> sid) body) {
  return using((arena) {
    final tok = arena<IntPtr>();
    if (_openProcessToken(_getCurrentProcess(), _tokenQuery, tok) == 0) {
      throw StateError('OpenProcessToken failed');
    }
    try {
      const size = 256; // TOKEN_USER + the largest SID fit easily
      final buf = arena<Uint8>(size);
      final got = arena<Uint32>();
      if (_getTokenInformation(tok.value, _tokenUser, buf.cast(), size, got) == 0) {
        throw StateError('GetTokenInformation failed');
      }
      return body(Pointer<Void>.fromAddress(buf.cast<IntPtr>().value)); // TOKEN_USER.User.Sid
    } finally {
      _closeHandle(tok.value);
    }
  });
}

/// The current user's SID as a string, e.g. S-1-5-21-…
String userSid() => _withUserSid((sid) {
  final out = calloc<Pointer<Utf16>>();
  try {
    if (_convertSidToStringSid(sid, out) == 0) throw StateError('ConvertSidToStringSid failed');
    final s = out.value.toDartString();
    _localFree(out.value.cast());
    return s;
  } finally {
    calloc.free(out);
  }
});

String enginePipeName([String? sid]) => r'\\.\pipe\NOBADFind-' + (sid ?? userSid());

bool _ownedByMe(int handle) {
  final owner = calloc<Pointer<Void>>();
  final sd = calloc<Pointer<Void>>();
  try {
    final err = _getSecurityInfo(
      handle,
      _seKernelObject,
      _ownerSecurityInformation,
      owner,
      nullptr,
      nullptr,
      nullptr,
      sd,
    );
    if (err != 0 || owner.value == nullptr) return false;
    return _withUserSid((me) => _equalSid(owner.value, me) != 0);
  } finally {
    if (sd.value != nullptr) _localFree(sd.value); // on every path, the null-owner and throw ones too
    calloc.free(owner);
    calloc.free(sd);
  }
}

class PipeNotOwned extends EngineUntrusted {
  const PipeNotOwned() : super('the pipe belongs to another account');
}

// ---------- who serves the pipe (security review 2026-11-22, M1: pipe squatting) ----------
final _getNamedPipeServerProcessId = _k32
    .lookupFunction<Int32 Function(IntPtr, Pointer<Uint32>), int Function(int, Pointer<Uint32>)>(
      'GetNamedPipeServerProcessId',
    );
final _openProcess = _k32.lookupFunction<IntPtr Function(Uint32, Int32, Uint32), int Function(int, int, int)>(
  'OpenProcess',
);
final _queryFullProcessImageName = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Uint32, Pointer<Utf16>, Pointer<Uint32>),
      int Function(int, int, Pointer<Utf16>, Pointer<Uint32>)
    >('QueryFullProcessImageNameW');
final _getSidSubAuthorityCount = _adv
    .lookupFunction<Pointer<Uint8> Function(Pointer<Void>), Pointer<Uint8> Function(Pointer<Void>)>(
      'GetSidSubAuthorityCount',
    );
final _getSidSubAuthority = _adv
    .lookupFunction<Pointer<Uint32> Function(Pointer<Void>, Uint32), Pointer<Uint32> Function(Pointer<Void>, int)>(
      'GetSidSubAuthority',
    );

const _processQueryLimited = 0x1000;
const _tokenIntegrityLevel = 25;
const _tokenIsAppContainer = 29;
const integrityMedium = 0x2000;
const integrityHigh = 0x3000;

/// What Windows says about the process serving a pipe (GetNamedPipeServerProcessId, its image and token).
class ServerProcess {
  const ServerProcess({
    required this.image,
    required this.integrity,
    required this.appContainer,
    required this.sameUser,
  });

  /// Windows couldn't say (the process can't be opened, or its token read).
  static const unknown = ServerProcess(image: '', integrity: -1, appContainer: false, sameUser: false);

  /// Full path of its exe ('' when unknown).
  final String image;

  /// Mandatory integrity level RID: 0x1000 low, 0x2000 medium, 0x3000 high; -1 unknown.
  final int integrity;
  final bool appContainer;

  /// Its token's user is this window's user.
  final bool sameUser;
}

String _plainPath(String p) {
  var s = p.replaceAll('/', r'\');
  if (s.startsWith(r'\\?\')) s = s.substring(4);
  return s.toLowerCase();
}

String _dirOf(String p) {
  final s = p.replaceAll('/', r'\');
  final i = s.lastIndexOf(r'\');
  return i < 0 ? '' : s.substring(0, i);
}

String _nameOf(String p) {
  final s = p.replaceAll('/', r'\');
  return s.substring(s.lastIndexOf(r'\') + 1).toLowerCase();
}

/// The engine exe the installed app has: NobadFind.exe next to this window's exe (nobad_find.exe).
String installedEngine(String uiExe) => '${_dirOf(uiExe)}\\NobadFind.exe';

/// Why the process serving the pipe isn't NOBAD Find's engine, or null when it is. [uiExe] is this window's exe.
/// Installed, the engine is exactly [installedEngine]; with no NobadFind.exe there (running from source) it is the
/// Python that runs the source tree (python.exe / pythonw.exe) or a frozen NobadFind.exe. Either way it runs as
/// this user at medium integrity, outside any AppContainer: a sandboxed or low-integrity process that took the
/// name first (pipe squatting) is refused, and the window sends it nothing.
String? engineProblem(ServerProcess p, {required String uiExe, required bool Function(String path) exists}) {
  if (p.integrity < 0 || p.image.isEmpty) return "Windows can't say which program serves the pipe";
  if (!p.sameUser) return 'it runs as another account';
  if (p.appContainer) return 'it runs in an app sandbox (AppContainer)';
  if (p.integrity < integrityMedium) return 'it runs at low integrity';
  if (p.integrity >= integrityHigh) return 'it runs as administrator, which the engine never does';
  final engine = installedEngine(uiExe);
  if (exists(engine)) {
    return _plainPath(p.image) == _plainPath(engine) ? null : "it isn't the NobadFind.exe next to this window";
  }
  return const {'python.exe', 'pythonw.exe', 'nobadfind.exe'}.contains(_nameOf(p.image))
      ? null
      : "it isn't NOBAD Find's engine";
}

/// The process serving the pipe at [handle], as Windows sees it.
ServerProcess serverProcess(int handle) => using((arena) {
  final pid = arena<Uint32>();
  if (_getNamedPipeServerProcessId(handle, pid) == 0 || pid.value == 0) return ServerProcess.unknown;
  final hp = _openProcess(_processQueryLimited, 0, pid.value);
  if (hp == 0) return ServerProcess.unknown;
  try {
    const cap = 32768;
    final buf = arena<Uint16>(cap).cast<Utf16>();
    final n = arena<Uint32>()..value = cap;
    if (_queryFullProcessImageName(hp, 0, buf, n) == 0) return ServerProcess.unknown;
    final image = buf.toDartString(length: n.value);
    final tok = arena<IntPtr>();
    if (_openProcessToken(hp, _tokenQuery, tok) == 0) return ServerProcess.unknown;
    try {
      const size = 256;
      final info = arena<Uint8>(size);
      final got = arena<Uint32>();
      if (_getTokenInformation(tok.value, _tokenUser, info.cast(), size, got) == 0) return ServerProcess.unknown;
      final user = Pointer<Void>.fromAddress(info.cast<IntPtr>().value);
      final same = _withUserSid((me) => _equalSid(user, me) != 0);
      final label = arena<Uint8>(size);
      if (_getTokenInformation(tok.value, _tokenIntegrityLevel, label.cast(), size, got) == 0) {
        return ServerProcess.unknown;
      }
      final sid = Pointer<Void>.fromAddress(label.cast<IntPtr>().value); // TOKEN_MANDATORY_LABEL.Label.Sid
      final count = _getSidSubAuthorityCount(sid).value;
      if (count == 0) return ServerProcess.unknown;
      final integrity = _getSidSubAuthority(sid, count - 1).value;
      final appc = arena<Uint32>();
      if (_getTokenInformation(tok.value, _tokenIsAppContainer, appc.cast(), 4, got) == 0) {
        return ServerProcess.unknown;
      }
      return ServerProcess(image: image, integrity: integrity, appContainer: appc.value != 0, sameUser: same);
    } finally {
      _closeHandle(tok.value);
    }
  } finally {
    _closeHandle(hp);
  }
});

/// A connected pipe. [connect] fails fast (EngineOffline) when no engine is listening.
class PipeTransport implements Transport {
  PipeTransport._(this._handle) {
    _wov.ref.hEvent = _createEvent(nullptr, 1, 0, nullptr);
  }

  static Future<Transport> connect([String? name]) async {
    final path = (name ?? enginePipeName()).toNativeUtf16();
    try {
      var h = _open(path);
      if (h == _invalidHandle && _waitNamedPipe(path, 1000) != 0) {
        h = _open(path); // every instance was busy a moment ago
      }
      if (h == _invalidHandle) throw const EngineOffline();
      if (!_ownedByMe(h)) {
        _closeHandle(h);
        throw const PipeNotOwned();
      }
      final problem = engineProblem(
        serverProcess(h),
        uiExe: Platform.resolvedExecutable,
        exists: (p) => File(p).existsSync(),
      );
      if (problem != null) {
        _closeHandle(h); // before a single byte is written
        throw EngineUntrusted(problem);
      }
      final t = PipeTransport._(h);
      await t._startReader();
      return t;
    } finally {
      calloc.free(path);
    }
  }

  static int _open(Pointer<Utf16> path) => _createFile(
    path,
    _genericReadWrite,
    0,
    nullptr,
    _openExisting,
    _fileFlagOverlapped | _securitySqosPresent | _securityIdentification,
    0,
  );

  final int _handle;
  final _wov = calloc<_OVERLAPPED>();
  final _written = calloc<Uint32>();
  final _lines = StreamController<String>();
  final _split = LineSplitterBytes();
  ReceivePort? _port;
  var _readerDone = false;
  var _closed = false;

  /// Set by close(); the reader isolate checks it before every read (a cancel between two reads finds nothing to
  /// cancel). Shared native memory, freed once the reader is done.
  final _stop = calloc<Int32>();
  Timer? _forceClose;

  @override
  Stream<String> get lines => _lines.stream;

  Future<void> _startReader() async {
    final port = _port = ReceivePort();
    port.listen((msg) {
      if (msg is TransferableTypedData) {
        try {
          for (final line in _split.feed(msg.materialize().asUint8List())) {
            _lines.add(line);
          }
        } on LineTooLong {
          close();
        }
      } else {
        _readerDone = true; // the pipe broke, or close() cancelled the read
        close();
      }
    });
    try {
      await Isolate.spawn(_readLoop, (_handle, port.sendPort, _stop.address), debugName: 'engine-pipe-reader');
    } on Object {
      _readerDone = true; // no reader: nothing else will release the handle
      _closed = true;
      _release();
      rethrow;
    }
  }

  @override
  void send(String line) {
    if (_closed) throw const EngineOffline();
    final bytes = utf8.encode('$line\n');
    if (bytes.length > maxMessage) throw const RpcException(-32600, 'Request too big');
    final buf = calloc<Uint8>(bytes.length);
    try {
      buf.asTypedList(bytes.length).setAll(0, bytes);
      _wov.ref
        ..internal = 0
        ..internalHigh = 0;
      _writeFile(_handle, buf, bytes.length, nullptr, _wov);
      // Small writes into the engine's 64 KB pipe buffer finish at once; the engine always reads.
      if (_getOverlappedResult(_handle, _wov, _written, 1) == 0 || _written.value != bytes.length) {
        close();
        throw const EngineOffline();
      }
    } finally {
      calloc.free(buf);
    }
  }

  @override
  Future<void> close() async {
    if (_closed) {
      if (_readerDone) _release();
      return;
    }
    _closed = true;
    _stop.value = 1;
    _cancelIoEx(_handle, nullptr); // wakes the reader isolate, which then reports done
    if (_readerDone) {
      _release();
    } else {
      // a read that started just after the cancel would wait forever: closing the handle ends it
      _forceClose = Timer(const Duration(milliseconds: 500), () {
        if (_readerDone) return;
        _cancelIoEx(_handle, nullptr);
        _closeHandleOnce();
      });
    }
    if (!_lines.isClosed) await _lines.close();
  }

  var _released = false;
  var _handleClosed = false;
  void _closeHandleOnce() {
    if (_handleClosed) return;
    _handleClosed = true;
    _closeHandle(_handle);
  }

  void _release() {
    if (_released) return;
    _released = true;
    _forceClose?.cancel();
    _port?.close();
    _closeHandleOnce();
    _closeHandle(_wov.ref.hEvent);
    calloc.free(_wov);
    calloc.free(_written);
    calloc.free(_stop);
  }
}

/// The reader isolate: overlapped ReadFile + wait, forever, sending each chunk back. Ends on any failure or a
/// zero-byte read (the pipe closed, or the UI cancelled the read to disconnect).
void _readLoop((int, SendPort, int) args) {
  final (handle, port, stopAddress) = args;
  final stop = Pointer<Int32>.fromAddress(stopAddress);
  final ov = calloc<_OVERLAPPED>();
  final buf = calloc<Uint8>(_bufSize);
  final got = calloc<Uint32>();
  ov.ref.hEvent = _createEvent(nullptr, 1, 0, nullptr);
  try {
    while (stop.value == 0) {
      ov.ref
        ..internal = 0
        ..internalHigh = 0;
      _readFile(handle, buf, _bufSize, nullptr, ov);
      // An immediate failure leaves Internal at 0 and 0 bytes: treated as the end, no GetLastError needed.
      if (_getOverlappedResult(handle, ov, got, 1) == 0 || got.value == 0) break;
      port.send(TransferableTypedData.fromList([Uint8List.fromList(buf.asTypedList(got.value))]));
    }
  } finally {
    _closeHandle(ov.ref.hEvent);
    calloc.free(ov);
    calloc.free(buf);
    calloc.free(got);
    port.send(null);
  }
}

# PyInstaller spec for NOBAD Find's engine - onedir, windowed (the installer wraps the folder). build.ps1 runs it from
# the repository root, then copies the Flutter UI (nobad_find.exe and its files) into the same folder:
#   python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\nobadfind.spec
# No uac_admin: NOBAD Find runs as the normal user and refuses to start elevated. The elevated steps ask for it
# themselves: the Windows Search switch (`NobadFind.exe --wsearch <word>`) and the turbo index's one-time setup and
# removal (`turbo\NobadFindTurbo.exe --turbo install|remove`, the second program below).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (provided by PyInstaller)
ROOT = os.path.dirname(HERE)
ICON = os.path.join(HERE, "nobadfind.ico")
VERSION = os.path.join(HERE, "version_info.txt")

# No window toolkit here: the window is the Flutter UI (ui_flutter), a separate exe.
datas = []
binaries = []

# Imported lazily inside functions (store / extract / embed); listed so a missing one fails the build, not the app.
hidden = ["sqlcipher3", "sqlcipher3.dbapi2", "pypdf", "numpy", "onnxruntime", "tokenizers"]
hidden += collect_submodules("pypdf")
binaries += collect_dynamic_libs("sqlcipher3") + collect_dynamic_libs("onnxruntime")
datas += collect_data_files("pypdf")

# Windows built-in OCR through the winrt projection (winrt-runtime + winrt-Windows.* packages). `winrt` is a
# namespace package split over many wheels, so collect whatever is installed; a build without it still works (the
# app then has no OCR).
try:
    import winrt  # noqa: F401
except ImportError:
    print("nobadfind.spec: winrt not installed - building without Windows OCR")
else:
    # Each projected namespace reads the _table.pywinrt data file beside it at import time, so the data files are
    # needed too (winrt-runtime also ships its own PyInstaller hook that does the same; collecting twice is harmless).
    hidden += collect_submodules("winrt")
    binaries += collect_dynamic_libs("winrt")
    datas += collect_data_files("winrt", excludes=["**/*.pyi"])

EXCLUDES = ["tkinter", "pytest", "_pytest", "pyflakes", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"]

a = Analysis([os.path.join(HERE, "launch.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=EXCLUDES, noarchive=False)
# winrt-runtime ships its own, older C++ runtime (winrt\msvcp140.dll, 14.29). Once winrt has loaded it, onnxruntime
# (needs 14.40+) fails with "DLL initialization routine failed". Leave that copy out: winrt then uses the current
# msvcp140.dll bundled at the top of _internal, like everything else.
_OLD_CRT = {os.path.normcase(os.path.join("winrt", n)) for n in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                                                                 "vcruntime140.dll", "vcruntime140_1.dll")}
a.binaries = [b for b in a.binaries if os.path.normcase(b[0]) not in _OLD_CRT]
a.datas = [d for d in a.datas if os.path.normcase(d[0]) not in _OLD_CRT]
pyz = PYZ(a.pure)
# No start-up picture: the engine starts the UI first thing (uilaunch.start_now), and the UI shows its own.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NobadFind", console=False, disable_windowed_traceback=False,
          icon=ICON, version=VERSION if os.path.exists(VERSION) else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NobadFind")

# The turbo index's helper (nobadfind/turbosvc.py): its own small program in dist\NobadFindTurbo, which build.ps1
# copies to dist\NobadFind\turbo. The elevated setup step copies ONLY this folder into Program Files and runs it as a
# service, so it must stay small: the standard library and nobadfind's ntfs, turbosvc, scope, winapi and const.
TURBO_EXCLUDES = EXCLUDES + ["numpy", "onnxruntime", "tokenizers", "sqlcipher3", "pypdf", "winrt", "PIL", "System",
                             "clr", "clr_loader", "unittest", "pydoc", "xmlrpc", "email",
                             "http", "urllib3", "ssl", "_ssl", "sqlite3", "asyncio", "concurrent"]
ta = Analysis([os.path.join(HERE, "turbo_launch.py")], pathex=[ROOT], binaries=[], datas=[], hiddenimports=[],
              excludes=TURBO_EXCLUDES, noarchive=False)
tpyz = PYZ(ta.pure)
texe = EXE(tpyz, ta.scripts, [], exclude_binaries=True, name="NobadFindTurbo", console=False,
           disable_windowed_traceback=True, icon=ICON, version=VERSION if os.path.exists(VERSION) else None)
tcoll = COLLECT(texe, ta.binaries, ta.datas, strip=False, upx=False, name="NobadFindTurbo")

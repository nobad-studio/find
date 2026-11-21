"""PyInstaller entry point for NobadFindTurbo.exe, the turbo index's helper (nobadfind/ntfs.py, nobadfind/turbosvc.py).

Its own small program (standard library and nobadfind's ntfs, turbosvc, scope, winapi, const only), so the copy
that runs as a Windows service carries no models, OCR, numpy or SQLCipher. It takes exactly `--turbo <word>` with a
word from ntfs.WORDS and nothing else: no window, no splash, no worker processes.
"""
import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 2 or args[0] != "--turbo":
        sys.exit(2)
    from nobadfind.ntfs import helper_main
    sys.exit(helper_main(args[1]))

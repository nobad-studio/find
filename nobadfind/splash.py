"""A native splash the moment NobadFind.exe starts (0.9.0), before Python has loaded the app, the engine has opened
the index and the Flutter window has drawn its first frame: a small dark card with the NOBAD Find icon, its name
and "Starting…", so a double-click never looks like nothing happened.

Plain Win32 through ctypes (no imports beyond the standard library: it runs before the app's own), on its own
thread with its own message loop. The engine closes it when the window says it's showing (ui_shown); it closes
itself after MAX_S in any case, and with the process.
"""
import ctypes
import os
import sys
import threading
from ctypes import wintypes

MAX_S = 20
W, H = 380, 150
_current = None
_lock = threading.Lock()

# Starts that never open a window, or open only the quick find bar (which must appear at once, not after a card).
NO_SPLASH = ("--background", "--engine", "--uninstall", "--wsearch", "--turbo", "--version", "--open-with", "--bar",
             "-h", "--help")


def wanted(argv):
    """A splash only for a start that opens the main window (a double-click, the Start menu, --page)."""
    if sys.platform != "win32" or os.environ.get("NOBAD_FIND_NO_SPLASH"):
        return False
    return not any(a.split("=", 1)[0] in NO_SPLASH for a in argv[1:])


def show(argv=None):
    """Show the splash on its own thread, if this start wants one. Returns it, or None."""
    global _current
    if not wanted(sys.argv if argv is None else argv):
        return None
    with _lock:
        if _current is None:
            s = Splash()
            if s.start():
                _current = s
        return _current


def close():
    """The window is up (or NOBAD Find is quitting): the splash goes. Safe to call any number of times."""
    global _current
    with _lock:
        s, _current = _current, None
    if s is not None:
        s.close()


WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x80, 0x8
WM_DESTROY, WM_CLOSE, WM_PAINT, WM_TIMER = 0x0002, 0x0010, 0x000F, 0x0113
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


def _rgb(r, g, b):
    return r | (g << 8) | (b << 16)


BG, TEXT, DIM, ORANGE = _rgb(11, 12, 15), _rgb(243, 244, 246), _rgb(150, 154, 162), _rgb(255, 77, 0)


class Splash:
    def __init__(self):
        self.hwnd = None
        self._ready = threading.Event()
        self._thread = None
        self._proc = WNDPROC(self._wndproc)          # kept alive as long as the window
        self._icon = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="splash")
        self._thread.start()
        return self._ready.wait(2) and self.hwnd is not None

    def close(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _u32(self):
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        u.CreateWindowExW.restype = wintypes.HWND
        u.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        u.BeginPaint.restype = wintypes.HDC
        u.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
        u.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT),
                                wintypes.UINT]
        u.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int,
                                 ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
        u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        return u

    def _load_icon(self):
        """The icon inside NobadFind.exe (or packaging/nobadfind.ico from source), 48 px."""
        try:
            exe = sys.executable if getattr(sys, "frozen", False) else ""
            if exe:
                sh = ctypes.WinDLL("shell32")
                large = wintypes.HICON()
                sh.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HICON),
                                              ctypes.c_void_p, wintypes.UINT]
                if sh.ExtractIconExW(exe, 0, ctypes.byref(large), None, 1) and large.value:
                    return large.value
            ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging",
                               "nobadfind.ico")
            if os.path.isfile(ico):
                u = ctypes.windll.user32
                u.LoadImageW.restype = wintypes.HANDLE
                u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                                         ctypes.c_int, wintypes.UINT]
                return u.LoadImageW(None, ico, 1, 48, 48, 0x10) or None        # IMAGE_ICON, LR_LOADFROMFILE
        except Exception:
            pass
        return None

    def _paint(self, u, hwnd):
        ps = _PAINTSTRUCT()
        hdc = u.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            self.draw(u, hdc)
        finally:
            u.EndPaint(hwnd, ctypes.byref(ps))

    def draw(self, u, hdc):
        """The card on any device context (the window's, or a bitmap's to look at it without a screen)."""
        g = ctypes.WinDLL("gdi32")
        g.CreateSolidBrush.restype = wintypes.HBRUSH
        g.CreateFontW.restype = wintypes.HFONT
        g.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        bg = g.CreateSolidBrush(BG)
        u.FillRect(hdc, ctypes.byref(wintypes.RECT(0, 0, W, H)), bg)
        g.DeleteObject(bg)
        bar = g.CreateSolidBrush(ORANGE)
        u.FillRect(hdc, ctypes.byref(wintypes.RECT(92, 100, 92 + 44, 103)), bar)
        g.DeleteObject(bar)
        if self._icon:
            u.DrawIconEx(hdc, 28, 30, self._icon, 48, 48, 0, None, 3)                 # DI_NORMAL
        g.SetBkMode(hdc, 1)                                                            # TRANSPARENT
        title = g.CreateFontW(-26, 0, 0, 0, 800, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        small = g.CreateFontW(-14, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        old = g.SelectObject(hdc, title)
        g.SetTextColor(hdc, TEXT)
        u.DrawTextW(hdc, "NOBAD Find", -1, ctypes.byref(wintypes.RECT(92, 30, W - 20, 64)), 0x20)   # SINGLELINE
        g.SelectObject(hdc, small)
        g.SetTextColor(hdc, DIM)
        u.DrawTextW(hdc, "Private file search. Starting…", -1, ctypes.byref(wintypes.RECT(92, 66, W - 20, 92)),
                    0x20)
        g.SelectObject(hdc, old)
        g.DeleteObject(title)
        g.DeleteObject(small)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        u = self._u
        if msg == WM_PAINT:
            self._paint(u, hwnd)
            return 0
        if msg == WM_TIMER:
            u.DestroyWindow(hwnd)
            return 0
        if msg == WM_CLOSE:
            u.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.hwnd = None
            u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            # Drawn at 96 DPI; on a scaled display Windows scales the whole card (this thread isn't DPI aware), so
            # the layout below holds at every scale.
            u = self._u = self._u32()
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            wc = _WNDCLASSEX()
            wc.cbSize = ctypes.sizeof(_WNDCLASSEX)
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = "NOBADFindSplash"
            ctypes.windll.user32.RegisterClassExW(ctypes.byref(wc))
            self._icon = self._load_icon()
            sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
            self.hwnd = u.CreateWindowExW(WS_EX_TOOLWINDOW, "NOBADFindSplash", "NOBAD Find", WS_POPUP | WS_VISIBLE,
                                          (sw - W) // 2, (sh - H) // 2, W, H, None, None, hinst, None)
            if not self.hwnd:
                return
            try:                                  # Windows 11: rounded corners like every other window
                pref = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(pref), 4)
            except Exception:
                pass
            u.SetTimer(self.hwnd, 1, MAX_S * 1000, None)
            u.UpdateWindow(self.hwnd)
        finally:
            self._ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

"""Thin ctypes layer over the Win32 calls the tool needs.

Everything here talks to the OS only through public user32/dwmapi APIs that act
on window geometry, DWM composition and the cursor. Display modes are only read. Nothing reads or writes game memory, so it
is safe to use next to EasyAntiCheat.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

# --- constants -------------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_OVERLAPPED = 0x00000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000

WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_TOPMOST = 0x00000008
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

FRAME_STYLES = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
FRAME_EXSTYLES = WS_EX_DLGMODALFRAME | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
SWP_ASYNCWINDOWPOS = 0x4000

HWND_TOP = 0
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_RETURN = 0x0D

MONITOR_DEFAULTTONEAREST = 2

ENUM_CURRENT_SETTINGS = -1
ENUM_REGISTRY_SETTINGS = -2

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


# --- structures ------------------------------------------------------------
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


class DEVMODEW(ctypes.Structure):
    # Display variant of the DEVMODEW union; sizeof == 220.
    _fields_ = [
        ("dmDeviceName", wt.WCHAR * 32),
        ("dmSpecVersion", wt.WORD), ("dmDriverVersion", wt.WORD),
        ("dmSize", wt.WORD), ("dmDriverExtra", wt.WORD),
        ("dmFields", wt.DWORD),
        ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wt.DWORD), ("dmDisplayFixedOutput", wt.DWORD),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wt.WCHAR * 32),
        ("dmLogPixels", wt.WORD),
        ("dmBitsPerPel", wt.DWORD), ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD),
        ("dmDisplayFlags", wt.DWORD), ("dmDisplayFrequency", wt.DWORD),
        ("dmICMMethod", wt.DWORD), ("dmICMIntent", wt.DWORD),
        ("dmMediaType", wt.DWORD), ("dmDitherType", wt.DWORD),
        ("dmReserved1", wt.DWORD), ("dmReserved2", wt.DWORD),
        ("dmPanningWidth", wt.DWORD), ("dmPanningHeight", wt.DWORD),
    ]


assert ctypes.sizeof(DEVMODEW) == 220

# --- prototypes ------------------------------------------------------------

user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.MapVirtualKeyW.restype = wt.UINT
user32.GetForegroundWindow.restype = wt.HWND
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
user32.MonitorFromPoint.restype = wt.HMONITOR
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.EnumDisplaySettingsW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(DEVMODEW)]
dwmapi.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]


# --- helpers ---------------------------------------------------------------
@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @classmethod
    def from_native(cls, r: RECT) -> "Rect":
        return cls(r.left, r.top, r.right, r.bottom)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class Monitor:
    rect: Rect
    device: str


@dataclass(frozen=True)
class DisplayMode:
    width: int
    height: int
    frequency: int


def last_error() -> int:
    return ctypes.get_last_error()


def windows_of_pids(pids: set[int], class_name: str) -> list[int]:
    """Visible top-level windows of `class_name` that belong to any of `pids`.

    FindWindowEx walks only windows of that class, which is far cheaper than an
    EnumWindows callback over every window on the desktop."""
    found: list[int] = []
    hwnd = None
    while True:
        hwnd = user32.FindWindowExW(None, hwnd, class_name, None)
        if not hwnd:
            break
        if window_pid(hwnd) in pids and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
    return found


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def is_window(hwnd: int | None) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def window_rect(hwnd: int) -> Rect:
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Rect.from_native(r)


def client_size(hwnd: int) -> tuple[int, int]:
    r = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top)


def get_style(hwnd: int) -> int:
    return user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF


def get_exstyle(hwnd: int) -> int:
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def _signed32(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


def set_style(hwnd: int, style: int) -> None:
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, _signed32(style))


def set_exstyle(hwnd: int, exstyle: int) -> None:
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, _signed32(exstyle))


def set_window_pos(hwnd: int, insert_after: int, x: int, y: int, w: int, h: int, flags: int) -> bool:
    return bool(user32.SetWindowPos(hwnd, insert_after, x, y, w, h, flags))


def set_z_order(hwnd: int, insert_after: int) -> bool:
    return set_window_pos(hwnd, insert_after, 0, 0, 0, 0,
                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def post_alt_enter(hwnd: int) -> None:
    """Deliver Alt+Enter straight to the window's message queue (no focus needed)."""
    scan = user32.MapVirtualKeyW(VK_RETURN, 0)
    down = 1 | (scan << 16) | (1 << 29)
    up = down | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_SYSKEYDOWN, VK_RETURN, down)
    user32.PostMessageW(hwnd, WM_SYSKEYUP, VK_RETURN, up)


def restore_if_minimized(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def monitor_of_window(hwnd: int) -> Monitor:
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    return _monitor_info(hmon)


def primary_monitor() -> Monitor:
    hmon = user32.MonitorFromPoint(wt.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
    return _monitor_info(hmon)


def _monitor_info(hmon) -> Monitor:
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    return Monitor(Rect.from_native(mi.rcMonitor), mi.szDevice)


def _display_mode(device: str | None, which: int) -> DisplayMode | None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(device, which & 0xFFFFFFFF, ctypes.byref(dm)):
        return None
    return DisplayMode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency)


def current_display_mode(device: str | None) -> DisplayMode | None:
    return _display_mode(device, ENUM_CURRENT_SETTINGS)


def desktop_display_mode(device: str | None) -> DisplayMode | None:
    """The mode saved for the desktop (what Windows Settings shows)."""
    return _display_mode(device, ENUM_REGISTRY_SETTINGS)


def style_dark_frame(hwnd: int) -> None:
    """Dark title area + rounded corners on Windows 11 (no-op elsewhere)."""
    for attr, value in ((DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
                        (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)):
        v = ctypes.c_int(value)
        dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

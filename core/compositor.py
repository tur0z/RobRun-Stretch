"""DWM thumbnails, cursor access and cursor hiding for the stretched 4:3 overlay.

Why a DWM thumbnail: the Desktop Window Manager already holds the game's latest
presented frame for composition. A thumbnail asks DWM to draw that same surface
into another window during the same composition pass, scaled to any rectangle,
with x and y scaled independently. No capture, no copy to the CPU, no access to
the game process.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from core.win32 import (RECT, Rect, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, dwmapi, get_exstyle,
                        set_exstyle, user32)

# --- DWM thumbnails ------------------------------------------------------------------------
DWM_TNP_RECTDESTINATION = 0x01
DWM_TNP_RECTSOURCE = 0x02
DWM_TNP_OPACITY = 0x04
DWM_TNP_VISIBLE = 0x08
DWM_TNP_SOURCECLIENTAREAONLY = 0x10


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [("dwFlags", wt.DWORD), ("rcDestination", RECT), ("rcSource", RECT),
                ("opacity", ctypes.c_ubyte), ("fVisible", wt.BOOL),
                ("fSourceClientAreaOnly", wt.BOOL)]


HTHUMBNAIL = ctypes.c_void_p
dwmapi.DwmRegisterThumbnail.argtypes = [wt.HWND, wt.HWND, ctypes.POINTER(HTHUMBNAIL)]
dwmapi.DwmRegisterThumbnail.restype = ctypes.c_long
dwmapi.DwmUnregisterThumbnail.argtypes = [HTHUMBNAIL]
dwmapi.DwmUnregisterThumbnail.restype = ctypes.c_long
dwmapi.DwmUpdateThumbnailProperties.argtypes = [HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
dwmapi.DwmUpdateThumbnailProperties.restype = ctypes.c_long


def register_thumbnail(dest_hwnd: int, source_hwnd: int) -> int:
    h = HTHUMBNAIL()
    hr = dwmapi.DwmRegisterThumbnail(dest_hwnd, source_hwnd, ctypes.byref(h))
    if hr < 0:
        raise OSError(f"DwmRegisterThumbnail failed (0x{hr & 0xFFFFFFFF:08X})")
    return h.value


def update_thumbnail(thumb: int, source: Rect, dest: Rect, visible: bool = True) -> None:
    """Draw `source` (game client coordinates) stretched into `dest` (destination
    window client coordinates)."""
    p = DWM_THUMBNAIL_PROPERTIES()
    p.dwFlags = (DWM_TNP_RECTDESTINATION | DWM_TNP_RECTSOURCE | DWM_TNP_OPACITY
                 | DWM_TNP_VISIBLE | DWM_TNP_SOURCECLIENTAREAONLY)
    p.rcDestination = RECT(*dest.as_tuple())
    p.rcSource = RECT(*source.as_tuple())
    p.opacity = 255
    p.fVisible = visible
    p.fSourceClientAreaOnly = True
    hr = dwmapi.DwmUpdateThumbnailProperties(HTHUMBNAIL(thumb), ctypes.byref(p))
    if hr < 0:
        raise OSError(f"DwmUpdateThumbnailProperties failed (0x{hr & 0xFFFFFFFF:08X})")


def unregister_thumbnail(thumb: int) -> None:
    dwmapi.DwmUnregisterThumbnail(HTHUMBNAIL(thumb))


WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD]


def make_click_through(hwnd: int, layered_alpha: bool = True) -> None:
    """Mouse input falls through to the window underneath; never activates."""
    set_exstyle(hwnd, get_exstyle(hwnd) | WS_EX_LAYERED | WS_EX_TRANSPARENT
                | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    if layered_alpha:
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x2)  # LWA_ALPHA


# --- cursor ----------------------------------------------------------------------------------
CURSOR_SHOWING = 0x1


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hCursor", wt.HANDLE),
                ("ptScreenPos", wt.POINT)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
user32.GetClipCursor.argtypes = [ctypes.POINTER(RECT)]
user32.GetIconInfo.argtypes = [wt.HANDLE, ctypes.POINTER(ICONINFO)]
user32.DrawIconEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.HANDLE, ctypes.c_int,
                              ctypes.c_int, wt.UINT, wt.HBRUSH, wt.UINT]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]


def cursor_state() -> tuple[bool, int, tuple[int, int]]:
    """(visible, HCURSOR, screen position) of the global cursor."""
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(ci)):
        return False, 0, (0, 0)
    return bool(ci.flags & CURSOR_SHOWING), ci.hCursor or 0, (ci.ptScreenPos.x, ci.ptScreenPos.y)


def clip_cursor(rect: Rect | None) -> None:
    user32.ClipCursor(ctypes.byref(RECT(*rect.as_tuple())) if rect else None)


def current_clip() -> Rect:
    r = RECT()
    user32.GetClipCursor(ctypes.byref(r))
    return Rect.from_native(r)


gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wt.HANDLE, wt.DWORD]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
gdi32.SelectObject.restype = wt.HANDLE
gdi32.DeleteObject.argtypes = [wt.HANDLE]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.PatBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.DWORD]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def _render_cursor(hcursor: int, size: int, white: bool) -> bytes:
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hdc = gdi32.CreateCompatibleDC(None)
    hbm = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(hdc, hbm)
    gdi32.PatBlt(hdc, 0, 0, size, size, 0x00FF0062 if white else 0x00000042)  # WHITENESS / BLACKNESS
    user32.DrawIconEx(hdc, 0, 0, hcursor, 0, 0, 0, None, 0x0003)  # DI_NORMAL
    data = ctypes.string_at(bits, size * size * 4)
    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc)
    return data


def cursor_image(hcursor: int) -> tuple[bytes, int, tuple[int, int]] | None:
    """Premultiplied BGRA pixels of a cursor, its square canvas size and hotspot.

    Drawn on black and on white: alpha = 255 - (white - black). That recovers
    alpha for 32-bit, colour and monochrome cursors alike."""
    info = ICONINFO()
    if not user32.GetIconInfo(hcursor, ctypes.byref(info)):
        return None
    for bm in (info.hbmMask, info.hbmColor):
        if bm:
            gdi32.DeleteObject(bm)
    size = max(64, user32.GetSystemMetrics(13) * 2)  # SM_CXCURSOR; room for large cursors
    black = _render_cursor(hcursor, size, False)
    white = _render_cursor(hcursor, size, True)
    out = bytearray(len(black))
    for i in range(0, len(black), 4):
        a = 255 - (white[i + 1] - black[i + 1])
        a = 0 if a < 0 else 255 if a > 255 else a
        out[i], out[i + 1], out[i + 2], out[i + 3] = black[i], black[i + 1], black[i + 2], a
    return bytes(out), size, (info.xHotspot, info.yHotspot)


# --- hiding the hardware cursor ---------------------------------------------------------------
_mag = None


def show_system_cursor(show: bool) -> bool:
    """Hide/show the hardware cursor (Magnification API, no UIAccess needed).
    Windows still delivers movement and clicks to the game; only drawing stops.
    The hidden state belongs to this process and ends when it exits."""
    global _mag
    if _mag is None:
        _mag = ctypes.WinDLL("magnification")
        _mag.MagShowSystemCursor.argtypes = [wt.BOOL]
        if not _mag.MagInitialize():
            _mag = None
            raise OSError("MagInitialize failed")
    return bool(_mag.MagShowSystemCursor(show))


def release_magnification() -> None:
    global _mag
    if _mag is not None:
        _mag.MagShowSystemCursor(True)
        _mag.MagUninitialize()
        _mag = None

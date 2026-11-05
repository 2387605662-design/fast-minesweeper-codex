"""Capture and send mouse messages to one verified XP Minesweeper window."""

import ctypes as ct
from ctypes import wintypes as wt
from pathlib import Path

from PIL import Image
import psutil


user = ct.WinDLL("user32", use_last_error=True)
gdi = ct.WinDLL("gdi32", use_last_error=True)
window_callback = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user.EnumWindows.argtypes = (window_callback, wt.LPARAM)
user.GetWindowThreadProcessId.argtypes = (wt.HWND, ct.POINTER(wt.DWORD))
user.GetClientRect.argtypes = (wt.HWND, ct.POINTER(wt.RECT))
user.IsWindowVisible.argtypes = (wt.HWND,)
user.IsIconic.argtypes = (wt.HWND,)
user.GetMenu.argtypes = (wt.HWND,)
user.GetMenu.restype = wt.HMENU
user.GetSubMenu.argtypes = (wt.HMENU, ct.c_int)
user.GetSubMenu.restype = wt.HMENU
user.GetMenuItemID.argtypes = (wt.HMENU, ct.c_int)
user.GetMenuItemID.restype = wt.UINT
user.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user.PrintWindow.argtypes = (wt.HWND, wt.HDC, wt.UINT)

gdi.CreateCompatibleDC.argtypes = (wt.HDC,)
gdi.CreateCompatibleDC.restype = wt.HDC
gdi.SelectObject.argtypes = (wt.HDC, wt.HGDIOBJ)
gdi.SelectObject.restype = wt.HGDIOBJ
gdi.DeleteObject.argtypes = (wt.HGDIOBJ,)
gdi.DeleteDC.argtypes = (wt.HDC,)


class BitmapInfo(ct.Structure):
    _fields_ = [
        ("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG),
        ("planes", wt.WORD), ("bits_per_pixel", wt.WORD), ("compression", wt.DWORD),
        ("image_size", wt.DWORD), ("x_resolution", wt.LONG), ("y_resolution", wt.LONG),
        ("colors_used", wt.DWORD), ("important_colors", wt.DWORD), ("color", wt.DWORD),
    ]


gdi.CreateDIBSection.argtypes = (
    wt.HDC, ct.POINTER(BitmapInfo), wt.UINT, ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD
)
gdi.CreateDIBSection.restype = wt.HBITMAP

MENU_IDS = (510, 521, 522, 523)
BUTTONS = {
    "left": (0x0201, 0x0202, 0x01),
    "right": (0x0204, 0x0205, 0x02),
    "middle": (0x0207, 0x0208, 0x10),
}


def process_id(handle):
    result = wt.DWORD()
    user.GetWindowThreadProcessId(handle, ct.byref(result))
    return result.value


def menu_ids(handle):
    menu = user.GetSubMenu(user.GetMenu(handle), 0)
    return tuple(user.GetMenuItemID(menu, position) for position in (0, 2, 3, 4)) if menu else ()


class GameWindow:
    def __init__(self, executable):
        path = Path(executable).resolve(strict=True)
        pids = set()
        for process in psutil.process_iter(("exe",)):
            candidate = process.info["exe"]
            if candidate and Path(candidate) == path:
                pids.add(process.pid)

        matches = []

        @window_callback
        def collect(handle, _):
            if user.IsWindowVisible(handle) and process_id(handle) in pids and menu_ids(handle) == MENU_IDS:
                matches.append(handle)
            return True

        user.EnumWindows(collect, 0)
        if len(matches) != 1:
            raise RuntimeError("Open exactly one XP Minesweeper window from the specified executable.")
        self.handle = matches[0]
        self.pid = process_id(self.handle)

    def size(self):
        if process_id(self.handle) != self.pid:
            raise RuntimeError("The selected Minesweeper window closed.")
        if user.IsIconic(self.handle):
            raise RuntimeError("Restore the Minesweeper window from the taskbar before running the command.")
        rect = wt.RECT()
        if not user.GetClientRect(self.handle, ct.byref(rect)):
            raise ct.WinError(ct.get_last_error())
        return rect.right, rect.bottom

    def post(self, message, wparam=0, lparam=0):
        if process_id(self.handle) != self.pid or not user.PostMessageW(self.handle, message, wparam, lparam):
            raise RuntimeError("Could not post to the verified Minesweeper window.")

    def menu(self, command):
        if command not in menu_ids(self.handle):
            raise RuntimeError("Minesweeper menu changed.")
        self.post(0x0111, command)

    def click(self, x, y, button):
        width, height = self.size()
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("Click outside the game window.")
        down, up, mask = BUTTONS[button]
        position = x | (y << 16)
        self.post(0x0200, 0, position)
        self.post(down, mask, position)
        self.post(up, 0, position)

    def capture(self):
        width, height = self.size()
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise RuntimeError("Unsupported window size.")
        dc = gdi.CreateCompatibleDC(None)
        if not dc:
            raise ct.WinError(ct.get_last_error())
        bitmap = previous = None
        try:
            info = BitmapInfo(size=40, width=width, height=-height, planes=1, bits_per_pixel=32)
            pixels = ct.c_void_p()
            bitmap = gdi.CreateDIBSection(dc, ct.byref(info), 0, ct.byref(pixels), None, 0)
            if not bitmap:
                raise ct.WinError(ct.get_last_error())
            previous = gdi.SelectObject(dc, bitmap)
            if not previous or not user.PrintWindow(self.handle, dc, 3):
                raise RuntimeError("Could not capture the Minesweeper client area.")
            return Image.frombytes("RGB", (width, height), ct.string_at(pixels, width*height*4), "raw", "BGRX")
        finally:
            if previous:
                gdi.SelectObject(dc, previous)
            if bitmap:
                gdi.DeleteObject(bitmap)
            gdi.DeleteDC(dc)

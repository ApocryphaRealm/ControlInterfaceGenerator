"""cig_see: one picture of one program's own window, on request only (plan 2.5). PrintWindow asks the window to draw
itself, so the picture is of that window even when another one covers it; nothing is recorded or kept on disk."""
from __future__ import annotations

import ctypes
import io

import win32gui
import win32ui
from PIL import Image
from mcp.server.fastmcp import Image as McpImage

PW_RENDERFULLCONTENT = 2


def grab(hwnd: int, max_w: int = 1280) -> Image.Image:
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = max(1, r - l), max(1, b - t)
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    try:
        ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_RENDERFULLCONTENT)
        info = bmp.GetInfo()
        im = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    return im


def see(engine, app: str):
    adapter, target = engine.resolve(app)
    if not target.hwnd:
        return {"ok": False, "error": "the program has no window"}
    im = grab(target.hwnd)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return McpImage(data=buf.getvalue(), format="png")

"""CIG reference gallery - Win32 common controls (USER32 + comctl32, created with pywin32; nothing downloaded).
Run: py -3 win32_gallery.py"""
import ctypes

import win32api
import win32con
import win32gui

ICC_BAR_CLASSES = 0x4


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint), ("dwICC", ctypes.c_uint)]


def main():
    icc = INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX), ICC_BAR_CLASSES | 0xFF)
    ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(icc))
    hinst = win32api.GetModuleHandle(None)
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "CIGWin32Gallery"
    wc.hInstance = hinst
    wc.hbrBackground = win32con.COLOR_WINDOW + 1
    wc.lpfnWndProc = {win32con.WM_DESTROY: lambda h, m, w, l: win32gui.PostQuitMessage(0)}
    win32gui.RegisterClass(wc)
    main_wnd = win32gui.CreateWindow("CIGWin32Gallery", "CIG Win32 Gallery",
                                     win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE, 200, 200, 520, 420, 0, 0,
                                     hinst, None)
    child = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP

    def make(cls, text, style, x, y, w, h, cid):
        return win32gui.CreateWindow(cls, text, child | style, x, y, w, h, main_wnd, cid, hinst, None)

    make("BUTTON", "Press me", win32con.BS_PUSHBUTTON, 10, 10, 160, 28, 101)
    make("BUTTON", "A checkbox", win32con.BS_AUTOCHECKBOX, 10, 45, 160, 24, 102)
    make("BUTTON", "Radio one", win32con.BS_AUTORADIOBUTTON | win32con.WS_GROUP, 10, 75, 120, 24, 103)
    make("BUTTON", "Radio two", win32con.BS_AUTORADIOBUTTON, 140, 75, 120, 24, 104)
    make("STATIC", "Text field:", 0, 10, 110, 80, 20, 105)
    make("EDIT", "", win32con.WS_BORDER | win32con.ES_AUTOHSCROLL, 95, 108, 300, 24, 106)
    make("STATIC", "Password field:", 0, 10, 140, 100, 20, 107)
    make("EDIT", "", win32con.WS_BORDER | win32con.ES_PASSWORD, 115, 138, 280, 24, 108)
    combo = make("COMBOBOX", "", win32con.CBS_DROPDOWNLIST | win32con.WS_VSCROLL, 10, 175, 160, 120, 109)
    for s in ("Alpha", "Beta", "Gamma"):
        win32gui.SendMessage(combo, win32con.CB_ADDSTRING, 0, s)
    win32gui.SendMessage(combo, win32con.CB_SETCURSEL, 0, 0)
    lb = make("LISTBOX", "", win32con.WS_BORDER | win32con.LBS_NOTIFY, 10, 210, 160, 70, 110)
    for s in ("One", "Two", "Three"):
        win32gui.SendMessage(lb, win32con.LB_ADDSTRING, 0, s)
    tb = make("msctls_trackbar32", "Slider", 0, 200, 210, 200, 30, 111)
    win32gui.SendMessage(tb, 0x0400 + 6, 1, win32api.MAKELONG(0, 10))     # TBM_SETRANGE
    win32gui.PumpMessages()


if __name__ == "__main__":
    main()

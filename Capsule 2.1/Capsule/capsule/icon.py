"""Puts the Capsule pill logo on the settings window, the game window and the taskbar."""
import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
PNG = os.path.join(ASSETS, "capsule.png")
ICO = os.path.join(ASSETS, "capsule.ico")


def set_app_id():
    """Without this, Windows shows the Python logo in the taskbar instead of Capsule's."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Capsule.App")
        except Exception:
            pass


def apply_tk(root):
    """Settings window (and any dialog boxes it opens)."""
    try:
        if sys.platform.startswith("win") and os.path.exists(ICO):
            root.iconbitmap(default=ICO)
        else:
            import tkinter as tk
            root._capsule_icon = tk.PhotoImage(file=PNG)  # keep a reference
            root.iconphoto(True, root._capsule_icon)
    except Exception:
        pass


def apply_opencv(title):
    """Game window. OpenCV has no icon option, so set it through Windows directly."""
    if not sys.platform.startswith("win") or not os.path.exists(ICO):
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        hwnd = user32.FindWindowW("Main HighGUI class", title)
        if not hwnd:
            return
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        for which, size in ((0, 16), (1, 48)):  # small (title bar), big (taskbar / Alt+Tab)
            h = user32.LoadImageW(None, ICO, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(hwnd, WM_SETICON, which, h)
    except Exception:
        pass

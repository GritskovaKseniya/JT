"""Icone e colore del titolo della finestra su Windows: una piccola (barra del titolo) e una grande (barra delle applicazioni, Alt+Tab).

Il comando `wm iconbitmap` di Tk imposta UNA sola immagine e Windows la ingrandisce o la riduce: nella barra delle
applicazioni si vedrebbe la versione piccola ingrandita e sfocata. Qui le due dimensioni giuste si caricano dal file .ico.
"""
import ctypes
from ctypes import wintypes

WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CXSMICON = 11, 49
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
DWMWA_TEXT_COLOR = 36           # Windows 11: colore del titolo (su Windows 10 la chiamata non ha effetto)
TITLE_COLOR = (0x3A, 0x40, 0x4B)   # grigio scuro, non nero


def set_window_icons(window, path):
    """Imposta icona piccola e grande della finestra. True se entrambe sono state caricate.
    Non solleva mai: fuori da Windows, o con un file mancante, ritorna False (resta l'icona di `iconbitmap`)."""
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        window.update_idletasks()
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        loaded = True
        for kind, metric in ((ICON_SMALL, SM_CXSMICON), (ICON_BIG, SM_CXICON)):
            size = user32.GetSystemMetrics(metric)
            handle = user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if handle:
                user32.SendMessageW(hwnd, WM_SETICON, kind, handle)
            else:
                loaded = False
        color = ctypes.c_uint(TITLE_COLOR[0] | TITLE_COLOR[1] << 8 | TITLE_COLOR[2] << 16)    # COLORREF = 0x00BBGGRR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_TEXT_COLOR, ctypes.byref(color),
                                                   ctypes.sizeof(color))
        return loaded
    except Exception:
        return False

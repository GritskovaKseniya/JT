"""Scala dello schermo.

Con un processo "DPI aware" i font (in punti) crescono da soli con Tk; le misure in pixel (margini, larghezze,
immagini) no: si passano da `px()`. A 100% non cambia nulla.
"""
_factor = 1.0


def set_factor(factor):
    global _factor
    _factor = max(1.0, float(factor))


def init(root):
    """Fattore dello schermo su cui gira la finestra (96 dpi = 1,0; 120 dpi = 1,25...)."""
    set_factor(root.winfo_fpixels('1i') / 96.0)


def factor():
    return _factor


def px(value):
    return int(round(value * _factor))


def pad(*values):
    """pad(10) -> (10,) scalato; pad(18, 14, 18, 12) -> tupla scalata, utile per padding=..."""
    return tuple(px(v) for v in values)

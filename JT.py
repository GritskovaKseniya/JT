"""JT - Jflex Translator: punto di ingresso.

    .venv\Scripts\python.exe JT.py
"""
import tkinter as tk

from jt.ui.app import JTApp
from jt.ui.dpi import enable_dpi_awareness


def main():
    enable_dpi_awareness()        # prima di creare la finestra: testo nitido su schermi con scala diversa da 100%
    root = tk.Tk()
    app = JTApp(root)
    try:
        root.mainloop()
    finally:
        app.shutdown()


if __name__ == '__main__':
    main()

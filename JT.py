"""JTools: punto di ingresso.

    .venv\Scripts\python.exe JT.py
"""
import os
import tkinter as tk

from jt.config import Paths
from jt.ui.app import JTApp
from jt.ui.dpi import enable_dpi_awareness


def use_bundled_oracle_client():
    """Se accanto al programma c'e' la cartella `oracle_client` (con oci.dll) si usa quella: il PC non ha bisogno di Oracle."""
    folder = os.path.join(Paths.default().base, 'oracle_client')
    if os.path.isdir(folder):
        os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')


def main():
    use_bundled_oracle_client()
    Paths.default().seed_user_files()        # installato: chiave Azure e log stanno in %LOCALAPPDATA%\JT
    enable_dpi_awareness()       # prima di creare la finestra: testo nitido su schermi con scala diversa da 100%
    root = tk.Tk()
    app = JTApp(root)
    try:
        root.mainloop()
    finally:
        app.shutdown()


if __name__ == '__main__':
    main()

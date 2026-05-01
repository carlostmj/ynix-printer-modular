from __future__ import annotations

import argparse
import sys
from .app import ThermalLabelApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="App de impressão térmica")
    parser.add_argument("files", nargs="*", help="PDF ou imagem")
    args = parser.parse_args(argv)

    try:
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
    except Exception:
        import tkinter as tk

        root = tk.Tk()
    ThermalLabelApp(root, args.files)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class LayerList(ttk.Frame):
    def __init__(self, parent: tk.Widget, on_select: Callable[[str], None]) -> None:
        super().__init__(parent, style="App.TFrame")
        self.on_select = on_select
        self._syncing = False
        self.tree = ttk.Treeview(self, columns=("type",), show="tree headings", height=7)
        self.tree.heading("#0", text="Camada")
        self.tree.heading("type", text="Tipo")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._select)

    def set_layers(self, overlays: list[dict[str, object]], selected_id: str | None) -> None:
        self._syncing = True
        try:
            current = tuple(self.tree.get_children())
            desired = tuple(str(overlay.get("id", "")) for overlay in reversed(overlays))
            if current != desired:
                self.tree.delete(*current)
                for overlay in reversed(overlays):
                    iid = str(overlay.get("id", ""))
                    flags = ("🔒 " if overlay.get("locked") else "") + ("" if overlay.get("visible", True) else "◌ ")
                    self.tree.insert("", "end", iid=iid, text=flags + str(overlay.get("name") or overlay.get("type", "Camada")), values=(overlay.get("type", ""),))
            else:
                for overlay in reversed(overlays):
                    iid = str(overlay.get("id", ""))
                    if self.tree.exists(iid):
                        flags = ("🔒 " if overlay.get("locked") else "") + ("" if overlay.get("visible", True) else "◌ ")
                        self.tree.item(iid, text=flags + str(overlay.get("name") or overlay.get("type", "Camada")), values=(overlay.get("type", ""),))
            if selected_id and self.tree.exists(selected_id):
                if tuple(self.tree.selection()) != (selected_id,):
                    self.tree.selection_set(selected_id)
                self.tree.focus(selected_id)
            elif self.tree.selection():
                self.tree.selection_remove(*self.tree.selection())
        finally:
            self._syncing = False

    def _select(self, _event=None) -> None:
        if self._syncing:
            return
        selection = self.tree.selection()
        if selection:
            self.on_select(selection[0])

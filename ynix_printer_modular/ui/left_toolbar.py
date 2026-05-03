from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(self.tip, text=self.text, padding=(8, 4), background="#202124", foreground="#f1f3f4")
        label.pack()

    def hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class LeftToolbar(ttk.Frame):
    def __init__(self, parent: tk.Widget, active_var: tk.StringVar, on_tool: Callable[[str], None]) -> None:
        super().__init__(parent, padding=(6, 8), style="LeftToolbar.TFrame")
        self.active_var = active_var
        self.on_tool = on_tool
        self.buttons: dict[str, ttk.Button] = {}
        tools = (
            ("select", "↖", "Selecionar e editar objetos"),
            ("move", "✥", "Mover objetos"),
            ("text", "T", "Texto: clique no canvas"),
            ("image", "▧", "Inserir imagem"),
            ("rect", "□", "Retângulo"),
            ("ellipse", "○", "Círculo / elipse"),
            ("line", "╱", "Linha"),
            ("barcode", "▥", "Código de barras editável"),
            ("qrcode", "▦", "QR Code editável"),
        )
        for tool, label, hint in tools:
            button = ttk.Button(self, text=label, width=3, command=lambda value=tool: self.on_tool(value))
            button.pack(fill="x", pady=(0, 6))
            ToolTip(button, hint)
            self.buttons[tool] = button
        self.refresh()

    def refresh(self) -> None:
        active = self.active_var.get()
        for tool, button in self.buttons.items():
            button.configure(style="SelectedTool.TButton" if tool == active else "Tool.TButton")

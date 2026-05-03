from __future__ import annotations

import tkinter as tk
from typing import Callable


class LayerContextMenu(tk.Menu):
    def __init__(self, parent: tk.Widget, command: Callable[[str], None]) -> None:
        super().__init__(parent, tearoff=False)
        for label, action in (
            ("Editar texto", "edit"),
            ("Duplicar", "duplicate"),
            ("Trazer para frente", "front"),
            ("Enviar para tras", "back"),
            ("Mover acima", "up"),
            ("Mover abaixo", "down"),
            ("Deletar", "delete"),
        ):
            self.add_command(label=label, command=lambda value=action: command(value))

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CanvasState:
    current_page: int = 0
    selected_layer_id: str | None = None
    active_tool: str = "select"
    snap_enabled: bool = False
    grid_size: int = 8
    zoom: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def snap(self, value: float) -> float:
        if not self.snap_enabled or self.grid_size <= 1:
            return value
        return round(value / self.grid_size) * self.grid_size

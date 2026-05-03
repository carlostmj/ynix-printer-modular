from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .layer import Layer
from .models import CanvasSpec, PrintConfig


@dataclass
class YnixProject:
    canvas: CanvasSpec
    layers_by_page: dict[int, list[Layer]] = field(default_factory=dict)
    source_files: list[Path] = field(default_factory=list)
    page_adjustments: dict[int, dict[str, Any]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    print_config: PrintConfig | None = None
    version: int = 1

    def layers(self, page: int) -> list[Layer]:
        return self.layers_by_page.setdefault(page, [])

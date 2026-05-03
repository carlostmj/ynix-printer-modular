from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_layer_id() -> str:
    return f"layer-{uuid4().hex[:10]}"


@dataclass
class Layer:
    id: str = field(default_factory=new_layer_id)
    type: str = "text"
    name: str = "Camada"
    x: float = 0.0
    y: float = 0.0
    w: float = 160.0
    h: float = 48.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    text: str = ""
    font_family: str = "DejaVu Sans"
    font_size: int = 28
    bold: bool = False
    italic: bool = False
    color: str = "#000000"
    align: str = "left"
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_overlay(cls, overlay: dict[str, Any]) -> "Layer":
        metadata = {k: v for k, v in overlay.items() if k not in cls._known_keys()}
        layer_type = str(overlay.get("type", "text"))
        name = str(overlay.get("name") or _default_name(layer_type, overlay))
        return cls(
            id=str(overlay.get("id") or new_layer_id()),
            type=layer_type,
            name=name,
            x=float(overlay.get("x", 0)),
            y=float(overlay.get("y", 0)),
            w=float(overlay.get("w", 160)),
            h=float(overlay.get("h", 48)),
            rotation=float(overlay.get("rotation", 0)),
            scale_x=float(overlay.get("scale_x", 1.0)),
            scale_y=float(overlay.get("scale_y", 1.0)),
            visible=bool(overlay.get("visible", True)),
            locked=bool(overlay.get("locked", False)),
            opacity=float(overlay.get("opacity", 1.0)),
            text=str(overlay.get("text", "")),
            font_family=str(overlay.get("font_family", "DejaVu Sans")),
            font_size=int(overlay.get("font_size", 28)),
            bold=bool(overlay.get("bold", False)),
            italic=bool(overlay.get("italic", False)),
            color=str(overlay.get("color", "#000000")),
            align=str(overlay.get("align", "left")),
            path=str(overlay.get("path", "")),
            metadata=metadata,
        )

    @staticmethod
    def _known_keys() -> set[str]:
        return {
            "id",
            "type",
            "name",
            "x",
            "y",
            "w",
            "h",
            "rotation",
            "scale_x",
            "scale_y",
            "visible",
            "locked",
            "opacity",
            "text",
            "font_family",
            "font_size",
            "bold",
            "italic",
            "color",
            "align",
            "path",
        }

    def to_overlay(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "rotation": self.rotation,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "visible": self.visible,
            "locked": self.locked,
            "opacity": self.opacity,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "color": self.color,
            "align": self.align,
        }
        if self.text:
            data["text"] = self.text
        if self.path:
            data["path"] = self.path
        data.update(self.metadata)
        return data

    def ensure_name(self) -> None:
        if not self.name.strip():
            self.name = _default_name(self.type, self.to_overlay())

    def relative_path(self, base: Path) -> str:
        if not self.path:
            return ""
        try:
            return str(Path(self.path).resolve().relative_to(base.resolve()))
        except (OSError, ValueError):
            return self.path


def _default_name(layer_type: str, overlay: dict[str, Any]) -> str:
    if layer_type == "image":
        path = str(overlay.get("path", ""))
        return Path(path).name or "Imagem"
    if layer_type == "counter":
        return "Numeracao"
    if layer_type == "text":
        text = str(overlay.get("text", "")).strip()
        return text[:24] if text else "Texto"
    return layer_type.title()

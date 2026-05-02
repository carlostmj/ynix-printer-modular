from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


FieldKind = Literal["text", "int", "choice", "color", "bool"]


@dataclass(frozen=True)
class ModuleField:
    key: str
    label: str
    kind: FieldKind = "text"
    default: Any = ""
    choices: tuple[str, ...] = ()
    min_value: int = 0
    max_value: int = 9999


@dataclass(frozen=True)
class ElementModule:
    id: str
    title: str
    fields: tuple[ModuleField, ...]

    def supports(self, overlay: dict[str, object]) -> bool:
        if self.id == "text":
            return overlay.get("type") == "text"
        if self.id == "counter":
            return overlay.get("type") == "counter"
        if self.id in {"qrcode", "barcode", "shape"}:
            return overlay.get("type") == "shape" and overlay.get("shape") == self.id
        if self.id == "generic_shape":
            return overlay.get("type") == "shape"
        return False


TEXT_MODULE = ElementModule(
    "text",
    "Módulo de texto",
    (
        ModuleField("text", "Texto", "text", "Texto"),
        ModuleField("font_size", "Tamanho", "int", 28, min_value=6, max_value=600),
        ModuleField("font_family", "Fonte", "choice", "DejaVu Sans"),
        ModuleField("align", "Alinhamento", "choice", "left", ("left", "center", "right")),
        ModuleField("bold", "Negrito", "bool", False),
        ModuleField("italic", "Itálico", "bool", False),
        ModuleField("color", "Cor", "color", "#000000"),
    ),
)

COUNTER_MODULE = ElementModule(
    "counter",
    "Módulo de numeração",
    (
        ModuleField("start", "Início", "int", 1, min_value=0, max_value=999999),
        ModuleField("end", "Fim", "int", 100, min_value=0, max_value=999999),
        ModuleField("digits", "Zeros", "int", 0, min_value=0, max_value=12),
        ModuleField("prefix", "Prefixo", "text", ""),
        ModuleField("suffix", "Sufixo", "text", ""),
        ModuleField("font_size", "Tamanho", "int", 28, min_value=6, max_value=600),
    ),
)

QRCODE_MODULE = ElementModule(
    "qrcode",
    "Módulo de QR Code",
    (
        ModuleField("data", "Conteúdo", "text", "YNIX"),
        ModuleField("stroke_color", "Cor", "color", "#000000"),
        ModuleField("fill_color", "Fundo", "color", "none"),
        ModuleField("line_width", "Módulo", "int", 3, min_value=1, max_value=40),
    ),
)

BARCODE_MODULE = ElementModule(
    "barcode",
    "Módulo de código de barras",
    (
        ModuleField("data", "Conteúdo", "text", "YNIX"),
        ModuleField("stroke_color", "Cor", "color", "#000000"),
        ModuleField("line_width", "Largura barra", "int", 3, min_value=1, max_value=40),
    ),
)

SHAPE_MODULE = ElementModule(
    "generic_shape",
    "Módulo de forma",
    (
        ModuleField("stroke_color", "Linha", "color", "#000000"),
        ModuleField("fill_color", "Fundo", "color", "none"),
        ModuleField("line_width", "Espessura", "int", 3, min_value=1, max_value=40),
    ),
)

MODULES = (TEXT_MODULE, COUNTER_MODULE, QRCODE_MODULE, BARCODE_MODULE, SHAPE_MODULE)


def module_for_overlay(overlay: dict[str, object] | None) -> ElementModule | None:
    if not overlay:
        return None
    for module in MODULES:
        if module.supports(overlay):
            return module
    return None

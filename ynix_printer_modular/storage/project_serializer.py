from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ynix_printer_modular.domain.layer import Layer
from ynix_printer_modular.domain.models import CanvasSpec, PrintConfig
from ynix_printer_modular.domain.project import YnixProject


PROJECT_VERSION = 1


class ProjectFormatError(ValueError):
    pass


def project_to_dict(project: YnixProject, base_path: Path | None = None) -> dict[str, Any]:
    base = base_path.parent if base_path else Path.cwd()
    return {
        "version": project.version or PROJECT_VERSION,
        "canvas": {
            "width_mm": project.canvas.width_mm,
            "height_mm": project.canvas.height_mm,
            "dpi": project.canvas.dpi,
        },
        "sources": [_maybe_relative(path, base) for path in project.source_files],
        "layers": {
            str(page): [layer.to_overlay() for layer in layers]
            for page, layers in sorted(project.layers_by_page.items())
        },
        "settings": project.settings,
        "page_adjustments": {str(page): data for page, data in sorted(project.page_adjustments.items())},
        "print_config": None
        if project.print_config is None
        else {
            "printer_name": project.print_config.printer_name,
            "output_mode": project.print_config.output_mode,
            "quality": project.print_config.quality,
            "invert": project.print_config.invert,
        },
    }


def project_from_dict(data: dict[str, Any], base_path: Path | None = None) -> YnixProject:
    if not isinstance(data, dict):
        raise ProjectFormatError("Projeto invalido.")
    canvas_data = data.get("canvas")
    if not isinstance(canvas_data, dict):
        raise ProjectFormatError("Projeto sem canvas.")
    canvas = CanvasSpec(float(canvas_data["width_mm"]), float(canvas_data["height_mm"]), int(canvas_data["dpi"]))
    base = base_path.parent if base_path else Path.cwd()
    sources = [_resolve_path(str(path), base) for path in data.get("sources", []) if str(path).strip()]
    layers_by_page: dict[int, list[Layer]] = {}
    raw_layers = data.get("layers", {})
    if isinstance(raw_layers, dict):
        for key, items in raw_layers.items():
            if not isinstance(items, list):
                continue
            layers_by_page[int(key)] = [Layer.from_overlay(item) for item in items if isinstance(item, dict)]
    print_config = None
    raw_print = data.get("print_config")
    if isinstance(raw_print, dict):
        print_config = PrintConfig(
            printer_name=str(raw_print.get("printer_name", "")),
            output_mode=str(raw_print.get("output_mode", "Térmica TSPL")),
            quality=str(raw_print.get("quality", "Normal")),
            invert=bool(raw_print.get("invert", False)),
        )
    page_adjustments = {}
    raw_adjustments = data.get("page_adjustments", {})
    if isinstance(raw_adjustments, dict):
        page_adjustments = {int(key): dict(value) for key, value in raw_adjustments.items() if isinstance(value, dict)}
    return YnixProject(
        canvas=canvas,
        layers_by_page=layers_by_page,
        source_files=sources,
        page_adjustments=page_adjustments,
        settings=dict(data.get("settings", {})),
        print_config=print_config,
        version=int(data.get("version", PROJECT_VERSION)),
    )


def save_project(project: YnixProject, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project_to_dict(project, path), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_project(path: Path) -> YnixProject:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(str(exc)) from exc
    return project_from_dict(data, path)


def _maybe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except (OSError, ValueError):
        return str(path)


def _resolve_path(path: str, base: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else base / value

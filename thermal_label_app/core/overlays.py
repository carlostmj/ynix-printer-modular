from __future__ import annotations

from copy import deepcopy
from typing import Any

from thermal_label_app.domain.layer import Layer, new_layer_id


def normalize_overlay(overlay: dict[str, Any]) -> dict[str, Any]:
    layer = Layer.from_overlay(overlay)
    return layer.to_overlay()


def duplicate_overlay(overlay: dict[str, Any], dx: float = 12, dy: float = 12) -> dict[str, Any]:
    clone = deepcopy(normalize_overlay(overlay))
    clone["id"] = new_layer_id()
    clone["name"] = f"{clone.get('name', 'Camada')} copia"
    clone["x"] = float(clone.get("x", 0)) + dx
    clone["y"] = float(clone.get("y", 0)) + dy
    return clone


def reorder(overlays: list[dict[str, Any]], layer_id: str, action: str) -> bool:
    for index, overlay in enumerate(overlays):
        if overlay.get("id") != layer_id:
            continue
        if action == "front":
            overlays.append(overlays.pop(index))
            return True
        if action == "back":
            overlays.insert(0, overlays.pop(index))
            return True
        if action == "up" and index < len(overlays) - 1:
            overlays[index], overlays[index + 1] = overlays[index + 1], overlay
            return True
        if action == "down" and index > 0:
            overlays[index], overlays[index - 1] = overlays[index - 1], overlay
            return True
        return False
    return False

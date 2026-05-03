from __future__ import annotations

from ynix_printer_modular.domain.layer import Layer


class Document:
    def __init__(self) -> None:
        self.layers_by_page: dict[int, list[Layer]] = {}

    def layers(self, page: int) -> list[Layer]:
        return self.layers_by_page.setdefault(page, [])

    def selected(self, page: int, layer_id: str | None) -> Layer | None:
        if not layer_id:
            return None
        for layer in self.layers(page):
            if layer.id == layer_id:
                return layer
        return None

    def bring_to_front(self, page: int, layer_id: str) -> bool:
        layers = self.layers(page)
        for index, layer in enumerate(layers):
            if layer.id == layer_id:
                layers.append(layers.pop(index))
                return True
        return False

    def send_to_back(self, page: int, layer_id: str) -> bool:
        layers = self.layers(page)
        for index, layer in enumerate(layers):
            if layer.id == layer_id:
                layers.insert(0, layers.pop(index))
                return True
        return False

    def move_up(self, page: int, layer_id: str) -> bool:
        layers = self.layers(page)
        for index, layer in enumerate(layers[:-1]):
            if layer.id == layer_id:
                layers[index], layers[index + 1] = layers[index + 1], layer
                return True
        return False

    def move_down(self, page: int, layer_id: str) -> bool:
        layers = self.layers(page)
        for index, layer in enumerate(layers[1:], start=1):
            if layer.id == layer_id:
                layers[index], layers[index - 1] = layers[index - 1], layer
                return True
        return False

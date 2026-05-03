from __future__ import annotations

from ynix_printer_modular.printing import send_document


class CupsAdapter:
    def send_document(self, printer_name: str, payload: bytes) -> str:
        return send_document(printer_name, payload)

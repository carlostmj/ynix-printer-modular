from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Callable

from ynix_printer_modular.infrastructure.cups_adapter import CupsAdapter
from ynix_printer_modular.infrastructure.tspl_adapter import TsplAdapter
from ynix_printer_modular.utils.logger import get_logger


@dataclass(frozen=True)
class PrintResult:
    ok: bool
    message: str
    attempts: int


class PrintService:
    def __init__(self, cups: CupsAdapter | None = None, tspl: TsplAdapter | None = None, retries: int = 2) -> None:
        self.cups = cups or CupsAdapter()
        self.tspl = tspl or TsplAdapter()
        self.retries = max(0, retries)
        self.log = get_logger("print-service")

    def send(self, printer: str, payload: bytes, output_mode: str) -> PrintResult:
        sender: Callable[[str, bytes], str]
        sender = self.cups.send_document if output_mode == "normal" else self.tspl.send_raw
        last_error = ""
        for attempt in range(1, self.retries + 2):
            try:
                self.log.info("printing attempt=%s printer=%s mode=%s bytes=%s", attempt, printer, output_mode, len(payload))
                return PrintResult(True, sender(printer, payload), attempt)
            except Exception as exc:
                last_error = str(exc)
                self.log.exception("print attempt failed attempt=%s printer=%s mode=%s", attempt, printer, output_mode)
                if attempt <= self.retries:
                    sleep(min(2.0, 0.4 * attempt))
        return PrintResult(False, last_error, self.retries + 1)

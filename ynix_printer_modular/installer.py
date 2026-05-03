from __future__ import annotations

from .printers import DEFAULT_CONTRACT
from .printers.contracts import PrinterInstallInfo


DEFAULT_TOMATE_NAME = DEFAULT_CONTRACT.default_queue_name


def inspect_tomate(name: str = DEFAULT_TOMATE_NAME, uri: str | None = None) -> PrinterInstallInfo:
    return DEFAULT_CONTRACT.inspect(name, uri)


def install_or_repair_tomate(name: str = DEFAULT_TOMATE_NAME, uri: str | None = None) -> tuple[bool, str]:
    return DEFAULT_CONTRACT.install_or_repair(name, uri)

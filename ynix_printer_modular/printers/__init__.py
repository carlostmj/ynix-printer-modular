from __future__ import annotations

from .contracts import PrinterContract, PrinterInstallInfo, list_printers
from .models import GENERIC_CUPS, TOMATE_MDK_007


CONTRACTS: tuple[PrinterContract, ...] = (TOMATE_MDK_007, GENERIC_CUPS)
DEFAULT_CONTRACT: PrinterContract = TOMATE_MDK_007


def get_contract(contract_id: str | None = None) -> PrinterContract:
    if not contract_id:
        return DEFAULT_CONTRACT
    for contract in CONTRACTS:
        if contract.id == contract_id:
            return contract
    return DEFAULT_CONTRACT


def contract_names() -> list[str]:
    return [contract.display_name for contract in CONTRACTS]


def contract_by_display_name(display_name: str) -> PrinterContract:
    for contract in CONTRACTS:
        if contract.display_name == display_name:
            return contract
    return DEFAULT_CONTRACT

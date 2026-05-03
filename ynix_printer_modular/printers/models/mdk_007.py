from __future__ import annotations

from ..contracts import RawTsplPrinter


class TomateMdk007(RawTsplPrinter):
    id = "tomate_mdk_007"
    display_name = "Tomate MDK-007"
    default_queue_name = "Tomate_MDK_007"
    aliases = ("Tomate_MDK_007", "Tomate MDK 007", "MDK_007", "MDK-007")
    cups_model = "raw"


CONTRACT = TomateMdk007()

from __future__ import annotations

from ..contracts import RawTsplPrinter


class GenericCupsPrinter(RawTsplPrinter):
    id = "generic_cups"
    display_name = "Impressora CUPS normal"
    default_queue_name = "Impressora_Normal"
    aliases = ("CUPS", "Impressora normal", "Generic")
    cups_model = "everywhere"
    output_mode = "normal"


CONTRACT = GenericCupsPrinter()


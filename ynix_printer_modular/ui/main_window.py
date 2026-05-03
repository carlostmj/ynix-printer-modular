from __future__ import annotations


def create_app(root, files):
    from ynix_printer_modular.app import ThermalLabelApp

    return ThermalLabelApp(root, files)

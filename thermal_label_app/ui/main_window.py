from __future__ import annotations


def create_app(root, files):
    from thermal_label_app.app import ThermalLabelApp

    return ThermalLabelApp(root, files)

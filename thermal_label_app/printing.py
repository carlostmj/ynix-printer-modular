from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


class PrinterError(RuntimeError):
    pass


def send_raw(printer_name: str, payload: bytes) -> str:
    lp = shutil.which("lp")
    if not lp:
        raise PrinterError("Comando 'lp' não encontrado.")
    if not printer_name.strip():
        raise PrinterError("Informe o nome da impressora.")

    with tempfile.NamedTemporaryFile(prefix="tspl_", suffix=".bin", delete=False) as tmp:
        tmp.write(payload)
        path = tmp.name

    try:
        result = subprocess.run([lp, "-d", printer_name.strip(), "-o", "raw", path], check=True, capture_output=True, text=True)
        return (result.stdout + result.stderr).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def send_document(printer_name: str, payload: bytes, suffix: str = ".png") -> str:
    lp = shutil.which("lp")
    if not lp:
        raise PrinterError("Comando 'lp' não encontrado.")
    if not printer_name.strip():
        raise PrinterError("Informe o nome da impressora.")

    with tempfile.NamedTemporaryFile(prefix="thermal_label_doc_", suffix=suffix, delete=False) as tmp:
        tmp.write(payload)
        path = tmp.name

    try:
        result = subprocess.run([lp, "-d", printer_name.strip(), path], check=True, capture_output=True, text=True)
        return (result.stdout + result.stderr).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

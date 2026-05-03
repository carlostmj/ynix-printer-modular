from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import subprocess


@dataclass(frozen=True)
class PrinterInstallInfo:
    name: str
    uri: str
    installed: bool
    status: str
    command: list[str]
    contract_id: str
    display_name: str
    available_uris: list[str]


class PrinterContract(Protocol):
    id: str
    display_name: str
    default_queue_name: str
    aliases: tuple[str, ...]
    cups_model: str
    output_mode: str

    def detect_uri(self) -> str | None:
        ...

    def detect_uris(self) -> list[str]:
        ...

    def install_command(self, queue_name: str, uri: str) -> list[str]:
        ...

    def inspect(self, queue_name: str | None = None, uri: str | None = None) -> PrinterInstallInfo:
        ...

    def install_or_repair(self, queue_name: str | None = None, uri: str | None = None) -> tuple[bool, str]:
        ...


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        return str(exc)
    return (result.stdout + result.stderr).strip()


def list_cups_printers() -> list[str]:
    output = run_text(["lpstat", "-e"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def list_printers() -> list[str]:
    names: list[str] = []
    for command in (["lpstat", "-e"], ["lpstat", "-a"]):
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError:
            continue
        for line in result.stdout.splitlines():
            name = line.split()[0].strip()
            if name and name not in names:
                names.append(name)
        if names:
            break
    return names


def find_parallel_uri() -> str | None:
    for path in sorted(Path("/dev/usb").glob("lp*")):
        return f"parallel:{path}"
    output = run_text(["lpinfo", "-v"])
    for line in output.splitlines():
        if "parallel:" in line:
            return line.split()[-1]
    return None


def list_device_uris() -> list[str]:
    uris: list[str] = []
    for path in sorted(Path("/dev/usb").glob("lp*")):
        uris.append(f"parallel:{path}")
    output = run_text(["lpinfo", "-v"])
    for line in output.splitlines():
        parts = line.split()
        if parts:
            uri = parts[-1]
            if uri not in uris:
                uris.append(uri)
    return uris


class RawTsplPrinter:
    id = "raw_tspl"
    display_name = "TSPL Raw"
    default_queue_name = "TSPL_RAW"
    aliases: tuple[str, ...] = ()
    cups_model = "raw"
    output_mode = "tspl"

    def detect_uri(self) -> str | None:
        uris = self.detect_uris()
        return uris[0] if uris else None

    def detect_uris(self) -> list[str]:
        uris = list_device_uris()
        parallel_uris = [uri for uri in uris if uri.startswith("parallel:")]
        return parallel_uris + [uri for uri in uris if uri not in parallel_uris]

    def install_command(self, queue_name: str, uri: str) -> list[str]:
        return ["lpadmin", "-p", queue_name, "-E", "-v", uri, "-m", self.cups_model]

    def inspect(self, queue_name: str | None = None, uri: str | None = None) -> PrinterInstallInfo:
        name = queue_name or self.default_queue_name
        configured = run_text(["lpstat", "-v", name])
        cups_printers = list_cups_printers()
        installed = name in cups_printers or "device for" in configured
        if "device for" in configured and ":" in configured:
            selected_uri = configured.split(":", 1)[1].strip()
        else:
            selected_uri = uri or self.detect_uri() or "parallel:/dev/usb/lp0"

        if installed:
            status_parts = [
                "Detectada na lista CUPS.",
                run_text(["lpstat", "-p", name, "-l"]),
                configured,
            ]
            status = "\n".join(part for part in status_parts if part.strip())
        else:
            status = "Impressora ainda nao instalada no CUPS."

        return PrinterInstallInfo(
            name=name,
            installed=installed,
            status=status,
            uri=selected_uri,
            command=self.install_command(name, selected_uri),
            contract_id=self.id,
            display_name=self.display_name,
            available_uris=self.detect_uris(),
        )

    def install_or_repair(self, queue_name: str | None = None, uri: str | None = None) -> tuple[bool, str]:
        info = self.inspect(queue_name, uri)
        result = subprocess.run(info.command, check=False, capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return False, output or f"Falha ao executar: {' '.join(info.command)}"

        accept = subprocess.run(["cupsaccept", info.name], check=False, capture_output=True, text=True)
        enable = subprocess.run(["cupsenable", info.name], check=False, capture_output=True, text=True)
        details = "\n".join(part for part in (output, accept.stdout + accept.stderr, enable.stdout + enable.stderr) if part.strip())
        return True, details.strip() or "Impressora instalada/reparada com sucesso."

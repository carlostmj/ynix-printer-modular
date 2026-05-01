from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from .printing import send_document, send_raw


Payload = bytes
StatusCallback = Callable[["PrintJob"], None]


@dataclass
class PrintJob:
    id: int
    title: str
    printer: str
    quality: str
    payloads: list[Payload]
    output_mode: str = "tspl"
    status: str = "Pendente"
    error: str = ""
    cups_result: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    cancel_requested: bool = False


class PrintQueue:
    def __init__(self, on_change: StatusCallback):
        self._ids = count(1)
        self._queue: Queue[PrintJob] = Queue()
        self._jobs: dict[int, PrintJob] = {}
        self._on_change = on_change
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()

    def add(self, title: str, printer: str, quality: str, payloads: list[Payload], output_mode: str = "tspl") -> PrintJob:
        job = PrintJob(next(self._ids), title, printer, quality, payloads, output_mode)
        self._jobs[job.id] = job
        self._queue.put(job)
        self._on_change(job)
        return job

    def jobs(self) -> list[PrintJob]:
        return sorted(self._jobs.values(), key=lambda job: job.id)

    def get(self, job_id: int) -> PrintJob | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: int) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status in {"Concluido", "Erro", "Cancelado"}:
            return False
        job.cancel_requested = True
        if job.status == "Pendente":
            job.status = "Cancelado"
        self._on_change(job)
        return True

    def requeue(self, job_id: int) -> PrintJob | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return self.add(f"Reimpressao de #{job.id}", job.printer, job.quality, list(job.payloads), job.output_mode)

    def _run(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if job.cancel_requested or job.status == "Cancelado":
                job.status = "Cancelado"
                self._on_change(job)
                self._queue.task_done()
                continue
            try:
                job.status = "Imprimindo"
                self._on_change(job)
                results: list[str] = []
                for payload in job.payloads:
                    if job.cancel_requested:
                        job.status = "Cancelado"
                        self._on_change(job)
                        break
                    if job.output_mode == "normal":
                        result = send_document(job.printer, payload)
                    else:
                        result = send_raw(job.printer, payload)
                    if result:
                        results.append(result)
                else:
                    job.status = "Concluido"
                    job.cups_result = "\n".join(results)
                    self._on_change(job)
            except Exception as exc:
                job.status = "Erro"
                job.error = str(exc)
                self._on_change(job)
            finally:
                self._queue.task_done()

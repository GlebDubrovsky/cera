"""Потокобезопасное управление независимыми длительными задачами приложения."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Callable


@dataclass
class _Job:
    job_id: str
    status: str = "queued"
    total_count: int = 0
    candidate_count: int = 0
    processed_count: int = 0
    error_count: int = 0
    message: str = "Ожидает запуска"
    started_at: str | None = None
    finished_at: str | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class JobManager:
    """Запускает именованные workers и отдаёт UI их состояние без деталей потоков.

    Worker вызывается как ``worker(*args, stop_event=..., progress_callback=...)``.
    В памяти хранится только текущий запуск каждого ID; после завершения его
    можно безопасно запустить повторно, а активный или останавливаемый запуск
    нельзя случайно дублировать.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()

    def start(self, job_id: str, worker: Callable[..., Any], *args: Any) -> bool:
        """Запускает worker в daemon-потоке; возвращает False при активном дубле."""
        with self._lock:
            current = self._jobs.get(job_id)
            if current and current.status in {"queued", "running", "stopping"}:
                return False

            job = _Job(
                job_id=job_id,
                status="running",
                message="Задача запущена",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._jobs[job_id] = job
            job.thread = threading.Thread(
                target=self._execute,
                args=(job, worker, args),
                name=f"job-{job_id}",
                daemon=True,
            )
            job.thread.start()
            return True

    def _execute(self, job: _Job, worker: Callable[..., Any], args: tuple[Any, ...]) -> None:
        def report(**updates: Any) -> None:
            self.update(job.job_id, **updates)

        try:
            worker(*args, stop_event=job.stop_event, progress_callback=report)
        except Exception as error:
            with self._lock:
                job.status = "failed"
                job.message = f"Задача завершилась с ошибкой ({type(error).__name__})"
        else:
            with self._lock:
                if job.stop_event.is_set():
                    job.status = "stopped"
                    if job.message in {
                        "Остановка запрошена; завершается текущая операция",
                        "Приложение завершает работу",
                    }:
                        job.message = "Обработка остановлена"
                else:
                    job.status = "completed"
                    if job.message == "Задача запущена":
                        job.message = "Обработка завершена"
        finally:
            with self._lock:
                job.finished_at = datetime.now(timezone.utc).isoformat()

    def update(self, job_id: str, **updates: Any) -> None:
        """Применяет ограниченный набор счётчиков и сообщение о ходе задачи."""
        allowed = {"total_count", "candidate_count", "processed_count", "error_count", "message"}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for name, value in updates.items():
                if name in allowed:
                    setattr(job, name, value)

    def stop(self, job_id: str) -> bool:
        """Запрашивает остановку; worker проверяет сигнал между единицами работы."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running", "stopping"}:
                return False
            job.stop_event.set()
            job.status = "stopping"
            job.message = "Остановка запрошена; завершается текущая операция"
            return True

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Возвращает UI-safe snapshot, не включая Event и Thread объекты."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {
                    "job_id": job_id,
                    "status": "idle",
                    "total_count": 0,
                    "candidate_count": 0,
                    "processed_count": 0,
                    "error_count": 0,
                    "message": "Ожидает запуска",
                    "started_at": None,
                    "finished_at": None,
                }
            return {
                "job_id": job.job_id,
                "status": job.status,
                "total_count": job.total_count,
                "candidate_count": job.candidate_count,
                "processed_count": job.processed_count,
                "error_count": job.error_count,
                "message": job.message,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }

    def shutdown(self, join_timeout: float = 2.0) -> None:
        """Сигнализирует workers об остановке и ждёт ограниченное время."""
        with self._lock:
            active_jobs = [
                job for job in self._jobs.values()
                if job.status in {"queued", "running", "stopping"}
            ]
            for job in active_jobs:
                job.stop_event.set()
                job.status = "stopping"
                job.message = "Приложение завершает работу"

        for job in active_jobs:
            if job.thread is not None:
                job.thread.join(timeout=join_timeout)

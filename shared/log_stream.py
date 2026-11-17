import asyncio
import contextvars
import json
from pathlib import Path
import queue
import sys
import threading
import time
import uuid
from typing import Any, Callable


class LogSession:
    def __init__(self) -> None:
        self.messages: queue.Queue[str] = queue.Queue()
        self.done = threading.Event()
        self.finished_at: float | None = None

    def finish(self) -> None:
        self.finished_at = time.monotonic()
        self.done.set()


_active_session: contextvars.ContextVar[LogSession | None] = contextvars.ContextVar(
    "active_log_session", default=None
)
_sessions: dict[str, LogSession] = {}
_sessions_lock = threading.Lock()
LOG_FILE_PATH = Path(__file__).resolve().parents[1] / "logs.txt"
_log_file_lock = threading.Lock()


def _append_log_archive(text: str) -> None:
    """Append captured output so clearing the browser panel never loses logs."""
    with _log_file_lock:
        with LOG_FILE_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(text)


class _LogRoutingStdout:
    def __init__(self, original: Any) -> None:
        self._original = original

    def write(self, text: str) -> int:
        session = _active_session.get()
        if session is None:
            return self._original.write(text)
        if text:
            try:
                _append_log_archive(text)
            except OSError:
                self._original.write(
                    "[LOG_STREAM][ARCHIVE][FAILURE] Не удалось записать сообщение в logs.txt.\n"
                )
                self._original.flush()
            session.messages.put(text)
        return len(text)

    def flush(self) -> None:
        if _active_session.get() is None:
            self._original.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _install_stdout_router() -> None:
    if not isinstance(sys.stdout, _LogRoutingStdout):
        sys.stdout = _LogRoutingStdout(sys.stdout)


def _normalize_log_id(log_id: str) -> str | None:
    try:
        return str(uuid.UUID(log_id))
    except (ValueError, AttributeError, TypeError):
        return None


def _purge_finished_sessions() -> None:
    expired_before = time.monotonic() - 600
    for session_id, session in list(_sessions.items()):
        if session.finished_at is not None and session.finished_at < expired_before:
            _sessions.pop(session_id, None)


def get_or_create_session(log_id: str) -> LogSession | None:
    session_id = _normalize_log_id(log_id)
    if session_id is None:
        return None

    with _sessions_lock:
        _purge_finished_sessions()
        session = _sessions.get(session_id)
        if session is None:
            session = LogSession()
            _sessions[session_id] = session
        return session


def get_session(log_id: str) -> LogSession | None:
    session_id = _normalize_log_id(log_id)
    if session_id is None:
        return None

    with _sessions_lock:
        _purge_finished_sessions()
        return _sessions.get(session_id)


def run_with_log_capture(
    log_id: str, function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    session = get_or_create_session(log_id)
    if session is None:
        return function(*args, **kwargs)

    token = _active_session.set(session)
    try:
        return function(*args, **kwargs)
    finally:
        _active_session.reset(token)
        session.finish()


async def stream_session(log_id: str):
    session_id = _normalize_log_id(log_id)
    if session_id is None:
        yield "event: done\ndata: null\n\n"
        return

    session = get_session(session_id)
    while session is None:
        await asyncio.sleep(0.1)
        session = get_session(session_id)

    try:
        while True:
            try:
                message = session.messages.get_nowait()
            except queue.Empty:
                if session.done.is_set():
                    break
                await asyncio.sleep(0.1)
                continue

            yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"

        yield "event: done\ndata: null\n\n"
    finally:
        if session.done.is_set():
            with _sessions_lock:
                if _sessions.get(session_id) is session:
                    _sessions.pop(session_id, None)


_install_stdout_router()

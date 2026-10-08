"""Production-managed application logging.

The packaged backend enables this module through ``AIGATOR_MANAGED_LOGGING``.
It keeps application and Uvicorn diagnostics in a bounded local text log while
leaving development-server logging unchanged.
"""
from __future__ import annotations

import atexit
import logging
import os
import queue
import sys
import time
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path


APP_LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_RETENTION_DAYS = 30
TRUNCATION_MARKER = b"\n[log record truncated]\n"


def _default_log_dir() -> Path:
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local" / "AIGator" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "AIGator"
    return Path.home() / ".local" / "state" / "AIGator" / "logs"


LOG_DIR = _default_log_dir()
LOG_FILE = LOG_DIR / "gator_backend.log"
LEGACY_LOG_FILE = LOG_DIR / "aigator.log"


def _bounded_utf8_tail(data: bytes, limit: int) -> bytes:
    """Return at most *limit* bytes that independently decode as UTF-8."""
    if len(data) <= limit:
        return data.decode("utf-8", "ignore").encode("utf-8")
    return data[-limit:].decode("utf-8", "ignore").encode("utf-8")


def _normalize_file(path: Path, max_bytes: int) -> None:
    """Bound an existing log while retaining its newest valid UTF-8 content."""
    if not path.exists():
        return
    data = path.read_bytes()
    bounded = _bounded_utf8_tail(data, max_bytes)
    if bounded != data:
        path.write_bytes(bounded)


def migrate_legacy_logs(max_bytes: int = APP_LOG_MAX_BYTES) -> None:
    """Move legacy production logs to the managed names and normalize them."""
    pairs = (
        (LEGACY_LOG_FILE, LOG_FILE),
        (LEGACY_LOG_FILE.with_suffix(".1.log"), LOG_FILE.with_suffix(".1.log")),
    )
    for legacy, current in pairs:
        try:
            if legacy.exists() and not current.exists():
                legacy.replace(current)
            elif legacy.exists():
                legacy.unlink()
            _normalize_file(current, max_bytes)
        except OSError:
            pass


class StrictRotatingFileHandler(logging.Handler):
    """UTF-8 file handler that never lets either retained file exceed its cap."""

    terminator = "\n"

    def __init__(self, filename: Path, max_bytes: int = APP_LOG_MAX_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        super().__init__()
        self.filename = Path(filename)
        self.max_bytes = max_bytes
        self.backup = self.filename.with_suffix(".1.log")
        self._stream = None
        try:
            _normalize_file(self.filename, self.max_bytes)
            _normalize_file(self.backup, self.max_bytes)
        except OSError:
            pass

    def _open(self):
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        return open(self.filename, "ab")

    def _ensure_stream(self):
        if self._stream is None:
            self._stream = self._open()

    def _rotate(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self.backup.unlink(missing_ok=True)
        if self.filename.exists():
            self.filename.replace(self.backup)
        self._stream = self._open()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            data = (self.format(record) + self.terminator).encode("utf-8", "backslashreplace")
            if len(data) > self.max_bytes:
                budget = max(0, self.max_bytes - len(TRUNCATION_MARKER))
                data = data[:budget].decode("utf-8", "ignore").encode("utf-8")
                data += TRUNCATION_MARKER[: self.max_bytes - len(data)]
            self.acquire()
            try:
                self._ensure_stream()
                if self._stream.tell() + len(data) > self.max_bytes:
                    self._rotate()
                self._stream.write(data)
                self._stream.flush()
            finally:
                self.release()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            super().close()
        finally:
            self.release()

    def expire_active_if_older(self, cutoff: float) -> bool:
        """Replace an expired active file safely while the listener is running."""
        self.acquire()
        try:
            if not self.filename.exists() or self.filename.stat().st_mtime >= cutoff:
                return False
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self.filename.unlink(missing_ok=True)
            self._stream = self._open()
            return True
        finally:
            self.release()


class _NonBlockingQueueHandler(QueueHandler):
    """Drop a record when the listener is saturated rather than blocking work."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__(log_queue)
        self.dropped_records = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_records += 1


_listener: QueueListener | None = None
_queue_handler: _NonBlockingQueueHandler | None = None
_file_handler: StrictRotatingFileHandler | None = None


def cleanup_old_logs(now: float | None = None) -> int:
    """Remove managed application logs older than the retention period."""
    now = time.time() if now is None else now
    cutoff = now - LOG_RETENTION_DAYS * 24 * 60 * 60
    removed = 0
    for path in (
        LOG_FILE,
        LOG_FILE.with_suffix(".1.log"),
        LEGACY_LOG_FILE,
        LEGACY_LOG_FILE.with_suffix(".1.log"),
    ):
        try:
            # The active file is owned by the listener while the backend is
            # running. Startup cleanup still handles an old active file before
            # the listener is created.
            if path == LOG_FILE and _listener is not None and _file_handler is not None:
                if _file_handler.expire_active_if_older(cutoff):
                    removed += 1
                continue
            if path.exists() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logging.getLogger(__name__).warning("Unable to remove expired log file %s", path)
    return removed


def enabled() -> bool:
    return os.environ.get("AIGATOR_MANAGED_LOGGING") == "1"


def configure_production_logging() -> bool:
    """Configure the packaged backend's managed, non-blocking log pipeline."""
    global _listener, _queue_handler, _file_handler
    if not enabled():
        return False
    if _listener is not None:
        return True

    try:
        migrate_legacy_logs()
        cleanup_old_logs()
        _file_handler = StrictRotatingFileHandler(LOG_FILE)
        _file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        log_queue: queue.Queue = queue.Queue(maxsize=10_000)
        _queue_handler = _NonBlockingQueueHandler(log_queue)
        _listener = QueueListener(log_queue, _file_handler, respect_handler_level=True)
        _listener.start()

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(_queue_handler)
        root.setLevel(logging.INFO)
        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.propagate = True
        atexit.register(shutdown_production_logging)
        logging.getLogger(__name__).info("Managed production logging initialized")
        return True
    except Exception:
        _listener = None
        _queue_handler = None
        _file_handler = None
        return False


def shutdown_production_logging() -> None:
    global _listener, _queue_handler, _file_handler
    stopped = _listener is None
    if _listener is not None:
        try:
            _listener.stop()
            stopped = True
        except Exception:
            pass
        _listener = None
    _queue_handler = None
    if _file_handler is not None and stopped:
        _file_handler.close()
    if stopped:
        _file_handler = None

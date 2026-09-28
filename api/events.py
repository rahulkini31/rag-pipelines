"""In-memory event bus for live status updates and console logs between pipeline and SSE clients."""

import asyncio
import logging
import sys
import time
from io import StringIO
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import StreamingResponse


class LogCapture(logging.Handler):
    """Logging handler that captures log records and broadcasts to event bus."""

    def __init__(self, event_bus: "EventBus") -> None:
        super().__init__()
        self.event_bus = event_bus
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Broadcast to all tenants since logs are system-wide
            for tenant_id in self.event_bus._queues:
                self.event_bus.publish(
                    tenant_id,
                    "console_log",
                    {
                        "level": record.levelname,
                        "logger": record.name,
                        "message": msg,
                        "timestamp": time.time(),
                    },
                )
        except Exception:
            pass


class StdoutCapture:
    """Captures stdout/stderr and broadcasts to event bus."""

    def __init__(self, event_bus: "EventBus", stream_name: str) -> None:
        self.event_bus = event_bus
        self.stream_name = stream_name
        self._buffer = StringIO()
        self._original = getattr(sys, stream_name)

    def write(self, data: str) -> None:
        self._original.write(data)
        if data.strip():
            # Split by lines to avoid huge payloads
            for line in data.rstrip("\n").split("\n"):
                if line.strip():
                    self.event_bus.publish(
                        "system",
                        "console_log",
                        {
                            "level": "INFO" if self.stream_name == "stdout" else "ERROR",
                            "logger": f"sys.{self.stream_name}",
                            "message": line.rstrip(),
                            "timestamp": time.time(),
                        },
                    )

    def flush(self) -> None:
        self._original.flush()


class EventBus:
    """Simple in-memory pub/sub for tenant-scoped status events and console logs."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._global_handlers: list[Callable[[dict[str, Any]], None]] = []
        self._log_handler: LogCapture | None = None
        self._stdout_capture: StdoutCapture | None = None
        self._stderr_capture: StdoutCapture | None = None

    def subscribe(self, tenant_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.setdefault(tenant_id, []).append(queue)
        return queue

    def unsubscribe(self, tenant_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._queues.get(tenant_id, [])
        if queue in queues:
            queues.remove(queue)

    def publish(self, tenant_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "tenant_id": tenant_id,
            "timestamp": time.time(),
            "payload": payload,
        }
        for queue in self._queues.get(tenant_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception:
                pass

    def on_event(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self._global_handlers.append(handler)

    def start_log_capture(self) -> None:
        """Start capturing Python logs and stdout/stderr."""
        if self._log_handler is None:
            self._log_handler = LogCapture(self)
            # Capture root logger
            logging.getLogger().addHandler(self._log_handler)
            logging.getLogger().setLevel(logging.INFO)
            # Also capture uvicorn access logs
            uvicorn_access_logger = logging.getLogger("uvicorn.access")
            uvicorn_access_logger.addHandler(self._log_handler)
            uvicorn_access_logger.setLevel(logging.INFO)
            # Capture uvicorn error logs
            uvicorn_error_logger = logging.getLogger("uvicorn.error")
            uvicorn_error_logger.addHandler(self._log_handler)
            uvicorn_error_logger.setLevel(logging.INFO)

        if self._stdout_capture is None:
            self._stdout_capture = StdoutCapture(self, "stdout")
            sys.stdout = self._stdout_capture

        if self._stderr_capture is None:
            self._stderr_capture = StdoutCapture(self, "stderr")
            sys.stderr = self._stderr_capture

    def stop_log_capture(self) -> None:
        """Stop capturing and restore original streams."""
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None
        if self._stdout_capture:
            sys.stdout = self._stdout_capture._original
            self._stdout_capture = None
        if self._stderr_capture:
            sys.stderr = self._stderr_capture._original
            self._stderr_capture = None


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def init_log_capture() -> None:
    """Initialize log capture for the application."""
    bus = get_event_bus()
    bus.start_log_capture()


def publish_status(tenant_id: str, event_type: str, payload: dict[str, Any]) -> None:
    get_event_bus().publish(tenant_id, event_type, payload)


def publish_status_update(tenant_id: str, action: str, payload: dict[str, Any]) -> None:
    """Publish a generic status_update event; UI refreshes on this type."""
    publish_status(tenant_id, "status_update", {"action": action, **payload})


async def console_events_stream(request: Request, tenant_id: str) -> StreamingResponse:
    """SSE endpoint for real-time console logs."""
    bus = get_event_bus()
    queue = bus.subscribe(tenant_id)

    async def event_generator() -> str:
        try:
            # Send initial connected event
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    if event["type"] == "console_log":
                        payload = event["payload"]
                        data = f"[{payload['timestamp']:.0f}] {payload['level']} {payload['logger']}: {payload['message']}"
                        yield f"event: console\ndata: {data}\n\n"
                    elif event["type"] == "heartbeat":
                        yield f"event: heartbeat\ndata: {event['payload']}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {{\"tenant_id\": \"{tenant_id}\"}}\n\n"
        finally:
            bus.unsubscribe(tenant_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
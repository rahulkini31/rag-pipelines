"""Telemetry and live events endpoints."""

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .auth import CognitoUser, get_current_user
from .events import console_events_stream, get_event_bus

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.get("/summary")
async def telemetry_summary(user: CognitoUser = Depends(get_current_user)) -> dict:
    # Placeholder; aggregate summary can be enriched from Phoenix in future work.
    return {
        "tenant_id": user.tenant_id,
        "total_documents": 0,
        "successful_ingestions": 0,
        "failed_ingestions": 0,
        "average_stage_duration_ms": 0.0,
    }


@router.get("/traces")
async def list_traces(
    doc_id: str | None = None,
    limit: int = 50,
    user: CognitoUser = Depends(get_current_user),
) -> dict:
    # Placeholder; query Phoenix via OpenTelemetry API in future work.
    return {"tenant_id": user.tenant_id, "doc_id": doc_id, "traces": []}


@router.get("/events")
async def events_stream(request: Request, user: CognitoUser = Depends(get_current_user)) -> StreamingResponse:
    """Server-Sent Events stream for live document status updates."""
    bus = get_event_bus()
    queue = bus.subscribe(user.tenant_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send an initial connected event so the UI knows the stream is alive.
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"event: {event['type']}\ndata: {__import__('json').dumps(event['payload'])}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {{\"tenant_id\": \"{user.tenant_id}\"}}\n\n"
        finally:
            bus.unsubscribe(user.tenant_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/console")
async def console_stream(request: Request, user: CognitoUser = Depends(get_current_user)) -> StreamingResponse:
    """Server-Sent Events stream for real-time console logs."""
    return await console_events_stream(request, user.tenant_id)

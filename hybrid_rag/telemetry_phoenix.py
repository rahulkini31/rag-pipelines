"""Arize Phoenix tracing for the document ingestion pipeline."""

import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

import phoenix as px
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
from phoenix.otel import register

tracer: trace.Tracer | None = None


def init_phoenix_telemetry(
    project_name: str = "docling-qdrant-ingestion", launch_local_ui: bool = True
) -> trace.Tracer:
    """Start Phoenix locally and instrument LangChain and OpenAI-compatible calls."""
    if launch_local_ui:
        try:
            session = px.launch_app()
            print(f"Arize Phoenix UI running at: {session.url}")
        except Exception as exc:
            print(f"Phoenix UI unavailable; continuing without local UI: {exc}")

    try:
        tracer_provider = register(
            project_name=project_name,
            endpoint=os.getenv(
                "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"
            ),
        )
    except AttributeError as exc:
        if "_headers" not in str(exc):
            raise
        tracer_provider = trace.get_tracer_provider()
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    global tracer
    tracer = trace.get_tracer(project_name)
    return tracer


@contextmanager
def trace_pipeline_stage(
    stage_name: str,
    span_kind: str = "CHAIN",
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Trace a non-instrumented pipeline stage and record its duration/status."""
    if tracer is None:
        raise RuntimeError("Phoenix telemetry has not been initialized")
    with tracer.start_as_current_span(stage_name) as span:
        span.set_attribute("openinference.span.kind", span_kind)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        start_ts = time.perf_counter()
        try:
            yield span
            span.set_attribute(
                "stage.duration_ms", round((time.perf_counter() - start_ts) * 1000, 2)
            )
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
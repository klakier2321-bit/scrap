"""Tracing setup for the AI control layer."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def suppress_crewai_trace_console() -> None:
    """Disable CrewAI's interactive first-run trace prompts inside server runtime."""

    try:
        from crewai.events.listeners.tracing import first_time_trace_handler, utils
    except Exception:  # noqa: BLE001
        return

    utils.should_auto_collect_first_time_traces = lambda: False  # type: ignore[assignment]
    first_time_trace_handler.should_auto_collect_first_time_traces = (  # type: ignore[attr-defined]
        lambda: False
    )
    first_time_trace_handler.prompt_user_for_trace_viewing = (  # type: ignore[attr-defined]
        lambda timeout_seconds=20: False
    )
    first_time_trace_handler.FirstTimeTraceHandler._show_tracing_declined_message = (  # type: ignore[attr-defined]
        lambda self: None
    )
    first_time_trace_handler.FirstTimeTraceHandler._display_ephemeral_trace_link = (  # type: ignore[attr-defined]
        lambda self: None
    )
    first_time_trace_handler.FirstTimeTraceHandler._show_local_trace_message = (  # type: ignore[attr-defined]
        lambda self: None
    )


def setup_tracing(app: FastAPI, settings: Any) -> None:
    """Initialize OpenTelemetry only once for the current process."""

    if not settings.agent_tracing_enabled:
        return
    if getattr(setup_tracing, "_initialized", False):
        return

    resource = Resource.create(
        {
            "service.name": "crypto-ai-control",
            "service.namespace": "crypto-system",
            "deployment.environment": "local",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.agent_otlp_http_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    setup_tracing._initialized = True

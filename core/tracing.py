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

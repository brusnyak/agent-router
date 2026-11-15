"""OpenTelemetry instrumentation for the agent router.

Exports spans over OTLP HTTP to Arize Phoenix at
http://127.0.0.1:6006/v1/traces (running as a local Python process, no Docker).

Spans are additive wrappers around existing routing logic: nothing in the core
path is altered, and a failure here never breaks a run.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

_TRACER: Optional[object] = None


def _setup() -> Optional[object]:
    global _TRACER
    if _TRACER is not None:
        return _TRACER
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = os.environ.get("ROUTER_OTLP_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "agent-router",
                    "service.instance.id": os.environ.get("ROUTER_INSTANCE", "mac"),
                }
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("agent-router", "0.1.0")
    except Exception:
        _TRACER = False  # OTel unavailable: fail open, silently
    return _TRACER or None


def tracer():
    return _setup()


@contextmanager
def span(name: str, attrs: Optional[dict] = None) -> Iterator[Optional[object]]:
    tr = tracer()
    if not tr:
        yield None
        return
    with tr.start_as_current_span(name) as s:
        if s and attrs:
            for k, v in attrs.items():
                try:
                    s.set_attribute(k, v)
                except Exception:
                    pass
        yield s

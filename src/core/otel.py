"""OpenTelemetry integration — optional distributed tracing for PAGAL OS.

When enabled (``OTEL_ENABLED=true``), every agent run, LLM call, and tool
invocation is emitted as an OpenTelemetry span.  Spans are exported to a
configurable OTLP endpoint (default: ``http://localhost:4317``).

If the ``opentelemetry-api`` package is not installed the module degrades
gracefully — all public functions become no-ops.

Environment variables:
    OTEL_ENABLED        — set to "true" to enable (default: disabled)
    OTEL_SERVICE_NAME   — service name for spans (default: "pagal-os")
    OTEL_EXPORTER_OTLP_ENDPOINT — OTLP gRPC endpoint (default: localhost:4317)
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger("pagal_os")

_ENABLED = os.environ.get("OTEL_ENABLED", "").lower() in ("true", "1", "yes")
_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "pagal-os")

# Lazy-initialised tracer
_tracer: Any = None


def _get_tracer() -> Any:
    """Initialise and return the OpenTelemetry tracer (once).

    Returns the tracer object, or None if OTEL is disabled or packages
    are not installed.
    """
    global _tracer
    if _tracer is not None:
        return _tracer

    if not _ENABLED:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Try OTLP gRPC exporter first, fall back to console
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter()
        except ImportError:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter as HTTPExporter,
                )
                exporter = HTTPExporter()
            except ImportError:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter
                exporter = ConsoleSpanExporter()
                logger.info("OTEL: using ConsoleSpanExporter (install opentelemetry-exporter-otlp for OTLP)")

        resource = Resource.create({"service.name": _SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("pagal-os", "0.1.0")
        logger.info("OpenTelemetry tracing enabled (service=%s)", _SERVICE_NAME)
        return _tracer

    except ImportError:
        logger.debug("OpenTelemetry packages not installed — tracing disabled")
        return None
    except Exception as e:
        logger.warning("Failed to initialise OpenTelemetry: %s", e)
        return None


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Context manager that creates an OTEL span (or a no-op if disabled).

    Usage::

        with trace_span("llm_call", {"model": "gpt-4", "agent": "research"}) as span:
            result = call_llm(...)
            span.set_attribute("tokens", result["usage"]["total_tokens"])

    Args:
        name: Span name (e.g. "agent_run", "tool_call", "llm_call").
        attributes: Optional dict of span attributes.

    Yields:
        The OTEL span object (has ``set_attribute``, ``set_status``,
        ``record_exception`` methods) or a lightweight no-op stub.
    """
    tracer = _get_tracer()
    if tracer is None:
        yield _NoOpSpan()
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


class _NoOpSpan:
    """Lightweight stub returned when OpenTelemetry is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass

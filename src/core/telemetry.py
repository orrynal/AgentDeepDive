import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from fastapi import FastAPI

from src.config import settings

logger = structlog.get_logger()

_tracer_initialized = False

def initialize_telemetry(app: FastAPI | None = None):
    """Initialize OpenTelemetry tracer provider and optionally instrument FastAPI."""
    global _tracer_initialized
    if _tracer_initialized:
        return
        
    if not settings.enable_tracing:
        logger.info("OpenTelemetry Tracing is disabled.")
        return

    try:
        logger.info("Initializing OpenTelemetry Tracing", endpoint=settings.otlp_endpoint)
        
        # Define Resource attributes
        resource = Resource.create({
            "service.name": settings.app_name,
            "service.version": settings.app_version,
        })
        
        provider = TracerProvider(resource=resource)
        
        # Configure OTLP Exporter
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True)
            span_processor = BatchSpanProcessor(otlp_exporter)
            provider.add_span_processor(span_processor)
            logger.info("OpenTelemetry OTLP Exporter registered successfully", endpoint=settings.otlp_endpoint)
        except Exception as exporter_err:
            logger.error("Failed to register OpenTelemetry OTLP Exporter, falling back to Console", error=str(exporter_err))
            console_exporter = ConsoleSpanExporter()
            span_processor = BatchSpanProcessor(console_exporter)
            provider.add_span_processor(span_processor)
            
        trace.set_tracer_provider(provider)
        _tracer_initialized = True
        
        # Instrument FastAPI app if provided
        if app is not None:
            FastAPIInstrumentor().instrument_app(app)
            logger.info("FastAPI Application instrumented with OpenTelemetry")
            
    except Exception as e:
        logger.error("Failed to initialize OpenTelemetry Tracing", error=str(e))

def get_tracer():
    """Get the tracer instance for manual tracing."""
    return trace.get_tracer(settings.app_name)

def get_trace_context_keys() -> dict[str, str]:
    """Helper to return current trace and span ID for structured logging."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        ctx = span.get_span_context()
        # Format as standard hex strings
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x")
        }
    return {}

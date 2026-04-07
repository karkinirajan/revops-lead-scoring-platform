import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

# Fields that must never appear in logs
_PII_FIELDS = frozenset({"password", "hashed_password", "authorization", "x-api-key", "token", "secret"})


def _redact_headers(headers: dict) -> dict:
    return {k: "[REDACTED]" if k.lower() in _PII_FIELDS else v for k, v in headers.items()}


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        request.state.trace_id = trace_id

        start = time.perf_counter()
        response: Response | None = None

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "http_request",
                trace_id=trace_id,
                method=request.method,
                path=request.url.path,
                query=str(request.url.query) or None,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
                client_ip=request.client.host if request.client else None,
            )
            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
            return response
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "http_error",
                trace_id=trace_id,
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                error=str(exc),
                exc_info=True,
            )
            raise


def configure_logging(log_level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

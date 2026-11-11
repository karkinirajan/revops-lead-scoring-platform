import logging
import re
import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

# A caller's trace id is only kept if it looks like an id: it is written to the logs and sent back in a response header.
_TRACE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def trace_id_for(request: Request) -> str:
    supplied = request.headers.get("X-Trace-Id", "")
    return supplied if _TRACE_ID.fullmatch(supplied) else str(uuid.uuid4())


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = trace_id_for(request)
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
    level = logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

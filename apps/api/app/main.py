import time

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import router as v1_router
from app.auth.dependencies import AdminRequired
from app.config import get_settings
from app.database import check_db_health
from app.middleware.logging import StructuredLoggingMiddleware, configure_logging
from app.middleware.rate_limit import limiter

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="RevOps Lead Scoring Platform",
    description="Production lead scoring pipeline — ingest, normalize, score, sync.",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

# ---- Middleware ----
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Trace-Id"],
    expose_headers=["X-Trace-Id"],
)

# ---- Rate limiting ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]  # slowapi's handler is typed more narrowly than Starlette expects


# ---- Exception handlers ----
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 with where each problem is and what it is, but not the values sent (a password or token in a bad request must not be echoed back or logged)."""
    problems = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": problems})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import structlog

    log = structlog.get_logger(__name__)
    trace_id = getattr(request.state, "trace_id", "unknown")
    log.error("unhandled_exception", trace_id=trace_id, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "trace_id": trace_id},
    )


# ---- Observability endpoints ----
@app.get("/health", tags=["observability"])
def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/ready", tags=["observability"])
def ready():
    db_ok = check_db_health()
    if not db_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "db": "unreachable"},
        )
    return {"status": "ready", "db": "ok"}


@app.get("/metrics", tags=["observability"], dependencies=[AdminRequired])
def metrics():
    """Lightweight process metrics. In production, prefer Prometheus /metrics exporter."""
    import os
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "pid": os.getpid(),
        "user_cpu_seconds": usage.ru_utime,
        "system_cpu_seconds": usage.ru_stime,
        "max_rss_kb": usage.ru_maxrss,
    }


# ---- Versioned API routes ----
app.include_router(v1_router)

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api import chat, conversations, documents, goals, memories, planner, profile
from app.core.config import settings
from app.core.logging_config import configure_logging, log_event, request_id_var

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s (environment=%s, debug=%s)",
        settings.app_name,
        settings.environment,
        settings.debug,
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(memories.router)
app.include_router(documents.router)
app.include_router(planner.router)
app.include_router(profile.router)
app.include_router(goals.router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Kasih tiap request satu id, ikat ke semua log dalam request itu lewat
    contextvar, dan catat durasi total (Bagian 21: "request", "latency").

    Ini best-effort observability, bukan jalur bisnis -- kalau ada error di
    handler, middleware ini tidak boleh menyembunyikannya (exception tetap
    dilempar ulang), cuma menambahkan logging di sekitarnya.
    """
    request_id = str(uuid.uuid4())
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    log_event(logger, "request_started", method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger,
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger,
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }

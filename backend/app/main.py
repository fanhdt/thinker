import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import chat, conversations, documents, memories
from app.core.config import settings
from app.core.logging_config import configure_logging

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


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }

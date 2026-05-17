"""
FastAPI main application with Telegram MTProto client lifecycle.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import get_settings
from .database import init_db
from .telegram import start_telegram_client, stop_telegram_client
from .routers import (
    auth_router,
    files_router,
    folders_router,
    streaming_router,
    tv_router,
)

from . import bot

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

settings = get_settings()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""

    logger.info("Starting TelePlay Backend...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start telegram client INSIDE the active event loop
    await start_telegram_client()
    logger.info("Telegram client started")

    # Import bot handlers ONLY after client startup
    # This prevents different event loop attachment issues
    from . import bot  # noqa: F401

    yield

    logger.info("Shutting down...")

    # Stop telegram client gracefully
    await stop_telegram_client()
    logger.info("Telegram client stopped")


app = FastAPI(
    title="TelePlay API",
    description="Stream files from Telegram to Android TV and Web",
    version="1.0.0",
    lifespan=lifespan,
)


# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Allowed CORS origins
allowed_origins = [
    settings.web_base_url,
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Range"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(streaming_router, prefix="/api")
app.include_router(tv_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "healthy"}


# Mount static assets
if os.path.exists("app/static/assets"):
    app.mount(
        "/assets",
        StaticFiles(directory="app/static/assets"),
        name="assets",
    )


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve React SPA."""

    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API Endpoint not found")

    static_file_path = f"app/static/{full_path}"

    if os.path.exists(static_file_path) and os.path.isfile(static_file_path):
        return FileResponse(static_file_path)

    if os.path.exists("app/static/index.html"):
        return FileResponse("app/static/index.html")

    return {
        "message": "Backend running. Frontend not built/mounted (dev mode)."
    }


if __name__ == "__main__":
    import uvicorn

    # IMPORTANT:
    # reload=False prevents multiple event loops in production
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,
    )

import asyncio

# FIX FOR:
# Future attached to a different loop
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

from fastapi import FastAPI
from contextlib import asynccontextmanager

from .telegram import (
    start_telegram_client,
    stop_telegram_client,
)

from . import bot  # noqa


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await start_telegram_client()

    yield

    # Shutdown
    await stop_telegram_client()


app = FastAPI(
    title="TelePlay",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"status": "running"}

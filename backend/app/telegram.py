"""
PyroTGFork MTProto client for Telegram interactions.
Fully fixed Railway-compatible version.
"""

from .patch import Client
from pyrogram.types import Message
from .config import get_settings
from pathlib import Path
import logging

settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = BASE_DIR / "session"

logger = logging.getLogger(__name__)

clients = []


def get_session_name(index: int) -> str:
    return str(SESSION_DIR / f"bot_{index}")


# CREATE MAIN CLIENT IMMEDIATELY
# Prevents:
# AttributeError: 'NoneType' object has no attribute 'on_message'
main_token = settings.all_bot_tokens[0]

tg_client = Client(
    name=get_session_name(0),
    api_id=settings.telegram_api_id,
    api_hash=settings.telegram_api_hash,
    bot_token=main_token,
    ipv6=False,
    max_concurrent_transmissions=settings.telegram_client_concurrency,
    no_updates=False,
)

clients.append(tg_client)


async def start_one_client(i, token):
    global tg_client

    try:
        # Main client already exists
        if i == 0:
            client = tg_client
        else:
            client = Client(
                name=get_session_name(i),
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash,
                bot_token=token,
                ipv6=False,
                max_concurrent_transmissions=settings.telegram_client_concurrency,
                no_updates=True,
            )

            clients.append(client)

        if not client.is_connected:
            await client.start()

        client.pool_index = i

        me = await client.get_me()

        label = "Main" if i == 0 else "Helper"
        logger.info(
            "Client %d (%s) started -> @%s",
            i,
            label,
            me.username,
        )

    except Exception as e:
        logger.error("Client %d failed to start: %s", i, e)


async def start_all_clients():
    """
    IMPORTANT:
    Sequential startup fixes:
    got Future attached to a different loop
    """

    logger.info("Starting Telegram client(s)...")

    tokens = settings.all_bot_tokens

    # DO NOT USE asyncio.gather HERE
    # Pyrogram breaks on Railway with concurrent startup
    for i, token in enumerate(tokens):
        await start_one_client(i, token)


async def stop_one_client(c):
    try:
        if c.is_connected:
            await c.stop()
    except Exception:
        pass


async def stop_all_clients():
    for c in clients:
        await stop_one_client(c)


async def start_telegram_client():
    await start_all_clients()


async def stop_telegram_client():
    await stop_all_clients()


# HELPERS

async def get_message_from_channel(message_id: int) -> Message:
    if tg_client is None:
        raise RuntimeError("Telegram client not started")

    return await tg_client.get_messages(
        settings.telegram_storage_channel_id,
        message_id,
    )


async def forward_to_storage_channel(message: Message) -> Message:
    if tg_client is None:
        raise RuntimeError("Telegram client not started")

    return await message.copy(
        settings.telegram_storage_channel_id
    )


async def delete_from_storage_channel(
    message_ids: int | list[int]
) -> bool:
    if tg_client is None:
        return False

    try:
        await tg_client.delete_messages(
            settings.telegram_storage_channel_id,
            message_ids,
        )
        return True

    except Exception:
        return False

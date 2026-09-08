import asyncio
import logging

import httpx

from app.core.config import settings
from app.db.session import async_session_factory
from app.services import conversation_service, message_pipeline
from app.services.embedding_service import embedding_service
from app.services.llm import LLMServiceError, llm_service
from app.telegram.client import TelegramClient

logger = logging.getLogger(__name__)

POLL_ERROR_BACKOFF_SECONDS = 5


async def _handle_update(client: TelegramClient, update: dict) -> None:
    message = update.get("message")
    if message is None or "text" not in message:
        # Abaikan update yang bukan pesan teks seperti foto, sticker, join event, dst --
        # Thinker cuma paham teks untuk saat ini
        return
    chat_id = message["chat"]["id"]
    text = message["text"]

    async with async_session_factory() as session:
        try:
            user = await conversation_service.get_or_create_default_user(session)
            conversation = await conversation_service.get_or_create_conversation_for_telegram_chat(
                session, user.id, chat_id
            )
            result = await message_pipeline.process_incoming_message(
                session, llm_service, embedding_service, conversation, text
            )
          
        except LLMServiceError as exc:
            logger.error(
                "Gagal proses pesan Telegram dari chat %s: %s",
                chat_id,
                exc,
            )

            try:
                await client.send_message(
                chat_id,
                "Maaf ada gangguan sementara di sisi saya. Coba lagi sebentar yaa.",
                )
            except httpx.RequestError as exc:
                logger.error(
                    "Gagal mengirim pesan error ke chat %s: %s",
                    chat_id,
                    exc,
                )
            return
        try:
            await client.send_message(chat_id, result.reply)
        except httpx.RequestError as exc:
            logger.error(
                "Gagal mengirim response ke chat %s: %s",
                chat_id,
                exc,
            )


async def run_bot() -> None:
    """Loop long-polling utama. Jalankan lewat `uv run python -m app.telegram.bot`
    sebagai proses TERPISAH dari server FastAPI (`uvicorn`) -- keduanya
    independen, sama sama memanggil message_pipeline
    yang sama, tapi tidak saling bergantung"""

    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN belum diisi di .env. Buat bot lewat @botFather di"
            "Telegram, lalu isi tokennya."
        )

    client = TelegramClient(settings.telegram_bot_token)
    offset: int | None = None
    logger.info("Bot Telegram mulai polling...")
    try:
        while True:
            try:
                updates = await client.get_updates(offset)
            except Exception as exc:
                logger.error(
                    "Gagal getUpdates, retry dalam %ss: %s", POLL_ERROR_BACKOFF_SECONDS, exc
                )
                await asyncio.sleep(POLL_ERROR_BACKOFF_SECONDS)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                await _handle_update(client, update)
    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())

import logging

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
LONG_POLL_TIMEOUT_SECONDS = 30
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramClient:
    """Wrapper tipis di atas Telegram Bot API. Cuma 2 endpoint yang kita
    butuhkan: getUpdates (long-polling pesan masuk) dan sendMessage (kirim
    balasan). Sengaja tidak pakai library python-telegram-bot -- permukaan
    API yang dibutuhkan kecil, menambah dependency besar untuk ini berlebihan.
    """

    def __init__(self, bot_token: str, client: httpx.AsyncClient | None = None):
        self._base_url = f"{TELEGRAM_API_BASE}/bot{bot_token}"
        self._client = client or httpx.AsyncClient(timeout=LONG_POLL_TIMEOUT_SECONDS + 10)

    async def get_updates(self, offset: int | None = None) -> list[dict]:
        """Ambil update (pesan baru) yang belum diproses. `offset` adalah
        update_id terakhir yang sudah ditangani + 1 -- Telegram tidak akan
        mengirim ulang update yang sudah di-acknowledge lewat offset ini.
        """
        params: dict[str, int] = {"timeout": LONG_POLL_TIMEOUT_SECONDS}
        if offset is not None:
            params["offset"] = offset

        response = await self._client.get(f"{self._base_url}/getUpdates", params=params)
        response.raise_for_status()
        data = response.json()
        return data["result"]

    async def send_message(self, chat_id: int, text: str) -> None:
        """Kirim pesan teks ke chat_id. Otomatis melewati teks kosong dan
        memecah teks yang melebihi limit 4096 karakter dari Telegram jadi
        beberapa pesan berurutan.
        """
        if not text or not text.strip():
            logger.warning("Teks balasan kosong untuk chat %s, dilewati.", chat_id)
            return

        for i in range(0, len(text), TELEGRAM_MAX_MESSAGE_LENGTH):
            chunk = text[i : i + TELEGRAM_MAX_MESSAGE_LENGTH]
            response = await self._client.post(
                f"{self._base_url}/sendMessage", json={"chat_id": chat_id, "text": chunk}
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "sendMessage gagal untuk chat %s (status %s): %s",
                    chat_id, response.status_code, response.text,
                )
                raise

    async def close(self) -> None:
        await self._client.aclose()
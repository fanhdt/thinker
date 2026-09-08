import asyncio

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
LONG_POLL_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 10
SEND_MESSAGE_MAX_RETRIES = 3


class TelegramClient:
    """Wrapper tipis di atas Telegram Bot API.
    cuma 2 endpoint yang kita butuhkan :
    getUpdates (long-polling pesan masuk)
    dan sendMessage (kirim balasan). Sengaja tidak pakai
    library python-telegram-bot --permukaan
    API yang dibutuhkan kecil, menambah dependency besar
    untuk ini terlalu berlebihan"""

    def __init__(self, bot_token: str, client: httpx.AsyncClient | None = None):
        self._base_url = f"{TELEGRAM_API_BASE}/bot{bot_token}"
        self._client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

    async def get_updates(self, offset: int | None = None) -> list[dict]:
        """Ambil update (pesan baru) yang belum diproses. 'offset' adalah
        update_id terakhir yang ditangani + 1 --
        Telegram tidak mengirim ulang update yang sudah
        di acknowledge lewat offset ini
        """

        params: dict[str, int] = {"timeout": LONG_POLL_TIMEOUT_SECONDS}
        if offset is not None:
            params["offset"] = offset

        response = await self._client.get(f"{self._base_url}/getUpdates", 
        params=params, 
        timeout=LONG_POLL_TIMEOUT_SECONDS + 10)
        response.raise_for_status()
        data = response.json()
        return data["result"]

    async def send_message(self, chat_id: int, text: str) -> None:
        for attempt in range(SEND_MESSAGE_MAX_RETRIES):
            try:
                response = await self._client.post(
                    f"{self._base_url}/sendMessage", 
                    json={"chat_id": chat_id, "text": text}
                )
                response.raise_for_status()
                return
            except httpx.RequestError:
                if attempt == SEND_MESSAGE_MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2**attempt)

    async def close(self) -> None:
        await self._client.aclose()

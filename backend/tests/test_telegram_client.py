from unittest.mock import AsyncMock, MagicMock

import pytest

from app.telegram.client import TelegramClient


def _fake_httpx_client(json_response: dict, raise_for_status_ok: bool = True):
    fake_response = MagicMock()
    fake_response.json.return_value = json_response
    if raise_for_status_ok:
        fake_response.raise_for_status = MagicMock()
    else:
        fake_response.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.post = AsyncMock(return_value=fake_response)
    return fake_client


async def test_get_updates_returns_result_list():
    fake_httpx_client = _fake_httpx_client({"ok": True, "result": [{"update_id": 1}]})
    client = TelegramClient("fake-token", client=fake_httpx_client)

    updates = await client.get_updates()

    assert updates == [{"update_id": 1}]
    call_kwargs = fake_httpx_client.get.call_args.kwargs
    assert call_kwargs["params"] == {"timeout": 30}


async def test_get_updates_passes_offset_when_given():
    fake_httpx_client = _fake_httpx_client({"ok": True, "result": []})
    client = TelegramClient("fake-token", client=fake_httpx_client)

    await client.get_updates(offset=42)

    call_kwargs = fake_httpx_client.get.call_args.kwargs
    assert call_kwargs["params"] == {"timeout": 30, "offset": 42}


async def test_send_message_posts_chat_id_and_text():
    fake_httpx_client = _fake_httpx_client({"ok": True})
    client = TelegramClient("fake-token", client=fake_httpx_client)

    await client.send_message(chat_id=123, text="Halo!")

    call_kwargs = fake_httpx_client.post.call_args.kwargs
    assert call_kwargs["json"] == {"chat_id": 123, "text": "Halo!"}


async def test_get_updates_raises_on_http_error():
    fake_httpx_client = _fake_httpx_client({}, raise_for_status_ok=False)
    client = TelegramClient("fake-token", client=fake_httpx_client)

    with pytest.raises(Exception, match="HTTP error"):
        await client.get_updates()

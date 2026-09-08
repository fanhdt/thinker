import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm import LLMServiceError
from app.services.message_pipeline import MessagePipelineResult
from app.telegram.bot import _handle_update


class FakeSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _fake_session_factory(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def test_handle_update_ignores_messages_without_text():
    """Update berupa sticker/foto/dll tidak punya key 'text' -- Thinker
    cuma paham teks untuk saat ini, jadi harus diabaikan diam-diam."""
    fake_client = MagicMock()
    fake_client.send_message = AsyncMock()

    update = {"update_id": 1, "message": {"sticker": {}}}

    await _handle_update(fake_client, update)

    fake_client.send_message.assert_not_called()


async def test_handle_update_ignores_updates_without_message():
    """Update bertipe lain (mis. edited_message) tidak punya key 'message'."""
    fake_client = MagicMock()
    fake_client.send_message = AsyncMock()

    update = {"update_id": 1, "edited_message": {"text": "diedit"}}

    await _handle_update(fake_client, update)

    fake_client.send_message.assert_not_called()


async def test_handle_update_processes_text_message_and_replies():
    fake_client = MagicMock()
    fake_client.send_message = AsyncMock()
    fake_session = FakeSession()
    fake_user = MagicMock(id=uuid.uuid4())
    fake_conversation = MagicMock()

    update = {"update_id": 1, "message": {"chat": {"id": 999}, "text": "Halo Thinker"}}

    with (
        patch("app.telegram.bot.async_session_factory", new=_fake_session_factory(fake_session)),
        patch(
            "app.telegram.bot.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.telegram.bot.conversation_service.get_or_create_conversation_for_telegram_chat",
            new=AsyncMock(return_value=fake_conversation),
        ) as mock_get_conv,
        patch(
            "app.telegram.bot.message_pipeline.process_incoming_message",
            new=AsyncMock(
                return_value=MessagePipelineResult(
                    reply="Halo juga!", model="fake-model", used_planner=False
                )
            ),
        ),
    ):
        await _handle_update(fake_client, update)

    mock_get_conv.assert_called_once_with(fake_session, fake_user.id, 999)
    fake_client.send_message.assert_called_once_with(999, "Halo juga!")


async def test_handle_update_sends_fallback_message_on_pipeline_failure():
    fake_client = MagicMock()
    fake_client.send_message = AsyncMock()
    fake_session = FakeSession()
    fake_user = MagicMock(id=uuid.uuid4())
    fake_conversation = MagicMock()

    update = {"update_id": 1, "message": {"chat": {"id": 999}, "text": "Halo"}}

    with (
        patch("app.telegram.bot.async_session_factory", new=_fake_session_factory(fake_session)),
        patch(
            "app.telegram.bot.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.telegram.bot.conversation_service.get_or_create_conversation_for_telegram_chat",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch(
            "app.telegram.bot.message_pipeline.process_incoming_message",
            new=AsyncMock(side_effect=LLMServiceError("gagal")),
        ),
    ):
        await _handle_update(fake_client, update)

    fake_client.send_message.assert_called_once()
    call_args = fake_client.send_message.call_args.args
    assert call_args[0] == 999
    assert "gangguan" in call_args[1].lower()

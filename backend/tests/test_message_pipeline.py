import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm import LLMServiceError, Plan, PlanTask, TaskEvaluation
from app.services.message_pipeline import process_incoming_message


class FakeLLMService:
    """Duck-typed test double yang mengimplementasikan seluruh MessagePipelineLLM
    Protocol. Sama polanya dengan FakeLLMService di test_orchestrator_service.py,
    ditambah extract_fact & model yang dibutuhkan message_pipeline.
    """

    def __init__(self, needs_planning: bool = False, extraction=None):
        self.needs_planning = needs_planning
        self.extraction = extraction
        self.model = "fake-model"

    async def classify_message(self, message: str) -> bool:
        return self.needs_planning

    async def chat_with_history(self, history, *, system_instruction=None) -> str:
        return "balasan chat"

    async def create_plan(self, goal: str) -> Plan:
        return Plan(goal=goal, tasks=[PlanTask(description="Task 1")])

    async def execute_task(self, task_description: str, prior_context: str) -> str:
        return f"hasil dari {task_description}"

    async def evaluate_result(self, task_description: str, result: str) -> TaskEvaluation:
        return TaskEvaluation(is_correct=True, feedback="")

    async def extract_fact(self, message: str, existing_memories: list[str]):
        return self.extraction


class FakeSession:
    """Sesi DB palsu yang melacak commit/rollback -- dibutuhkan untuk membuktikan
    session.rollback() benar-benar terpanggil saat orchestrator gagal.
    """

    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _fake_conversation():
    conv = MagicMock()
    conv.id = uuid.uuid4()
    conv.user_id = uuid.uuid4()
    return conv


def _enter_pipeline_deps(stack: ExitStack, fake_user) -> None:
    stack.enter_context(
        patch("app.services.message_pipeline.conversation_service.add_message", new=AsyncMock())
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.conversation_service.get_messages",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        )
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.memory_service.retrieve_relevant_memories",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.memory_service.get_all_memories",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.document_service.retrieve_relevant_chunks",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch(
            "app.services.message_pipeline.goal_service.get_goals", new=AsyncMock(return_value=[])
        )
    )


async def test_process_incoming_message_returns_reply_on_success():
    fake_llm = FakeLLMService(needs_planning=False)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        result = await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Halo"
        )

    assert result.reply == "balasan chat"
    assert result.model == "fake-model"
    assert result.used_planner is False
    assert fake_session.committed is True


async def test_retrieval_failure_is_non_fatal():
    """Kalau embed_query gagal (mis. Gemini down), chat tetap harus jalan
    tanpa context_text -- ini regresi untuk perilaku graceful-degradation
    yang eksplisit di kode.
    """
    fake_llm = FakeLLMService(needs_planning=False)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(side_effect=LLMServiceError("gemini down"))
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        result = await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Halo"
        )

    assert result.reply == "balasan chat"


async def test_memory_created_when_fact_extracted():
    extraction = MagicMock(
        operation="CREATE", fact="User suka kopi tanpa gula", importance=4, target_index=None
    )
    fake_llm = FakeLLMService(needs_planning=False, extraction=extraction)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1])
    fake_embedder.embed_document = AsyncMock(return_value=[0.2])
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        mock_apply = stack.enter_context(
            patch(
                "app.services.message_pipeline.memory_service.apply_extraction",
                new=AsyncMock(),
            )
        )
        await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Aku suka kopi tanpa gula"
        )

    fake_embedder.embed_document.assert_called_once_with("User suka kopi tanpa gula")
    mock_apply.assert_called_once_with(
        fake_session,
        conversation.user_id,
        "CREATE",
        [],
        "User suka kopi tanpa gula",
        [0.2],
        4,
        None,
    )


async def test_memory_deleted_when_forget_requested():
    """`target_index` merujuk ke memory existing -- fact tidak perlu di-embed."""
    existing = MagicMock(content="User suka kopi")
    extraction = MagicMock(operation="DELETE", fact=None, importance=3, target_index=0)
    fake_llm = FakeLLMService(needs_planning=False, extraction=extraction)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1])
    fake_embedder.embed_document = AsyncMock()
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        stack.enter_context(
            patch(
                "app.services.message_pipeline.memory_service.get_all_memories",
                new=AsyncMock(return_value=[existing]),
            )
        )
        mock_apply = stack.enter_context(
            patch(
                "app.services.message_pipeline.memory_service.apply_extraction",
                new=AsyncMock(),
            )
        )
        await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Lupakan bahwa aku suka kopi"
        )

    fake_embedder.embed_document.assert_not_called()
    mock_apply.assert_called_once_with(
        fake_session, conversation.user_id, "DELETE", [existing], None, None, 3, 0
    )


async def test_memory_skipped_when_no_fact_extracted():
    fake_llm = FakeLLMService(needs_planning=False, extraction=None)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1])
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        mock_apply = stack.enter_context(
            patch(
                "app.services.message_pipeline.memory_service.apply_extraction",
                new=AsyncMock(),
            )
        )
        await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Apa kabar?"
        )

    mock_apply.assert_not_called()


async def test_planner_branch_returns_plan_result():
    fake_llm = FakeLLMService(needs_planning=True)
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1])
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        result = await process_incoming_message(
            fake_session, fake_llm, fake_embedder, conversation, "Rencanakan olahraga ringan"
        )

    assert result.used_planner is True
    assert result.plan_result is not None
    assert result.plan_result.executions[0].description == "Task 1"


async def test_orchestrator_failure_rolls_back_and_propagates():
    fake_llm = FakeLLMService(needs_planning=False)

    async def _failing_chat(history, *, system_instruction=None):
        raise LLMServiceError("gagal chat")

    fake_llm.chat_with_history = _failing_chat

    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1])
    fake_session = FakeSession()
    fake_user = MagicMock(preferences={})
    conversation = _fake_conversation()

    with ExitStack() as stack:
        _enter_pipeline_deps(stack, fake_user)
        with pytest.raises(LLMServiceError):
            await process_incoming_message(
                fake_session, fake_llm, fake_embedder, conversation, "Halo"
            )

    assert fake_session.rolled_back is True

from app.services.llm import MessagePlan, PlanTask, TaskOutcome
from app.services.orchestrator_service import handle_message


class FakeLLMService:
    def __init__(self, needs_planning: bool):
        self.needs_planning = needs_planning
        self.chat_with_history_calls: list[dict] = []
        self.classify_and_plan_calls: list[dict] = []

    async def classify_and_plan(self, message: str) -> MessagePlan:
        self.classify_and_plan_calls.append({"message": message})
        tasks = [PlanTask(description="Satu task saja")] if self.needs_planning else []
        return MessagePlan(needs_planning=self.needs_planning, tasks=tasks)

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str:
        self.chat_with_history_calls.append(
            {"history": history, "system_instruction": system_instruction}
        )
        return "balasan chat biasa"

    async def create_plan(self, goal: str):
        # Orchestrator sekarang selalu mengoper plan langsung dari
        # classify_and_plan ke run_plan(), jadi create_plan TIDAK seharusnya
        # pernah terpanggil lewat jalur ini -- kalau terpanggil, berarti ada
        # regresi (plan dibuat dua kali, dua kali biaya panggilan Gemini).
        raise AssertionError("create_plan tidak seharusnya terpanggil lewat orchestrator")

    async def execute_and_evaluate(self, task_description: str, prior_context: str) -> TaskOutcome:
        return TaskOutcome(
            result=f"hasil dari {task_description} (konteks: {prior_context!r})",
            is_correct=True,
            feedback="",
        )


async def test_simple_message_uses_chat_not_planner():
    fake_llm = FakeLLMService(needs_planning=False)
    result = await handle_message(fake_llm, "Halo, apa kabar?", history=[], context_text=None)

    assert result.used_planner is False
    assert result.plan_result is None
    assert result.reply == "balasan chat biasa"
    assert len(fake_llm.chat_with_history_calls) == 1


async def test_complex_goal_uses_planner_not_chat():
    fake_llm = FakeLLMService(needs_planning=True)
    result = await handle_message(
        fake_llm, "Rencanakan liburan ke Bali", history=[], context_text=None
    )

    assert result.used_planner is True
    assert result.plan_result is not None
    assert len(result.plan_result.executions) == 1
    assert len(fake_llm.classify_and_plan_calls) == 1
    assert len(fake_llm.chat_with_history_calls) == 0


async def test_context_text_reaches_chat_path():
    fake_llm = FakeLLMService(needs_planning=False)
    context = "Fakta: user alergi kacang."

    await handle_message(fake_llm, "Rekomendasiin cemilan", history=[], context_text=context)

    assert fake_llm.chat_with_history_calls[0]["system_instruction"] == context


async def test_context_text_reaches_planner_path():
    fake_llm = FakeLLMService(needs_planning=True)
    context = "Preferensi user:\n- tone: formal"

    result = await handle_message(
        fake_llm, "Rencanakan olahraga ringan", history=[], context_text=context
    )

    assert result.plan_result is not None

    first_task_result = result.plan_result.executions[0].result
    assert "tone: formal" in first_task_result


async def test_message_handled_logged_for_chat_branch_too(caplog):
    """Regresi: sebelumnya event `message_handled` cuma di-log untuk jalur
    planner, jadi jalur chat biasa (paling sering dipakai) tidak
    terekam sama sekali di observability."""
    fake_llm = FakeLLMService(needs_planning=False)

    with caplog.at_level("INFO"):
        await handle_message(fake_llm, "Halo", history=[], context_text=None)

    messages = [record.message for record in caplog.records]
    assert "message_handled" in messages
    assert "planner_decision" in messages
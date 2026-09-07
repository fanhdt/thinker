from app.services.llm import Plan, PlanTask, TaskEvaluation
from app.services.orchestrator_service import handle_message


class FakeLLMService:
    def __init__(self, needs_planning: bool):
        self.needs_planning = needs_planning
        self.chat_with_history_calls: list[dict] = []
        self.run_plan_calls: list[dict] = []

    async def classify_message(self, message: str) -> bool:
        return self.needs_planning

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str:
        self.chat_with_history_calls.append(
            {"history": history, "system_instruction": system_instruction}
        )
        return "balasan chat biasa"

    async def create_plan(self, goal: str) -> Plan:
        self.run_plan_calls.append({"goal": goal})
        return Plan(goal=goal, tasks=[PlanTask(description="Satu task saja")])

    async def execute_task(self, task_description: str, prior_context: str) -> str:
        return f"hasil dari {task_description} (konteks: {prior_context!r})"

    async def evaluate_result(self, task_description: str, result: str) -> TaskEvaluation:
        return TaskEvaluation(is_correct=True, feedback="")


async def test_simple_message_uses_chat_not_planner():
    fake_llm = FakeLLMService(needs_planning=False)
    result = await handle_message(fake_llm, "Halo, apa kabar?", history=[], context_text=None)

    assert result.used_planner is False
    assert result.plan_result is None
    assert result.reply == "balasan chat biasa"
    assert len(fake_llm.chat_with_history_calls) == 1
    assert len(fake_llm.run_plan_calls) == 0


async def test_complex_goal_uses_planner_not_chat():
    fake_llm = FakeLLMService(needs_planning=True)
    result = await handle_message(
        fake_llm, "Rencanakan liburan ke Bali", history=[], context_text=None
    )

    assert result.used_planner is True
    assert result.plan_result is not None
    assert len(result.plan_result.executions) == 1
    assert len(fake_llm.run_plan_calls) == 1
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

    first_task_result = result.plan_result.executions[0].result
    assert "tone: formal" in first_task_result

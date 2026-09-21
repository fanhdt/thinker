from app.services.llm import Plan, PlanTask, TaskOutcome
from app.services.planner_service import MAX_REFLECTION_ATTEMPTS, build_summary_text, run_plan


class FakeLLMService:
    def __init__(self, evaluation_pattern: list[bool] | None = None, num_tasks: int = 1):
        self.evaluation_pattern = evaluation_pattern or [True]
        self.num_tasks = num_tasks
        self.execute_call_count = 0
        self.received_contexts: list[str] = []

    async def create_plan(self, goal: str) -> Plan:
        return Plan(
            goal=goal,
            tasks=[PlanTask(description=f"Task {i + 1}") for i in range(self.num_tasks)],
        )

    async def execute_and_evaluate(self, task_description: str, prior_context: str) -> TaskOutcome:
        """Gabungan execute+evaluate dalam satu panggilan (lihat
        `LLMService.execute_and_evaluate`) -- fake ini melacak jumlah
        panggilan di `execute_call_count` seperti sebelumnya, tapi sekarang
        cuma SATU counter untuk kedua hal (dulu ada execute_call_count DAN
        evaluate_call_count terpisah, sekarang memang satu panggilan)."""
        index = min(self.execute_call_count, len(self.evaluation_pattern) - 1)
        is_correct = self.evaluation_pattern[index]
        self.received_contexts.append(prior_context)
        self.execute_call_count += 1

        result = f"Hasil percobaan ke-{self.execute_call_count} untuk {task_description}"
        if is_correct:
            return TaskOutcome(result=result, is_correct=True, feedback="")
        return TaskOutcome(
            result=result, is_correct=False, feedback="Kurang detail, tolong perbaiki."
        )


async def test_task_passes_on_first_attempt_needs_no_retry():
    fake_llm = FakeLLMService(evaluation_pattern=[True])
    execution_result = await run_plan(fake_llm, "Goal contoh")

    task = execution_result.executions[0]
    assert task.passed_evaluation is True
    assert task.attempts == 1
    assert fake_llm.execute_call_count == 1


async def test_task_retries_and_eventually_passes():
    fake_llm = FakeLLMService(evaluation_pattern=[False, False, True])
    execution_result = await run_plan(fake_llm, "Goal contoh")

    task = execution_result.executions[0]
    assert task.passed_evaluation is True
    assert task.attempts == 3


async def test_reflection_loop_is_bounded_even_when_always_wrong():
    fake_llm = FakeLLMService(evaluation_pattern=[False])
    execution_result = await run_plan(fake_llm, "Goal yang tidak akan pernah 'benar'")

    task = execution_result.executions[0]
    expected_total_attempts = MAX_REFLECTION_ATTEMPTS + 1

    assert task.attempts == expected_total_attempts
    assert task.passed_evaluation is False
    assert fake_llm.execute_call_count == expected_total_attempts


async def test_feedback_from_failed_evaluation_is_passed_to_next_attempt():
    fake_llm = FakeLLMService(evaluation_pattern=[False, True])
    await run_plan(fake_llm, "Goal contoh")

    assert "Kurang detail" not in fake_llm.received_contexts[0]
    assert "Kurang detail" in fake_llm.received_contexts[1]


async def test_run_plan_executes_multiple_tasks_in_order():
    fake_llm = FakeLLMService(evaluation_pattern=[True], num_tasks=2)
    execution_result = await run_plan(fake_llm, "Goal contoh")

    assert len(execution_result.executions) == 2
    assert execution_result.executions[0].description == "Task 1"
    assert execution_result.executions[1].description == "Task 2"


async def test_build_summary_text_flags_tasks_that_never_passed():
    fake_llm = FakeLLMService(evaluation_pattern=[False])
    execution_result = await run_plan(fake_llm, "Goal sulit")

    summary = build_summary_text(execution_result)
    assert "belum sempurna" in summary


async def test_personalization_context_reacher_every_task():
    fake_llm = FakeLLMService(evaluation_pattern=[True], num_tasks=2)
    personalization = "Preferensi user:\n- tone:santai"

    await run_plan(fake_llm, "Goal contoh", personalization_context=personalization)

    assert "tone:santai" in fake_llm.received_contexts[0]
    assert "tone:santai" in fake_llm.received_contexts[1]


async def test_empty_personalization_context_does_not_break_run_plan():
    fake_llm = FakeLLMService(evaluation_pattern=[True])

    execution_result = await run_plan(fake_llm, "Goal contoh", personalization_context="")

    assert execution_result.executions[0].passed_evaluation is True


async def test_run_plan_uses_provided_plan_without_calling_create_plan():
    """Regresi: kalau orchestrator sudah dapat plan dari classify_and_plan,
    run_plan TIDAK boleh manggil create_plan lagi (itu akan jadi panggilan
    Gemini kedua yang mubazir -- justru pemborosan yang barusan kita benahi)."""

    class FakeLLMNoCreatePlan(FakeLLMService):
        async def create_plan(self, goal: str) -> Plan:
            raise AssertionError(
                "create_plan tidak seharusnya terpanggil kalau plan sudah diberikan"
            )

    fake_llm = FakeLLMNoCreatePlan(evaluation_pattern=[True])
    given_plan = Plan(goal="Goal contoh", tasks=[PlanTask(description="Task dari luar")])

    execution_result = await run_plan(fake_llm, "Goal contoh", plan=given_plan)

    assert execution_result.executions[0].description == "Task dari luar"

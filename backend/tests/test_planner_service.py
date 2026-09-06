from app.services.llm import Plan, PlanTask, TaskEvaluation
from app.services.planner_service import MAX_REFLECTION_ATTEMPTS, build_summary_text, run_plan


class FakeLLMService:
    def __init__(self, evaluation_pattern: list[bool] | None = None, num_tasks: int = 1):
        self.evaluation_pattern = evaluation_pattern or [True]
        self.num_tasks = num_tasks
        self.execute_call_count = 0
        self.evaluate_call_count = 0
        self.received_contexts: list[str] = []

    async def create_plan(self, goal: str) -> Plan:
        return Plan(
            goal=goal,
            tasks=[PlanTask(description=f"Task {i + 1}") for i in range(self.num_tasks)],
        )

    async def execute_task(self, task_description: str, prior_context: str) -> str:
        self.execute_call_count += 1
        self.received_contexts.append(prior_context)
        return f"Hasil percobaan ke-{self.execute_call_count} untuk {task_description}"

    async def evaluate_result(self, task_description: str, result: str) -> TaskEvaluation:
        index = min(self.evaluate_call_count, len(self.evaluation_pattern) - 1)
        is_correct = self.evaluation_pattern[index]
        self.evaluate_call_count += 1

        if is_correct:
            return TaskEvaluation(is_correct=True, feedback="")
        return TaskEvaluation(is_correct=False, feedback="Kurang detail, tolong perbaiki.")


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

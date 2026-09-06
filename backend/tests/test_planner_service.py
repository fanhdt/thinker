from app.services.llm import Plan, PlanTask
from app.services.planner_service import build_summary_text, run_plan


class FakeLLMService:
    def __init__(self):
        self.received_contexts: list[str] = []

    async def create_plan(self, goal: str) -> Plan:
        return Plan(
            goal=goal,
            tasks=[
                PlanTask(description="task pertama"),
                PlanTask(description="task kedua"),
            ],
        )

    async def execute_task(self, task_description: str, prior_context: str) -> str:
        self.received_contexts.append(prior_context)
        return f"Hasil dari {task_description}"


async def test_run_plan_executes_tasks_in_order():
    fake_llm = FakeLLMService()
    execution_result = await run_plan(fake_llm, "Goal contoh")

    assert execution_result.goal == "Goal contoh"
    assert len(execution_result.executions) == 2
    assert execution_result.executions[0].result == "Hasil dari task pertama"
    assert execution_result.executions[1].result == "Hasil dari task kedua"


async def test_run_plan_passes_prior_results_as_context():
    fake_llm = FakeLLMService()
    await run_plan(fake_llm, "Goal contoh")

    assert fake_llm.received_contexts[0] == ""
    assert "task pertama" in fake_llm.received_contexts[1]
    assert "Hasil dari task pertama" in fake_llm.received_contexts[1]


async def test_build_summary_text_includes_all_tasks():
    fake_llm = FakeLLMService()
    execution_result = await run_plan(fake_llm, "rencanakan sesuatu")
    summary = build_summary_text(execution_result)

    assert "rencanakan sesuatu" in summary
    assert "Hasil dari task pertama" in summary
    assert "Hasil dari task kedua" in summary

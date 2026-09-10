import logging
from dataclasses import dataclass

from app.core.logging_config import log_event
from app.services.llm import Plan
from app.services.llm_provider import PlannerLLM

MAX_REFLECTION_ATTEMPTS = 2

logger = logging.getLogger(__name__)


@dataclass
class TaskExecution:
    description: str
    result: str
    passed_evaluation: bool
    attempts: int


@dataclass
class PlanExecutionResult:
    goal: str
    executions: list[TaskExecution]


async def _execute_task_with_reflection(
    llm: PlannerLLM, task_description: str, context_so_far: str
) -> TaskExecution:
    feedback = ""
    result = ""

    total_attempts = MAX_REFLECTION_ATTEMPTS + 1
    for attempt in range(1, total_attempts + 1):
        prompt_context = context_so_far
        if feedback:
            prompt_context += (
                f"\n\nCatatan dari percobaan sebelumnya yang KURANG TEPAT"
                f"{feedback}\nPerbaiki hasil sesuai catatan ini"
            )
        result = await llm.execute_task(task_description, prompt_context)
        evaluation = await llm.evaluate_result(task_description, result)

        if evaluation.is_correct:
            log_event(
                logger,
                "task_execution_finished",
                task=task_description,
                passed_evaluation=True,
                attempts=attempt,
            )
            return TaskExecution(
                description=task_description,
                result=result,
                passed_evaluation=True,
                attempts=attempt,
            )

        feedback = evaluation.feedback
        log_event(
            logger,
            "reflection_retry",
            task=task_description,
            attempt=attempt,
            max_attempts=total_attempts,
            feedback=feedback,
        )

    log_event(
        logger,
        "task_execution_finished",
        task=task_description,
        passed_evaluation=False,
        attempts=total_attempts,
    )

    return TaskExecution(
        description=task_description,
        result=result,
        passed_evaluation=False,
        attempts=total_attempts,
    )


async def run_plan(
    llm: PlannerLLM, goal: str, personalization_context: str = ""
) -> PlanExecutionResult:
    plan: Plan = await llm.create_plan(goal)

    executions: list[TaskExecution] = []
    context_so_far = f"{personalization_context}\n" if personalization_context else ""

    for task in plan.tasks:
        execution = await _execute_task_with_reflection(llm, task.description, context_so_far)
        executions.append(execution)
        context_so_far += f'\nTask : "{task.description}"\nHasil: {execution.result}\n'

    return PlanExecutionResult(goal=goal, executions=executions)


def build_summary_text(execution_result: PlanExecutionResult) -> str:
    lines = [f"Goal :{execution_result.goal}", ""]
    for i, execution in enumerate(execution_result.executions, start=1):
        status = (
            "" if execution.passed_evaluation else " (belum sempurna setelah beberapa percobaan)"
        )
        lines.append(f"{i}, {execution.description}{status}")
        lines.append(f"  -> {execution.result}")
    return "\n".join(lines)

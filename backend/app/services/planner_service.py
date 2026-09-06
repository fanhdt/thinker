from dataclasses import dataclass

from app.services.llm import LLMService, Plan


@dataclass
class TaskExecution:
    description: str
    result: str


@dataclass
class PlanExecutionResult:
    goal: str
    executions: list[TaskExecution]


async def run_plan(llm: LLMService, goal: str) -> PlanExecutionResult:
    plan: Plan = await llm.create_plan(goal)

    executions: list[TaskExecution] = []
    context_so_far = ""

    for task in plan.tasks:
        result = await llm.execute_task(task.description, context_so_far)
        executions.append(TaskExecution(description=task.description, result=result))
        context_so_far += f'\nTask:"{task.description}"\nHasil:{result}\n'

    return PlanExecutionResult(goal=goal, executions=executions)


def build_summary_text(execution_result: PlanExecutionResult) -> str:
    lines = [f"Goal :{execution_result.goal}", ""]
    for i, execution in enumerate(execution_result.executions, start=1):
        lines.append(f"{i}, {execution.description}")
        lines.append(f"  -> {execution.result}")
    return "\n".join(lines)

from dataclasses import dataclass

from app.services.llm_provider import OrchestratorLLM
from app.services.planner_service import PlanExecutionResult, build_summary_text, run_plan


@dataclass
class OrchestratedResponse:
    reply: str
    used_planner: bool
    plan_result: PlanExecutionResult | None = None


async def handle_message(
    llm: OrchestratorLLM,
    message: str,
    history: list[dict[str, str]],
    context_text: str | None,
) -> OrchestratedResponse:
    needs_planning = await llm.classify_message(message)

    if needs_planning:
        execution_result = await run_plan(llm, message, personalization_context=context_text or "")
        summary = build_summary_text(execution_result)
        return OrchestratedResponse(reply=summary, used_planner=True, plan_result=execution_result)
    reply = await llm.chat_with_history(history, system_instruction=context_text)
    return OrchestratedResponse(reply=reply, used_planner=False)

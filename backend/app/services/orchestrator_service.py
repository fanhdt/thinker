import logging
from dataclasses import dataclass

from app.core.logging_config import log_event
from app.services.llm import Plan
from app.services.llm_provider import OrchestratorLLM
from app.services.planner_service import PlanExecutionResult, build_summary_text, run_plan

logger = logging.getLogger(__name__)


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
    message_plan = await llm.classify_and_plan(message)
    log_event(logger, "planner_decision", needs_planning=message_plan.needs_planning)

    if message_plan.needs_planning:
        plan = Plan(goal=message, tasks=message_plan.tasks)
        execution_result = await run_plan(
            llm, message, personalization_context=context_text or "", plan=plan
        )
        summary = build_summary_text(execution_result)
        log_event(logger, "message_handled", used_planner=True)
        return OrchestratedResponse(reply=summary, used_planner=True, plan_result=execution_result)

    reply = await llm.chat_with_history(history, system_instruction=context_text)
    log_event(logger, "message_handled", used_planner=False)
    return OrchestratedResponse(reply=reply, used_planner=False)

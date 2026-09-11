from typing import Protocol

from app.services.llm import MemoryExtraction, Plan, TaskEvaluation


class PlannerLLM(Protocol):
    """Interface minimal yang dibutuhkan planner_service.run_plan dari LLM
    apapun (Gemini, OpenAI, model lokal, dst). Cuma 3 method -- bukan
    seluruh kemampuan LLMService -- supaya test double tidak perlu
    implementasi method yang tidak pernah dipakai fungsi ini.
    """

    async def create_plan(self, goal: str) -> Plan: ...

    async def execute_task(self, task_description: str, prior_context: str) -> str: ...

    async def evaluate_result(self, task_description: str, result: str) -> TaskEvaluation: ...


class OrchestratorLLM(PlannerLLM, Protocol):
    """Superset dari PlannerLLM -- orchestrator_service.handle_message
    memanggil run_plan() di dalamnya (butuh 3 method PlannerLLM), ditambah
    classify_message & chat_with_history untuk jalur non-planner.
    """

    async def classify_message(self, message: str) -> bool: ...

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str: ...


class MessagePipelineLLM(OrchestratorLLM, Protocol):
    """Superset lagi dari OrchestratorLLM -- message_pipeline.process_incoming_message
    memanggil orchestrator_service.handle_message() (butuh semua method
    OrchestratorLLM) DITAMBAH extract_fact (ekstraksi memori) dan model
    (dipakai di response). Ini interface paling lengkap di aplikasi -- dipakai
    di titik paling luar (HTTP route, Telegram bot), bukan di business logic
    inti seperti planner/orchestrator itu sendiri.
    """

    @property
    def model(self) -> str: ...

    async def extract_fact(
        self, message: str, existing_memories: list[str]
    ) -> MemoryExtraction | None: ...

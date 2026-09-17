from typing import Protocol

from app.services.llm import MemoryExtraction, MessagePlan, Plan, TaskOutcome


class PlannerLLM(Protocol):
    """Interface minimal yang dibutuhkan planner_service.run_plan dari LLM
    apapun (Gemini, OpenAI, model lokal, dst). Cuma 2 method -- bukan
    seluruh kemampuan LLMService -- supaya test double tidak perlu
    implementasi method yang tidak pernah dipakai fungsi ini.
    """

    async def create_plan(self, goal: str) -> Plan: ...

    async def execute_and_evaluate(self, task_description: str, prior_context: str) -> TaskOutcome: ...


class OrchestratorLLM(PlannerLLM, Protocol):
    """Superset dari PlannerLLM -- orchestrator_service.handle_message
    memanggil run_plan() di dalamnya (butuh method PlannerLLM), ditambah
    classify_and_plan & chat_with_history untuk memutuskan+menjalankan
    jalur planner vs jalur chat biasa.
    """

    async def classify_and_plan(self, message: str) -> MessagePlan: ...

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
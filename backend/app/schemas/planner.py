import uuid

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)


class TaskResultOut(BaseModel):
    description: str
    result: str
    passed_evaluation: bool
    attempts: int


class PlanResponse(BaseModel):
    goal: str
    tasks: list[TaskResultOut]
    summary: str
    conversation_id: uuid.UUID

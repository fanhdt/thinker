import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GoalCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)


class GoalUpdate(BaseModel):
    status: str = Field(pattern="^(active|completed)$")


class GoalOut(BaseModel):
    id: uuid.UUID
    description: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.planner import TaskResultOut


class ConversationCreate(BaseModel):
    title: str = Field(default="Percakapan Baru", max_length=200)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SendMessageResponse(BaseModel):
    reply: str
    model: str
    conversation_id: uuid.UUID
    used_planner: bool = False
    tasks: list[TaskResultOut] | None = None

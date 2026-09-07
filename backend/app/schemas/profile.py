import uuid

from pydantic import BaseModel, ConfigDict


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    preferences: dict

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdate(BaseModel):
    name: str | None = None
    preferences: dict | None = None

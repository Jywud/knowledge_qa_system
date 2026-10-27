from datetime import datetime

from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    username: str
    role: str = "user"

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class PasswordResetRequest(BaseModel):
    password: str


class ChunkOut(BaseModel):
    id: int
    chunk_index: int
    page_no: int
    content: str

    model_config = {"from_attributes": True}


class KnowledgeBaseOut(BaseModel):
    id: int
    name: str
    description: str = ""
    file_count: int = 0
    chunk_count: int = 0
    created_at: datetime


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = ""


class KnowledgeBaseUpdate(BaseModel):
    name: str
    description: str = ""


class FileOut(BaseModel):
    id: int
    kb_id: int | None = None
    filename: str
    file_type: str
    size: int
    version: int
    status: str
    chunk_count: int = 0
    uploader: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    title: str
    kb_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources: str | None = None

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str | None = None
    kb_id: int | None = None


class ChatRequest(BaseModel):
    content: str
    kb_id: int | None = None


class SystemSettingOut(BaseModel):
    id: int
    chunk_size: int
    chunk_overlap: int
    top_k: int

    model_config = {"from_attributes": True}


class SystemSettingUpdate(BaseModel):
    chunk_size: int
    chunk_overlap: int
    top_k: int

from datetime import datetime

from pydantic import BaseModel, Field, PositiveInt


class RoleSummary(BaseModel):
    id: int
    name: str
    system_key: str | None = None

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    username: str
    roles: list[RoleSummary] = Field(default_factory=list)
    is_admin: bool = False

    model_config = {"from_attributes": True}


class LoginOut(BaseModel):
    token: str
    user: UserOut


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role_ids: list[PositiveInt] = Field(min_length=1)

    model_config = {"extra": "forbid"}


class UserRolesUpdate(BaseModel):
    role_ids: list[PositiveInt] = Field(min_length=1)


class RoleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    kb_ids: list[PositiveInt] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RoleOut(RoleSummary):
    description: str
    kb_ids: list[int]
    user_count: int


class PasswordResetRequest(BaseModel):
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class ChunkOut(BaseModel):
    id: int
    chunk_index: int
    page_no: int
    content: str

    model_config = {"from_attributes": True}


class ChunkDetailOut(ChunkOut):
    file_id: int
    file_version: int
    filename: str
    file_type: str


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
    status_message: str = ""
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

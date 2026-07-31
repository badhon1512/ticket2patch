from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=120)
    repo: str = Field(min_length=1, max_length=120)
    base_branch: str = Field(min_length=1, max_length=255)
    ticket_key: str = Field(
        min_length=3,
        max_length=40,
        pattern=r"^[A-Z][A-Z0-9_]{0,29}-[1-9][0-9]*$",
    )
    message: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=160)


class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    message: str
    status: str


class JiraTicket(BaseModel):
    key: str
    summary: str
    status: str
    issue_type: str
    priority: str | None = None
    updated: str | None = None
    url: str


class GitHubRepository(BaseModel):
    name: str
    full_name: str
    url: str
    language: str | None = None
    updated_at: str
    default_branch: str
    private: bool

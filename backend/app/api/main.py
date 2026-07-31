from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.db import ActivityStore
from app.schemas.activity import ActivityCreate, RunCreate, RunUpdate
from app.schemas.chat import ChatRequest, ChatResponse, GitHubRepository, JiraTicket
from app.services.chat_service import ChatService, ChatSessionNotFoundError


@lru_cache
def get_activity_store() -> ActivityStore:
    return ActivityStore()


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService()


ActivityStoreDependency = Annotated[
    ActivityStore,
    Depends(get_activity_store),
]
ChatServiceDependency = Annotated[
    ChatService,
    Depends(get_chat_service),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the shared LangGraph agent once when the API process starts."""

    await get_chat_service().initialize()
    yield


app = FastAPI(
    title="Ticket2Patch Activity API",
    version="0.1.0",
    description="Run summaries and append-only activity timelines.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs")
def list_runs(
    store: ActivityStoreDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    return store.list_runs(limit)


@app.post("/api/runs", status_code=status.HTTP_201_CREATED)
def create_run(
    request: RunCreate,
    store: ActivityStoreDependency,
) -> dict:
    return store.create_run(
        run_id=request.id,
        ticket_key=request.ticket_key,
        repository=request.repository,
        status=request.status,
    )


@app.get("/api/runs/{run_id}")
def get_run(
    run_id: str,
    store: ActivityStoreDependency,
) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {**run, "events": store.list_events(run_id)}


@app.patch("/api/runs/{run_id}")
def update_run(
    run_id: str,
    request: RunUpdate,
    store: ActivityStoreDependency,
) -> dict:
    try:
        return store.update_run(run_id, **request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post(
    "/api/runs/{run_id}/events",
    status_code=status.HTTP_201_CREATED,
)
def append_event(
    run_id: str,
    request: ActivityCreate,
    store: ActivityStoreDependency,
) -> dict:
    try:
        return store.append_event(run_id, **request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    store: ActivityStoreDependency,
    chat_service: ChatServiceDependency,
) -> dict[str, str]:
    try:
        return await chat_service.send_message(
            owner=request.owner,
            repo=request.repo,
            ticket_key=request.ticket_key,
            base_branch=request.base_branch,
            message=request.message,
            session_id=request.session_id,
            store=store,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Chat session expired or was not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/jira/issues", response_model=list[JiraTicket])
async def list_jira_issues(
    chat_service: ChatServiceDependency,
) -> list[dict[str, str | None]]:
    try:
        return await chat_service.list_jira_tickets()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/github/repositories", response_model=list[GitHubRepository])
async def list_github_repositories(
    chat_service: ChatServiceDependency,
    owner: Annotated[str, Query(min_length=1, max_length=39)],
) -> list[dict[str, str | bool | None]]:
    try:
        return await chat_service.list_recent_repositories(owner)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

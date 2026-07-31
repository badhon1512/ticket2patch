import argparse
import asyncio
import os
import sys
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.agents.agent import create_agent
from app.agents.guardrails import EligibilityPolicy
from app.agents.state import Ticket2PatchState
from app.db import ActivityStore
from app.observability.activity_callbacks import ActivityCallbackHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat with Ticket2Patch using scoped GitHub issue tools."
    )
    parser.add_argument("--owner", required=True, help="GitHub owner or organization")
    parser.add_argument("--repo", required=True, help="GitHub repository name")
    parser.add_argument(
        "--model",
        default=os.getenv("TICKET2PATCH_MODEL", "gpt-4.1-mini"),
        help="OpenAI chat model",
    )
    return parser.parse_args()


def require_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def initial_state(owner: str, repo: str) -> Ticket2PatchState:
    repository = f"{owner}/{repo}"
    run_id = f"local-{uuid4()}"
    return {
        "messages": [],
        "run_id": run_id,
        "attempt": 1,
        "status": "received",
        "trigger_event_id": run_id,
        "ticket_key": "LOCAL-1",
        "ticket_snapshot": {
            "project_key": "LOCAL",
            "issue_type": "Developer Investigation",
            "status": "Ready for Agent",
            "labels": ["ticket2patch"],
            "repository": repository,
        },
        "repository": repository,
        "evidence": [],
        "hypotheses": [],
        "risk": "low",
        "approvals": [],
        "changed_files": [],
        "validation_results": [],
        "review_findings": [],
    }


async def chat(args: argparse.Namespace) -> None:
    require_environment("OPENAI_API_KEY")

    policy = EligibilityPolicy(
        allowed_projects=frozenset({"LOCAL"}),
        allowed_issue_types=frozenset({"Developer Investigation"}),
    )
    model = ChatOpenAI(model=args.model, temperature=0)
    agent = await create_agent(
        model=model,
        eligibility_policy=policy,
    )

    state = initial_state(args.owner, args.repo)
    thread_id = state["run_id"]
    store = ActivityStore()
    store.create_run(
        run_id=thread_id,
        ticket_key=state["ticket_key"],
        repository=state["repository"],
        status=state["status"],
    )
    store.append_event(
        thread_id,
        event_type="run_started",
        title="Local agent session started",
        detail=f"Repository scope: {state['repository']}",
        level="success",
        actor="system",
    )
    activity_callback = ActivityCallbackHandler(store, thread_id)

    print(f"Ticket2Patch Git chat: {args.owner}/{args.repo}")
    print("Scoped GitHub issue tools enabled. Type /exit to quit.")

    try:
        while True:
            try:
                question = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not question:
                continue
            if question.lower() in {"/exit", "/quit"}:
                return

            store.append_event(
                thread_id,
                event_type="developer_message",
                title="Developer sent a message",
                detail=question,
                actor="developer",
            )
            store.update_run(thread_id, status="investigating")
            state["messages"] = [
                *state.get("messages", []),
                HumanMessage(
                    content=(
                        f"Repository scope: {args.owner}/{args.repo}\n"
                        f"Developer question: {question}"
                    )
                ),
            ]

            try:
                state = await agent.ainvoke(
                    state,
                    thread_id=thread_id,
                    callbacks=[activity_callback],
                )
            except Exception as exc:  # noqa: BLE001 - keep session alive
                store.append_event(
                    thread_id,
                    event_type="agent_error",
                    title="Agent request failed",
                    detail=str(exc),
                    level="error",
                    actor="agent",
                )
                store.update_run(
                    thread_id,
                    status="failed",
                    failure_reason=str(exc),
                )
                print(f"\nagent error> {exc}", file=sys.stderr)
                continue

            messages = state.get("messages", [])
            if messages:
                response = str(messages[-1].content)
                store.append_event(
                    thread_id,
                    event_type="agent_response",
                    title="Agent responded",
                    detail=response,
                    level="success",
                    actor="agent",
                )
                store.update_run(
                    thread_id,
                    status=state.get("status", "investigating"),
                    summary=response[:1000],
                )
                print(f"\nagent> {response}")
    finally:
        current_run = store.get_run(thread_id)
        if current_run and current_run["status"] != "failed":
            store.append_event(
                thread_id,
                event_type="run_completed",
                title="Local agent session ended",
                level="success",
                actor="system",
            )
            store.update_run(thread_id, status="completed", completed=True)


def main() -> None:
    try:
        asyncio.run(chat(parse_args()))
    except RuntimeError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

from typing import Annotated, Any, Literal, NotRequired, Required, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

RunStatus = Literal[
    "received",
    "ineligible",
    "investigating",
    "analysis_complete",
    "awaiting_plan_approval",
    "workspace_ready",
    "patching",
    "validating",
    "reviewing",
    "awaiting_publication_approval",
    "publishing",
    "completed",
    "failed",
    "cancelled",
]

RiskLevel = Literal["low", "medium", "high", "blocked"]
ApprovalDecision = Literal["approved", "rejected", "changes_requested"]


class RootCauseAnalysis(BaseModel):
    """Small, evidence-backed handoff from investigation to patching."""

    symptom: str = Field(description="Observed problem and its impact")
    evidence: list[str] = Field(description="Ticket or repository facts supporting the conclusion")
    root_cause: str = Field(description="Most likely underlying cause")
    confidence: Literal["low", "medium", "high"]
    proposed_fix: str = Field(description="Smallest reasonable fix")
    affected_files: list[str] = Field(description="Repository-relative files likely to change")
    test_plan: list[str] = Field(description="Focused regression and validation checks")
    open_questions: list[str] = Field(default_factory=list)


class EvidenceReference(TypedDict):
    source: Literal[
        "jira",
        "repository",
        "logs",
        "traces",
        "deployment",
        "documentation",
        "ci",
    ]
    reference: str
    summary: str


class Hypothesis(TypedDict):
    summary: str
    confidence: float
    evidence_refs: list[str]


class ApprovalRecord(TypedDict):
    stage: Literal["plan", "publication"]
    decision: ApprovalDecision
    actor_id: str
    decided_at: str
    comment: NotRequired[str]


class ValidationResult(TypedDict):
    name: str
    status: Literal["passed", "failed", "skipped"]
    artifact_ref: NotRequired[str]
    summary: NotRequired[str]


class Ticket2PatchState(TypedDict, total=False):
    """Durable state for one ticket-to-patch run.

    Large logs, diffs, and test outputs are stored as external artifacts and
    referenced from state instead of being copied into every checkpoint.
    """

    messages: Annotated[list[Any], add_messages]
    run_id: Required[str]
    attempt: Required[int]
    status: Required[RunStatus]
    trigger_event_id: Required[str]
    ticket_key: Required[str]
    ticket_snapshot: Required[dict]

    service: NotRequired[str]
    repository: NotRequired[str]
    base_branch: NotRequired[str]
    base_sha: NotRequired[str]
    workspace_id: NotRequired[str]
    branch_name: NotRequired[str]

    evidence: Required[list[EvidenceReference]]
    hypotheses: Required[list[Hypothesis]]
    reproduction: NotRequired[dict]
    proposed_plan: NotRequired[dict]
    analysis: NotRequired[dict[str, Any]]
    risk: Required[RiskLevel]
    approvals: Required[list[ApprovalRecord]]

    changed_files: Required[list[str]]
    patch_artifact_ref: NotRequired[str]
    validation_results: Required[list[ValidationResult]]
    review_findings: Required[list[dict]]

    pull_request_url: NotRequired[str]
    failure_reason: NotRequired[str | None]

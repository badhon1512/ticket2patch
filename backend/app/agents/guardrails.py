from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EligibilityPolicy:
    allowed_projects: frozenset[str]
    allowed_issue_types: frozenset[str]
    activation_label: str = "ticket2patch"
    allowed_statuses: frozenset[str] = field(
        default_factory=lambda: frozenset({"Ready for Agent"})
    )
    blocked_labels: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "security-incident",
                "data-loss",
                "database-migration",
                "multi-repository",
            }
        )
    )


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]


def evaluate_ticket(
    ticket: dict[str, Any],
    policy: EligibilityPolicy,
) -> EligibilityResult:
    """Evaluate ticket metadata without asking an LLM to authorize the run."""

    reasons: list[str] = []
    project_key = str(ticket.get("project_key", ""))
    issue_type = str(ticket.get("issue_type", ""))
    status = str(ticket.get("status", ""))
    labels = {str(label) for label in ticket.get("labels", [])}
    repository = ticket.get("repository")

    if project_key not in policy.allowed_projects:
        reasons.append("project is not approved")
    if issue_type not in policy.allowed_issue_types:
        reasons.append("issue type is not supported")
    if status not in policy.allowed_statuses:
        reasons.append("ticket is not in an eligible status")
    if policy.activation_label not in labels:
        reasons.append("activation label is missing")

    blocked = labels.intersection(policy.blocked_labels)
    if blocked:
        reasons.append(f"blocked labels present: {', '.join(sorted(blocked))}")
    if not repository:
        reasons.append("repository mapping is missing")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))

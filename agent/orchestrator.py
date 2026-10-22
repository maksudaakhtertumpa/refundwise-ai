"""Run the RefundWise multi-agent pipeline for one customer message."""

from __future__ import annotations

from agent.checks import run_checks
from agent.critic import run_critic
from agent.decide import propose_decision
from agent.evidence import gather_evidence
from agent.intake import run_intake
from agent.reporter import write_report
from agent.runtime import MAX_MODEL_CALLS, ModelBudgetExceeded
from agent.state import CaseFile

MAX_REVISIONS = 2


def run_case(message: str, customer_id: str, demo_today: str | None = None) -> CaseFile:
    """Run intake → evidence → checks → decide → critic → reporter.

    On critic revise, gather more evidence (at most two extra passes).
    If the 12 model-call cap is hit, stop and return human_review.
    """
    case = CaseFile(message=message, customer_id=customer_id)
    if demo_today:
        case.demo_today = demo_today
    try:
        run_intake(case)
        gather_evidence(case)
        run_checks(case)
        propose_decision(case)
        revisions = 0
        while True:
            critique = run_critic(case)
            if critique.get("verdict") != "revise":
                break
            if critique.get("hard_guard"):
                break
            if revisions >= MAX_REVISIONS:
                case.decision = "human_review"
                case.add_trace(
                    step="orchestrator",
                    agent="orchestrator",
                    action="revision_cap",
                    detail="Reached 2 revisions; escalating to human_review",
                )
                break
            revisions += 1
            request = critique.get("missing_evidence") or critique.get("reason") or "Need more evidence"
            case.add_trace(
                step="orchestrator",
                agent="orchestrator",
                action="revise",
                detail=f"revision {revisions}: {request}",
            )
            gather_evidence(case, extra_request=str(request))
            run_checks(case)
            propose_decision(case)
        if case.decision not in {"approve", "reject", "human_review"}:
            case.decision = "human_review"
        write_report(case)
    except ModelBudgetExceeded as exc:
        case.decision = "human_review"
        if case.confidence is None:
            case.confidence = 0.2
        case.limitations = list(case.limitations) + [str(exc)]
        case.add_trace(
            step="orchestrator",
            agent="orchestrator",
            action="budget",
            detail=str(exc),
        )
        if not case.customer_reply:
            case.customer_reply = (
                "Thank you for writing in. A support lead will review this "
                "request because we could not finish the automated checks."
            )
    case.add_trace(
        step="orchestrator",
        agent="orchestrator",
        action="done",
        detail=(
            f"decision={case.decision} confidence={case.confidence} "
            f"model_calls={case.model_calls}/{MAX_MODEL_CALLS}"
        ),
    )
    return case

"""Run the RefundWise multi-agent pipeline for one customer message."""

from __future__ import annotations

from agent.checks import run_checks
from agent.critic import apply_hard_guards, run_critic
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
    except RuntimeError as exc:
        # The model provider failed or timed out. Never crash the run and never
        # guess. If the Python policy guards already settle the case (for
        # example "already refunded"), use them; otherwise hand it to a person.
        case.add_trace(
            step="orchestrator",
            agent="orchestrator",
            action="model_error",
            detail=str(exc)[:300],
        )
        guard = apply_hard_guards(case) if case.checks else None
        if guard:
            case.decision = guard["decision"]
            case.confidence = 0.95
            case.rules_applied = list(dict.fromkeys(list(case.rules_applied or []) + [guard["rule"]]))
            case.limitations = list(case.limitations) + [
                "The AI model did not answer in time; the decision comes from the "
                f"deterministic policy guard {guard['rule']}: {guard['reason']}"
            ]
            case.add_trace(
                step="orchestrator",
                agent="orchestrator",
                action="guard_fallback",
                detail=f"{guard['rule']}: {guard['reason']} -> {guard['decision']}",
            )
        else:
            case.decision = "human_review"
            case.confidence = 0.0
            case.limitations = list(case.limitations) + [
                "The AI model did not answer in time, so the automated review stopped early."
            ]
        if not case.customer_reply:
            case.customer_reply = _fallback_reply(case.decision)
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


def _fallback_reply(decision: str | None) -> str:
    """Plain customer reply used when the reporter model could not run."""
    if decision == "reject":
        return (
            "Thank you for writing in. We checked your order against our refund "
            "policy and are unable to offer a refund for this request. A support "
            "agent can explain the details if you reply to this message."
        )
    return (
        "Thank you for writing in. A support lead will review this request "
        "and get back to you shortly."
    )

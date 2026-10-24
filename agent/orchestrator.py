"""Run the RefundWise multi-agent pipeline for one customer message."""

from __future__ import annotations

from agent.checks import run_checks
from agent.critic import apply_hard_guards, run_critic
from agent.decide import propose_decision
from agent.evidence import _run_fallbacks, gather_evidence
from agent.intake import run_intake
from agent.reporter import write_report
from agent.router import route_request
from agent.runtime import MAX_MODEL_CALLS, ModelBudgetExceeded
from agent.state import CaseFile
from agent.verifier import verify_proposal
from agent.tracing import write_log

MAX_REVISIONS = 2


def run_case(
    message: str,
    customer_id: str,
    demo_today: str | None = None,
    request_id: str | None = None,
) -> CaseFile:
    """Run one case end to end and write its JSONL trace to logs/<trace_id>.jsonl."""
    case = _run_case(message, customer_id, demo_today, request_id)
    case.log_path = write_log(case)
    return case


def _run_case(message: str, customer_id: str, demo_today: str | None, request_id: str | None) -> CaseFile:
    """Run Scout Intent, then intake → evidence → checks → decide → critic → reporter.

    On critic revise, gather more evidence (at most two extra passes).
    If the 12 model-call cap is hit, stop and return human_review.
    """
    case = CaseFile(message=message, customer_id=customer_id, request_id=request_id)
    if demo_today:
        case.demo_today = demo_today
    # Scout Intent runs first: it may refuse, clarify, or answer without the agent team.
    if route_request(case) != "refund":
        case.add_trace(
            step="orchestrator",
            agent="orchestrator",
            action="done",
            detail=f"decision={case.decision} routed_by=scout intent={case.scout.get('intent')} model_calls={case.model_calls}",
        )
        return case
    try:
        if case.order_id and case.reason_type:
            case.add_trace(
                step="intake",
                agent="intake",
                action="skipped",
                detail=f"Scout contract already bound order_id={case.order_id} reason_type={case.reason_type}",
            )
        else:
            scout_order, scout_reason = case.order_id, case.reason_type
            run_intake(case)
            case.order_id = case.order_id or scout_order
            case.reason_type = case.reason_type if case.reason_type not in (None, "other") else (scout_reason or case.reason_type)
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
            if critique.get("revise_target") == "decide":
                case.add_trace(
                    step="orchestrator",
                    agent="orchestrator",
                    action="revise",
                    detail=f"revision {revisions}: decide must fix: {critique.get('reason')}"[:500],
                )
                propose_decision(case)
                continue
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
        if case.decision == "approve":
            # Final approval gate: an approval must pass the deterministic policy checks, whatever the models said.
            blockers = verify_proposal(case) if case.proposed_decision else ["no proposal on record"]
            if blockers:
                case.decision = "human_review"
                case.limitations = list(case.limitations) + ["Approval blocked by the policy gate: " + "; ".join(blockers)]
                case.add_trace(step="orchestrator", agent="orchestrator", action="approval_gate",
                               detail="blocked: " + "; ".join(blockers)[:400])
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
        if not case.checks and case.order_id:
            # The model failed before the facts were in. Collect them with the fixed,
            # customer-scoped queries so the policy guards can still decide safely.
            try:
                _run_fallbacks(case, reason="model_unavailable")
                run_checks(case)
            except Exception as fallback_exc:  # noqa: BLE001 - never crash the case
                case.add_trace(step="orchestrator", agent="orchestrator", action="model_error",
                               detail=f"fallback evidence failed: {fallback_exc}"[:300])
        guard = apply_hard_guards(case) if case.checks else None
        accepted = (case.critique or {}).get("verdict") == "accept" and case.decision in {"approve", "reject", "human_review"}
        if accepted and not guard:
            # The critic already accepted the decision; only the reply writer failed.
            case.limitations = list(case.limitations) + [
                "The reply-writing model did not answer in time; the decision was already "
                "accepted by the critic, and the customer reply uses a standard template."
            ]
            case.add_trace(
                step="orchestrator",
                agent="orchestrator",
                action="reporter_fallback",
                detail=f"kept critic-accepted decision {case.decision}",
            )
        elif guard:
            case.decision = guard["decision"]
            case.confidence = 0.95
            case.rules_applied = list(dict.fromkeys(list(case.rules_applied or []) + [guard["rule"]]))
            case.limitations = list(case.limitations) + [
                "The AI model was not available or did not answer in time; the decision comes from the "
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
                "The AI model was not available or did not answer in time, so the automated review stopped early."
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
    if decision == "approve":
        return (
            "Thank you for writing in. Your request meets our refund policy and is approved "
            "for processing. You will get a confirmation once the refund is issued."
        )
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

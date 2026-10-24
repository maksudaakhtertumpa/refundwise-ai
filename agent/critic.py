"""Critic agent: check the proposal against evidence and hard guards (deep lane)."""

from __future__ import annotations

import json

from agent.parse import extract_json_object, message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile
from agent.verifier import verify_proposal

VERDICTS = frozenset({"accept", "revise", "escalate"})

_SYSTEM = """You are a strict critic for RefundWise refund decisions.
Confirm every factual claim in the proposal is supported by an evidence id and
agrees with the Python checks (those checks win if they conflict).
Reply with a single JSON object:
{
  "verdict": "accept" | "revise" | "escalate",
  "missing_evidence": "what to query next, or empty string",
  "reason": "short explanation",
  "issues": ["optional list of problems"]
}
Use revise only if a specific query would likely change the outcome.
Item condition (for example "unopened" in R2) is not stored in any table, so no query can find it.
checks.customer_says_unopened records what the customer stated, and the warehouse verifies it on return:
treat that check as the evidence for condition and do not ask for more.
Use escalate when the case is too uncertain for automation.
"""


def run_critic(case: CaseFile) -> dict:
    """Review the proposal, then apply hard Python guards.

    Returns the critique dict (verdict accept/revise/escalate).
    """
    critique = _ask(case) or {
        "verdict": "escalate",
        "missing_evidence": "",
        "reason": "Critic did not return valid JSON.",
        "issues": ["invalid_json"],
    }
    issues = verify_proposal(case)
    case.add_trace(
        step="critic",
        agent="policy-verifier",
        action="verify_claims",
        detail=("; ".join(issues) if issues else "All cited evidence, rules, numbers and windows match the checks."),
        confidence=None,
    )
    guard = apply_hard_guards(case)
    if issues and not guard:
        critique = {
            **critique,
            "model_verdict": critique.get("verdict"),
            "verdict": "revise",
            "revise_target": "decide",
            "reason": "Policy verifier found problems: " + "; ".join(issues),
            "issues": issues,
        }
    if guard:
        critique = {
            **critique,
            "hard_guard": guard,
            "verdict": (
                "accept"
                if (case.proposed_decision or {}).get("decision") == guard["decision"]
                else "escalate"
            ),
            "reason": guard["reason"],
        }
        _apply_forced_decision(case, guard)
        # Guards always settle the case; never ask for another evidence pass.
        if critique["verdict"] == "revise":
            critique["verdict"] = "escalate"
    case.critique = critique
    if critique.get("verdict") == "accept" and not guard:
        proposal = case.proposed_decision or {}
        case.decision = proposal.get("decision")
        case.confidence = proposal.get("confidence")
        case.rules_applied = list(proposal.get("rules_applied") or [])
    elif critique.get("verdict") == "escalate" and not guard:
        case.decision = "human_review"
        case.rules_applied = _merge_rules(case.rules_applied, ["R10"])
        if case.confidence is None:
            case.confidence = 0.4
    case.add_trace(
        step="critic",
        agent="critic",
        action="verdict",
        detail=json.dumps(
            {
                "verdict": critique.get("verdict"),
                "reason": critique.get("reason"),
                "decision": case.decision,
                "revise_target": critique.get("revise_target"),
            }
        ),
        confidence=case.confidence,
    )
    return critique


def apply_hard_guards(case: CaseFile) -> dict | None:
    """Force reject/human_review for policy tripwires the model must not override."""
    checks = case.checks or {}
    if checks.get("order_found") is False:
        return {
            "decision": "human_review",
            "rule": "R10",
            "reason": "Order was not found on this customer's account.",
        }
    if checks.get("order_belongs_to_customer") is False:
        return {
            "decision": "human_review",
            "rule": "R10",
            "reason": "Order belongs to a different customer.",
        }
    if checks.get("already_refunded"):
        return {
            "decision": "reject",
            "rule": "R9",
            "reason": "Order already refunded (status or refund_history).",
        }
    if checks.get("over_auto_limit"):
        return {
            "decision": "human_review",
            "rule": "R7",
            "reason": "Order total exceeds the 200.00 auto-approve limit.",
        }
    if int(checks.get("approved_refunds_last_90_days") or 0) >= 3:
        return {
            "decision": "human_review",
            "rule": "R8",
            "reason": "Customer has 3 or more approved refunds in the last 90 days.",
        }
    if case.reason_type == "not_received" and checks.get("delivered") is True:
        return {
            "decision": "human_review",
            "rule": "R10",
            "reason": "Customer claims not received but records show delivered.",
        }
    return None


def _apply_forced_decision(case: CaseFile, guard: dict) -> None:
    """Write a guard-forced outcome onto the case file."""
    case.decision = guard["decision"]
    case.rules_applied = _merge_rules(case.rules_applied, [guard["rule"]])
    if case.confidence is None or case.confidence < 0.9:
        case.confidence = 0.95


def _merge_rules(existing: list[str] | None, extra: list[str]) -> list[str]:
    """Append rule ids without duplicates, preserving order."""
    seen: list[str] = []
    for rule in list(existing or []) + extra:
        if rule and rule not in seen:
            seen.append(rule)
    return seen


def _ask(case: CaseFile) -> dict | None:
    """Ask the deep model to accept, revise, or escalate the proposal."""
    result = tracked_chat(
        case,
        agent="critic",
        step="critic",
        action="review",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_payload(case)},
        ],
        lane="deep",
        detail="Check proposal against evidence and checks",
    )
    return validate_critique(extract_json_object(message_text(result.get("message"))))


def _user_payload(case: CaseFile) -> str:
    """Serialise proposal, checks and evidence for the critic."""
    return json.dumps(
        {
            "message": case.message,
            "reason_type": case.reason_type,
            "checks": case.checks,
            "proposed_decision": case.proposed_decision,
            "evidence": [
                {
                    "id": item.id,
                    "source": item.source,
                    "note": item.note,
                    "rows": item.rows,
                    "sql": item.sql,
                }
                for item in case.evidence
            ],
        },
        default=str,
    )


def validate_critique(data: dict | None) -> dict | None:
    """Normalise critic JSON."""
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict") or data.get("decision") or "").strip().lower()
    if verdict in {"accepted", "ok", "approve"}:
        verdict = "accept"
    if verdict in {"retry", "more_evidence"}:
        verdict = "revise"
    if verdict in {"human_review", "reject"}:
        verdict = "escalate"
    if verdict not in VERDICTS:
        return None
    missing = data.get("missing_evidence") or data.get("request") or ""
    if isinstance(missing, list):
        missing = "; ".join(str(part) for part in missing)
    issues = data.get("issues") or []
    if isinstance(issues, str):
        issues = [issues]
    return {
        "verdict": verdict,
        "missing_evidence": str(missing).strip(),
        "reason": str(data.get("reason") or ""),
        "issues": [str(item) for item in issues],
    }

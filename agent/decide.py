"""Decision agent: propose a refund outcome (deep lane)."""

from __future__ import annotations

import json

from agent.checks import policy_rows
from agent.parse import extract_json_object, message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile

DECISIONS = frozenset({"approve", "reject", "human_review"})

_SYSTEM = """You are RefundWise, proposing a refund decision from evidence and checks.
The checks object is computed in Python and is authoritative — do not contradict it.
Use only the policy rule texts provided. Cite evidence ids (E1, E2, ...).
Reply with a single JSON object:
{
  "decision": "approve" | "reject" | "human_review",
  "rules_applied": ["R3"],
  "confidence": 0.0,
  "rationale": "short explanation citing evidence ids",
  "evidence_ids": ["E1"]
}
Guidance:
- Defective items within 30 days of delivery: R3 approve if under 200.00.
- Change of mind: R1 30 days, except Electronics R2 15 days.
- R2 also requires the item to be unopened. The database has no item condition; checks.customer_says_unopened
  records what the customer stated (the warehouse verifies it on return). Approve under R2 only if it is true;
  if it is false, reject; if it is null, use human_review.
- Not received and not delivered 14+ days after order: R4 approve.
- Final sale: R5 reject unless defective.
- Digital once delivered: R6 reject unless it does not work.
- order_total > 200: R7 human_review (do not auto-approve).
- 3 or more approved refunds in last 90 days: R8 human_review.
- already_refunded: R9 reject.
- Customer says not_received but delivered is true: R10 human_review.
confidence is between 0 and 1.
If "critic_feedback" is present, your previous proposal was rejected: fix every
issue it lists, using only the checks and evidence.
"""


def propose_decision(case: CaseFile) -> None:
    """Ask the deep model for a proposed decision and store it on the case."""
    payload = _ask(case)
    if payload is None:
        case.add_trace(step="decide", agent="decide", action="retry_json",
                       detail="Proposal was not valid JSON; asking once more")
        payload = _ask(case, retry=True)
    if payload is None:
        payload = {
            "decision": "human_review",
            "rules_applied": [],
            "confidence": 0.3,
            "rationale": "The decision model did not return valid JSON.",
            "evidence_ids": [item.id for item in case.evidence],
        }
        case.add_trace(
            step="decide",
            agent="decide",
            action="invalid_json",
            detail="Fell back to human_review",
        )
    case.add_trace(
        step="decide",
        agent="decide",
        action="proposal",
        detail=f"{payload['decision']} rules={payload['rules_applied']} evidence={payload.get('evidence_ids')}",
        confidence=payload.get("confidence"),
    )
    case.proposed_decision = payload
    case.decision = payload["decision"]
    case.confidence = payload["confidence"]
    case.rules_applied = payload["rules_applied"]


def _ask(case: CaseFile, retry: bool = False) -> dict | None:
    """Request a JSON proposal from the deep lane (on a retry, insist on JSON only)."""
    content = _user_payload(case)
    if retry:
        content += "\n\nYour previous answer was not a valid JSON object. Reply with only the JSON object, nothing else."
    result = tracked_chat(
        case,
        agent="decide",
        step="decide",
        action="propose",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content},
        ],
        lane="deep",
        detail="Retry proposal as JSON only" if retry else "Propose decision from checks and policy",
    )
    return validate_proposal(extract_json_object(message_text(result.get("message"))))


def _user_payload(case: CaseFile) -> str:
    """Serialise the case facts for the decision model."""
    policies = []
    for row in policy_rows(case):
        policies.append(
            {
                "rule_id": row.get("rule_id"),
                "category": row.get("category"),
                "reason_type": row.get("reason_type"),
                "window_days": row.get("window_days"),
                "outcome": row.get("outcome"),
                "rule_text": row.get("rule_text"),
            }
        )
    evidence = [
        {
            "id": item.id,
            "source": item.source,
            "note": item.note,
            "sql": item.sql,
            "rows": item.rows,
        }
        for item in case.evidence
    ]
    return json.dumps(
        {
            "message": case.message,
            "customer_id": case.customer_id,
            "order_id": case.order_id,
            "intent": case.intent,
            "reason_type": case.reason_type,
            "demo_today": case.demo_today,
            "checks": case.checks,
            "policy_rules": policies,
            "evidence": evidence,
            **(
                {
                    "previous_proposal": case.proposed_decision,
                    "critic_feedback": (case.critique or {}).get("issues") or [(case.critique or {}).get("reason")],
                }
                if (case.critique or {}).get("verdict") == "revise"
                else {}
            ),
        },
        default=str,
    )


def validate_proposal(data: dict | None) -> dict | None:
    """Normalise a decision JSON object."""
    if not isinstance(data, dict):
        return None
    decision = str(data.get("decision") or "").strip().lower().replace(" ", "_")
    if decision in {"human-review", "review", "escalate"}:
        decision = "human_review"
    if decision not in DECISIONS:
        return None
    rules = data.get("rules_applied") or data.get("rule_ids") or []
    if isinstance(rules, str):
        rules = [rules]
    rules = [str(rule).strip().upper() for rule in rules if str(rule).strip()]
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    evidence_ids = data.get("evidence_ids") or []
    if isinstance(evidence_ids, str):
        evidence_ids = [evidence_ids]
    return {
        "decision": decision,
        "rules_applied": rules,
        "confidence": confidence,
        "rationale": str(data.get("rationale") or data.get("reason") or ""),
        "evidence_ids": [str(eid) for eid in evidence_ids],
    }

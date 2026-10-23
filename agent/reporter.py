"""Reporter agent: customer reply and audit explanation (fast lane)."""

from __future__ import annotations

import json

from agent.parse import extract_json_object, message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile

_SYSTEM = """You write the customer-facing outcome for RefundWise.
Be short and polite. Do not mention internal rule ids in the customer_reply;
put those in the explanation steps instead.
Reply with a single JSON object:
{
  "customer_reply": "2-4 sentences to the customer",
  "explanation": [
    {"step": "what we checked", "evidence_id": "E1", "detail": "what we found"}
  ],
  "limitations": ["anything we could not verify"]
}
Every explanation step should include an evidence id when one exists.
"""


def write_report(case: CaseFile) -> None:
    """Fill customer_reply and limitations from the fast model, with a fallback."""
    payload = _ask(case)
    if payload is None:
        payload = _fallback_report(case)
        case.add_trace(
            step="reporter",
            agent="reporter",
            action="fallback_text",
            detail="Used template reply after invalid JSON",
        )
    case.customer_reply = payload["customer_reply"]
    for item in payload.get("limitations") or []:
        if item not in case.limitations:
            case.limitations.append(item)
    case.explanation = list(payload.get("explanation") or [])
    case.add_trace(
        step="reporter",
        agent="reporter",
        action="reply",
        detail=json.dumps(
            {
                "decision": case.decision,
                "steps": payload.get("explanation"),
            },
            default=str,
        ),
    )


def _ask(case: CaseFile) -> dict | None:
    """Ask the fast model for the customer reply JSON."""
    result = tracked_chat(
        case,
        agent="reporter",
        step="reporter",
        action="write",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_payload(case)},
        ],
        lane="fast",
        detail="Write customer reply and explanation",
    )
    return validate_report(extract_json_object(message_text(result.get("message"))))


def _user_payload(case: CaseFile) -> str:
    """Serialise the settled case for the reporter."""
    return json.dumps(
        {
            "customer_id": case.customer_id,
            "message": case.message,
            "decision": case.decision,
            "confidence": case.confidence,
            "rules_applied": case.rules_applied,
            "reason_type": case.reason_type,
            "checks": case.checks,
            "proposed_decision": case.proposed_decision,
            "critique": case.critique,
            "evidence": [
                {"id": item.id, "source": item.source, "note": item.note, "rows": item.rows}
                for item in case.evidence
            ],
        },
        default=str,
    )


def validate_report(data: dict | None) -> dict | None:
    """Normalise reporter JSON."""
    if not isinstance(data, dict):
        return None
    reply = str(data.get("customer_reply") or data.get("reply") or "").strip()
    if not reply:
        return None
    limitations = data.get("limitations") or []
    if isinstance(limitations, str):
        limitations = [limitations]
    explanation = data.get("explanation") or data.get("steps") or []
    if not isinstance(explanation, list):
        explanation = [explanation]
    return {
        "customer_reply": reply,
        "explanation": explanation,
        "limitations": [str(item) for item in limitations if str(item).strip()],
    }


def _fallback_report(case: CaseFile) -> dict:
    """Template reply used when the reporter JSON is unusable."""
    decision = case.decision or "human_review"
    if decision == "approve":
        reply = (
            "Thank you for writing in. We have approved a refund for this order "
            "and you should see the credit after processing."
        )
    elif decision == "reject":
        reply = (
            "Thank you for writing in. We are unable to refund this order under "
            "the current refund policy."
        )
    else:
        reply = (
            "Thank you for writing in. A support lead will review this request "
            "and contact you shortly."
        )
    steps = [
        {"step": item.note or item.source, "evidence_id": item.id, "detail": item.source}
        for item in case.evidence
    ]
    return {
        "customer_reply": reply,
        "explanation": steps,
        "limitations": ["Automated reply; reporter model did not return JSON."],
    }

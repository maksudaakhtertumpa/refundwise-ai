"""Reporter agent: customer reply and audit explanation (fast lane)."""

from __future__ import annotations

import json
import re

from agent.parse import extract_json_object, message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile
from agent.verifier import review_report

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
Every explanation step should include exactly one evidence id when one exists.
Only mention amounts that appear in the evidence. Do not promise payment timing or say money
has been sent: RefundWise decides, and the refund is processed separately.
"""


def write_report(case: CaseFile) -> None:
    """Fill customer_reply and limitations from the fast model, with a fallback."""
    payload = _ask(case)
    if payload is not None:
        issues = review_report(case, payload)
        case.add_trace(
            step="reporter",
            agent="final-reviewer",
            action="review",
            detail=("; ".join(issues) + f" | rejected reply: {str(payload.get('customer_reply'))[:200]}")
            if issues else "Every explanation step cites real evidence and the reply matches the decision.",
        )
        if issues:
            revised = _ask(case, feedback=issues)
            still = review_report(case, revised) if revised else issues
            case.add_trace(
                step="reporter",
                agent="final-reviewer",
                action="re-review",
                detail="; ".join(still) if still else "Revised reply passes review.",
            )
            if revised and not still:
                payload = revised
            else:
                payload = _repair(case, revised or payload, still)
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


def _repair(case: CaseFile, payload: dict, issues: list[str]) -> dict:
    """Keep only steps that cite real evidence; use the template reply if it contradicts the decision."""
    ids = {item.id for item in case.evidence}
    bad = " ".join(i for i in issues if i.startswith("Mentions "))
    steps = [s for s in payload.get("explanation") or [] if isinstance(s, dict) and s.get("evidence_id") in ids
             and not any(tok in bad for tok in re.findall(r"\$\s?[\d.,]+", str(s.get("detail") or "")))]
    reply = payload.get("customer_reply")
    if any(i.startswith("Reply:") for i in issues):
        reply = _fallback_report(case)["customer_reply"]
    case.add_trace(step="reporter", agent="final-reviewer", action="repair",
                   detail=f"kept {len(steps)} cited steps; template reply={reply != payload.get('customer_reply')}")
    return {**payload, "customer_reply": reply, "explanation": steps or _fallback_report(case)["explanation"]}


def _ask(case: CaseFile, feedback: list[str] | None = None) -> dict | None:
    """Ask the fast model for the customer reply JSON (with reviewer feedback on a retry)."""
    content = _user_payload(case)
    if feedback:
        content += "\n\nThe final reviewer rejected your previous answer. Fix these issues: " + json.dumps(feedback)
    result = tracked_chat(
        case,
        agent="reporter",
        step="reporter",
        action="write",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content},
        ],
        lane="fast",
        detail="Revise reply after review" if feedback else "Write customer reply and explanation",
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
            "Thank you for writing in. Your request meets our refund policy and is approved "
            "for processing. You will get a confirmation once the refund is issued."
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

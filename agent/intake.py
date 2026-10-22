"""Intake agent: classify the customer message (fast lane)."""

from __future__ import annotations

from agent.parse import extract_json_object, extract_order_id, message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile

INTENTS = frozenset({"refund_request", "other"})
REASONS = frozenset({"defective", "changed_mind", "not_received", "wrong_item", "other"})
_REASON_ALIASES = {
    "damaged": "defective",
    "broken": "defective",
    "does_not_work": "defective",
    "doesnt_work": "defective",
    "faulty": "defective",
    "change_of_mind": "changed_mind",
    "changedmind": "changed_mind",
    "dont_like": "changed_mind",
    "don't_like": "changed_mind",
    "never_arrived": "not_received",
    "not_arrived": "not_received",
    "missing": "not_received",
    "undelivered": "not_received",
    "wrong_size": "wrong_item",
    "wrong_product": "wrong_item",
}

_SYSTEM = """You extract fields from a customer support message about a possible refund.
Reply with a single JSON object only, no markdown:
{"intent": "refund_request" or "other", "reason_type": "defective"|"changed_mind"|"not_received"|"wrong_item"|"other", "order_id": "ORD-####" or null}
Rules:
- intent is refund_request if they ask to return an item or get money back.
- defective: damaged, broken, sole coming off, will not turn on, stopped working.
- changed_mind: do not like it, does not fit, do not need it.
- not_received: never arrived, still has not arrived.
- wrong_item: wrong product sent.
- Copy the order id exactly if present (pattern ORD-####)."""


def run_intake(case: CaseFile) -> None:
    """Fill intent, reason_type and order_id from the customer message."""
    parsed = _ask(case, retry=False)
    if parsed is None:
        parsed = _ask(case, retry=True)
    if parsed is None:
        parsed = {
            "intent": "refund_request",
            "reason_type": "other",
            "order_id": extract_order_id(case.message),
        }
        case.add_trace(
            step="intake",
            agent="intake",
            action="fallback_parse",
            detail=f"Invalid model JSON; used regex order_id={parsed['order_id']}",
        )
    case.intent = parsed["intent"]
    case.reason_type = parsed["reason_type"]
    case.order_id = parsed["order_id"] or extract_order_id(case.message)


def _ask(case: CaseFile, *, retry: bool) -> dict | None:
    """Ask the fast model for intake JSON and validate it."""
    user = (
        f"Customer id: {case.customer_id}\n"
        f"Message: {case.message}\n"
    )
    if retry:
        user += (
            "Your previous reply was not valid JSON with intent, reason_type "
            "and order_id. Reply with only the JSON object."
        )
    result = tracked_chat(
        case,
        agent="intake",
        step="intake",
        action="classify" if not retry else "classify_retry",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        lane="fast",
        detail="Extract intent, reason_type, order_id",
    )
    return validate_intake(extract_json_object(message_text(result.get("message"))))


def validate_intake(data: dict | None) -> dict | None:
    """Return a normalised intake dict, or None if the payload is unusable."""
    if not isinstance(data, dict):
        return None
    intent = str(data.get("intent") or "").strip().lower()
    reason = _normalise_reason(data.get("reason_type"))
    if intent not in INTENTS or reason not in REASONS:
        return None
    order_id = data.get("order_id")
    if order_id in (None, "", "null", "none", "None"):
        order_id = None
    else:
        order_id = extract_order_id(str(order_id)) or str(order_id).strip().upper()
    return {"intent": intent, "reason_type": reason, "order_id": order_id}


def _normalise_reason(value: object) -> str:
    """Map free-text reason labels onto the allowed enum."""
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _REASON_ALIASES.get(raw, raw)

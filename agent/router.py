"""Route each customer message with Scout Intent before any agent runs.

Scout decides what the customer wants and returns a signed execution contract.
This module verifies the contract and then sends the case down one of these paths:

  refund.request / order.not-received -> the multi-agent refund review (returns "refund")
  order.status                        -> a direct Zetaris order lookup, no model calls
  policy.question                     -> the refund policy from Zetaris, no model calls
  order.cancel / account.update       -> human review (high risk, needs operator approval)
  GENERAL                             -> a polite reply, no tools
  blocked by Scout                    -> refused, no model or data access at all
  unclear                             -> Scout's clarification question back to the customer
"""

from __future__ import annotations

import json
import re

from agent import scout_gate
from agent.state import CaseFile
from agent.tools_zetaris import run_sql

REFUND_INTENTS = {"refund.request", "order.not-received"}
_ORDER_ID = re.compile(r"^ORD-\d{3,}$")
_CUSTOMER_ID = re.compile(r"^C\d{3,}$")


def route_request(case: CaseFile) -> str:
    """Run Scout, record the decision on the case, and return "refund" or "done"."""
    if not _CUSTOMER_ID.match(case.customer_id or ""):
        # The customer id comes from the signed-in session; anything else is refused
        # before it can reach Scout, a model or a SQL query.
        _finish(case, "refused", 1.0, "We couldn't verify your account. Please sign in again.",
                limitation="Invalid customer id")
        case.add_trace(step="scout", agent="router", action="invalid_customer", detail="customer id failed validation")
        return "done"
    try:
        decision = scout_gate.decide(case.message, case.customer_id)
    except scout_gate.ScoutUnavailable as exc:
        # Nothing acts on a raw prompt: without a contract, a person takes over.
        _finish(case, "human_review", 0.0, "Thank you for writing in. A support lead will review this request shortly.",
                limitation=f"Scout Intent was unavailable ({exc}); no automated action was taken.")
        case.add_trace(step="scout", agent="scout", action="unavailable", detail=str(exc)[:300])
        return "done"

    primary = decision["intent"]["primary"]
    contract = decision.get("executionContract")
    case.scout = {
        "intent": primary["id"],
        "score": primary["score"],
        "band": primary["band"],
        "risk": decision["risk"],
        "parameters": decision["intent"]["parameters"],
        "toolPlan": [f"{s['capability']} -> {s['tool']}" for s in decision.get("toolPlan", [])],
        "modelProfile": (decision.get("modelProfile") or {}).get("id"),
        "contractId": contract["contractId"] if contract else None,
        "clarification": decision.get("clarification"),
        "latencyMs": decision.get("latencyMs"),
    }
    case.add_trace(
        step="scout",
        agent="scout-intent",
        action="decide",
        detail=json.dumps(
            {
                "intent": primary["id"],
                "score": primary["score"],
                "band": primary["band"],
                "risk": decision["risk"]["level"],
                "flags": decision["risk"]["flags"],
                "contract": case.scout["contractId"],
                "latencyMs": decision.get("latencyMs"),
            }
        ),
    )

    if decision["risk"]["level"] == "block":
        _finish(
            case,
            "refused",
            1.0,
            "We can't process this message. If you need help with an order, please describe the problem and include your order number.",
            limitation=f"Blocked by Scout Intent guard: {decision['risk'].get('reason', 'policy')}",
        )
        return "done"

    if decision.get("clarification"):
        clar = decision["clarification"]
        options = "; ".join(o["label"] for o in clar.get("options", [])[:3])
        reply = clar["question"] + (f" For example: {options}." if options and clar["trigger"] != "params" else "")
        _finish(case, "needs_info", None, reply, limitation=f"Scout asked for clarification ({clar['trigger']}).")
        return "done"

    intent = primary["id"]
    params = decision["intent"]["parameters"]

    if intent in REFUND_INTENTS:
        ok, why = _verify(case, contract, "agent.review")
        if not ok:
            return "done"
        case.intent = "refund_request"
        order_id = params.get("order_id")
        if order_id and _ORDER_ID.match(order_id):
            case.order_id = order_id
        reason = params.get("reason_type")
        if reason and reason != "other":
            case.reason_type = reason
        return "refund"

    if intent == "order.status":
        if _verify(case, contract, "order.lookup")[0]:
            _answer_status(case, params.get("order_id"))
        return "done"

    if intent == "policy.question":
        if _verify(case, contract, "policy.lookup")[0]:
            _answer_policy(case)
        return "done"

    if intent in {"order.cancel", "account.update"}:
        ok, why = scout_gate.verify_contract(contract)
        case.add_trace(step="scout", agent="executor", action="contract.verify", detail=why)
        _finish(
            case,
            "human_review",
            0.95,
            "Thanks, we've received your request. Because it changes your order or account, a support lead will confirm it with you before anything is changed.",
            limitation="High-risk intent: Scout requires operator approval before any change.",
        )
        return "done"

    _finish(case, "answered", primary["score"],
            "Thanks for your message! I can help with refunds, missing orders, order tracking and our return policy. What can I do for you?")
    return "done"


def _verify(case: CaseFile, contract: dict | None, capability: str) -> tuple[bool, str]:
    """Executor check: the contract must be genuine, unexpired and allow this capability."""
    ok, why = scout_gate.verify_contract(contract, capability)
    case.add_trace(step="scout", agent="executor", action="contract.verified" if ok else "contract.refused",
                   detail=f"{capability}: {why}")
    if not ok:
        _finish(case, "human_review", 0.0, "Thank you for writing in. A support lead will review this request shortly.",
                limitation=f"Execution contract refused ({why}).")
    return ok, why


def _answer_status(case: CaseFile, order_id: str | None) -> None:
    """Order tracking: one read-only Zetaris query, then a templated reply."""
    if not order_id or not _ORDER_ID.match(order_id):
        _finish(case, "needs_info", None, "Could you share your order number (it looks like ORD-1234)?")
        return
    sql = (
        "SELECT order_id, product_name, order_date, delivery_date, status "
        f"FROM shop_orders.orders WHERE order_id = '{order_id}' AND customer_id = '{case.customer_id}'"
    )
    res = run_sql(sql)
    item = case.add_evidence(source="shop_orders.orders", sql=sql, rows=res.get("rows", []), note="order status")
    case.order_id = order_id
    if not res.get("ok") or not res.get("rows"):
        _finish(case, "needs_info", None, f"I couldn't find {order_id} on your account. Could you check the order number?")
        return
    row = res["rows"][0]
    if row.get("delivery_date"):
        reply = f"Your {row['product_name']} ({order_id}) was delivered on {row['delivery_date']}."
    else:
        reply = f"Your {row['product_name']} ({order_id}) was ordered on {row['order_date']} and is currently {row['status']}."
    _finish(case, "answered", 1.0, reply + f" [evidence {item.id}]")


def _answer_policy(case: CaseFile) -> None:
    """Policy questions: read the rules from Zetaris and quote the relevant ones."""
    sql = "SELECT rule_id, category, reason_type, rule_text FROM policy_kb.refund_policy ORDER BY rule_id"
    res = run_sql(sql)
    rows = res.get("rows", [])
    item = case.add_evidence(source="policy_kb.refund_policy", sql=sql, rows=rows, note="policy question")
    text = case.message.lower()
    picked = [r for r in rows if r.get("category", "ALL").lower() != "all" and r["category"].lower().split()[0] in text]
    picked += [r for r in rows if r.get("rule_id") in {"R1", "R3"}]
    seen, lines = set(), []
    for r in picked:
        if r["rule_id"] not in seen:
            seen.add(r["rule_id"])
            lines.append(f"{r['rule_text']} ({r['rule_id']})")
    case.rules_applied = sorted(seen)
    reply = " ".join(lines[:3]) if lines else "Please contact support for the full policy."
    _finish(case, "answered", 1.0, reply + f" [evidence {item.id}]")


def _finish(case: CaseFile, decision: str, confidence: float | None, reply: str, limitation: str | None = None) -> None:
    case.decision = decision
    case.confidence = confidence
    case.customer_reply = reply
    if limitation:
        case.limitations = list(case.limitations) + [limitation]

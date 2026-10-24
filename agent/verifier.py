"""Policy verifier: deterministic checks on what the LLM agents claim.

The critic model reviews a proposal in natural language. This module checks the
same proposal against the facts in Python, so a fluent but wrong claim cannot
pass: cited evidence must exist, cited rules must fit the order's category and
reason, numbers must match the checks, and the decision must respect the policy
windows. Any issue sends the proposal back to the decide agent for revision.

The final reviewer does the same for the reporter: every "why" line must cite
real evidence, and the customer reply must not contradict the decision.
"""

from __future__ import annotations

import re
from typing import Any

from agent.checks import policy_rows
from agent.state import CaseFile

_DAYS = re.compile(r"\b(\d{1,4})\s*-?\s*days?\b", re.I)
_MONEY = re.compile(r"(?:\$\s?|\b)(\d{1,3}(?:,\d{3})*\.\d{2})\b")
# Rules the code guards apply on their own (agent/critic.py); they are valid even if not retrieved.
_GUARD_RULES = {"R7", "R8", "R9", "R10"}
# Policy windows from the refund policy (R1 30, R2 15, R3 30, R4 14, R8 90 days).
_POLICY_WINDOWS = {14, 15, 30, 90}
_MONEY_ANY = re.compile(r"(?:\$|RM|USD)\s?(\d+(?:,\d{3})*(?:\.\d{1,2})?)", re.I)
# A promise to the customer, not a quote of the policy ("items may be returned for a full refund ...").
_GRANT = re.compile(r"\b(we(?:'ll| will| are going to| have| are)\s+(?:\w+\s+){0,2}refund(?:ing|ed)?|you(?:'ll| will) (?:receive|get) (?:a |your |the )?(?:full )?refund|(?:your |the )?refund (?:has been|will be|is) (?:approved|processed|issued|on its way))\b", re.I)
_NEGATION = re.compile(r"\b(not|cannot|can't|unable|won't|no longer|isn't|aren't|don't|doesn't)\b", re.I)
_DENIES = re.compile(r"\b(unable to (?:offer|issue|provide) a refund|cannot (?:offer|issue) a refund|not eligible for a refund|can't refund)\b", re.I)
_PAYMENT_PROMISE = re.compile(r"\b(business days|will be credited|has been credited|refund has been issued|has been refunded|within \d+\s*(?:-|to)\s*\d+ days)\b", re.I)
_APPROVED_WORDS = re.compile(r"\b(has been approved|is approved|approved a (?:full )?refund|we(?:'ve| have) approved|refund has been issued)\b", re.I)


def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def verify_proposal(case: CaseFile) -> list[str]:
    """Return a list of concrete problems with the decide agent's proposal (empty = OK)."""
    proposal = case.proposed_decision or {}
    checks = case.checks or {}
    issues: list[str] = []
    if not proposal:
        return issues

    evidence_ids = {item.id for item in case.evidence}
    for eid in proposal.get("evidence_ids") or []:
        if eid not in evidence_ids:
            issues.append(f"Cites evidence {eid}, which does not exist (have: {', '.join(sorted(evidence_ids))}).")

    rules = {str(r.get("rule_id")): r for r in policy_rows(case) if r.get("rule_id")}
    category = str(checks.get("category") or "")
    reason = case.reason_type or ""
    cited = [str(r).upper() for r in proposal.get("rules_applied") or []]
    for rid in cited:
        rule = rules.get(rid)
        if rules and rule is None:
            if rid not in _GUARD_RULES:
                issues.append(f"Cites rule {rid}, which is not in the retrieved policy rows.")
            continue
        if not rule:
            continue
        rule_cat = str(rule.get("category") or "ALL")
        rule_reason = str(rule.get("reason_type") or "any")
        if rule_cat not in ("ALL", category):
            issues.append(f"Rule {rid} is for {rule_cat} items, but this order is {category or 'unknown'}.")
        if rule_reason not in ("any", reason) and reason in {"changed_mind", "defective", "not_received"}:
            issues.append(f"Rule {rid} covers '{rule_reason}' requests, but this request is '{reason}'.")
    if "R1" in cited and category == "Electronics" and reason == "changed_mind":
        issues.append("Electronics change-of-mind returns fall under R2 (15 days), not R1 (30 days).")

    decision = proposal.get("decision")
    days_delivery = checks.get("days_since_delivery")
    if decision == "approve":
        if checks.get("final_sale") and reason != "defective":
            issues.append("Approves a final-sale item that is not defective (R5 says reject).")
        if category == "Digital" and checks.get("delivered") and reason != "defective":
            issues.append("Approves a delivered digital product that is not faulty (R6 says reject).")
        if reason in {"changed_mind", "defective"} and days_delivery is None:
            issues.append("Approves without a delivery date, so the policy window cannot be checked; this needs human review.")
        if reason == "not_received":
            days_order = checks.get("days_since_order")
            if days_order is None:
                issues.append("Approves 'not received' without an order date; R4 cannot be checked.")
            elif days_order < 14:
                issues.append(f"Approves 'not received' only {days_order} days after ordering; R4 requires 14 days.")
        if reason == "changed_mind" and category == "Electronics" and checks.get("customer_says_unopened") is not True:
            issues.append("Approves an Electronics change-of-mind return, but R2 requires the item to be unopened "
                          "and the customer has not said it is.")
        if reason == "changed_mind" and days_delivery is not None:
            window = 15 if category == "Electronics" else 30
            if days_delivery > window:
                issues.append(f"Approves a change-of-mind return {days_delivery} days after delivery; the window is {window} days.")
        if reason == "defective" and days_delivery is not None and days_delivery > 30:
            issues.append(f"Approves a defect claim {days_delivery} days after delivery; R3 allows 30 days.")
        if reason == "not_received" and checks.get("delivered"):
            issues.append("Approves 'not received' although the order record shows it was delivered.")

    text = str(proposal.get("rationale") or "")
    allowed_days = {v for v in (checks.get("days_since_delivery"), checks.get("days_since_order"),
                                checks.get("approved_refunds_last_90_days")) if v is not None}
    allowed_days |= {int(_num(r.get("window_days")) or 0) for r in rules.values()} | {0} | _POLICY_WINDOWS
    for match in _DAYS.finditer(text):
        n = int(match.group(1))
        if n not in allowed_days:
            issues.append(f"Rationale says '{match.group(0)}', which matches no check (delivery {checks.get('days_since_delivery')} days, order {checks.get('days_since_order')} days).")
    total = _num(checks.get("order_total"))
    allowed_money = {200.0, 0.0} | ({round(total, 2)} if total is not None else set())
    allowed_money |= {round(_num(r.get("auto_approve_limit")) or 0, 2) for r in rules.values()}
    for item in case.evidence:  # any amount that really appears in the retrieved rows
        for row in item.rows or []:
            values = row.values() if isinstance(row, dict) else (row if isinstance(row, (list, tuple)) else [])
            for v in values:
                n = _num(v)
                if n is not None:
                    allowed_money.add(round(n, 2))
    for match in _MONEY.finditer(text):
        value = _num(match.group(1))
        if value is not None and round(value, 2) not in allowed_money:
            issues.append(f"Rationale mentions {match.group(1)}, but the order total is {checks.get('order_total')}.")
    return list(dict.fromkeys(issues))


def review_report(case: CaseFile, payload: dict) -> list[str]:
    """Return problems with the reporter's reply and explanation (empty = OK)."""
    issues: list[str] = []
    evidence_ids = {item.id for item in case.evidence}
    steps = payload.get("explanation") or []
    if case.evidence and not steps:
        issues.append("The explanation has no steps; cite the evidence behind the decision.")
    for i, step in enumerate(steps, 1):
        eid = step.get("evidence_id") if isinstance(step, dict) else None
        if case.evidence and (not eid or eid not in evidence_ids):
            issues.append(f"Explanation step {i} cites '{eid}', which is not an evidence id ({', '.join(sorted(evidence_ids))}).")
    reply = str(payload.get("customer_reply") or "")
    if case.decision in {"reject", "human_review"} and (_APPROVED_WORDS.search(reply) or _grants_refund(reply)):
        issues.append(f"Reply: it tells the customer they will be refunded, but the decision is {case.decision}.")
    if case.decision == "approve" and _DENIES.search(reply):
        issues.append("Reply: it tells the customer the refund is refused, but the decision is approve.")
    if _PAYMENT_PROMISE.search(reply):
        issues.append("Reply: it promises payment timing or completion; RefundWise only decides, payment is processed separately.")
    allowed = _allowed_money(case)
    texts = [reply] + [str(s.get("detail") or "") + " " + str(s.get("step") or "") for s in steps if isinstance(s, dict)]
    for index, text in enumerate(texts):
        for match in _MONEY_ANY.finditer(text):
            value = _num(match.group(1))
            if value is not None and round(value, 2) not in allowed:
                where = "Reply: mentions" if index == 0 else "Mentions"
                issues.append(f"{where} {match.group(0).strip()}, which is not an amount in the evidence.")
    return list(dict.fromkeys(issues))


def _allowed_money(case: CaseFile) -> set:
    allowed = {200.0, 0.0}
    total = _num((case.checks or {}).get("order_total"))
    if total is not None:
        allowed.add(round(total, 2))
    for item in case.evidence:
        for row in item.rows or []:
            values = row.values() if isinstance(row, dict) else (row if isinstance(row, (list, tuple)) else [])
            for v in values:
                n = _num(v)
                if n is not None:
                    allowed.add(round(n, 2))
    return allowed


def _grants_refund(text: str) -> bool:
    """True if a sentence promises a refund without a negation."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _GRANT.search(sentence) and not _NEGATION.search(sentence):
            return True
    return False

"""Deterministic checks derived from evidence. The model may not change these."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from agent.state import CaseFile, EvidenceItem

AUTO_APPROVE_LIMIT = 200.0


def run_checks(case: CaseFile) -> None:
    """Compute factual checks from collected evidence rows."""
    order = _find_order_row(case)
    history = _find_history_rows(case)
    today = _as_date(case.demo_today) or date(2026, 10, 25)

    order_date = _as_date(_get(order, "order_date"))
    delivery_date = _as_date(_get(order, "delivery_date"))
    status = str(_get(order, "status") or "").strip().lower()
    order_total = _as_float(_get(order, "order_total")) or 0.0
    category = _get(order, "category")
    final_sale = _as_bool(_get(order, "final_sale"))
    this_order_id = case.order_id or _get(order, "order_id")
    order_customer = _get(order, "customer_id")
    order_found = bool(order)
    belongs = (str(order_customer) == case.customer_id) if order_customer else None

    delivered = status == "delivered"
    already_refunded = _already_refunded(status, history, this_order_id)
    approved_90 = _approved_refunds_last_90_days(history, today)

    case.checks = {
        "days_since_delivery": (today - delivery_date).days if delivery_date else None,
        "days_since_order": (today - order_date).days if order_date else None,
        "delivered": delivered,
        "order_total": order_total,
        "already_refunded": already_refunded,
        "approved_refunds_last_90_days": approved_90,
        "final_sale": final_sale,
        "category": category,
        "over_auto_limit": order_total > AUTO_APPROVE_LIMIT,
        "order_status": status or None,
        "delivery_date": delivery_date.isoformat() if delivery_date else None,
        "order_date": order_date.isoformat() if order_date else None,
        "order_found": order_found,
        "order_belongs_to_customer": belongs,
    }
    case.add_trace(
        step="checks",
        agent="checks",
        action="compute",
        detail=str(case.checks),
    )


def _already_refunded(status: str, history: list[dict], order_id: str | None) -> bool:
    """True if the order is marked refunded or has an approved history row."""
    if status == "refunded":
        return True
    if not order_id:
        return False
    for row in history:
        if str(_get(row, "order_id") or "") != order_id:
            continue
        if str(_get(row, "decision") or "").strip().lower() == "approved":
            return True
    return False


def _approved_refunds_last_90_days(history: list[dict], today: date) -> int:
    """Count approved refunds whose request_date is within 90 days."""
    cutoff = today - timedelta(days=90)
    count = 0
    for row in history:
        if str(_get(row, "decision") or "").strip().lower() != "approved":
            continue
        requested = _as_date(_get(row, "request_date"))
        if requested is not None and cutoff <= requested <= today:
            count += 1
    return count


def _find_order_row(case: CaseFile) -> dict[str, Any]:
    """Return the best matching order row from evidence."""
    for item in case.evidence:
        for row in _rows_as_dicts(item):
            if case.order_id and str(_get(row, "order_id") or "") != case.order_id:
                continue
            if row.get("customer_id") and str(row["customer_id"]) != case.customer_id:
                continue
            if "order_total" in row or "product_name" in row or "status" in row:
                return row
        if item.source == "lightning.metastore.refundwise.refundwise_usl.orders":
            rows = [
                r for r in _rows_as_dicts(item)
                if (not case.order_id or str(r.get("order_id") or "") == case.order_id)
            ]
            if rows:
                return rows[0]
    return {}


def _find_history_rows(case: CaseFile) -> list[dict[str, Any]]:
    """Return refund_history rows from evidence."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in case.evidence:
        looks_like_history = (
            item.source == "lightning.metastore.refundwise.refundwise_usl.refund_history"
            or "refund_history" in (item.sql or "").lower()
            or "refund history" in (item.note or "").lower()
        )
        for row in _rows_as_dicts(item):
            if not looks_like_history and "refund_id" not in row:
                continue
            # Never count another customer's refunds (model SQL may over-fetch).
            if row.get("customer_id") and str(row["customer_id"]) != case.customer_id:
                continue
            if "refund_id" not in row and "request_date" not in row:
                continue
            key = str(row.get("refund_id") or row)
            if key in seen:
                continue
            seen.add(key)
            found.append(row)
    return found


def policy_rows(case: CaseFile) -> list[dict[str, Any]]:
    """Return policy rule rows from evidence."""
    found: list[dict[str, Any]] = []
    for item in case.evidence:
        for row in _rows_as_dicts(item):
            if "rule_id" in row or "rule_text" in row:
                found.append(row)
    return found


def _rows_as_dicts(item: EvidenceItem) -> list[dict[str, Any]]:
    """Normalise evidence rows to dictionaries."""
    rows: list[dict[str, Any]] = []
    for row in item.rows or []:
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _get(row: dict[str, Any] | None, key: str) -> Any:
    """Read a column, matching keys case-insensitively."""
    if not row:
        return None
    if key in row:
        return row[key]
    lower = key.lower()
    for name, value in row.items():
        if str(name).lower() == lower:
            return value
    return None


def _as_date(value: Any) -> date | None:
    """Parse a Zetaris date string."""
    if value in (None, "", "null", "None", "NULL"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    """Parse a Zetaris numeric string."""
    if value in (None, "", "null", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    """Parse a Zetaris boolean string."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "t", "1", "yes"}

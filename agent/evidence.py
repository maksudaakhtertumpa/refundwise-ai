"""Evidence agent: gather order, history and policy rows via SQL (fast lane)."""

from __future__ import annotations

import json
from typing import Any

from agent.parse import message_text
from agent.runtime import tracked_chat
from agent.state import CaseFile
from agent.tools_zetaris import run_sql

MAX_TOOL_CALLS = 5

SCHEMA = """Zetaris tables (always query as source.table). All values come back as strings.

shop_orders.orders(
  order_id, customer_id, order_date, delivery_date, product_name, category,
  unit_price, quantity, order_total, payment_method, status, final_sale
)
support_desk.refund_history(
  refund_id, customer_id, order_id, request_date, amount, reason, decision
)
policy_kb.refund_policy(
  rule_id, category, reason_type, window_days, auto_approve_limit, outcome, rule_text
)

You must collect:
(a) the order row for this order_id and customer_id
(b) this customer's full refund_history
(c) refund_policy rows for the order's category AND category = 'ALL'

Read-only SELECT/WITH only, one statement per call. Use literal quoted strings (no bind parameters).
Every query on shop_orders.orders or support_desk.refund_history MUST filter on this
customer's customer_id; other queries are refused.
Call run_sql for each query. After you have a, b and c, stop calling tools and reply DONE.
"""

RUN_SQL_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Run a read-only SQL query against Zetaris.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SELECT/WITH query using source.table names.",
                    },
                    "limit": {"type": "integer", "description": "Max rows (default 100)."},
                },
                "required": ["sql"],
            },
        },
    }
]


def gather_evidence(case: CaseFile, extra_request: str | None = None) -> None:
    """Collect order, history and policy evidence, with SQL fallbacks."""
    sql_failed = _tool_loop(case, extra_request=extra_request)
    missing = _missing_buckets(case)
    if sql_failed or missing:
        _run_fallbacks(case, reason="sql_failed" if sql_failed else "missing " + ",".join(missing))


def _tool_loop(case: CaseFile, extra_request: str | None) -> bool:
    """Let the fast model call run_sql up to MAX_TOOL_CALLS times."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SCHEMA},
        {"role": "user", "content": _user_prompt(case, extra_request)},
    ]
    sql_failed = False
    tool_calls_used = 0
    while tool_calls_used < MAX_TOOL_CALLS:
        result = tracked_chat(
            case,
            agent="evidence",
            step="evidence",
            action="tool_round",
            messages=messages,
            lane="fast",
            tools=RUN_SQL_TOOL,
            detail=extra_request or "Collect order, history, policy",
        )
        message = result.get("message") or {}
        calls = _tool_calls(message)
        if not calls:
            break
        messages.append(message)
        for call in calls:
            if tool_calls_used >= MAX_TOOL_CALLS:
                break
            tool_calls_used += 1
            sql, limit = _sql_from_call(call)
            scope_error = scope_error_for(sql, case.customer_id) if sql else None
            if scope_error:
                payload = {"ok": False, "sql": sql, "rows": [], "error": scope_error}
                case.add_trace(step="evidence", agent="evidence", action="refused_sql", detail=scope_error)
            elif sql:
                payload = run_sql(sql, limit=limit)
            else:
                payload = {"ok": False, "sql": sql, "rows": [], "error": "Missing sql argument"}
            if not payload.get("ok"):
                sql_failed = True
            item = case.add_evidence(
                source=infer_source(sql),
                sql=payload.get("sql") or sql or "",
                rows=payload.get("rows") or [],
                note=_note_for(payload, infer_source(sql)),
            )
            case.add_trace(
                step="evidence",
                agent="evidence",
                action="run_sql",
                detail=f"{item.id} ok={payload.get('ok')} source={item.source}"
                + ("" if payload.get("ok") else f" error={str(payload.get('error'))[:200]}"),
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or item.id,
                    "content": json.dumps(
                        {
                            "ok": payload.get("ok"),
                            "error": payload.get("error"),
                            "columns": payload.get("columns"),
                            "rows": payload.get("rows"),
                            "evidence_id": item.id,
                        }
                    ),
                }
            )
        if _missing_buckets(case) == [] and not extra_request:
            break
    return sql_failed


def _user_prompt(case: CaseFile, extra_request: str | None) -> str:
    """Build the evidence-gathering user message."""
    lines = [
        f"Customer id: {case.customer_id}",
        f"Order id: {case.order_id}",
        f"Reason type: {case.reason_type}",
        f"Demo today: {case.demo_today}",
        f"Customer message: {case.message}",
    ]
    if extra_request:
        lines.append("The critic asked for more evidence:")
        lines.append(extra_request)
        if case.evidence:
            have = ", ".join(f"{item.id}={item.source}" for item in case.evidence)
            lines.append(f"Already collected: {have}")
    return "\n".join(lines)


def _run_fallbacks(case: CaseFile, *, reason: str) -> None:
    """Run the three fixed queries so the pipeline never stalls."""
    category = _category_from_evidence(case)
    for source, sql, note in _fallback_queries(case, category):
        if _has_source(case, source) and note != "critic extra":
            continue
        payload = run_sql(sql)
        item = case.add_evidence(
            source=source,
            sql=sql,
            rows=payload.get("rows") or [],
            note=f"fallback ({reason}): {note}"
            + ("" if payload.get("ok") else f" [query failed: {str(payload.get('error'))[:200]}]"),
        )
        case.add_trace(
            step="evidence",
            agent="evidence",
            action="fallback_sql",
            detail=f"{item.id} {source} ok={payload.get('ok')}"
            + ("" if payload.get("ok") else f" error={str(payload.get('error'))[:200]}"),
        )


def _fallback_queries(case: CaseFile, category: str | None) -> list[tuple[str, str, str]]:
    """Parameterised order, history and policy SELECTs."""
    cid = _sql_literal(case.customer_id)
    oid = _sql_literal(case.order_id or "")
    queries = [
        (
            "shop_orders.orders",
            (
                "SELECT order_id, customer_id, order_date, delivery_date, product_name, "
                "category, unit_price, quantity, order_total, payment_method, status, final_sale "
                f"FROM shop_orders.orders WHERE order_id = {oid} AND customer_id = {cid}"
            ),
            "order row",
        ),
        (
            "support_desk.refund_history",
            (
                "SELECT refund_id, customer_id, order_id, request_date, amount, reason, decision "
                f"FROM support_desk.refund_history WHERE customer_id = {cid}"
            ),
            "customer refund history",
        ),
    ]
    if category:
        cat = _sql_literal(category)
        policy_sql = (
            "SELECT rule_id, category, reason_type, window_days, auto_approve_limit, outcome, rule_text "
            f"FROM policy_kb.refund_policy WHERE category IN ({cat}, 'ALL')"
        )
    else:
        policy_sql = (
            "SELECT rule_id, category, reason_type, window_days, auto_approve_limit, outcome, rule_text "
            "FROM policy_kb.refund_policy"
        )
    queries.append(("policy_kb.refund_policy", policy_sql, "policy rules"))
    return queries


_CUSTOMER_SCOPED = ("shop_orders.orders", "support_desk.refund_history")


def scope_error_for(sql: str, customer_id: str) -> str | None:
    """Refuse model-written SQL that could read another customer's data.

    Order and refund-history queries must contain this customer's id; the customers
    table (names, emails) is not needed for a refund decision and is not exposed.
    """
    lower = (sql or "").lower()
    if "support_desk.customers" in lower:
        return "Query refused: the customers table is not needed for refund evidence"
    if any(t in lower for t in _CUSTOMER_SCOPED):
        if "customer_id" not in lower or f"'{customer_id.lower()}'" not in lower:
            return f"Query refused: filter by customer_id = '{customer_id}'"
    return None


def _sql_literal(value: str) -> str:
    """Quote a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def infer_source(sql: str) -> str:
    """Guess which table a query reads."""
    lower = (sql or "").lower()
    for name in (
        "shop_orders.orders",
        "support_desk.refund_history",
        "support_desk.customers",
        "policy_kb.refund_policy",
    ):
        if name in lower:
            return name
    return "zetaris"


def _note_for(payload: dict[str, Any], source: str) -> str:
    """Short note stored on the evidence item."""
    if payload.get("ok"):
        return source
    return f"query failed: {payload.get('error')}"


def _missing_buckets(case: CaseFile) -> list[str]:
    """Return which of order/history/policy evidence is still missing."""
    missing: list[str] = []
    if not _has_source(case, "shop_orders.orders"):
        missing.append("order")
    if not _has_source(case, "support_desk.refund_history"):
        missing.append("history")
    if not _has_source(case, "policy_kb.refund_policy"):
        missing.append("policy")
    return missing


def _has_source(case: CaseFile, source: str) -> bool:
    """True if we already stored a successful (or any) query for this table."""
    for item in case.evidence:
        if item.source == source and item.rows:
            return True
        if item.source == source and "failed" not in (item.note or "").lower():
            # Empty history is a valid result.
            if source == "support_desk.refund_history":
                return True
    return False


def _category_from_evidence(case: CaseFile) -> str | None:
    """Read category from an order evidence row if we already have one."""
    for item in case.evidence:
        if item.source != "shop_orders.orders":
            continue
        for row in item.rows or []:
            if isinstance(row, dict) and row.get("category"):
                return str(row["category"])
    return None


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise tool_calls from a chat message dict."""
    raw = message.get("tool_calls") or []
    calls: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            calls.append(item)
        elif hasattr(item, "model_dump"):
            calls.append(item.model_dump())
    if calls:
        return calls
    # Some models write a SQL statement in content instead of a tool call.
    text = message_text(message)
    if text and text.strip().upper().startswith("SELECT"):
        return [{"id": "inline-sql", "function": {"name": "run_sql", "arguments": json.dumps({"sql": text.strip()})}}]
    return []


def _sql_from_call(call: dict[str, Any]) -> tuple[str, int]:
    """Extract sql and limit from a tool call."""
    fn = call.get("function") or call
    name = (fn.get("name") if isinstance(fn, dict) else None) or call.get("name")
    if name and name != "run_sql":
        return "", 100
    arguments = fn.get("arguments") if isinstance(fn, dict) else call.get("arguments")
    parsed: dict[str, Any] = {}
    if isinstance(arguments, dict):
        parsed = arguments
    elif isinstance(arguments, str) and arguments.strip():
        try:
            loaded = json.loads(arguments)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = {"sql": arguments}
    sql = str(parsed.get("sql") or parsed.get("query") or "").strip()
    try:
        limit = int(parsed.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    return sql, limit

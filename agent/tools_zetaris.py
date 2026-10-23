"""Zetaris SQL tool for RefundWise AI.

Runs read-only SQL against the Zetaris REST API. Credentials come from
environment variables loaded via python-dotenv; the API key is never
printed, logged, or returned.
"""

from __future__ import annotations

import os
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

_ALLOWED_PREFIXES = ("SELECT", "WITH", "SHOW", "DESCRIBE")
_LONG_DECIMAL = re.compile(r"^-?\d+\.\d{6,}$")
_TWO_PLACES = Decimal("0.01")


def run_sql(sql: str, limit: int = 100) -> dict:
    """Execute a read-only SQL statement through Zetaris.

    Returns {"ok", "sql", "columns", "rows", "error"} and, when a JSON
    body is available, "raw_keys" with the top-level response keys.
    """
    result: dict[str, Any] = {
        "ok": False,
        "sql": sql,
        "columns": [],
        "rows": [],
        "error": None,
    }

    safe_error = _safety_error(sql)
    if safe_error:
        result["error"] = safe_error
        return result

    if (os.getenv("SAMPLE_MODE") or "").strip().lower() in {"1", "true", "yes"}:
        return _run_sample(sql, limit, result)

    rest_url = (os.getenv("ZETARIS_REST_URL") or "").rstrip("/")
    org_id = os.getenv("ZETARIS_ORG_ID") or ""
    api_key = os.getenv("ZETARIS_API_KEY") or ""
    if not rest_url or not org_id or not api_key:
        result["error"] = "Missing Zetaris settings: ZETARIS_REST_URL, ZETARIS_ORG_ID, ZETARIS_API_KEY"
        return result

    url = f"{rest_url}/sql-editor/sqls/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Org-ID": org_id,
        "X-Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "queryId": str(uuid.uuid4()),
        "sql": sql,
        "source": "SqlEditor",
        "limit": limit,
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=60)
    except requests.RequestException as exc:
        result["error"] = f"Request failed: {_public_error(exc)}"
        return result

    payload = _parse_json(response)
    if isinstance(payload, dict):
        result["raw_keys"] = list(payload.keys())
    elif payload is not None:
        result["raw_keys"] = []

    if response.status_code >= 400:
        result["error"] = _http_error(response.status_code, payload)
        return result

    if not isinstance(payload, dict):
        result["error"] = "Zetaris did not return a JSON object"
        return result

    api_error = _payload_error(payload)
    if api_error:
        result["error"] = api_error
        return result

    columns, rows = _extract_table(payload)
    result["ok"] = True
    result["columns"] = columns
    result["rows"] = _round_decimals(rows)
    return result


_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|grant|revoke|merge|register|cache|uncache|refresh|set)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*)", re.IGNORECASE)
# The only Zetaris tables RefundWise may read.
ALLOWED_TABLES = frozenset(
    {"shop_orders.orders", "support_desk.customers", "support_desk.refund_history", "policy_kb.refund_policy"}
)


def _strip_literals(sql: str) -> str:
    """Remove quoted string literals so keywords inside values are not flagged."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _safety_error(sql: str) -> str | None:
    stripped = sql.strip()
    if not stripped:
        return "Empty SQL is not allowed"
    first = stripped.split(None, 1)[0].upper().rstrip(";")
    if first not in _ALLOWED_PREFIXES:
        return (
            f"Only read-only statements are allowed "
            f"(SELECT, WITH, SHOW, DESCRIBE); refused {first!r}"
        )
    bare = _strip_literals(stripped)
    if ";" in bare.rstrip().rstrip(";"):
        return "Only one SQL statement per call is allowed"
    if _WRITE_WORDS.search(bare):
        return "Write or admin keywords are not allowed in read-only queries"
    if first in {"SELECT", "WITH"}:
        for table in _TABLE_REF.findall(bare):
            if table.lower() not in ALLOWED_TABLES:
                return f"Table {table} is not on the RefundWise allow-list"
    return None


def _parse_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _http_error(status_code: int, payload: Any) -> str:
    detail = _payload_error(payload) if payload is not None else None
    if not detail and isinstance(payload, dict):
        detail = payload.get("message") or payload.get("error")
    if not detail and isinstance(payload, str) and payload.strip():
        detail = payload.strip()[:500]
    if detail:
        return f"HTTP {status_code}: {detail}"
    return f"HTTP {status_code}"


def _payload_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("error", "errorMessage", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and key != "message":
            return value
        if isinstance(value, dict):
            nested = value.get("message") or value.get("error") or value.get("detail")
            if isinstance(nested, str) and nested.strip():
                return nested
    status = str(payload.get("status") or payload.get("state") or "").upper()
    if status in {"FAILED", "ERROR", "FAILURE"}:
        return str(
            payload.get("message")
            or payload.get("reason")
            or f"Query {status.lower()}"
        )
    success = payload.get("success")
    if success is False:
        return str(payload.get("message") or "Query failed")
    return None


def _extract_table(payload: dict) -> tuple[list, list]:
    direct = _table_from_mapping(payload)
    if direct is not None:
        return direct

    for key in ("data", "result", "payload", "body", "response", "content"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _extract_table(nested)
            if found[0] or found[1]:
                return found
        elif isinstance(nested, list) and nested:
            return _table_from_rows(nested)

    rows = payload.get("rows")
    if isinstance(rows, list):
        return _table_from_rows(rows)
    return [], []


def _table_from_mapping(payload: dict) -> tuple[list, list] | None:
    columns_raw = (
        payload.get("columns")
        or payload.get("headers")
        or payload.get("columnNames")
        or payload.get("cols")
        or payload.get("fields")
    )
    rows_raw = payload.get("rows")
    if rows_raw is None:
        rows_raw = payload.get("data")
    if rows_raw is None:
        rows_raw = payload.get("records")
    if rows_raw is None:
        rows_raw = payload.get("values")

    if not isinstance(columns_raw, list) and not isinstance(rows_raw, list):
        return None
    if isinstance(rows_raw, list):
        columns = _column_names(columns_raw) if isinstance(columns_raw, list) else []
        if not columns and rows_raw and isinstance(rows_raw[0], dict):
            columns = list(rows_raw[0].keys())
        rows = _normalize_rows(rows_raw, columns)
        return columns, rows
    if isinstance(columns_raw, list):
        return _column_names(columns_raw), []
    return None


def _table_from_rows(rows_raw: list) -> tuple[list, list]:
    columns: list[str] = []
    if rows_raw and isinstance(rows_raw[0], dict):
        columns = list(rows_raw[0].keys())
    return columns, _normalize_rows(rows_raw, columns)


def _column_names(columns: list) -> list[str]:
    names: list[str] = []
    for col in columns:
        if isinstance(col, str):
            names.append(col)
        elif isinstance(col, dict):
            name = (
                col.get("name")
                or col.get("columnName")
                or col.get("column")
                or col.get("label")
                or col.get("field")
            )
            names.append(str(name) if name is not None else str(col))
        else:
            names.append(str(col))
    return names


def _normalize_rows(rows_raw: list, columns: list[str]) -> list:
    rows: list = []
    for row in rows_raw:
        if isinstance(row, dict):
            if columns:
                rows.append({col: row.get(col) for col in columns})
            else:
                rows.append(dict(row))
        elif isinstance(row, list):
            if columns:
                rows.append(dict(zip(columns, row)))
            else:
                rows.append(list(row))
        else:
            rows.append(row)
    return rows


def _round_decimals(value: Any) -> Any:
    if isinstance(value, str) and _LONG_DECIMAL.match(value):
        try:
            return str(Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
        except InvalidOperation:
            return value
    if isinstance(value, Decimal):
        return str(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))
    if isinstance(value, dict):
        return {key: _round_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_decimals(item) for item in value]
    return value


def _public_error(exc: BaseException) -> str:
    text = str(exc)
    api_key = os.getenv("ZETARIS_API_KEY") or ""
    if api_key and api_key in text:
        text = text.replace(api_key, "***")
    return text


# ---------------------------------------------------------------------------
# SAMPLE_MODE: run the same read-only SQL against the CSV snapshot in data/sample
# (SQLite, one attached database per Zetaris source) when Zetaris is not running.
# ---------------------------------------------------------------------------
_SAMPLE_DB = None


def _sample_db():
    global _SAMPLE_DB
    if _SAMPLE_DB is not None:
        return _SAMPLE_DB
    import csv
    import sqlite3

    con = sqlite3.connect(":memory:")
    for path in sorted((_ROOT / "data" / "sample").glob("*__*.csv")):
        source, table = path.stem.split("__", 1)
        if source not in {r[1] for r in con.execute("PRAGMA database_list")}:
            con.execute(f"ATTACH DATABASE ':memory:' AS {source}")
        with path.open(newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            cols = ", ".join(f'"{c}" TEXT' for c in header)
            con.execute(f"CREATE TABLE {source}.{table} ({cols})")
            marks = ", ".join("?" for _ in header)
            con.executemany(
                f"INSERT INTO {source}.{table} VALUES ({marks})",
                ([v if v != "" else None for v in row] for row in reader),
            )
    _SAMPLE_DB = con
    return con


def _run_sample(sql: str, limit: int, result: dict) -> dict:
    """Execute against the CSV snapshot; same return shape as the Zetaris path."""
    import sqlite3

    try:
        cur = _sample_db().execute(sql)
        columns = [d[0] for d in cur.description or []]
        rows = [dict(zip(columns, r)) for r in cur.fetchmany(limit)]
    except sqlite3.Error as exc:
        result["error"] = f"SAMPLE_MODE query failed: {exc}"
        return result
    result.update({"ok": True, "columns": columns, "rows": _round_decimals(rows), "mode": "sample"})
    return result

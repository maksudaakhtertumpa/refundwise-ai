"""Smoke-test the Zetaris run_sql tool against a trivial query and the demo join."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools_zetaris import run_sql  # noqa: E402


def last_select_statement(path: Path) -> str:
    selects = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip().upper().startswith("SELECT")
    ]
    if not selects:
        raise SystemExit(f"No SELECT statement found in {path}")
    return selects[-1]


def main() -> None:
    first = run_sql("SELECT 1 AS one")
    print("=== SELECT 1 AS one ===")
    print("raw JSON top-level keys:", first.get("raw_keys"))
    print(first)

    join_sql = last_select_statement(ROOT / "data" / "zetaris_register.sql")
    second = run_sql(join_sql)
    print("=== last SELECT in data/zetaris_register.sql ===")
    print(second)


if __name__ == "__main__":
    main()

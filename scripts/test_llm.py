"""Smoke-test Meterless chat on the fast and deep lanes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.llm import chat  # noqa: E402

PROMPT = "Reply with one short sentence confirming you are ready."


def main() -> None:
    messages = [{"role": "user", "content": PROMPT}]
    for lane in ("fast", "deep"):
        result = chat(messages, lane=lane)
        message = result.get("message") or {}
        answer = message.get("content") if isinstance(message, dict) else message
        print(f"=== lane={lane} ===")
        print("model:", result.get("model"))
        if result.get("note"):
            print("note:", result["note"])
        print("answer:", answer)


if __name__ == "__main__":
    main()

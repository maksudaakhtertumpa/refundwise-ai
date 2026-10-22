"""JSON helpers for model outputs."""

from __future__ import annotations

import json
import re
from typing import Any

_ORDER_ID = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """Parse the first JSON object found in model text."""
    if not text or not str(text).strip():
        return None
    blob = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", blob, re.DOTALL | re.IGNORECASE)
    if fenced:
        blob = fenced.group(1)
    decoder = json.JSONDecoder()
    for index, char in enumerate(blob):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(blob[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def message_text(message: dict[str, Any] | None) -> str:
    """Flatten chat message content to a string."""
    if not message:
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return "" if content is None else str(content)


def extract_order_id(text: str | None) -> str | None:
    """Pull an ORD-#### token out of free text."""
    if not text:
        return None
    match = _ORDER_ID.search(text)
    return match.group(0).upper() if match else None

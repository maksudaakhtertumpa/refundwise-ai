"""Meterless / Nightshift chat client for RefundWise AI.

Uses the OpenAI-compatible API. The runtime token is never printed, logged,
or returned.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI, OpenAIError

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

_FAST_DEFAULT = "nvidia/nemotron-3.5-lightning-30b-a3b"
_DEEP_DEFAULT = "nvidia/nemotron-3.5-super-vl-120b-a12b"
_FALLBACK_DEFAULT = "meterless/auto"
_HEADERS = {
    "meterless-app": "refundwise",
    "meterless-scope": "user",
}

_client: OpenAI | None = None


def chat(
    messages: list,
    lane: str = "fast",
    tools: list | None = None,
    temperature: float = 0.2,
    timeout: float | None = None,
) -> dict:
    """Send a chat completion.

    ``timeout`` caps the total wait in seconds (the caller's remaining case
    budget); without it the lane's own timeout and retries apply.

    Returns the assistant message, the model that answered, and a note when
    Nightshift rejected the requested model id and a fallback was used.
    """
    requested = _model_for_lane(lane)
    fallback = os.getenv("METERLESS_MODEL") or _FALLBACK_DEFAULT
    # The deep lane (a 120B model on a free hosted endpoint) can take minutes,
    # so it gets a longer timeout and fewer retries than the fast lane.
    started = time.monotonic()
    lane_timeout = _timeout_for_lane(lane)
    retries = 1 if lane.strip().lower() == "deep" else 2
    if timeout is not None:
        # Never let retries outlive the case budget.
        retries = 1 if timeout >= 2 * lane_timeout else 0
        lane_timeout = max(5.0, min(lane_timeout, timeout))
    client = _get_client().with_options(timeout=lane_timeout, max_retries=retries)

    try:
        completion, used_model, note = _complete(
            client,
            messages=messages,
            model=requested,
            tools=tools,
            temperature=temperature,
            fallback_model=fallback,
        )
    except RuntimeError as exc:
        # Nightshift sometimes aborts a request (HTTP 499) when the hosted
        # endpoint is slow or rate-limited. Retry once on the fast Nemotron
        # lane so the case can finish, and record that it happened.
        if not _is_aborted(exc):
            raise
        retry_timeout = _timeout_for_lane("fast")
        if timeout is not None:
            retry_timeout = min(retry_timeout, timeout - (time.monotonic() - started))
            if retry_timeout < 10:
                raise RuntimeError(f"{exc} (no time left in the case budget to retry)") from exc
        retry_model = _model_for_lane("fast")
        completion, used_model, note = _complete(
            _get_client().with_options(timeout=retry_timeout, max_retries=0 if timeout is not None else 1),
            messages=messages,
            model=retry_model,
            tools=tools,
            temperature=temperature,
            fallback_model=fallback,
        )
        note = f"Request on {requested!r} was aborted; retried on {retry_model!r}."
    choice = completion.choices[0].message
    message = _assistant_message(choice)
    answered = completion.model or used_model
    return {
        "message": message,
        "model": answered,
        "note": note,
    }


def _get_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client

    base_url = (os.getenv("METERLESS_BASE_URL") or "").rstrip("/")
    api_key = os.getenv("METERLESS_RUNTIME_TOKEN") or ""
    if not base_url or not api_key:
        raise RuntimeError(
            "Missing Meterless settings: METERLESS_BASE_URL, METERLESS_RUNTIME_TOKEN"
        )

    _client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=90,
        max_retries=2,
        default_headers=_HEADERS,
    )
    return _client


def _is_aborted(exc: BaseException) -> bool:
    """True when Nightshift aborted or timed out the request, or the upstream returned 5xx."""
    text = str(exc)
    return (
        "request_aborted" in text
        or "Error code: 499" in text
        or "timed out" in text.lower()
        or "Error code: 50" in text
    )


def _timeout_for_lane(lane: str) -> float:
    """Seconds to wait for one completion on this lane (override in .env)."""
    if lane.strip().lower() == "deep":
        return float(os.getenv("NEMOTRON_DEEP_TIMEOUT") or 180)
    return float(os.getenv("NEMOTRON_FAST_TIMEOUT") or 90)


def _model_for_lane(lane: str) -> str:
    key = lane.strip().lower()
    if key == "fast":
        return os.getenv("NEMOTRON_FAST_MODEL") or _FAST_DEFAULT
    if key == "deep":
        return os.getenv("NEMOTRON_DEEP_MODEL") or _DEEP_DEFAULT
    raise ValueError(f"Unknown lane {lane!r}; use 'fast' or 'deep'")


def _complete(
    client: OpenAI,
    *,
    messages: list,
    model: str,
    tools: list | None,
    temperature: float,
    fallback_model: str,
) -> tuple[Any, str, str | None]:
    try:
        completion = _create(
            client,
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature,
        )
        return completion, model, None
    except OpenAIError as exc:
        if not _is_model_rejected(exc) or model == fallback_model:
            raise RuntimeError(_public_error(exc)) from None
        try:
            completion = _create(
                client,
                messages=messages,
                model=fallback_model,
                tools=tools,
                temperature=temperature,
            )
        except OpenAIError as fallback_exc:
            raise RuntimeError(_public_error(fallback_exc)) from None
        note = (
            f"Nightshift rejected model {model!r}; "
            f"fell back to {fallback_model!r}."
        )
        return completion, fallback_model, note


def _create(
    client: OpenAI,
    *,
    messages: list,
    model: str,
    tools: list | None,
    temperature: float,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools is not None:
        kwargs["tools"] = tools
    return client.chat.completions.create(**kwargs)


def _assistant_message(choice: Any) -> dict[str, Any]:
    if hasattr(choice, "model_dump"):
        dumped = choice.model_dump(exclude_none=True)
        dumped.setdefault("role", "assistant")
        return dumped
    message: dict[str, Any] = {
        "role": getattr(choice, "role", None) or "assistant",
        "content": getattr(choice, "content", None),
    }
    tool_calls = getattr(choice, "tool_calls", None)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _is_model_rejected(exc: OpenAIError) -> bool:
    status = getattr(exc, "status_code", None)
    text = _error_text(exc).lower()
    looks_like_model = any(
        token in text
        for token in (
            "model",
            "unknown model",
            "invalid model",
            "not found",
            "unsupported",
            "does not exist",
        )
    )
    if isinstance(exc, APIStatusError) and status in {400, 404, 422}:
        return looks_like_model or status in {404, 422}
    return looks_like_model and status in {400, 404, 422, None}


def _error_text(exc: BaseException) -> str:
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(response.text)
        except Exception:
            pass
    return " ".join(parts)


def _public_error(exc: BaseException) -> str:
    text = _error_text(exc)
    token = os.getenv("METERLESS_RUNTIME_TOKEN") or ""
    if token and token in text:
        text = text.replace(token, "***")
    return text

"""Scout Intent gate: nothing in RefundWise acts on a raw customer message.

Every message first goes through the Meterless Scout Intent engine (scout/, Node).
Scout senses the intent, guards against injection and policy violations, routes to
tools and returns a signed execution contract. This module calls Scout and verifies
the contract before any agent, model or Zetaris query is allowed to run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOUT_CLI = ROOT / "scout" / "cli.js"
REGISTRY = ROOT / "scout" / "registry" / "refundwise.json"
POLICY_PACKS = ["default", "refundwise"]
TELEMETRY = ROOT / "scout" / "telemetry" / "events.jsonl"

# One signing key per process unless SCOUT_SIGNING_SECRET is set: Scout signs with it,
# and this module verifies with it, so a contract cannot be altered in between.
_SECRET = os.environ.get("SCOUT_SIGNING_SECRET") or secrets.token_hex(32)


class ScoutUnavailable(RuntimeError):
    """Scout could not run (Node missing, crash or timeout)."""


def decide(message: str, customer_id: str, *, role: str = "customer", surface: str = "chat") -> dict[str, Any]:
    """Run the full Scout pipeline on one message and return its decision."""
    node = shutil.which("node")
    if not node:
        raise ScoutUnavailable("Node.js is not installed, so Scout Intent cannot run")
    payload = {
        "prompt": message,
        "user": {"id": customer_id, "role": role},
        "surface": surface,
        "intentRegistry": str(REGISTRY),
        "policyPack": POLICY_PACKS,
    }
    env = {**os.environ, "SCOUT_SIGNING_SECRET": _SECRET, "SCOUT_TELEMETRY": str(TELEMETRY)}
    try:
        proc = subprocess.run(
            [node, str(SCOUT_CLI)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            cwd=str(ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScoutUnavailable(f"Scout did not finish: {exc}") from None
    if proc.returncode != 0:
        raise ScoutUnavailable(f"Scout failed: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout)


def canonical_json(value: Any) -> str:
    """Same canonical encoding Scout signs (sorted keys, no whitespace)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_contract(
    contract: dict[str, Any] | None,
    capability: str | None = None,
    approvals_granted: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Executor-side check before acting: signature, expiry, scope, approvals."""
    if not contract or not isinstance(contract.get("signature"), str):
        return False, "unsigned"
    body = {k: v for k, v in contract.items() if k != "signature"}
    expected = hmac.new(_SECRET.encode(), canonical_json(body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, contract["signature"]):
        return False, "bad-signature"
    expires = datetime.fromisoformat(contract["expiresAt"].replace("Z", "+00:00"))
    if expires <= datetime.now(timezone.utc):
        return False, "expired"
    if capability and capability not in (contract.get("scope") or {}).get("capabilities", []):
        return False, "scope-mismatch"
    needed = [a for a in (contract.get("risk") or {}).get("approvals", []) if a not in approvals_granted]
    if needed:
        return False, "approval-required:" + ",".join(needed)
    return True, "ok"

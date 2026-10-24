"""The critic loop and the final reviewer, tested without a live model.

The model is replaced by a scripted stand-in so the test is deterministic. The
data comes from the CSV snapshot (SAMPLE_MODE), Scout Intent runs for real, and
every check, guard, verifier and loop is the production code.
Run:  .venv/bin/python -m unittest discover tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SAMPLE_MODE"] = "true"
os.environ["TRACE_STDOUT"] = "false"
os.environ.setdefault("REFUNDWISE_LOG_DIR", tempfile.mkdtemp(prefix="refundwise-logs-"))

from agent import runtime  # noqa: E402
from agent.checks import run_checks  # noqa: E402
from agent.orchestrator import run_case  # noqa: E402
from agent.state import CaseFile  # noqa: E402
from agent.verifier import review_report, verify_proposal  # noqa: E402

HEADPHONES = "I don't really like the wireless headphones I bought (ORD-1017). I'd like my money back."


def scripted_model(proposals: list[dict], report: dict):
    """A stand-in for Nightshift: decide returns the scripted proposals in order."""
    state = {"decide": 0}

    def chat(messages, lane="fast", tools=None, temperature=0.2, timeout=None):
        system = messages[0]["content"]
        if "proposing a refund decision" in system:
            body = proposals[min(state["decide"], len(proposals) - 1)]
            state["decide"] += 1
        elif "strict critic" in system:
            body = {"verdict": "accept", "missing_evidence": "", "reason": "Looks fine to me.", "issues": []}
        elif "customer_reply" in system:
            body = report
        else:  # intake / evidence agent: no tool calls, so the fixed customer-scoped queries run
            body = {}
        return {"message": {"role": "assistant", "content": json.dumps(body)}, "model": "scripted-test-model", "note": None}

    return chat, state


class CriticLoop(unittest.TestCase):
    def test_wrong_proposal_is_sent_back_and_fixed(self):
        wrong = {"decision": "approve", "rules_applied": ["R1"], "confidence": 0.9,
                 "rationale": "Change of mind within 30 days (E1).", "evidence_ids": ["E1"]}
        right = {"decision": "reject", "rules_applied": ["R2"], "confidence": 0.95,
                 "rationale": "Electronics change of mind is limited to 15 days; delivered 66 days ago (E1, E3).",
                 "evidence_ids": ["E1", "E3"]}
        report = {"customer_reply": "Sorry, we can't refund these headphones: the 15-day window for electronics has passed.",
                  "explanation": [{"step": "Order", "evidence_id": "E1", "detail": "Delivered 66 days ago"},
                                  {"step": "Policy", "evidence_id": "E3", "detail": "R2: 15 days for electronics"}],
                  "limitations": []}
        chat, state = scripted_model([wrong, right], report)
        with mock.patch.object(runtime, "chat", chat):
            case = run_case(HEADPHONES, "C007", demo_today="2026-10-25")
        self.assertEqual(state["decide"], 2, "decide should be asked twice")
        self.assertEqual(case.decision, "reject")
        actions = [(t.agent, t.action) for t in case.trace]
        self.assertIn(("orchestrator", "revise"), actions)
        verdicts = [json.loads(t.detail)["verdict"] for t in case.trace if t.agent == "critic" and t.action == "verdict"]
        self.assertEqual(verdicts, ["revise", "accept"])
        self.assertTrue(case.log_path)


class Verifier(unittest.TestCase):
    def _case(self):
        case = CaseFile(message=HEADPHONES, customer_id="C007", demo_today="2026-10-25")
        case.order_id, case.reason_type = "ORD-1017", "changed_mind"
        case.add_evidence(source="lightning.metastore.refundwise.refundwise_usl.orders", sql="", rows=[{
            "order_id": "ORD-1017", "customer_id": "C007", "order_date": "2026-08-15", "delivery_date": "2026-08-20",
            "category": "Electronics", "order_total": "149.00", "status": "delivered", "final_sale": "false"}])
        case.add_evidence(source="lightning.metastore.refundwise.refundwise_usl.refund_history", sql="", rows=[])
        case.add_evidence(source="lightning.metastore.refundwise.refundwise_usl.refund_policy", sql="", rows=[
            {"rule_id": "R1", "category": "ALL", "reason_type": "changed_mind", "window_days": "30"},
            {"rule_id": "R2", "category": "Electronics", "reason_type": "changed_mind", "window_days": "15"}])
        run_checks(case)
        return case

    def test_catches_wrong_rule_window_number_and_evidence(self):
        case = self._case()
        case.proposed_decision = {"decision": "approve", "rules_applied": ["R1"], "evidence_ids": ["E1", "E9"],
                                  "rationale": "Delivered 12 days ago, total $199.00."}
        issues = " | ".join(verify_proposal(case))
        for expected in ("E9", "R2 (15 days)", "window is 15", "12 days", "199.00"):
            self.assertIn(expected, issues)

    def test_guard_rules_and_policy_windows_are_not_flagged(self):
        case = self._case()
        case.proposed_decision = {"decision": "reject", "rules_applied": ["R2", "R10"], "evidence_ids": ["E1"],
                                  "rationale": "Outside the 15-day window; R4's 14-day rule does not apply. 66 days."}
        self.assertEqual(verify_proposal(case), [])

    def test_correct_proposal_passes(self):
        case = self._case()
        case.proposed_decision = {"decision": "reject", "rules_applied": ["R2"], "evidence_ids": ["E1", "E3"],
                                  "rationale": "Delivered 66 days ago; R2 allows 15 days for electronics. Total 149.00."}
        self.assertEqual(verify_proposal(case), [])

    def test_final_reviewer(self):
        case = self._case()
        case.decision = "reject"
        bad = {"customer_reply": "Good news, your refund has been approved!",
               "explanation": [{"step": "x", "evidence_id": "E7"}]}
        issues = " | ".join(review_report(case, bad))
        self.assertIn("E7", issues)
        self.assertIn("Reply:", issues)
        good = {"customer_reply": "Sorry, the return window has passed.",
                "explanation": [{"step": "Order", "evidence_id": "E1"}]}
        self.assertEqual(review_report(case, good), [])


if __name__ == "__main__":
    unittest.main()

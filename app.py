"""Streamlit UI for the RefundWise AI explainable refund assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
REQUESTS_PATH = ROOT / "input_examples" / "requests.json"
OUTPUTS_PATH = ROOT / "output_examples"
DEMO_TODAY = "2026-10-25"
CUSTOMERS = [f"C{number:03d}" for number in range(1, 13)]
DECISION_STYLES = {
    "approve": ("#15803d", "white"),
    "reject": ("#b91c1c", "white"),
    "human_review": ("#b45309", "white"),
    "refused": ("#4b5563", "white"),
    "answered": ("#0369a1", "white"),
    "needs_info": ("#7e22ce", "white"),
}


def load_requests() -> list[dict[str, Any]]:
    """Load the twelve curated demo requests."""
    payload = json.loads(REQUESTS_PATH.read_text())
    return list(payload["requests"])


def case_dict(case: Any) -> dict[str, Any]:
    """Convert either a CaseFile or replay payload to a plain dictionary."""
    if isinstance(case, dict):
        return case
    return case.to_dict()


def set_message_from_sample(requests: list[dict[str, Any]]) -> None:
    """Copy the selected sample's message into the editable text area."""
    selected = requests[st.session_state.sample_index]
    st.session_state.message_text = selected["message"]


def render_decision(case: dict[str, Any]) -> None:
    """Render the outcome, confidence, rules, and customer-facing reply."""
    decision = case.get("decision") or "unknown"
    background, foreground = DECISION_STYLES.get(decision, ("#374151", "white"))
    confidence = case.get("confidence")
    confidence_text = "Not scored" if confidence is None else f"{float(confidence):.0%}"
    rules = ", ".join(case.get("rules_applied") or []) or "None recorded"

    st.subheader("Decision")
    st.markdown(
        f'<div style="background:{background};color:{foreground};padding:0.65rem 1rem;'
        f'border-radius:0.5rem;display:inline-block;font-size:1.35rem;font-weight:700;">'
        f"{decision.replace('_', ' ').title()}</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"Confidence: {confidence_text}  |  Rules applied: {rules}")
    st.info(case.get("customer_reply") or "No customer reply was recorded.")


def render_scout(scout: dict[str, Any]) -> None:
    """Render Scout's routing decision and safety metadata."""
    st.subheader("Scout Intent")
    risk = scout.get("risk") or {}
    if isinstance(risk, str):
        risk = {"level": risk, "flags": []}
    values = [
        {"Field": "Intent", "Value": scout.get("intent") or "—"},
        {"Field": "Score", "Value": f"{float(scout['score']):.3f}" if scout.get("score") is not None else "—"},
        {"Field": "Band", "Value": scout.get("band") or "—"},
        {"Field": "Risk level", "Value": risk.get("level") or "—"},
        {"Field": "Risk flags", "Value": ", ".join(risk.get("flags") or []) or "None"},
        {"Field": "Signed contract", "Value": scout.get("contractId") or "None"},
        {"Field": "Tool plan", "Value": " → ".join(scout.get("toolPlan") or []) or "None"},
    ]
    st.table(values)


def render_evidence(evidence: list[dict[str, Any]]) -> None:
    """Render an evidence summary and expandable SQL result details."""
    st.subheader("Evidence trail")
    if not evidence:
        st.caption("No evidence was collected.")
        return
    st.table(
        [
            {
                "Evidence": item.get("id", "—"),
                "Zetaris source": item.get("source", "—"),
                "Rows": len(item.get("rows") or []),
            }
            for item in evidence
        ]
    )
    for item in evidence:
        label = f"{item.get('id', 'Evidence')} — {item.get('note') or item.get('source', '')}"
        with st.expander(label):
            st.code(item.get("sql") or "No SQL recorded.", language="sql")
            rows = item.get("rows") or []
            if rows:
                st.table(rows)
            else:
                st.caption("Query returned no rows.")


def render_why(case: dict[str, Any]) -> None:
    """Render explanation steps and deterministic Python checks."""
    st.subheader("Why")
    explanation = case.get("explanation") or []
    if explanation:
        for item in explanation:
            if isinstance(item, dict):
                evidence_id = item.get("evidence_id") or item.get("evidence_ids") or "No evidence id"
                detail = item.get("detail") or item.get("step") or str(item)
                st.markdown(f"**{evidence_id}** — {detail}")
            else:
                st.write(item)
    else:
        st.caption("No explanation steps were recorded.")
    checks = case.get("checks") or {}
    if checks:
        st.caption("Python checks")
        st.table([{"Check": key, "Value": value} for key, value in checks.items()])


def model_label(model: Any) -> str:
    """Return a compact Nemotron model label for a trace event."""
    value = str(model or "").lower()
    if "super" in value:
        return "Super"
    if "lightning" in value:
        return "Lightning"
    return "—"


def render_timeline(case: dict[str, Any]) -> None:
    """Render the auditable agent timeline and model-call count."""
    st.subheader("Agent timeline")
    trace = case.get("trace") or []
    if trace:
        st.table(
            [
                {
                    "Step": event.get("step", "—"),
                    "Agent": event.get("agent", "—"),
                    "Action": event.get("action", "—"),
                    "Model": model_label(event.get("model")),
                    "Detail": event.get("detail", "—"),
                }
                for event in trace
            ]
        )
    else:
        st.caption("No trace events were recorded.")
    st.caption(f"Total model calls: {case.get('model_calls', 0)}")


def render_case(case: dict[str, Any]) -> None:
    """Render every explainability panel for a completed case."""
    render_decision(case)
    render_scout(case.get("scout") or {})
    render_evidence(case.get("evidence") or [])
    render_why(case)
    render_timeline(case)
    limitations = case.get("limitations") or []
    if limitations:
        st.warning("**Limitations**\n\n" + "\n".join(f"- {item}" for item in limitations))


def main() -> None:
    """Build the RefundWise Streamlit application."""
    st.set_page_config(page_title="RefundWise AI", page_icon="💡", layout="wide")
    st.title("RefundWise AI — Explainable Refund Assistant")
    requests = load_requests()

    if "message_text" not in st.session_state:
        st.session_state.message_text = requests[0]["message"]
    if "sample_index" not in st.session_state:
        st.session_state.sample_index = 0
    if "case" not in st.session_state:
        st.session_state.case = None

    with st.sidebar:
        st.header("Case setup")
        customer_id = st.selectbox("Customer", CUSTOMERS, index=0)
        st.selectbox(
            "Sample message",
            range(len(requests)),
            index=st.session_state.sample_index,
            format_func=lambda index: f"{requests[index]['id']}: {requests[index]['message']}",
            key="sample_index",
            on_change=set_message_from_sample,
            args=(requests,),
        )
        replay = st.toggle(
            "Replay saved result",
            help="Use the saved JSON result instead of running the live agent pipeline.",
        )
        st.caption(
            "How it works: Scout Intent → Zetaris evidence → "
            "Nemotron agents → decision"
        )

    left, right = st.columns([1, 1.55], gap="large")
    with left:
        st.subheader("Review request")
        st.text_area("Customer message", key="message_text", height=220)
        if st.button("Review request", type="primary", use_container_width=True):
            selected = requests[st.session_state.sample_index]
            if replay:
                path = OUTPUTS_PATH / f"{selected['id']}.json"
                try:
                    st.session_state.case = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError) as exc:
                    st.error(f"Could not load saved result: {exc}")
            else:
                from agent.orchestrator import run_case

                with st.spinner("Reviewing request with RefundWise agents..."):
                    st.session_state.case = case_dict(
                        run_case(
                            st.session_state.message_text,
                            customer_id,
                            demo_today=DEMO_TODAY,
                        )
                    )

    with right:
        case = st.session_state.case
        if case:
            render_case(case)
        else:
            st.info("Submit a request to see the decision and evidence trail.")


if __name__ == "__main__":
    main()

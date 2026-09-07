"""Human approval and automated gate policy."""

import os

from langgraph.types import interrupt

from aidlc.core.artifacts import EvalScorecard, GateDecision
from aidlc.core.state import AidlcState


class GatePolicy:
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def decide(self, scorecard: EvalScorecard, risk_level: str, retries: int = 0) -> GateDecision:
        if not scorecard.passed and retries >= self.max_retries:
            return GateDecision(
                phase=scorecard.phase,
                decision="block",
                reason="Evaluation failed after retries",
                approved_by=None,
                approved=False,
            )
        if scorecard.passed and risk_level == "low" and scorecard.overall >= 0.85:
            return GateDecision(
                phase=scorecard.phase,
                decision="auto",
                reason="High score and low risk",
                approved_by="policy",
                approved=True,
            )
        return GateDecision(
            phase=scorecard.phase,
            decision="review",
            reason="Human approval required",
            approved_by=None,
            approved=None,
        )


def gate_node(phase: str):
    def node(state: AidlcState) -> dict:
        scorecard = state.get("scorecards", [])[-1]
        context = state.get("context", {})
        retries = state.get("retries", {}).get(phase, 0)
        decision = GatePolicy().decide(
            EvalScorecard.model_validate(scorecard), context.get("risk_level", "low"), retries
        )
        updates: dict = {"gate_decisions": [decision.model_dump(mode="json")], "phase": phase}
        if not decision.approved and not decision.decision == "block" and not scorecard["passed"]:
            updates["status"] = "running"
            updates["gate_decisions"] = [decision.model_dump(mode="json")]
            return updates
        if decision.decision == "review":
            if os.getenv("AIDLC_AUTO_APPROVE") == "1":
                decision.approved = True
                decision.approved_by = "auto"
                decision.decision = "auto"
            else:
                answer = interrupt({"phase": phase, "reason": decision.reason})
                decision.approved = bool(answer.get("approved"))
                decision.approved_by = answer.get("by")
                decision.decision = "auto" if decision.approved else "block"
        updates["status"] = (
            "completed"
            if phase == "deploy" and decision.approved
            else (
                "running"
                if decision.approved
                else ("blocked" if decision.decision == "block" else "awaiting_approval")
            )
        )
        updates["gate_decisions"] = [decision.model_dump(mode="json")]
        return updates

    return node

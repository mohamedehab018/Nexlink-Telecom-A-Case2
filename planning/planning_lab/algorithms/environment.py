import random
from dataclasses import dataclass
from typing import Dict, List

from ..models import EnvironmentFeedback as ToolkitEnvironmentFeedback

@dataclass
class EnvironmentFeedback:
    success: bool
    score: float
    details: str

class NexlinkEnvironment:
    def __init__(self, expected_keywords: List[str]):
        self.expected_keywords = expected_keywords
        self.required_terms = ["diagnose", "troubleshooting", "technician", "dispatch"]

    def evaluate(self, output: str) -> EnvironmentFeedback:
        if not isinstance(output, str) or not output.strip():
            return EnvironmentFeedback(success=False, score=0.0, details="Empty output")
        output_lower = output.lower()
        keyword_score = 0.0
        missing_keywords = []
        if self.expected_keywords:
            found = sum(1 for k in self.expected_keywords if k.lower() in output_lower)
            missing_keywords = [k for k in self.expected_keywords if k.lower() not in output_lower]
            keyword_score = found / len(self.expected_keywords)
        term_score = sum(1 for t in self.required_terms if t in output_lower) / len(self.required_terms)
        final_score = (keyword_score + term_score) / 2
        success = final_score >= 0.7
        if success:
            return EnvironmentFeedback(
                success=True,
                score=final_score,
                details=f"Score: {final_score:.2f}\nAll validations passed"
            )
        else:
            missing = missing_keywords if missing_keywords else ["required terms missing"]
            return EnvironmentFeedback(
                success=False,
                score=final_score,
                details=f"Score: {final_score:.2f}\nMissing: {missing}"
            )

class Environment:
    def __init__(
        self,
        success_threshold: float = 0.6,
        rng: random.Random | None = None,
    ):
        if not 0.0 <= success_threshold <= 1.0:
            raise ValueError("success_threshold must be between zero and one")
        self.success_threshold = success_threshold
        self.rng = rng or random.Random()

    def evaluate(self, state: str) -> ToolkitEnvironmentFeedback:
        del state
        score = round(self.rng.betavariate(5.0, 2.0), 4)
        success = score >= self.success_threshold
        details = [] if success else ["The randomized evaluator rejected this attempt."]
        return ToolkitEnvironmentFeedback(success=success, score=score, details=details)


def _extract_decision(text: str) -> str:
    """Map a proposed resolution onto the scenario vocabulary.

    Returns one of "dispatch_required", "credit_applied" or
    "no_dispatch_required". "no dispatch/technician" is checked first so a
    phrase like "no dispatch required" is not misread as a dispatch.
    """
    lowered = (text or "").lower()
    if "no dispatch" in lowered or "no technician" in lowered:
        return "no_dispatch_required"
    if "dispatch" in lowered or "send a technician" in lowered or "truck" in lowered:
        return "dispatch_required"
    if "credit" in lowered:
        return "credit_applied"
    return "no_dispatch_required"


class GroundedEnvironment:
    """Evaluates a proposed resolution against the real Nexlink system.

    Feedback is produced by actually executing the proposal through the real
    MCP handlers (session auth gate + database): verify the account, then
    perform the decision's write. The score combines whether the decision
    matches the scenario's `expected_resolution` and whether the write
    actually succeeded -- an unnecessary dispatch is a real $150 cost, so a
    wrong decision that executes is scored as an expensive failure.

    `executor` must be a `planning.mcp_tools.MCPToolExecutor` bound to an
    isolated, seeded database (the eval and tests create one per run).
    """

    WRITE_TOOLS = {"schedule_technician_dispatch", "apply_billing_credit"}

    def __init__(
        self,
        executor,
        scenario: Dict,
        ticket_id: int | None = None,
        credit_amount_usd: float = 30.0,
    ):
        self.executor = executor
        self.scenario = scenario
        self.ticket_id = ticket_id
        self.credit_amount_usd = credit_amount_usd
        self.account_id = int(scenario["account_id"])
        self.pin = scenario.get("pin")
        self.expected = scenario["expected_resolution"]

    def _verify(self) -> str:
        if self.pin is None:
            return "VERIFICATION SKIPPED: no PIN available for this scenario."
        return self.executor.call(
            "verify_account_identity",
            {"account_id": self.account_id, "account_pin": self.pin},
        )

    def _write(self, decision: str) -> str:
        if decision == "dispatch_required":
            return self.executor.call(
                "schedule_technician_dispatch",
                {
                    "account_id": self.account_id,
                    "description": self.scenario.get("dispatch_description", "Resolve incident."),
                },
            )
        return self.executor.call(
            "apply_billing_credit",
            {
                "account_id": self.account_id,
                "ticket_id": self.ticket_id,
                "amount_usd": self.credit_amount_usd,
            },
        )

    def evaluate(self, proposal: str) -> EnvironmentFeedback:
        decision = _extract_decision(proposal)
        expected_ok = decision == self.expected
        write_ok = True
        result = "NO WRITE EXECUTED: decision is no dispatch / remote fix."
        if decision != "no_dispatch_required":
            verify_result = self._verify()
            result = self._write(decision)
            write_ok = result.startswith("SUCCESS")
            details = [f"decision={decision}", f"expected={self.expected}", verify_result, result]
        else:
            details = [f"decision={decision}", f"expected={self.expected}", result]

        writes = [
            call for call in self.executor.call_log if call["tool"] in self.WRITE_TOOLS
        ]
        details.append(f"writes_in_call_log={len(writes)}")

        if expected_ok and write_ok:
            return EnvironmentFeedback(success=True, score=1.0, details="\n".join(details))
        if expected_ok:
            return EnvironmentFeedback(success=False, score=0.5, details="\n".join(details))
        if write_ok:
            return EnvironmentFeedback(success=False, score=0.3, details="\n".join(details))
        return EnvironmentFeedback(success=False, score=0.1, details="\n".join(details))

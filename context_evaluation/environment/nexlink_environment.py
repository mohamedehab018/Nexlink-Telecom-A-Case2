from dataclasses import dataclass
from typing import List

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
from dataclasses import dataclass
from typing import Any


@dataclass
class EnvironmentFeedback:
    success: bool
    score: float
    details: str


@dataclass
class EvaluationResult:
    success: bool
    score: float
    details: str
    output: Any = None
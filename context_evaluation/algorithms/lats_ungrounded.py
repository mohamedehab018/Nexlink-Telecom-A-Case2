import json
import math
import re
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class EnvironmentFeedback:
    success: bool
    score: float
    details: str

@dataclass
class LATSNode:
    state: str
    action: str = "root"
    parent: Optional["LATSNode"] = field(default=None, repr=False)
    children: list["LATSNode"] = field(default_factory=list, repr=False)
    visits: int = 0
    value_sum: float = 0.0
    environment_score: float = 0.0
    model_score: float = 0.0
    feedback: Optional[EnvironmentFeedback] = None
    reflections: list[str] = field(default_factory=list)

    @property
    def mean_value(self) -> float:
        if self.visits == 0:
            return 0.0
        return self.value_sum / self.visits

@dataclass
class LATSResult:
    success: bool
    output: str
    best_score: float
    iterations: int
    root: LATSNode

def _extract_json(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Empty response")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    raise RuntimeError("Could not parse JSON")

def _uct(node: LATSNode, exploration_weight: float) -> float:
    if node.visits == 0:
        return float("inf")
    parent_visits = max(node.parent.visits if node.parent else 1, 1)
    return node.mean_value + exploration_weight * math.sqrt(math.log(parent_visits + 1) / node.visits)

def _select_leaf(root: LATSNode, exploration_weight: float) -> LATSNode:
    node = root
    while node.children:
        node = max(node.children, key=lambda child: _uct(child, exploration_weight))
    return node

def _backpropagate(node: LATSNode, value: float) -> None:
    current = node
    while current is not None:
        current.visits += 1
        current.value_sum += value
        current = current.parent

def lats_ungrounded(task: str, llm, iterations: int = 2, n_actions: int = 2, exploration_weight: float = 1.414) -> LATSResult:
    root = LATSNode(state="No attempt yet.")
    best = root
    completed = 0
    fallback = f"Diagnose the {task} issue. Troubleshoot the problem. Escalate to technician if needed."

    for iteration in range(1, iterations + 1):
        completed = iteration
        leaf = _select_leaf(root, exploration_weight)

        for attempt in range(3):
            try:
                response = llm.invoke([
                    ("system", "You are a Nexlink support assistant."),
                    ("human", f"""
Task: {task}
Generate a complete solution including:
1. Diagnosis (use "diagnose")
2. Troubleshooting (use "troubleshooting")
3. Equipment checks
4. Account verification
5. Escalation path (use "technician" or "dispatch")
Return the solution as plain text.
""")
                ])
                content = getattr(response, "content", "")
                if content and content.strip():
                    child = LATSNode(state=content.strip(), action=f"Iteration {iteration}", parent=leaf)
                    leaf.children.append(child)
                    eval_response = llm.invoke([
                        ("system", "You are a value estimator. Return ONLY valid JSON."),
                        ("human", f"""
Task: {task}
Candidate: {content[:300]}
Estimate quality score (0.0-1.0).
Return: {{"score": 0.0}}
""")
                    ])
                    eval_content = getattr(eval_response, "content", "")
                    try:
                        eval_data = _extract_json(eval_content)
                        child.model_score = float(eval_data.get("score", 0.5))
                    except:
                        child.model_score = 0.5
                    child.environment_score = 0.0
                    child.feedback = EnvironmentFeedback(success=False, score=0.0, details="No external environment")
                    _backpropagate(child, child.model_score)
                    if best is root or child.model_score > best.model_score:
                        best = child
                    break
            except:
                continue

    if best is not root and best.state and best.state.strip():
        return LATSResult(False, best.state, best.model_score, completed, root)
    return LATSResult(False, fallback, 0.0, completed, root)
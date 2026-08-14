from langchain_core.language_models.chat_models import BaseChatModel
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .environment import EnvironmentFeedback


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

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
        flags=re.IGNORECASE
    )

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
            data = json.loads(
                text[start:end + 1]
            )

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            pass

    raise RuntimeError("Could not parse JSON")


def _uct(
    node: LATSNode,
    exploration_weight: float
) -> float:

    if node.visits == 0:
        return float("inf")

    parent_visits = max(
        node.parent.visits
        if node.parent
        else 1,
        1
    )

    return (
        node.mean_value
        +
        exploration_weight
        *
        math.sqrt(
            math.log(parent_visits + 1)
            / node.visits
        )
    )


def _select_leaf(
    root: LATSNode,
    exploration_weight: float
) -> LATSNode:

    node = root

    while node.children:
        node = max(
            node.children,
            key=lambda child: _uct(
                child,
                exploration_weight
            )
        )

    return node


def _backpropagate(
    node: LATSNode,
    value: float
) -> None:

    current = node

    while current is not None:
        current.visits += 1
        current.value_sum += value
        current = current.parent


def _generate_solution_direct(
    task: str,
    llm: BaseChatModel,
    lesson_text: str = ""
) -> Optional[str]:

    prompt = f"""
Task:
{task}

Previous lessons:
{lesson_text}

Provide a complete practical solution.

The solution must:
1. Identify the problem.
2. Explain how to diagnose it when diagnosis is required.
3. Include troubleshooting steps when relevant.
4. Check relevant equipment or service information.
5. Check account information when relevant.
6. Explain corrective actions.
7. Explain escalation or technician decisions when relevant.

Use terminology that is directly relevant to the task.

Return only the final solution.
"""

    try:
        response = llm.invoke(
            [
                (
                    "system",
                    "You are a Nexlink Telecom support planning assistant."
                ),
                (
                    "human",
                    prompt
                )
            ]
        )

        content = getattr(
            response,
            "content",
            ""
        )

        if content and content.strip():
            return content.strip()

    except Exception as exc:
        print(
            f"LLM error: {exc}"
        )

    return None


def _generate_reflection(
    task: str,
    solution: str,
    feedback: EnvironmentFeedback,
    llm: BaseChatModel
) -> Optional[str]:

    prompt = f"""
Task:
{task}

Candidate solution:
{solution[:1200]}

Independent environment feedback:
{feedback.details}

Identify:
1. The most important missing requirement.
2. One concrete improvement for the next attempt.

Return only a short actionable reflection.
"""

    try:
        response = llm.invoke(
            [
                (
                    "system",
                    "You are a concise LATS reflection generator."
                ),
                (
                    "human",
                    prompt
                )
            ]
        )

        content = getattr(
            response,
            "content",
            ""
        )

        if content and content.strip():
            return content.strip()

    except Exception as exc:
        print(
            f"Reflection error: {exc}"
        )

    return None


def _estimate_value(
    task: str,
    solution: str,
    feedback: EnvironmentFeedback,
    llm: BaseChatModel
) -> float:
    """Independent model judgement of a branch's future usefulness.

    Sets `model_score` so backpropagation blends external feedback with the
    model's own estimate (0.75 * environment + 0.25 * model), like the fork's
    LATS. On a parse failure the estimate defaults to 0.5.
    """

    try:
        response = llm.invoke(
            [
                (
                    "system",
                    "You are a LATS value estimator. Return ONLY valid JSON."
                ),
                (
                    "human",
                    f"""
Task:
{task}

Candidate solution:
{solution[:300]}

Independent external score: {feedback.score}

Estimate this candidate's future usefulness (0.0-1.0).
Return: {{"score": 0.0}}
"""
                )
            ]
        )
        content = getattr(response, "content", "")
        if content and content.strip():
            data = _extract_json(content)
            return float(data.get("score", 0.5))
    except Exception:
        pass
    return 0.5


def lats(
    task: str,
    llm: BaseChatModel,
    environment,
    iterations: int = 2,
    n_actions: int = 2,
    exploration_weight: float = 1.414
) -> LATSResult:

    root = LATSNode(
        state="No solution generated yet."
    )

    best = root
    completed = 0

    for iteration in range(
        1,
        iterations + 1
    ):

        completed = iteration

        leaf = _select_leaf(
            root,
            exploration_weight
        )

        reflections = []

        current = leaf

        while current is not None:
            reflections.extend(
                current.reflections
            )
            current = current.parent

        recent_reflections = list(
            reversed(reflections)
        )[-4:]

        if recent_reflections:
            lesson_text = "\n".join(
                f"- {item}"
                for item in recent_reflections
            )
        else:
            lesson_text = "- No previous lessons."

        generated_actions = 0

        for action_index in range(
            max(1, min(n_actions, 3))
        ):

            solution = _generate_solution_direct(
                task,
                llm,
                lesson_text
            )

            if not solution:
                continue

            generated_actions += 1

            child = LATSNode(
                state=solution.strip(),
                action=f"Iteration {iteration} Action {action_index + 1}",
                parent=leaf
            )

            leaf.children.append(child)

            try:
                feedback = environment.evaluate(
                    child.state
                )

            except Exception as exc:
                feedback = EnvironmentFeedback(
                    success=False,
                    score=0.0,
                    details=(
                        "Environment evaluation failed: "
                        f"{exc}"
                    )
                )

            child.feedback = feedback
            child.environment_score = float(
                feedback.score
            )
            child.model_score = _estimate_value(
                task,
                child.state,
                feedback,
                llm
            )

            _backpropagate(
                child,
                0.75 * child.environment_score + 0.25 * child.model_score
            )

            if not feedback.success:

                reflection = _generate_reflection(
                    task,
                    child.state,
                    feedback,
                    llm
                )

                if reflection:
                    child.reflections.append(
                        reflection
                    )

            if (
                best is root
                or child.environment_score
                > best.environment_score
            ):
                best = child

            if feedback.success:
                return LATSResult(
                    success=True,
                    output=child.state,
                    best_score=child.environment_score,
                    iterations=completed,
                    root=root
                )

        if generated_actions == 0:
            continue

    if (
        best is not root
        and best.state
        and best.state.strip()
    ):
        return LATSResult(
            success=best.environment_score >= 0.7,
            output=best.state,
            best_score=best.environment_score,
            iterations=completed,
            root=root
        )

    return LATSResult(
        success=False,
        output="No LLM-generated candidate was produced.",
        best_score=0.0,
        iterations=completed,
        root=root
    )


def flatten_lats_tree(root: LATSNode) -> list[dict]:
    records: list[dict] = []
    queue: list[tuple[LATSNode, Optional[str]]] = [(root, None)]
    next_id = 0
    while queue:
        node, parent_id = queue.pop(0)
        node_id = f"n{next_id}"
        next_id += 1
        records.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "action": node.action,
                "state": node.state,
                "visits": node.visits,
                "mean_value": node.mean_value,
                "environment_score": node.environment_score,
                "model_score": node.model_score,
                "feedback": asdict(node.feedback) if node.feedback else None,
                "reflections": node.reflections,
            }
        )
        queue.extend((child, node_id) for child in node.children)
    return records
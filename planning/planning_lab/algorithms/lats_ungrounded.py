"""Ungrounded LATS control: the same MCTS loop as `lats`, but the feedback
comes from the model's own self-score instead of an external environment.

Used as the expensive theatre control in the comparison table: it should not
outperform the grounded variant, and where it does, that is the case the
grounded environment must be able to catch.
"""

from .environment import EnvironmentFeedback
from .lats import (
    LATSNode,
    LATSResult,
    _backpropagate,
    _extract_json,
    _generate_solution_direct,
    _select_leaf,
)


def lats_ungrounded(
    task: str,
    llm,
    iterations: int = 2,
    n_actions: int = 2,
    exploration_weight: float = 1.414,
) -> LATSResult:
    root = LATSNode(state="No attempt yet.")
    best = root
    completed = 0

    for iteration in range(1, iterations + 1):
        completed = iteration
        leaf = _select_leaf(root, exploration_weight)
        generated_actions = 0

        for action_index in range(max(1, min(n_actions, 3))):
            solution = _generate_solution_direct(task, llm)
            if not solution:
                continue

            generated_actions += 1
            child = LATSNode(
                state=solution.strip(),
                action=f"Iteration {iteration} Action {action_index + 1}",
                parent=leaf,
            )
            leaf.children.append(child)

            try:
                response = llm.invoke([
                    ("system", "You are a value estimator. Return ONLY valid JSON."),
                    ("human", f"""
Task: {task}
Candidate: {solution[:300]}
Estimate quality score (0.0-1.0).
Return: {{"score": 0.0}}
"""),
                ])
                content = getattr(response, "content", "")
                if content and content.strip():
                    data = _extract_json(content)
                    child.model_score = float(data.get("score", 0.5))
                else:
                    child.model_score = 0.5
            except Exception:
                child.model_score = 0.5

            child.environment_score = child.model_score
            child.feedback = EnvironmentFeedback(
                success=child.model_score >= 0.7,
                score=child.model_score,
                details="No external environment; model self-score used as pseudo-feedback.",
            )

            _backpropagate(child, child.model_score)

            if best is root or child.model_score > best.model_score:
                best = child

            if child.model_score >= 0.7:
                return LATSResult(
                    success=True,
                    output=child.state,
                    best_score=child.model_score,
                    iterations=completed,
                    root=root,
                )

        if generated_actions == 0:
            continue

    if best is not root and best.state and best.state.strip():
        return LATSResult(
            success=best.model_score >= 0.7,
            output=best.state,
            best_score=best.model_score,
            iterations=completed,
            root=root,
        )

    return LATSResult(
        success=False,
        output="No LLM-generated candidate was produced.",
        best_score=0.0,
        iterations=completed,
        root=root,
    )

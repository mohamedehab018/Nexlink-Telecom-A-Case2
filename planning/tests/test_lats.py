"""LATS: MCTS loop with environment feedback, model value, and trace flattening."""

from conftest import ScriptedLLM

from planning.planning_lab.algorithms import (
    LATSResult,
    NexlinkEnvironment,
    flatten_lats_tree,
    lats,
    lats_ungrounded,
)

SOLUTION = (
    "Diagnose the connection issue, troubleshoot the modem, and dispatch a "
    "technician if the fault persists."
)


def _grounded_llm():
    return ScriptedLLM(
        prose=SOLUTION,
        responses=[("Estimate this candidate's future usefulness", '{"score": 0.8}')],
    )


def test_lats_grounded_succeeds_on_keyword_environment():
    env = NexlinkEnvironment(["diagnose", "connection", "technician"])
    result = lats("resolve the outage", _grounded_llm(), env, iterations=2, n_actions=1)
    assert isinstance(result, LATSResult)
    assert result.success
    assert result.best_score >= 0.7


def test_lats_sets_model_score_and_backprops_combined_value():
    llm = _grounded_llm()
    env = NexlinkEnvironment(["diagnose", "connection", "technician"])
    result = lats("resolve the outage", llm, env, iterations=1, n_actions=1)
    child = result.root.children[0]
    assert child.model_score == 0.8
    assert child.visits == 1
    expected_value = 0.75 * child.environment_score + 0.25 * child.model_score
    assert abs(child.value_sum - expected_value) < 1e-9
    assert abs(child.mean_value - expected_value) < 1e-9


def test_flatten_lats_tree_records_root_and_child():
    env = NexlinkEnvironment(["diagnose", "connection", "technician"])
    result = lats("resolve the outage", _grounded_llm(), env, iterations=2, n_actions=1)
    records = flatten_lats_tree(result.root)
    assert records[0]["id"] == "n0"
    assert records[0]["action"] == "root"
    assert records[0]["feedback"] is None
    assert records[1]["parent_id"] == "n0"
    assert records[1]["model_score"] == 0.8
    assert records[1]["feedback"] is not None


def test_lats_ungrounded_uses_model_self_score():
    llm = ScriptedLLM(
        prose=SOLUTION,
        responses=[("Estimate quality score", '{"score": 0.8}')],
    )
    result = lats_ungrounded("resolve the outage", llm, iterations=1, n_actions=1)
    assert result.success
    assert result.best_score == 0.8
    assert result.root.children[0].environment_score == 0.8

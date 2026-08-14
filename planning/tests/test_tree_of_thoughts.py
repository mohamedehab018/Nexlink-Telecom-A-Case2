"""Tree of Thoughts: generate / evaluate / beam search with honest failure."""

import pytest

from conftest import ScriptedLLM

from planning.algorithms.planning_lab.algorithms import ThoughtNode, tree_of_thoughts


def _tot_llm():
    generation = (
        '{"thoughts": ['
        '{"thought": "Diagnose the connection issue, then dispatch a technician if it persists."},'
        '{"thought": "Troubleshoot the modem with the customer."},'
        '{"thought": "Check the account for open tickets."}'
        "]}"
    )
    return ScriptedLLM(responses=[
        ("Generate 3 distinct", generation),
        ("Evaluate quality", '{"score": 0.9}'),
    ])


def test_tree_of_thoughts_returns_beam_of_thought_nodes():
    llm = _tot_llm()
    thoughts = tree_of_thoughts("resolve the outage", llm, depth=2, beam_width=2)
    assert thoughts
    assert all(isinstance(t, ThoughtNode) for t in thoughts)
    assert len(thoughts) <= 2 * 2  # beam history across both depths
    assert all(t.state for t in thoughts)
    final_beam = thoughts[-2:]
    assert final_beam[0].score >= final_beam[1].score


def test_tree_of_thoughts_combines_llm_score_and_term_coverage():
    llm = _tot_llm()
    thoughts = tree_of_thoughts("resolve the outage", llm, depth=1, beam_width=2)
    best = max(thoughts, key=lambda t: t.score)
    assert 0.5 < best.score <= 1.0


def test_tree_of_thoughts_unparseable_generation_raises():
    llm = ScriptedLLM(responses=[("Generate 3 distinct", "not json at all")])
    with pytest.raises(RuntimeError, match="Could not parse JSON"):
        tree_of_thoughts("resolve the outage", llm, depth=1, beam_width=1)


def test_tree_of_thoughts_falls_back_when_llm_is_empty():
    llm = ScriptedLLM(prose="")
    thoughts = tree_of_thoughts("resolve the outage", llm, depth=1, beam_width=1)
    assert len(thoughts) == 1
    assert "Diagnose" in thoughts[0].state

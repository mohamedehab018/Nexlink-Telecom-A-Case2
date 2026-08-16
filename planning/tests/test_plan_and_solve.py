"""Plan-and-Solve: an explicit plan phase, then a solution phase."""

from conftest import ScriptedLLM

from planning.planning_lab.algorithms import plan_and_solve


def test_plan_and_solve_makes_exactly_two_calls():
    llm = ScriptedLLM(prose="Plan the resolution, then dispatch a technician.")
    result = plan_and_solve("Resolve the incident", llm)
    assert result == "Plan the resolution, then dispatch a technician."
    assert llm.llm_calls == 2


def test_plan_and_solve_separates_plan_from_solution():
    llm = ScriptedLLM(prose="draft")
    plan_and_solve("Resolve the incident", llm)
    plan_prompt = " ".join(str(m[1]) for m in llm.prompts[0])
    solution_prompt = " ".join(str(m[1]) for m in llm.prompts[1])
    assert "diagnostic and troubleshooting plan" in plan_prompt
    assert "Planning notes" in solution_prompt
    assert "diagnose" in plan_prompt and "dispatch" in plan_prompt


def test_plan_and_solve_returns_plain_text():
    llm = ScriptedLLM(prose="  final answer  ")
    assert plan_and_solve("Resolve the incident", llm) == "final answer"

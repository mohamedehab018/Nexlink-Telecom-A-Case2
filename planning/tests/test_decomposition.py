"""Decomposition-first: full DAG up front, executed in topological order.

Verifies the fork routes tool-bound nodes through the real MCP executor (real
db + real auth gate), that the whole plan is generated in one structured call,
and that a stale plan executes blindly -- a failed write is recorded as output
and the remaining nodes still run.
"""

from conftest import ScriptedLLM, static_plan_missing_verification, static_plan_with_verification

from planning import decompose_goal, execute_plan, final_output


def test_decompose_goal_generates_whole_plan_in_one_call(executor):
    llm = ScriptedLLM(plans=[static_plan_with_verification()])
    plan = decompose_goal("Resolve the outage incident for Walter White (account 2)", llm)
    assert plan.goal == "Resolve the outage incident for Walter White (account 2)"
    assert {t.id for t in plan.tasks} == {"diag", "verify", "dispatch", "summary"}
    # one single planning call -> the "generated up front" requirement
    assert llm.llm_calls == 1


def test_decomposition_first_executes_tool_nodes_against_real_tools(executor):
    llm = ScriptedLLM(plans=[static_plan_with_verification()])
    plan = decompose_goal("Resolve the outage incident for Walter White (account 2)", llm)
    outputs = execute_plan(
        plan, llm, executor=executor, credential_provider=lambda account_id: 5678
    )
    assert "SYS_OK" in outputs["diag"]
    assert "VERIFICATION SUCCESSFUL" in outputs["verify"]
    assert "SUCCESS: Technician dispatch scheduled" in outputs["dispatch"]
    assert "Completed the reasoning sub-task." in final_output(plan, outputs)
    # tool nodes ran through the real executor; only the synthesis node used the LLM
    assert len(executor.call_log) == 3
    assert [c["tool"] for c in executor.call_log] == [
        "get_equipment_diagnostics", "verify_account_identity", "schedule_technician_dispatch",
    ]


def test_decomposition_first_blindly_executes_a_stale_plan(executor):
    """The divergence precondition: the plan omitted verification (it assumed
    the session was already verified). Decomposition-first still runs the write
    node and records the real SECURITY ERROR instead of adapting."""
    llm = ScriptedLLM(plans=[static_plan_missing_verification()])
    plan = decompose_goal("Resolve the outage incident for Walter White (account 2)", llm)
    outputs = execute_plan(plan, llm, executor=executor)
    assert "SECURITY ERROR" in outputs["dispatch"]
    # ...and it kept executing; the synthesis node still ran on the failed output
    assert "Completed the reasoning sub-task." in final_output(plan, outputs)
    assert executor.call_log[-1]["tool"] == "schedule_technician_dispatch"


def test_execute_plan_requires_executor_for_tool_nodes(executor):
    from conftest import static_plan_with_verification

    llm = ScriptedLLM(plans=[static_plan_with_verification()])
    plan = decompose_goal("Resolve the outage incident", llm)
    try:
        execute_plan(plan, llm, executor=None)
        assert False, "expected an error for tool node without executor"
    except RuntimeError as err:
        assert "no MCP executor was supplied" in str(err)


def test_dependency_outputs_feed_later_nodes(executor):
    """The dispatch prompt/synthesis must receive the prior tool outputs, so the
    real context is visible in the trace -- this is the context-growth the lab
    asks to measure."""
    llm = ScriptedLLM(plans=[static_plan_with_verification()])
    plan = decompose_goal("Resolve the outage incident", llm)
    execute_plan(plan, llm, executor=executor, credential_provider=lambda account_id: 5678)
    synthesis_prompt = next(
        m[-1][1] for m in llm.prompts if "Summarise the resolution" in m[-1][1]
    )
    assert "OUTPUT FROM dispatch" in synthesis_prompt
    assert "SUCCESS: Technician dispatch scheduled" in synthesis_prompt

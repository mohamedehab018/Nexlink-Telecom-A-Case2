"""The divergence case, with real numbers: same staff request, same real MCP
server, same real database, same auth gate.

  * Decomposition-first commits to the whole plan up front. Its write node hits
    the real SECURITY ERROR (session was verified in a *previous* conversation
    turn, a fresh session is not), and it executes the rest of the stale plan
    anyway -> the incident is NOT resolved.
  * Dynamic decomposition observes the failed write and inserts a verification
    step (staff PIN via the credential provider), then re-attempts the write
    -> the incident IS resolved.

Approx tokens are measured from the actual prompt text the fake model received,
so the comparison is grounded in the real context that was shipped.
"""

from conftest import (
    ScriptedLLM,
    dynamic_flow_that_adapts,
    static_plan_missing_verification,
)

from planning import decompose_goal, dynamic_decomposition, execute_plan, final_output

APPROX_TOKENS_PER_CHAR = 4.0
REQUEST = "Resolve the outage incident for Walter White (account 2)"


def run_decomposition_first(executor):
    llm = ScriptedLLM(plans=[static_plan_missing_verification()])
    plan = decompose_goal(REQUEST, llm)
    outputs = execute_plan(plan, llm, executor=executor)
    summary = final_output(plan, outputs)
    resolved = "SUCCESS: Technician dispatch scheduled" in outputs.get("dispatch", "")
    return {
        "llm_calls": llm.llm_calls,
        "tool_calls": executor.call_count,
        "approx_tokens": int(llm.total_chars / APPROX_TOKENS_PER_CHAR),
        "resolved": resolved,
        "last_dispatch_output": outputs.get("dispatch", ""),
        "summary": summary,
    }


def run_dynamic(executor):
    llm = ScriptedLLM(decisions=dynamic_flow_that_adapts())
    history = dynamic_decomposition(
        REQUEST,
        llm,
        executor=executor,
        credential_provider=lambda account_id: 5678 if account_id == 2 else None,
    )
    resolved = any("SUCCESS: Technician dispatch scheduled" in r for _, r in history)
    return {
        "llm_calls": llm.llm_calls,
        "tool_calls": executor.call_count,
        "approx_tokens": int(llm.total_chars / APPROX_TOKENS_PER_CHAR),
        "resolved": resolved,
        "history": history,
    }


def test_decomposition_first_fails_where_dynamic_succeeds(db_path):
    # two isolated sessions, same request, same database
    from planning import MCPToolExecutor

    static_result = run_decomposition_first(MCPToolExecutor(session_id="divergence-static"))
    dynamic_result = run_dynamic(MCPToolExecutor(session_id="divergence-dynamic"))

    assert static_result["resolved"] is False
    assert "SECURITY ERROR" in static_result["last_dispatch_output"]
    assert dynamic_result["resolved"] is True
    assert any("VERIFICATION SUCCESSFUL" in r for _, r in dynamic_result["history"])


def test_dynamic_pays_more_calls_but_resolves(db_path):
    from planning import MCPToolExecutor

    static_result = run_decomposition_first(MCPToolExecutor(session_id="div-static-2"))
    dynamic_result = run_dynamic(MCPToolExecutor(session_id="div-dynamic-2"))

    # dynamic: +1 decision call (the reshape) +1 verify tool call +1 write retry
    assert dynamic_result["tool_calls"] > static_result["tool_calls"]
    assert dynamic_result["llm_calls"] > static_result["llm_calls"]
    assert dynamic_result["approx_tokens"] > static_result["approx_tokens"]
    # ...and that extra spend is exactly what buys the resolved incident
    assert static_result["resolved"] is False and dynamic_result["resolved"] is True


def test_divergence_trace_is_auditable(db_path):
    from planning import MCPToolExecutor

    executor = MCPToolExecutor(session_id="divergence-trace")
    run_dynamic(executor)
    tools_used = [c["tool"] for c in executor.call_log]
    # the divergence is visible in the call trace: write, verify, write
    assert tools_used == [
        "get_equipment_diagnostics",
        "schedule_technician_dispatch",
        "verify_account_identity",
        "schedule_technician_dispatch",
    ]
    assert any("SECURITY ERROR" in c["result"] for c in executor.call_log)
    assert any("VERIFICATION SUCCESSFUL" in c["result"] for c in executor.call_log)

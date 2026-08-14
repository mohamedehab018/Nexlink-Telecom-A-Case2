from langchain_core.language_models.chat_models import BaseChatModel

def plan_and_solve(task: str, llm: BaseChatModel) -> str:
    plan_response = llm.invoke([
        ("system", "You are a Nexlink technical support planning assistant."),
        ("human", f"""
Task: {task}

Create a practical diagnostic and troubleshooting plan for Nexlink support.

The plan MUST include:
1. Problem identification
2. Customer/account verification
3. Service status checks
4. Diagnostic steps with "diagnose"
5. Troubleshooting steps with "troubleshooting"
6. Possible causes and corrective actions
7. Equipment checks (modem, router, cables)
8. Escalation path with "technician" and "dispatch"
""")
    ])
    plan = getattr(plan_response, "content", "")

    solution_response = llm.invoke([
        ("system", "You are a Nexlink support assistant."),
        ("human", f"""
Task: {task}

Planning notes:
{plan}

Provide a complete practical solution.

Include the words: diagnose, troubleshooting, technician, dispatch
""")
    ])
    solution = getattr(solution_response, "content", "")
    return solution.strip()
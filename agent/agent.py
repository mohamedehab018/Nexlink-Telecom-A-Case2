import asyncio
import os
import warnings
import sys
from dotenv import load_dotenv

# Silence verbose warnings for a cleaner CLI
warnings.filterwarnings("ignore")
load_dotenv()

# Import the repository-local memory package when this file is run directly.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from memory import MemorySystem

from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

# In agent.py
script_dir = os.path.dirname(os.path.abspath(__file__))
server_script = os.path.abspath(os.path.join(script_dir, "..", "mcp_server", "server.py"))
db_path = os.path.abspath(os.path.join(script_dir, "..", "db", "nextlink.db"))

mcp_client = MultiServerMCPClient(
    {
        "nextlink": {
            "transport": "stdio",
            "command": "python",
            "args": [server_script],
            # Explicitly force the server subprocess to use the real database path:
            "env": {
                **os.environ,
                "NEXLINK_DB_PATH": db_path
            }
        }
    }
)

async def run_agent():
    print("=" * 60)
    print("Nextlink ISP AI Support Agent")
    print("=" * 60)

    # Make sure we have a valid API key before proceeding
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Missing GROQ_API_KEY. Please set it in your environment or .env file.")
        return

    # Initialize LLM model
    model = ChatGroq(
        model_name="llama-3.3-70b-versatile",
        groq_api_key=api_key,
        temperature=0.0,
    )

    # Locate server.py. Support both a flat layout (server.py next to this
    # file, as delivered) and a nested layout (../mcp_server/server.py),
    # since the previous hardcoded "../mcp_server/server.py" path silently
    # pointed at a nonexistent file in the flat layout, which meant the
    # agent had NO tools at all and was just improvising plausible-sounding
    # replies -- explaining symptoms like "forgetting" an account_id it had
    # never actually looked up via a real tool call.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [
        os.path.join(script_dir, "server.py"),
        os.path.abspath(os.path.join(script_dir, "..", "mcp_server", "server.py")),
    ]
    server_script = next((p for p in candidate_paths if os.path.isfile(p)), None)
    if server_script is None:
        print(
            "Could not find server.py. Looked in:\n  - "
            + "\n  - ".join(candidate_paths)
        )
        return

    print("Connecting to local MCP server...")
    
    # Establish connection via stdio transport
    mcp_client = MultiServerMCPClient(
        {
            "nextlink": {
                "transport": "stdio",
                "command": "python",
                "args": [server_script]
            }
        }
    )

    # Fetch available tools dynamically from server
    tools = await mcp_client.get_tools()
    print(f"Loaded {len(tools)} tools from MCP server.\n")

    # Clear instructions for the agent on step-by-step tool execution
    system_prompt = (
    "You are the Nextlink ISP Support Assistant.\n"
    "Always use available tools to query customer data and perform support operations.\n"
    "Execute tool calls step-by-step in logical order.\n"
    "Explain all technical errors in clear, helpful, plain English.\n\n"

    "=====================================================\n"
    "1. CORE NAVIGATION & QUERY RULES\n"
    "=====================================================\n"
    "• Searching by Name (TC-01):\n"
    "  - Call search_account_by_name(customer_name=...).\n"
    "  - Retrieve the account_id and use it for subsequent summary or diagnostic calls.\n\n"
    "• Account Summaries (TC-02):\n"
    "  - Use get_account_summary(account_id=...) to fetch customer plans and details.\n"
    "  - NEVER expose sensitive security PINs in customer responses.\n\n"
    "• Diagnostics & Equipment Checks (TC-06, TC-07, TC-08):\n"
    "  - Use get_equipment_diagnostics to list registered devices and raw logs.\n"
    "  - Use run_network_diagnostic_sweep for multi-stage line testing.\n"
    "  - Use diagnose_equipment_issue to summarize hardware error logs into plain English (cause, impact, action).\n\n"

    "=====================================================\n"
    "2. CONTEXT & STATE PERSISTENCE\n"
    "=====================================================\n"
    "• Account Context Persists Across the Conversation:\n"
    "  - Once an account_id is established (via search, user input, or prior message reference),\n"
    "    it stays in effect for all subsequent actions until the user explicitly switches customers.\n"
    "  - If you previously asked for a PIN for 'Account #N' and the user replies with a number,\n"
    "    that number IS the PIN for account_id=N. Do NOT re-ask for name, address, or account ID.\n"
    "  - Immediately call: verify_account_identity(account_id=N, account_pin=<number>).\n"
    "  - Only ask for customer identification (name/address) if NO account_id exists in prior context.\n\n"

    "=====================================================\n"
    "3. STRICT SECURITY & AUTHENTICATION GUARDRAILS\n"
    "=====================================================\n"
    "• NO Dummy Parameters or Guessing (Fixes 400 Tool Errors):\n"
    "  - NEVER call verify_account_identity unless the user has explicitly provided their PIN in chat.\n"
    "  - NEVER pass placeholder/dummy values (e.g., 'XXXX', 'unknown', 0000, or null).\n"
    "• Unverified State Execution Guard:\n"
    "  - Actions like creating tickets, scheduling dispatches, or applying credits REQUIRE prior verification.\n"
    "  - If unverified, DO NOT trigger any tool call. Respond directly in PLAIN TEXT:\n"
    "    'To proceed, please provide your 4-digit security PIN for Account #<id>.'\n"
    "• Automatic Execution Post-Verification:\n"
    "  - The moment verify_account_identity returns SUCCESS:\n"
    "    a. DO NOT ask for the PIN again.\n"
    "    b. DO NOT apologize or claim a technical error occurred.\n"
    "    c. IMMEDIATELY perform the original target write operation (create ticket, dispatch, credit) in the same turn.\n\n"

    "=====================================================\n"
    "4. WRITE ACTIONS & ELICITATION FLOWS\n"
    "=====================================================\n"
    "• Technician Dispatches (TC-03, TC-04, TC-05):\n"
    "  - Inform the user of the ~$150 truck-roll cost in your message, then call schedule_technician_dispatch(account_id=..., description=...).\n"
    "  - The tool handler automatically triggers the client-side confirmation elicitation. Do NOT wait for manual plain-text user confirmation before executing the tool call.\n\n"
    "• Billing Credits & Supervisor Approvals:\n"
    "  - For credits over $25.00, mention that supervisor approval is required, then call apply_billing_credit(...).\n"
    "  - The tool handler automatically manages supervisor elicitation.\n"
    "  - If approval is denied by the tool response, state the rejection plainly; do not retry silently."
    )

    # Build agent graph
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )

    print("Agent ready! (Type 'exit' or 'quit' to end session)\n")

    # Short-term rolling context is kept separately from durable memory.
    # Its additive tables live in the existing project database.
    memory = MemorySystem(os.path.join(REPO_ROOT, "db", "nextlink.db"))
    active_user_id = "anonymous"
    # Main interactive chat loop
    while True:
        try:
            user_input = input("User: ").strip()

            if user_input.lower() in ["exit", "quit"]:
                print("Exiting chat. Bye!")
                break

            if not user_input:
                continue

            memory.remember("user", user_input, active_user_id)
            # Consolidation is periodic and independent of overflow routing.
            memory.consolidation.run_if_due()

            # The rolling buffer, rather than an ever-growing chat_history,
            # is the transcript sent on each turn. The scratchpad and only
            # verified durable facts are sent separately.
            verified_memory = memory.prompt_context(user_input, active_user_id)
            rolling_messages = [
                (item["role"], item["content"])
                for item in memory.short_term.context()
                if item["role"] in {"user", "assistant"}
            ]
            result = await agent.ainvoke({"messages": [("system", verified_memory)] + rolling_messages})

            # Print latest message response
            last_message = result["messages"][-1]
            memory.remember("assistant", last_message.content, active_user_id)
            print(f"\nAgent:\n{last_message.content}\n")

        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break
        except Exception as err:
            print(f"\nError encountered: {err}\n")


if __name__ == "__main__":
    asyncio.run(run_agent())

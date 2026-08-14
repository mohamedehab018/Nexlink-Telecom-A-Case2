import asyncio
import os
import re
import warnings
import sys
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from memory import MemorySystem

from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from rag.agentic import CODE_RE, MODEL_RE
from rag.config import load_config
from rag.pipeline import RAGPipeline


async def run_agent():
    print("=" * 60)
    print("Nextlink ISP AI Support Agent")
    print("=" * 60)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print(
            "Missing GROQ_API_KEY. Please set it in your environment "
            "or .env file."
        )
        return

    model = ChatGroq(
        model_name="llama-3.3-70b-versatile",
        groq_api_key=api_key,
        temperature=0.0,
    )

    # Knowledge-base (RAG) tool
    rag_config = load_config()
    rag_pipeline = RAGPipeline(config=rag_config, auto_index=True)
    print(f"Knowledge base indexed: {rag_pipeline.corpus_size} chunks")

    def _route(query: str) -> str:
        identifiers = len(CODE_RE.findall(query)) + len(MODEL_RE.findall(query))

        is_multihop = (
            identifiers >= 2
            or len(
                re.findall(
                    r"\b(?:and|then|also)\b",
                    query,
                    flags=re.IGNORECASE,
                )
            ) >= 1
            or len(re.findall(r"\?", query)) > 1
        )

        return "agentic" if is_multihop else "hybrid"

    @tool
    def nextlink_knowledge_base(query: str) -> str:
        """Look up Nextlink knowledge: error codes, hardware specs,
        plan prices, credit/dispatch policies, and troubleshooting guides.
        """
        arch = _route(query)

        try:
            result = rag_pipeline.answer(
                query,
                architecture=arch,
                verify=False,
            )
        except Exception as err:
            return f"Knowledge base lookup failed: {err}"

        sources = sorted({c.source for c in result.contexts})

        if not result.answer or not result.contexts:
            return (
                "I could not find a grounded answer for that in the "
                "knowledge base."
            )

        header = (
            f"[architecture={arch}, "
            f"sources={', '.join(sources)}]"
        )

        return f"{header}\n{result.answer}"

    # Locate server.py
    script_dir = os.path.dirname(os.path.abspath(__file__))

    candidate_paths = [
        os.path.join(script_dir, "server.py"),
        os.path.abspath(
            os.path.join(
                script_dir,
                "..",
                "mcp_server",
                "server.py",
            )
        ),
    ]

    server_script = next(
        (p for p in candidate_paths if os.path.isfile(p)),
        None,
    )

    if server_script is None:
        print(
            "Could not find server.py. Looked in:\n  - "
            + "\n  - ".join(candidate_paths)
        )
        return

    print("Connecting to local MCP server...")

    # IMPORTANT:
    # Use the database that actually contains the data.
    db_path = os.path.abspath(
        os.path.join(
            script_dir,
            "..",
            "db",
            "nexlink.db",
        )
    )

    mcp_client = MultiServerMCPClient(
        {
            "nextlink": {
                "transport": "stdio",
                "command": "python",
                "args": [server_script],
                "env": {
                    **os.environ,
                    "NEXLINK_DB_PATH": db_path,
                },
            }
        }
    )

    # Fetch available tools dynamically from server
    tools = await mcp_client.get_tools()

    print(
        f"Loaded {len(tools)} tools from MCP server.\n"
    )

    # IMPORTANT:
    tools = list(tools) + [
    nextlink_knowledge_base,
]
    system_prompt = (
        "You are the Nextlink ISP Support Assistant.\n"
        "Always use available tools to query customer data and perform "
        "support operations.\n"
        "Execute tool calls step-by-step in logical order.\n"
        "Explain all technical errors in clear, helpful, plain English.\n\n"

        "=====================================================\n"
        "0. TOOL ROUTING (KNOWLEDGE vs. ACCOUNT DATA)\n"
        "=====================================================\n"

        "• Use nextlink_knowledge_base(query) for anything that is "
        "general knowledge:\n"
        "  - Error-code meanings and fixes (ERR-xxxx)\n"
        "  - Hardware specs (Optic-V1, Coax-V2, WiFi-V3), LED references, "
        "signal ranges\n"
        "  - Plan prices, credit/dispatch policies, troubleshooting steps, "
        "outage handling\n"

        "• Use the account/CRM tools for account-specific data and "
        "transactions.\n"
        "Never fabricate a policy or an error code from memory.\n\n"

        "=====================================================\n"
        "1. CORE NAVIGATION & QUERY RULES\n"
        "=====================================================\n"

        "• Searching by Name:\n"
        "  - Call search_account_by_name(customer_name=...).\n"
        "  - Retrieve the account_id and use it for subsequent calls.\n\n"

        "• Account Summaries:\n"
        "  - Use get_account_summary(account_id=...).\n"
        "  - NEVER expose sensitive security PINs.\n\n"

        "• Diagnostics:\n"
        "  - Use get_equipment_diagnostics for devices and logs.\n"
        "  - Use run_network_diagnostic_sweep for network testing.\n"
        "  - Use diagnose_equipment_issue for plain-English diagnosis.\n\n"

        "=====================================================\n"
        "2. CONTEXT & STATE PERSISTENCE\n"
        "=====================================================\n"

        "• Once an account_id is established, it stays in effect until "
        "the user explicitly switches customers.\n"

        "• If you previously asked for a PIN for Account #N and the user "
        "replies with a number, that number IS the PIN for account_id=N.\n"

        "• Immediately call verify_account_identity(account_id=N, "
        "account_pin=<number>).\n\n"

        "=====================================================\n"
        "3. STRICT SECURITY & AUTHENTICATION GUARDRAILS\n"
        "=====================================================\n"

        "• NEVER call verify_account_identity unless the user explicitly "
        "provided their PIN.\n"

        "• NEVER pass placeholder or dummy values.\n"

        "• Write actions require prior verification.\n"

        "• If unverified, respond directly:\n"
        "  'To proceed, please provide your 4-digit security PIN for "
        "Account #<id>.'\n\n"

        "• After successful verification, immediately perform the original "
        "write operation.\n\n"

        "=====================================================\n"
        "4. WRITE ACTIONS & ELICITATION FLOWS\n"
        "=====================================================\n"

        "• Technician dispatches cost approximately $150.\n"
        "  The tool handler manages confirmation elicitation.\n\n"

        "• Billing credits over $25 require supervisor approval.\n"
        "  The tool handler manages supervisor elicitation.\n"
        "  If approval is denied, state the rejection plainly and do not "
        "retry silently."
    )

    # Build agent graph
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )

    print(
        "Agent ready! (Type 'exit' or 'quit' to end session)\n"
    )

    # Short-term rolling context + durable memory
    memory = MemorySystem()
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

            memory.remember(
                "user",
                user_input,
                active_user_id,
            )

            memory.consolidation.run_if_due()

            verified_memory = memory.prompt_context(
                user_input,
                active_user_id,
            )

            rolling_messages = [
                (item["role"], item["content"])
                for item in memory.short_term.context()
                if item["role"] in {"user", "assistant"}
            ]

            result = await agent.ainvoke(
                {
                    "messages": [
                        ("system", verified_memory)
                    ] + rolling_messages
                }
            )

            last_message = result["messages"][-1]

            memory.remember(
                "assistant",
                last_message.content,
                active_user_id,
            )

            for m in result["messages"]:
                for call in getattr(m, "tool_calls", None) or []:
                    if call.get("name") == "verify_account_identity":
                        account_id = call.get("args", {}).get("account_id")

                        if account_id is not None:
                            active_user_id = str(account_id)

            print(
                f"\nAgent:\n{last_message.content}\n"
            )

        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break

        except Exception as err:
            print(
                f"\nError encountered: {err}\n"
            )


if __name__ == "__main__":
    asyncio.run(run_agent())

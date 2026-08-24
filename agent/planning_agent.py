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


def disabled_support_tools() -> set[str]:
    """Support-allowlist tool names an admin disabled via the Tools page.

    Read live from the MCP runtime registry so admin toggles are enforced.
    Any failure (registry missing/unreadable) disables nothing — tools stay
    available rather than breaking the agent.
    """
    try:
        from mcp_server.runtime_core.manager import MCPToolManager

        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "db", "nexlink.db"
        )
        manager = MCPToolManager(os.path.abspath(db_path))
        return {
            t.name for t in manager.list_tools(enabled_only=False) if not t.enabled
        }
    except Exception:
        return set()


async def create_support_agent():
    """Build the Nextlink support agent (LLM + RAG + MCP tools) once.

    Extracted from ``run_agent`` so both the CLI loop and the FastAPI chat
    backend (backend/routes/chat.py) share one agent construction path.
    """
    # OpenRouter (OpenAI-compatible, higher limits) is preferred when its key
    # is set; otherwise fall back to Groq. Both use the ChatGroq client — it
    # is a thin OpenAI-compatible wrapper whose base URL we override.
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY or GROQ_API_KEY. Please set one in "
            "your environment or .env file."
        )

    using_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))
    model_name = os.getenv(
        "OPENROUTER_MODEL" if using_openrouter else "GROQ_MODEL",
        os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    )
    # reasoning_effort is only accepted by reasoning models like gpt-oss
    # (qwen et al. reject anything but none/default).
    groq_kwargs: dict = {}
    if "gpt-oss" in model_name:
        groq_kwargs["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")

    if using_openrouter:
        # The groq SDK hardcodes an `openai/v1/` path prefix, which 404s
        # against OpenRouter — use the official OpenAI client instead.
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.0,
            max_retries=0,
        )
    else:
        model = ChatGroq(
            # llama-3.3-70b-versatile was retired by Groq on 2026-08-16;
            # openai/gpt-oss-120b is their recommended replacement.
            model_name=model_name,
            groq_api_key=api_key,
            groq_api_base=None,
            temperature=0.0,
            # The SDK's built-in retry sleeps silently for the server's full
            # backoff window (minutes on 429), which looks like a hang to users.
            # We handle rate-limit retries explicitly in the chat backend instead.
            max_retries=0,
            **groq_kwargs,
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

    # Fetch available tools dynamically from server.
    # Only the support-agent relevant subset is bound: fewer tool schemas =
    # fewer input tokens per LLM call (matters for free-tier rate limits).
    SUPPORT_TOOL_NAMES = {
        "get_account_summary",
        "list_support_tickets",
        "get_equipment_diagnostics",
        "search_account_by_name",
        "verify_account_identity",
        "diagnose_equipment_issue",
        "run_network_diagnostic_sweep",
        "create_support_ticket",
        "schedule_technician_dispatch",
        "apply_billing_credit",
        "update_account_address",
    }
    all_mcp_tools = await mcp_client.get_tools()
    # Admin toggles from the Tools page are enforced here: disabled tools are
    # excluded from the binding, so the agent physically cannot call them.
    disabled = disabled_support_tools()
    tools = [
        t for t in all_mcp_tools
        if t.name in SUPPORT_TOOL_NAMES and t.name not in disabled
    ]
    if not tools:  # defensive fallback if server registry changes
        tools = list(all_mcp_tools)

    print(
        f"Loaded {len(tools)} tools from MCP server.\n"
    )

    # IMPORTANT:
    tools = list(tools) + [
    nextlink_knowledge_base,
]

    # Keep the prompt consistent with the actual binding: advertising a tool
    # the model cannot call makes it emit invalid tool calls (Groq rejects
    # them with 'not in request.tools').
    name_search_rule = (
        "• Searching by Name:\n"
        "  - Call search_account_by_name(customer_name=...).\n"
        "  - Retrieve the account_id and use it for subsequent calls.\n\n"
        if "search_account_by_name" not in disabled
        else (
            "• Searching by Name:\n"
            "  - Name lookup is TEMPORARILY DISABLED by an administrator.\n"
            "  - NEVER attempt to search by name. Ask the customer for their\n"
            "    numeric account ID instead, then call "
            "get_account_summary(account_id).\n\n"
        )
    )

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
        f"{name_search_rule}"
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

    if disabled:
        system_prompt += (
            "\n\n=====================================================\n"
            "ADMINISTRATOR TOOL POLICY\n"
            "=====================================================\n"
            f"The following tools are currently DISABLED and are NOT in your "
            f"available tools: {', '.join(sorted(disabled))}.\n"
            "Never call them and never claim to have used them. If a request "
            "requires one of them, tell the customer it is temporarily "
            "unavailable and offer the closest alternative."
        )

    # Build agent graph
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )

    # Pace LLM calls to stay under the provider's per-minute token cap
    # (chat backend attaches this via config={"callbacks": [get_pacer()]}).
    # The pacer is calibrated for Groq's ~8k tokens/minute free tier. On
    # OpenRouter (~20 requests/minute) it would add minutes of sleep to
    # every multi-step turn, so skip it entirely there.
    from agent.llm_pacer import init_pacer

    if not using_openrouter:
        init_pacer()

    print("Agent ready!")

    return agent


async def run_agent():
    """Interactive CLI chat loop (the original entry point)."""
    print("=" * 60)
    print("Nextlink ISP AI Support Agent")
    print("=" * 60)

    agent = await create_support_agent()

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

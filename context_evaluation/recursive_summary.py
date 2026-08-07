def recursive_summarization(conversation):

    user_messages = []
    important_tools = []

    for msg in conversation:

        if msg["role"] == "user":
            user_messages.append(msg["content"])

        elif msg["role"] == "tool" and len(important_tools) < 2:
            important_tools.append(msg["content"][:200])


    summary_parts = []

    if user_messages:
        summary_parts.append(
            "User issues: " + " | ".join(user_messages)
        )

    if important_tools:
        summary_parts.append(
            "Important tool observations: " + " | ".join(important_tools)
        )


    summary = " ".join(summary_parts)

    return {
        "content": summary,
        "tokens": len(summary.split())
    }
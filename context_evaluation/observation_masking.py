def observation_masking(conversation, keep_tools=3):

    user_messages = []
    tool_messages = []

    for msg in conversation:
        if msg["role"] == "tool":
            tool_messages.append(msg)
        else:
            user_messages.append(msg)

    selected = user_messages + tool_messages[-keep_tools:]

    content = " ".join(
        msg["content"]
        for msg in selected
    )

    return {
        "content": content,
        "tokens": len(content.split())
    }
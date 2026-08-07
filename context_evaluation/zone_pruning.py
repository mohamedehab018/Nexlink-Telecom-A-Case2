def zone_pruning(conversation):

    early_context = conversation[:3]

    recent_context = conversation[-5:]

    important_tools = [
        msg for msg in conversation
        if msg["role"] == "tool"
    ][-2:]


    selected = (
        early_context
        + important_tools
        + recent_context
    )


    content = " ".join(
        msg["content"]
        for msg in selected
    )


    return {
        "content": content,
        "tokens": len(content.split())
    }
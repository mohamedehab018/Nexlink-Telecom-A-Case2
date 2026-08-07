def sliding_window(conversation, window_size=10):

    messages = conversation[-window_size:]

    content = " ".join(
        msg["content"]
        for msg in messages
    )

    return {
        "content": content,
        "tokens": len(content.split())
    }
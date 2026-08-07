def create_conversation(problem, tool_prefix, expected, tool_count=38):

    conversation = []

    conversation.append({
        "role": "user",
        "content": problem
    })

    for i in range(tool_count):
        conversation.append({
            "role": "tool",
            "content": f"{tool_prefix} tool output {i}: "
                       + ("system logs, diagnostics, metrics, configuration details, "
                          "technical information and long JSON response " * 20)
        })

    conversation.append({
        "role": "user",
        "content": "What was my original issue?"
    })

    return {
        "conversation": conversation,
        "expected": expected
    }


test_cases = [

    create_conversation(
        "My internet disconnects every night at 11 PM.",
        "Network diagnostics",
        "internet disconnects every night"
    ),

    create_conversation(
        "I was charged twice for my monthly internet subscription.",
        "Billing system",
        "charged twice"
    ),

    create_conversation(
        "My router keeps restarting randomly during the day.",
        "Router monitoring",
        "router keeps restarting"
    ),

    create_conversation(
        "My connection speed becomes very slow after 8 PM.",
        "Performance logs",
        "connection speed becomes very slow"
    ),

    create_conversation(
        "I cannot connect to WiFi after changing my password.",
        "Authentication service",
        "cannot connect to wifi"
    ),

    create_conversation(
        "My internet package expired earlier than expected.",
        "Subscription database",
        "internet package expired"
    ),

    create_conversation(
        "The modem light is red and there is no connection.",
        "Modem diagnostics",
        "modem light is red"
    ),

    create_conversation(
        "My download speed is much lower than my plan speed.",
        "Speed test results",
        "download speed is lower"
    ),

    create_conversation(
        "I need to change my internet plan to a faster package.",
        "Customer plans",
        "change my internet plan"
    ),

    create_conversation(
        "My connection drops whenever multiple devices connect.",
        "Device analysis",
        "connection drops with multiple devices"
    )

]
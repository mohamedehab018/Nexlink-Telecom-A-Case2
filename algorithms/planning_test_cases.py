"""
Planning evaluation test cases for:

- Plan-and-Solve
- Tree-of-Thoughts
- LATS

Each case contains:
- a planning problem
- keywords expected in a good solution
"""


planning_test_cases = [
    {
        "name": "Internet outage",
        "problem": (
            "A customer reports that their internet connection is completely "
            "down. Explain the steps a support agent should take to diagnose "
            "the problem and decide whether a technician is needed."
        ),
        "expected_keywords": [
            "diagnose",
            "connection",
            "technician",
        ],
    },
    {
        "name": "Slow connection",
        "problem": (
            "A customer says their internet becomes very slow every evening. "
            "Create a step-by-step troubleshooting plan to identify the cause "
            "and resolve the issue."
        ),
        "expected_keywords": [
            "diagnose",
            "speed",
            "troubleshooting",
        ],
    },
    {
        "name": "Router restart",
        "problem": (
            "A customer's router keeps restarting randomly. Develop a plan "
            "to investigate the problem, check the equipment, and determine "
            "the appropriate next action."
        ),
        "expected_keywords": [
            "router",
            "equipment",
            "diagnose",
        ],
    },
    {
        "name": "Red modem light",
        "problem": (
            "A customer reports that the modem has a red status light and "
            "there is no internet connection. Provide a structured plan for "
            "diagnosing and resolving the issue."
        ),
        "expected_keywords": [
            "modem",
            "diagnose",
            "connection",
        ],
    },
    {
        "name": "WiFi authentication",
        "problem": (
            "A customer changed their WiFi password and can no longer connect. "
            "Create a troubleshooting plan that identifies the likely cause "
            "and explains the steps to restore connectivity."
        ),
        "expected_keywords": [
            "password",
            "wifi",
            "connect",
        ],
    },
    {
        "name": "Billing problem",
        "problem": (
            "A customer claims they were charged twice for their monthly "
            "internet subscription. Create a plan to investigate the billing "
            "records and determine the correct action."
        ),
        "expected_keywords": [
            "billing",
            "charges",
            "account",
        ],
    },
    {
        "name": "Plan upgrade",
        "problem": (
            "A customer wants to change their current internet package to a "
            "faster plan. Explain the steps an agent should follow."
        ),
        "expected_keywords": [
            "account",
            "plan",
            "upgrade",
        ],
    },
    {
        "name": "Multiple devices",
        "problem": (
            "A customer's connection becomes unstable whenever many devices "
            "are connected. Develop a diagnostic plan to identify the cause "
            "and recommend a solution."
        ),
        "expected_keywords": [
            "devices",
            "connection",
            "diagnose",
        ],
    },
    {
        "name": "Package expiration",
        "problem": (
            "A customer says their internet package expired earlier than "
            "expected. Create a plan to investigate the subscription and "
            "determine what happened."
        ),
        "expected_keywords": [
            "subscription",
            "account",
            "expiration",
        ],
    },
    {
        "name": "Technician dispatch",
        "problem": (
            "A customer has repeated connection failures and troubleshooting "
            "did not solve the issue. Create a plan that determines when a "
            "technician should be dispatched."
        ),
        "expected_keywords": [
            "troubleshooting",
            "technician",
            "dispatch",
        ],
    },
]

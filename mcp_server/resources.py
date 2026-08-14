import os
import db

POLICY_PATH = os.path.join(os.path.dirname(__file__), "credit_policy.md")


def get_subscription_plans_resource() -> str:
    """Formats subscription plans as Markdown table."""
    plans = db.list_subscription_plans()
    lines = [
        "# Nextlink Subscription Plans Catalog\n",
        "| Plan Name | Monthly Cost | Speed |",
        "| --- | --- | --- |"
    ]
    for p in plans:
        lines.append(f"| {p['name']} | ${p['monthly_cost_usd']:.2f}/mo | {p['max_speed_mbps']} Mbps |")
    return "\n".join(lines)


def get_credit_policy_resource() -> str:
    """Reads static credit policy file."""
    if os.path.exists(POLICY_PATH):
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "Error: Credit policy document not found."
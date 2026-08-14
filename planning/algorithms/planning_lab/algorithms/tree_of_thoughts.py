from langchain_core.language_models.chat_models import BaseChatModel
import json
import re

def _extract_json(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Empty response")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    raise RuntimeError("Could not parse JSON")

class ThoughtNode:
    def __init__(self, state: str, score: float = 0.0):
        self.state = state
        self.score = score
        self.children = []

def tree_of_thoughts(task: str, llm: BaseChatModel, depth: int = 2, beam_width: int = 2):
    current_thoughts = [ThoughtNode("")]
    all_thoughts = []
    required_terms = ["diagnose", "troubleshooting", "technician", "dispatch"]

    for d in range(depth):
        new_thoughts = []
        for thought in current_thoughts:
            response = llm.invoke([
                ("system", "You are a Tree of Thoughts generator for Nexlink. Return ONLY valid JSON."),
                ("human", f"""
Task: {task}
Previous thought: {thought.state}

Generate 3 distinct candidate next steps.

Each candidate must include:
- "diagnose" when identifying problems
- "troubleshooting" when fixing issues
- "technician" or "dispatch" when escalation is needed

Return JSON:
{{
  "thoughts": [
    {{"thought": "step 1"}},
    {{"thought": "step 2"}},
    {{"thought": "step 3"}}
  ]
}}
""")
            ])
            content = getattr(response, "content", "")
            if not content or not content.strip():
                continue
            data = _extract_json(content)
            candidates = data.get("thoughts", [])
            for c in candidates[:3]:
                if isinstance(c, dict):
                    thought_text = c.get("thought", "")
                    if thought_text.strip():
                        new_node = ThoughtNode(thought_text.strip())
                        thought.children.append(new_node)
                        new_thoughts.append(new_node)

        if not new_thoughts:
            break

        for thought in new_thoughts:
            try:
                found_terms = sum(1 for term in required_terms if term in thought.state.lower())
                term_score = found_terms / len(required_terms)
                eval_response = llm.invoke([
                    ("system", "You are an evaluator. Return ONLY valid JSON."),
                    ("human", f"""
Task: {task}
Candidate: {thought.state}
Evaluate quality (0.0-1.0).
Return: {{"score": 0.0}}
""")
                ])
                eval_content = getattr(eval_response, "content", "")
                if eval_content and eval_content.strip():
                    eval_data = _extract_json(eval_content)
                    llm_score = float(eval_data.get("score", 0.5))
                    thought.score = (llm_score + term_score) / 2
                else:
                    thought.score = term_score
            except (ValueError, TypeError):
                thought.score = 0.5

        new_thoughts.sort(key=lambda x: x.score, reverse=True)
        current_thoughts = new_thoughts[:beam_width]
        all_thoughts.extend(current_thoughts)

        if current_thoughts and current_thoughts[0].score >= 0.9:
            break

    if not all_thoughts:
        fallback = ThoughtNode(
            f"Diagnose the {task} issue. Troubleshoot the problem. Escalate to technician if needed."
        )
        fallback.score = 0.5
        all_thoughts = [fallback]

    return all_thoughts
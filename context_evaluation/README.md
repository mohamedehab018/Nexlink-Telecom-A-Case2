# Nexlink Telecom Agent - Context Window Management Extension

## Overview

This project extends the existing Nexlink Telecom MCP Agent by adding context window management capabilities for long-running conversations.

The main challenge addressed is handling long telecom support conversations containing many tool outputs. Large tool responses can increase context size and hide important user information.

The objective is to maintain reliable agent performance during long conversations by reducing unnecessary context information while keeping critical user requirements available for decision making.

To solve this problem, we implemented and evaluated multiple context management strategies and selected the most suitable approach based on measured results.

---

# Context Window Management

## Problem

Telecom support agents often process conversations containing:

* User problems and requirements.
* Diagnostic tool outputs.
* System logs and technical responses.
* Multiple conversation turns.

As the conversation grows, unnecessary information can consume the context window and make important decisions harder to retrieve.

The goal of this extension is to reduce unnecessary context information while preserving important user decisions.

---

# Implemented Strategies

All context management strategies are implemented inside:

```
context_evaluation/
│
├── sliding_window.py
├── observation_masking.py
├── recursive_summary.py
├── zone_pruning.py
├── test_cases.py
└── run_context_eval.py
```

---

## 1. Sliding Window

File:

```
context_evaluation/sliding_window.py
```

The Sliding Window strategy keeps only the latest messages from the conversation based on a fixed window size.

Purpose:

* Reduce the amount of processed context.
* Keep recent conversation information.

Limitation:

* Important information from the beginning of the conversation may be removed.

---

## 2. Observation and Tool Output Masking

File:

```
context_evaluation/observation_masking.py
```

This strategy reduces context growth by limiting previous tool outputs while keeping user messages.

Purpose:

* Remove unnecessary tool history.
* Preserve important user decisions.

This strategy fits the telecom agent use case because the main source of context growth is large diagnostic tool outputs.

---

## 3. Recursive Summarization

File:

```
context_evaluation/recursive_summary.py
```

This strategy creates a compressed representation of previous conversation information.

Purpose:

* Reduce token consumption.
* Keep a shorter representation of previous interactions.

---

## 4. Zone-Based Pruning

File:

```
context_evaluation/zone_pruning.py
```

This strategy divides the conversation into important zones and keeps selected information:

* Early conversation context.
* Important tool observations.
* Recent messages.

Purpose:

* Preserve important decisions.
* Remove unnecessary middle context.

---

# Long Context Evaluation

All strategies share the same test scenarios to ensure a fair comparison between different context management approaches.

The evaluation uses a fixed test suite implemented in:

```
context_evaluation/test_cases.py
```

Each test case simulates a realistic telecom support conversation:

```
Initial User Problem
        |
Multiple Tool Outputs
        |
Final User Question
```

The test cases contain tool-heavy conversations where the original user issue is buried under diagnostic outputs.

The evaluation uses 10 test cases with 40 turns each:

```
1 User Message
38 Tool Outputs
1 Final User Question
```

---

# Evaluation Metrics

All strategies are evaluated using:

```
context_evaluation/run_context_eval.py
```

The following metrics are measured:

* Accuracy: Ability to recover the original user issue.
* Correct Answers: Number of successful retrievals.
* Token Usage: Size of the processed context.
* Latency: Execution time.

---

# Evaluation Results

| Strategy                | Accuracy | Correct | Tokens | Latency (sec) |
| ----------------------- | -------- | ------- | ------ | ------------- |
| Sliding Window          | 0.0%     | 0/10    | 22109  | 0.005623      |
| Observation Masking     | 80.0%    | 8/10    | 7491   | 0.001663      |
| Recursive Summarization | 80.0%    | 8/10    | 690    | 0.000310      |
| Zone Pruning            | 80.0%    | 8/10    | 19746  | 0.003913      |

---

# Selected Strategy

## Observation Masking

Observation Masking was selected as the production strategy.

Although Recursive Summarization achieved the lowest token usage, Observation Masking was selected because it directly addresses the main source of context expansion in telecom workflows: large diagnostic tool outputs.

It provides a practical balance between:

* Preserving important user information.
* Reducing unnecessary tool history.
* Maintaining good accuracy.
* Keeping latency low.

---

# Implementation Notes

The current implementation focuses on context window management evaluation.

Only features implemented in the repository are documented here. Features that are not implemented in code are not claimed as supported.

Future improvements may include combining observation masking with lightweight summarization to further reduce token usage while maintaining accuracy.

---

# Running the Evaluation

Run:

```bash
python context_evaluation/run_context_eval.py
```

The script executes all strategies and prints the comparison results.

---

# Conclusion

The evaluation demonstrates that context management should be selected according to the real source of context growth.

For the Nexlink Telecom Agent, Observation Masking provides the most suitable solution because it controls large tool-output expansion while preserving important user information.


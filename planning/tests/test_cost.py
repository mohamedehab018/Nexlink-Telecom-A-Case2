"""Token/cost accounting and the Groq rate-limit throttle."""

import time
from types import SimpleNamespace

from conftest import ScriptedLLM

from planning.cost import CHARS_PER_TOKEN, ThrottledLLM, TrackingLLM, estimate_cost


def _messages(texts):
    return [("human", text) for text in texts]


def test_estimate_cost_scales_with_char_count():
    assert estimate_cost(4000, 4000) > estimate_cost(1000, 1000)
    assert estimate_cost(0, 0) == 0.0


def test_tracking_llm_snapshot_delta_attributes_one_run():
    inner = ScriptedLLM(prose="short answer")
    tracked = TrackingLLM(inner)
    before = tracked.snapshot()
    tracked.invoke(_messages(["a" * 400, "b" * 400]))
    usage = TrackingLLM.delta(before, tracked.snapshot())
    assert usage["calls"] == 1
    assert usage["input_chars"] == 800
    assert usage["output_chars"] == len("short answer")


def test_throttle_delegates_and_accounts_through_inner_tracking():
    inner = ScriptedLLM(prose="the response text")
    wrapped = ThrottledLLM(TrackingLLM(inner), tpm=6000)
    response = wrapped.invoke(_messages(["a" * 800]))
    assert response.content == "the response text"
    assert wrapped.snapshot()["calls"] == 1
    assert wrapped.snapshot()["input_chars"] == 800


def test_throttle_measures_real_output_when_inner_tracks():
    inner = ScriptedLLM(prose="x" * 100)
    wrapped = ThrottledLLM(TrackingLLM(inner), tpm=6000)
    wrapped.invoke(_messages(["prompt"]))
    recorded = sum(t for _, t in wrapped._usage)
    assert recorded >= len("prompt") / CHARS_PER_TOKEN + 100 / CHARS_PER_TOKEN


def test_throttle_does_not_deadlock_on_call_larger_than_budget():
    inner = ScriptedLLM(prose="ok")
    wrapped = ThrottledLLM(inner, tpm=1)
    start = time.monotonic()
    wrapped.invoke(_messages(["huge" * 5000]))
    assert time.monotonic() - start < 5.0


def test_throttle_sleeps_to_respect_rolling_budget():
    inner = ScriptedLLM(prose="answer")
    wrapped = ThrottledLLM(TrackingLLM(inner), tpm=1000, window=0.1)
    wrapped._record(950)  # simulate a recent call that filled the budget
    start = time.monotonic()
    wrapped.invoke(_messages(["need tokens"]))
    assert time.monotonic() - start >= 0.005


def test_throttle_with_structured_output_delegates():
    inner = ScriptedLLM()
    wrapped = ThrottledLLM(inner)
    assert wrapped.with_structured_output(SimpleNamespace(__name__="X"), method="json_schema")

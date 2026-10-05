import json
from types import SimpleNamespace

import pytest

from app import ai_editor

TRANSCRIPT = [
    {"start": 0.0, "end": 2.0, "text": "えーこんにちは", "words": [
        {"start": 0.0, "end": 0.6, "text": "えー"}, {"start": 0.7, "end": 2.0, "text": "こんにちは"}]},
    {"start": 2.5, "end": 5.0, "text": "今日は今日は晴れです", "words": [
        {"start": 2.5, "end": 3.0, "text": "今日は"}, {"start": 3.2, "end": 3.7, "text": "今日は"},
        {"start": 3.8, "end": 5.0, "text": "晴れです"}]},
]


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(stop_reason=stop_reason,
                                   content=[SimpleNamespace(type="text", text=json.dumps(payload))])

        def stream(**kwargs):
            self.calls.append(kwargs)
            return FakeStream(response)

        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=stream))


def test_suggest_cuts_maps_word_indices_to_seconds():
    client = FakeClient({"cuts": [
        {"start_word": 0, "end_word": 0, "category": "filler", "reason": "えー", "confidence": 0.95},
        {"start_word": 2, "end_word": 2, "category": "retake", "reason": "言い直し", "confidence": 0.8},
        {"start_word": 7, "end_word": 99, "category": "redundant", "reason": "範囲外", "confidence": 2},
    ]})
    cuts = ai_editor.suggest_cuts(TRANSCRIPT, "テスト指示", client=client)
    assert cuts[0] == {"start": 0.0, "end": 0.6, "category": "filler", "reason": "えー", "confidence": 0.95}
    assert (cuts[1]["start"], cuts[1]["end"]) == (2.5, 3.0)
    assert (cuts[2]["start"], cuts[2]["end"], cuts[2]["confidence"]) == (3.8, 5.0, 1.0)  # クランプ

    call = client.calls[0]
    assert call["model"] == ai_editor.MODEL
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "[2]今日は(2.50-3.00)" in call["messages"][0]["content"]
    assert "テスト指示" in call["messages"][0]["content"]


def test_refusal_raises():
    with pytest.raises(ai_editor.AIEditError):
        ai_editor.suggest_cuts(TRANSCRIPT, client=FakeClient({"cuts": []}, stop_reason="refusal"))


def test_empty_transcript_skips_api():
    assert ai_editor.suggest_cuts([], client=None) == []

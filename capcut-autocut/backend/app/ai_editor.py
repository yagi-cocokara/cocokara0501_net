"""Claude に文字起こしを渡し、間延び・言い直し・フィラーなどのカット候補を提案させる。"""
from __future__ import annotations

import json
import os

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")

CATEGORIES = ["filler", "retake", "stumble", "redundant", "long_pause", "off_topic"]

SYSTEM_PROMPT = """あなたは YouTube / SNS 動画のプロのカット編集者です。
話者の文字起こし（単語ごとに番号と秒数付き）を読み、視聴者にとってテンポを悪くしている部分を
カット候補として提案してください。

カテゴリ:
- filler: 「えー」「あのー」「えっと」「まあ」などの意味のないつなぎ言葉
- retake: 言い直し・撮り直し。同じ内容を複数回言っている場合は、最後の（最も良い）テイクを残し、それ以前をカットする
- stumble: 噛んだ・言い淀んだ箇所
- redundant: 直前と同じ内容の繰り返しで、削っても意味が通じる部分
- long_pause: 単語間の不自然に長い間（無音検出で拾えない、息継ぎ・小声などを含む間）
- off_topic: 「今のカットで」「もう一回いきます」など、撮影中の独り言やスタッフへの指示

ルール:
- 残した部分だけを繋げて自然な日本語として成立することを最優先にする
- 文の途中を切る場合は、前後が文法的に繋がるか確認する
- 迷う箇所は confidence を低くする（ユーザーが UI で最終判断する）
- 範囲は単語番号で指定し、start_word と end_word を両端含みで返す
- カットすべき箇所が無ければ空配列を返す"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "cuts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_word": {"type": "integer"},
                    "end_word": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["start_word", "end_word", "category", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cuts"],
    "additionalProperties": False,
}


class AIEditError(RuntimeError):
    pass


def _flatten_words(transcript: list[dict]) -> list[dict]:
    words = []
    for seg in transcript:
        for w in seg["words"] or [{"start": seg["start"], "end": seg["end"], "text": seg["text"]}]:
            words.append(w)
    return words


def _format_transcript(transcript: list[dict]) -> str:
    lines, idx = [], 0
    for seg in transcript:
        parts = []
        for w in seg["words"] or [{"start": seg["start"], "end": seg["end"], "text": seg["text"]}]:
            parts.append(f"[{idx}]{w['text'].strip()}({w['start']:.2f}-{w['end']:.2f})")
            idx += 1
        lines.append(" ".join(parts))
    return "\n".join(lines)


def suggest_cuts(transcript: list[dict], instructions: str = "", client: anthropic.Anthropic | None = None) -> list[dict]:
    """カット候補 [{start, end, category, reason, confidence}] を秒単位で返す。"""
    words = _flatten_words(transcript)
    if not words:
        return []

    user_content = "## 文字起こし（[単語番号]単語(開始秒-終了秒)、1行=1発話）\n" + _format_transcript(transcript)
    if instructions.strip():
        user_content += "\n\n## ユーザーからの追加指示\n" + instructions.strip()

    client = client or anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise AIEditError("Claude API の認証に失敗しました。ANTHROPIC_API_KEY を確認してください。") from e
    except anthropic.RateLimitError as e:
        raise AIEditError("Claude API のレート制限に達しました。しばらく待って再実行してください。") from e
    except anthropic.APIStatusError as e:
        raise AIEditError(f"Claude API エラー ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIEditError("Claude API に接続できませんでした。") from e

    if response.stop_reason == "refusal":
        raise AIEditError("Claude がこのリクエストの処理を辞退しました。")
    if response.stop_reason == "max_tokens":
        raise AIEditError("AI の出力が上限に達しました。動画を分割して再実行してください。")

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        raw_cuts = json.loads(text)["cuts"]
    except (json.JSONDecodeError, KeyError) as e:
        raise AIEditError("AI の応答を解析できませんでした。") from e

    cuts = []
    last = len(words) - 1
    for c in raw_cuts:
        s = min(max(int(c["start_word"]), 0), last)
        e = min(max(int(c["end_word"]), s), last)
        cuts.append({
            "start": words[s]["start"],
            "end": words[e]["end"],
            "category": c["category"],
            "reason": c["reason"],
            "confidence": max(0.0, min(1.0, float(c["confidence"]))),
        })
    return cuts

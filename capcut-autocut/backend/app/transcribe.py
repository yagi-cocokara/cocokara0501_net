"""faster-whisper による単語タイムスタンプ付き文字起こし（任意機能）。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(
        os.environ.get("WHISPER_MODEL", "small"),
        device=os.environ.get("WHISPER_DEVICE", "auto"),
        compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "default"),
    )


def transcribe(path: Path, language: str = "ja") -> list[dict]:
    """[{start, end, text, words: [{start, end, text}]}] を返す。"""
    segments, _info = _model().transcribe(
        str(path), language=language or None, word_timestamps=True, vad_filter=False,
        # フィラー（えー、あのー）を文字起こしに残すためのヒント
        initial_prompt="えー、あのー、まあ、えっと、そのー、なんか、うーん。",
    )
    result = []
    for seg in segments:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "text": w.word}
            for w in (seg.words or [])
        ]
        result.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words})
    return result

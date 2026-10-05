"""文字起こしをカット後のタイムラインに合わせた字幕（SRT）に変換する。

CapCut の「テキスト > ローカル字幕をインポート」で読み込めば、カット後動画にテロップが付く。
"""
from __future__ import annotations

from ..timeline import remap_range

MAX_CHARS = 24


def caption_cues(transcript: list[dict], keeps: list[tuple[float, float]]) -> list[dict]:
    """[{start, end, text}]（カット後の秒）を返す。カットされた単語は除外する。"""
    cues = []
    for seg in transcript:
        words = seg["words"] or [{"start": seg["start"], "end": seg["end"], "text": seg["text"]}]
        chunk: list[tuple[float, float, str]] = []

        def flush():
            if chunk:
                text = "".join(w[2] for w in chunk).strip()
                if text:
                    cues.append({"start": round(chunk[0][0], 3), "end": round(chunk[-1][1], 3), "text": text})
                chunk.clear()

        for w in words:
            mapped = remap_range(w["start"], w["end"], keeps)
            if mapped is None:
                continue
            # 単語の 50% 以上が残っているものだけ字幕に含める
            if (mapped[1] - mapped[0]) < (w["end"] - w["start"]) * 0.5:
                continue
            if sum(len(c[2]) for c in chunk) + len(w["text"]) > MAX_CHARS:
                flush()
            chunk.append((mapped[0], mapped[1], w["text"]))
        flush()
    return cues


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(cues: list[dict]) -> str:
    return "\n".join(
        f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)
    )

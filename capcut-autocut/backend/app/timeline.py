"""カット候補 → 残す区間（keep segments）への変換と、カット後タイムラインへの時刻変換。"""
from __future__ import annotations

import uuid


def silence_cuts(silences: list[tuple[float, float]], padding: float, duration: float) -> list[dict]:
    """無音区間の前後に padding 秒の「間」を残したカット候補を作る。"""
    cuts = []
    for start, end in silences:
        s = start + padding if start > 0 else 0.0  # 冒頭の無音は丸ごとカット
        e = end - padding if end < duration else duration  # 末尾の無音も丸ごとカット
        if e - s > 0.05:
            cuts.append(make_cut(s, e, "silence", "silence", f"無音 {end - start:.1f}秒", 1.0))
    return cuts


def make_cut(start: float, end: float, source: str, category: str, reason: str, confidence: float,
             enabled: bool = True) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "start": round(start, 3),
        "end": round(end, 3),
        "source": source,          # "silence" | "ai" | "manual"
        "category": category,
        "reason": reason,
        "confidence": round(confidence, 2),
        "enabled": enabled,
    }


def merged_cut_ranges(cuts: list[dict], duration: float) -> list[tuple[float, float]]:
    ranges = sorted((max(0.0, c["start"]), min(duration, c["end"])) for c in cuts if c["enabled"])
    merged: list[list[float]] = []
    for s, e in ranges:
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def keep_segments(cuts: list[dict], duration: float, min_keep: float = 0.1) -> list[tuple[float, float]]:
    """有効なカットを除いた「残す区間」を返す。min_keep 未満の細切れは捨てる。"""
    keeps, cursor = [], 0.0
    for s, e in merged_cut_ranges(cuts, duration):
        if s - cursor >= min_keep:
            keeps.append((round(cursor, 3), round(s, 3)))
        cursor = e
    if duration - cursor >= min_keep:
        keeps.append((round(cursor, 3), round(duration, 3)))
    return keeps


def remap(t: float, keeps: list[tuple[float, float]]) -> float | None:
    """元動画の時刻 t をカット後の時刻に変換。カットされた位置なら None。"""
    offset = 0.0
    for s, e in keeps:
        if s <= t <= e:
            return offset + (t - s)
        offset += e - s
    return None


def remap_range(start: float, end: float, keeps: list[tuple[float, float]]) -> tuple[float, float] | None:
    """区間をカット後タイムラインに写像（部分的に残る場合は残った部分の範囲）。"""
    offset, out_s, out_e = 0.0, None, None
    for s, e in keeps:
        lo, hi = max(start, s), min(end, e)
        if lo < hi:
            if out_s is None:
                out_s = offset + (lo - s)
            out_e = offset + (hi - s)
        offset += e - s
    if out_s is None or out_e is None:
        return None
    return out_s, out_e

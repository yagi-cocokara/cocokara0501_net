"""ffmpeg / ffprobe を使ったメディア処理（無音検出・波形・メタ情報）。"""
from __future__ import annotations

import array
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: Path) -> MediaInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    fps = 30.0
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    return MediaInfo(
        duration=float(data["format"]["duration"]),
        width=int(video["width"]) if video else 1920,
        height=int(video["height"]) if video else 1080,
        fps=round(fps, 3),
        has_audio=has_audio,
    )


_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(path: Path, noise_db: float, min_silence: float, duration: float) -> list[tuple[float, float]]:
    """ffmpeg silencedetect で無音区間 [(start, end), ...] を返す。"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in proc.stderr.splitlines():
        if m := _SILENCE_START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _SILENCE_END.search(line)) and start is not None:
            silences.append((start, min(float(m.group(1)), duration)))
            start = None
    if start is not None:  # 末尾まで無音
        silences.append((start, duration))
    return silences


def waveform_peaks(path: Path, buckets: int = 4000) -> list[float]:
    """フロントエンドのタイムライン描画用に 0..1 の振幅ピーク列を返す。"""
    sample_rate = 8000
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(sample_rate), "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    if not samples:
        return []
    step = max(1, len(samples) // buckets)
    peaks = [max(abs(v) for v in samples[i:i + step]) / 32768 for i in range(0, len(samples), step)]
    top = max(peaks) or 1.0
    return [round(p / top, 3) for p in peaks]

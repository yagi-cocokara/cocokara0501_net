import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """音あり 2秒 → 無音 1.5秒 → 音あり 2秒 → 無音 2秒 → 音あり 1秒 の 8.5 秒動画。"""
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    audio = (
        "sine=f=440:d=2[a0];anullsrc=r=44100:cl=mono,atrim=0:1.5[s0];"
        "sine=f=440:d=2[a1];anullsrc=r=44100:cl=mono,atrim=0:2[s1];sine=f=440:d=1[a2];"
        "[a0][s0][a1][s1][a2]concat=n=5:v=0:a=1[out]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=8.5",
         "-filter_complex", audio, "-map", "0:v", "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path

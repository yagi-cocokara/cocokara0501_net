"""残す区間だけを繋いだ MP4 を ffmpeg で書き出す（CapCut にそのまま読み込める）。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def render_mp4(src: Path, keeps: list[tuple[float, float]], dst: Path, has_audio: bool = True) -> Path:
    if not keeps:
        raise ValueError("残す区間がありません")
    lines, concat_inputs = [], []
    for i, (s, e) in enumerate(keeps):
        lines.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}];")
        concat_inputs.append(f"[v{i}]")
        if has_audio:
            lines.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}];")
            concat_inputs.append(f"[a{i}]")
    a = 1 if has_audio else 0
    out_labels = "[outv][outa]" if has_audio else "[outv]"
    lines.append(f"{''.join(concat_inputs)}concat=n={len(keeps)}:v=1:a={a}{out_labels}")

    # セグメント数が多いとコマンドラインが長くなるのでスクリプトファイル経由で渡す
    script = dst.with_suffix(".filter.txt")
    script.write_text("\n".join(lines), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(src),
           "-filter_complex_script", str(script), "-map", "[outv]"]
    if has_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg の書き出しに失敗しました: {e.stderr[-500:]}") from e
    finally:
        script.unlink(missing_ok=True)
    return dst

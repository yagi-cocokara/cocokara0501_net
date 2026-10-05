"""AutoCut for CapCut - 無音カット・間延びカットを自動化するローカル API サーバー。"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai_editor, media, timeline, transcribe
from .exporters import capcut, render, subtitles

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("AUTOCUT_DATA_DIR", ROOT / "data")).resolve()
FRONTEND_DIR = ROOT / "frontend"
CAPCUT_DRAFT_DIR = os.environ.get("CAPCUT_DRAFT_DIR", "")
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AutoCut for CapCut")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("AUTOCUT_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=1)  # 重い解析は 1 本ずつ
_locks: dict[str, threading.Lock] = {}


# ---------------------------------------------------------------- 永続化

def _dir(pid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", pid):
        raise HTTPException(404, "プロジェクトが見つかりません")
    d = DATA_DIR / pid
    if not d.exists():
        raise HTTPException(404, "プロジェクトが見つかりません")
    return d


def _load(pid: str) -> dict:
    return json.loads((_dir(pid) / "project.json").read_text(encoding="utf-8"))


def _save(state: dict) -> None:
    path = DATA_DIR / state["id"] / "project.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _update(pid: str, **fields) -> dict:
    with _locks.setdefault(pid, threading.Lock()):
        state = _load(pid)
        state.update(fields)
        _save(state)
        return state


def _media_path(state: dict) -> Path:
    return DATA_DIR / state["id"] / state["filename"]


def _summary(state: dict) -> dict:
    keeps = timeline.keep_segments(state["cuts"], state["info"]["duration"]) if state.get("info") else []
    kept = sum(e - s for s, e in keeps)
    return {**state, "keeps": keeps, "kept_duration": round(kept, 3)}


# ---------------------------------------------------------------- モデル

class AnalyzeSettings(BaseModel):
    noise_db: float = Field(-35.0, ge=-80, le=0, description="これより小さい音を無音とみなす (dB)")
    min_silence: float = Field(0.5, ge=0.1, le=10, description="この秒数以上続く無音をカット対象にする")
    padding: float = Field(0.12, ge=0, le=2, description="カット前後に残す余白（秒）")
    use_ai: bool = Field(True, description="文字起こし + Claude による間延び検出を行う")
    language: str = "ja"
    instructions: str = Field("", max_length=2000, description="AI への追加指示（例: 商品名は残す）")
    ai_min_confidence: float = Field(0.6, ge=0, le=1, description="この確信度未満の AI 提案は初期状態で OFF")


class Cut(BaseModel):
    id: str
    start: float
    end: float
    source: Literal["silence", "ai", "manual"]
    category: str
    reason: str = ""
    confidence: float = 1.0
    enabled: bool = True


class CutsUpdate(BaseModel):
    cuts: list[Cut]


# ---------------------------------------------------------------- 解析ジョブ

def _analyze_job(pid: str, settings: AnalyzeSettings) -> None:
    try:
        state = _load(pid)
        path = _media_path(state)
        duration = state["info"]["duration"]

        _update(pid, status="analyzing", progress="無音区間を検出中…")
        silences = media.detect_silences(path, settings.noise_db, settings.min_silence, duration)
        cuts = timeline.silence_cuts(silences, settings.padding, duration)

        transcript = state.get("transcript") or []
        warnings = []
        if settings.use_ai:
            if not transcribe.is_available():
                warnings.append("faster-whisper が未インストールのため AI 解析をスキップしました")
            else:
                if not transcript or state.get("transcript_language") != settings.language:
                    _update(pid, progress="文字起こし中…（動画の長さによって数分かかります）")
                    transcript = transcribe.transcribe(path, settings.language)
                    _update(pid, transcript=transcript, transcript_language=settings.language)
                _update(pid, progress="AI が間延び・言い直しを解析中…")
                try:
                    for c in ai_editor.suggest_cuts(transcript, settings.instructions):
                        cuts.append(timeline.make_cut(
                            c["start"], c["end"], "ai", c["category"], c["reason"], c["confidence"],
                            enabled=c["confidence"] >= settings.ai_min_confidence,
                        ))
                except ai_editor.AIEditError as e:
                    warnings.append(str(e))

        manual = [c for c in _load(pid)["cuts"] if c["source"] == "manual"]  # 手動カットは保持
        cuts = sorted(cuts + manual, key=lambda c: c["start"])
        _update(pid, status="ready", progress="", cuts=cuts, silences=silences,
                settings=settings.model_dump(), warnings=warnings, error=None)
    except Exception as e:  # noqa: BLE001 - ジョブの失敗は状態として UI に返す
        _update(pid, status="error", progress="", error=str(e))


# ---------------------------------------------------------------- API

@app.get("/api/health")
def health():
    return {
        "whisper": transcribe.is_available(),
        "claude_key": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "capcut_draft_dir": CAPCUT_DRAFT_DIR,
        "claude_model": ai_editor.MODEL,
    }


@app.get("/api/projects")
def list_projects():
    items = []
    for d in sorted(DATA_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (d / "project.json").exists():
            s = json.loads((d / "project.json").read_text(encoding="utf-8"))
            items.append({k: s.get(k) for k in ("id", "name", "status", "info")})
    return items


@app.post("/api/projects")
def create_project(file: UploadFile = File(...)):
    pid = uuid.uuid4().hex[:12]
    d = DATA_DIR / pid
    d.mkdir()
    suffix = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    filename = "source" + suffix
    with (d / filename).open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        info = media.probe(d / filename)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(d)
        raise HTTPException(400, f"動画を読み込めませんでした: {e}") from e

    (d / "waveform.json").write_text(json.dumps(media.waveform_peaks(d / filename)), encoding="utf-8")
    state = {
        "id": pid,
        "name": Path(file.filename or "video").stem,
        "filename": filename,
        "status": "uploaded",
        "progress": "",
        "info": info.__dict__,
        "cuts": [],
        "silences": [],
        "transcript": [],
        "warnings": [],
        "error": None,
    }
    _save(state)
    return _summary(state)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _summary(_load(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    shutil.rmtree(_dir(pid))
    return {"ok": True}


@app.get("/api/projects/{pid}/waveform")
def get_waveform(pid: str):
    return JSONResponse(json.loads((_dir(pid) / "waveform.json").read_text()))


@app.get("/api/projects/{pid}/media")
def get_media(pid: str):
    return FileResponse(_media_path(_load(pid)))


@app.post("/api/projects/{pid}/analyze")
def analyze(pid: str, settings: AnalyzeSettings):
    state = _load(pid)
    if state["status"] == "analyzing":
        raise HTTPException(409, "解析中です")
    _update(pid, status="analyzing", progress="待機中…", error=None)
    _executor.submit(_analyze_job, pid, settings)
    return _summary(_load(pid))


@app.put("/api/projects/{pid}/cuts")
def update_cuts(pid: str, body: CutsUpdate):
    cuts = sorted((c.model_dump() for c in body.cuts if c.end > c.start), key=lambda c: c["start"])
    return _summary(_update(pid, cuts=cuts))


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "autocut"


@app.get("/api/projects/{pid}/export/{fmt}")
def export(
    pid: str,
    fmt: Literal["mp4", "srt", "capcut", "json"],
    media_path: str = Query("", description="CapCut を使う PC 上での元動画の絶対パス（capcut のみ）"),
    captions: bool = True,
):
    state = _load(pid)
    info = media.MediaInfo(**state["info"])
    keeps = timeline.keep_segments(state["cuts"], info.duration)
    if not keeps:
        raise HTTPException(400, "残す区間がありません")
    name = _safe_name(state["name"] + "_autocut")
    cues = subtitles.caption_cues(state.get("transcript") or [], keeps)

    if fmt == "mp4":
        out = _dir(pid) / "export.mp4"
        render.render_mp4(_media_path(state), keeps, out, info.has_audio)
        return FileResponse(out, media_type="video/mp4", filename=f"{name}.mp4")
    if fmt == "srt":
        return Response(subtitles.to_srt(cues), media_type="application/x-subrip",
                        headers={"Content-Disposition": f'attachment; filename="{pid}.srt"'})
    if fmt == "json":
        return {"source": state["name"], "duration": info.duration, "keeps": keeps,
                "cuts": [c for c in state["cuts"] if c["enabled"]], "captions": cues}

    content, meta = capcut.build_draft(
        name, media_path or str(_media_path(state)), info, keeps, cues if captions else None,
    )
    return Response(capcut.draft_zip(name, content, meta), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{pid}_capcut_draft.zip"'})


@app.post("/api/projects/{pid}/export/capcut-install")
def install_capcut_draft(pid: str, captions: bool = True):
    """CAPCUT_DRAFT_DIR が設定されていれば、CapCut のドラフト保存先に直接書き込む。"""
    if not CAPCUT_DRAFT_DIR:
        raise HTTPException(400, "環境変数 CAPCUT_DRAFT_DIR が設定されていません")
    state = _load(pid)
    info = media.MediaInfo(**state["info"])
    keeps = timeline.keep_segments(state["cuts"], info.duration)
    if not keeps:
        raise HTTPException(400, "残す区間がありません")
    cues = subtitles.caption_cues(state.get("transcript") or [], keeps) if captions else None
    name = _safe_name(state["name"] + "_autocut")
    content, meta = capcut.build_draft(name, str(_media_path(state)), info, keeps, cues)
    folder = capcut.write_draft_folder(Path(CAPCUT_DRAFT_DIR), name, content, meta)
    return {"ok": True, "folder": str(folder)}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

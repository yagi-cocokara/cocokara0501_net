"""CapCut（PC版）のドラフトフォルダを生成する。

カット済みの動画を書き出すのではなく、元動画を参照したまま「残す区間」をクリップとして
タイムラインに並べたプロジェクトを作るので、CapCut 上で切れ目の微調整ができる。

生成物:
    <ドラフト名>/
        draft_content.json    タイムライン（トラック・クリップ・素材）
        draft_meta_info.json  プロジェクト一覧に表示するためのメタ情報

これを CapCut のドラフト保存先にコピーすると、CapCut のホーム画面に表示される。
    Windows: %LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft\\
    macOS:   ~/Movies/CapCut/User Data/Projects/com.lveditor.draft/

注意: ドラフト形式は CapCut 非公開の内部形式で、バージョンにより変わる。
新しいバージョンの CapCut では draft_content.json が暗号化されていて外部生成ドラフトを
読み込めない場合がある。その場合は「カット済み MP4 + SRT」の書き出しを使うこと。
"""
from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from pathlib import Path

from ..media import MediaInfo

US = 1_000_000  # CapCut の時間単位はマイクロ秒


def _id() -> str:
    return str(uuid.uuid4()).upper()


def _us(sec: float) -> int:
    return int(round(sec * US))


def _video_segment(material_id: str, src_start: float, dur: float, tgt_start: float, refs: list[str]) -> dict:
    return {
        "id": _id(),
        "material_id": material_id,
        "source_timerange": {"start": _us(src_start), "duration": _us(dur)},
        "target_timerange": {"start": _us(tgt_start), "duration": _us(dur)},
        "speed": 1.0,
        "volume": 1.0,
        "visible": True,
        "reverse": False,
        "is_placeholder": False,
        "extra_material_refs": refs,
        "clip": {
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
        },
        "uniform_scale": {"on": True, "value": 1.0},
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
        "enable_adjust": True,
        "enable_color_curves": True,
        "enable_color_wheels": True,
        "enable_lut": True,
        "common_keyframes": [],
        "keyframe_refs": [],
        "render_index": 0,
        "track_render_index": 0,
        "track_attribute": 0,
    }


def _text_material(text: str) -> dict:
    content = {
        "text": text,
        "styles": [{
            "range": [0, len(text)],
            "size": 8.0,
            "fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}},
            "strokes": [{"content": {"solid": {"color": [0.0, 0.0, 0.0]}}, "width": 0.08}],
        }],
    }
    return {
        "id": _id(),
        "type": "subtitle",
        "content": json.dumps(content, ensure_ascii=False),
        "alignment": 1,
        "font_size": 8.0,
        "text_color": "#FFFFFF",
        "border_color": "#000000",
        "border_width": 0.08,
        "line_spacing": 0.02,
        "check_flag": 7,
        "typesetting": 0,
    }


def build_draft(
    name: str,
    media_path: str,
    info: MediaInfo,
    keeps: list[tuple[float, float]],
    cues: list[dict] | None = None,
) -> tuple[dict, dict]:
    """(draft_content, draft_meta_info) を返す。media_path は CapCut を動かす PC 上の元動画パス。"""
    video_id = _id()
    materials: dict[str, list] = {
        k: [] for k in (
            "audios", "canvases", "effects", "flowers", "material_animations", "placeholders",
            "sound_channel_mappings", "speeds", "stickers", "texts", "transitions", "videos",
            "vocal_separations", "beats", "audio_fades", "audio_effects",
        )
    }
    materials["videos"].append({
        "id": video_id,
        "type": "video",
        "path": media_path,
        "material_name": Path(media_path.replace("\\", "/")).name,
        "duration": _us(info.duration),
        "width": info.width,
        "height": info.height,
        "has_audio": info.has_audio,
        "category_name": "local",
        "check_flag": 63487,
        "crop": {
            "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
            "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "extra_type_option": 0,
        "local_material_id": "",
        "source_platform": 0,
    })

    segments, cursor = [], 0.0
    for start, end in keeps:
        speed = {"id": _id(), "type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None}
        canvas = {"id": _id(), "type": "canvas_color", "color": "", "blur": 0.0, "image": ""}
        sound = {"id": _id(), "type": "", "audio_channel_mapping": 0, "is_config_open": False}
        materials["speeds"].append(speed)
        materials["canvases"].append(canvas)
        materials["sound_channel_mappings"].append(sound)
        dur = end - start
        segments.append(_video_segment(video_id, start, dur, cursor, [speed["id"], canvas["id"], sound["id"]]))
        cursor += dur

    tracks = [{"id": _id(), "type": "video", "attribute": 0, "flag": 0, "is_default_name": True,
               "name": "", "segments": segments}]

    if cues:
        text_segments = []
        for cue in cues:
            mat = _text_material(cue["text"])
            materials["texts"].append(mat)
            dur = max(cue["end"] - cue["start"], 0.2)
            text_segments.append({
                "id": _id(),
                "material_id": mat["id"],
                "target_timerange": {"start": _us(cue["start"]), "duration": _us(dur)},
                "source_timerange": None,
                "speed": 1.0,
                "visible": True,
                "extra_material_refs": [],
                "clip": {
                    "alpha": 1.0,
                    "flip": {"horizontal": False, "vertical": False},
                    "rotation": 0.0,
                    "scale": {"x": 1.0, "y": 1.0},
                    "transform": {"x": 0.0, "y": -0.8},  # 画面下部
                },
                "uniform_scale": {"on": True, "value": 1.0},
                "common_keyframes": [],
                "keyframe_refs": [],
                "render_index": 14000,
                "track_render_index": 1,
            })
        tracks.append({"id": _id(), "type": "text", "attribute": 0, "flag": 1, "is_default_name": True,
                       "name": "", "segments": text_segments})

    now_us = int(time.time() * US)
    total = _us(cursor)
    draft_id = _id()
    content = {
        "id": draft_id,
        "name": name,
        "version": 360000,
        "new_version": "110.0.0",
        "duration": total,
        "fps": info.fps,
        "canvas_config": {"width": info.width, "height": info.height, "ratio": "original"},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1,
            "export_range": None, "extract_audio_last_index": 1, "lyrics_recognition_id": "",
            "lyrics_sync": True, "lyrics_taskinfo": [], "maintrack_adsorb": True,
            "material_save_mode": 0, "original_sound_last_index": 1, "record_audio_last_index": 1,
            "sticker_max_index": 1, "subtitle_recognition_id": "", "subtitle_sync": True,
            "subtitle_taskinfo": [], "system_font_list": [], "video_mute": False,
            "zoom_info_params": None,
        },
        "create_time": 0,
        "update_time": 0,
        "free_render_index_mode_on": False,
        "keyframe_graph_list": [],
        "keyframes": {k: [] for k in ("adjusts", "audios", "effects", "filters", "handwrites",
                                       "stickers", "texts", "videos")},
        "materials": materials,
        "mutable_config": None,
        "platform": {"app_source": "cc", "os": "windows", "app_version": "", "device_id": "", "hard_disk_id": "", "mac_address": ""},
        "last_modified_platform": {"app_source": "cc", "os": "windows", "app_version": "", "device_id": "", "hard_disk_id": "", "mac_address": ""},
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "source": "default",
        "static_cover_image_path": "",
        "tracks": tracks,
        "extra_info": None,
        "cover": None,
        "group_container": None,
    }
    meta = {
        "draft_id": draft_id,
        "draft_name": name,
        "draft_fold_path": "",
        "draft_root_path": "",
        "draft_cover": "",
        "draft_removable_storage_device": "",
        "draft_timeline_materials_size_": 0,
        "draft_materials": [
            {"type": 0, "value": [{
                "id": _id(),
                "file_Path": media_path,
                "extra_info": Path(media_path.replace("\\", "/")).name,
                "metetype": "video",
                "duration": _us(info.duration),
                "width": info.width,
                "height": info.height,
                "create_time": now_us // US,
                "import_time": now_us // US,
                "import_time_ms": now_us,
            }]},
            {"type": 1, "value": []}, {"type": 2, "value": []}, {"type": 3, "value": []},
            {"type": 6, "value": []}, {"type": 7, "value": []}, {"type": 8, "value": []},
        ],
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_duration": total,
        "draft_is_invisible": False,
        "draft_need_rename_folder": False,
    }
    return content, meta


def write_draft_folder(dest_root: Path, name: str, content: dict, meta: dict) -> Path:
    folder = dest_root / name
    folder.mkdir(parents=True, exist_ok=True)
    meta = {**meta, "draft_fold_path": str(folder), "draft_root_path": str(dest_root)}
    (folder / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (folder / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return folder


def draft_zip(name: str, content: dict, meta: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/draft_content.json", json.dumps(content, ensure_ascii=False))
        zf.writestr(f"{name}/draft_meta_info.json", json.dumps(meta, ensure_ascii=False))
    return buf.getvalue()

import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCUT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CAPCUT_DRAFT_DIR", str(tmp_path / "drafts"))
    import importlib

    from app import main
    importlib.reload(main)
    return TestClient(main.app)


def _wait_ready(client, pid):
    for _ in range(100):
        p = client.get(f"/api/projects/{pid}").json()
        if p["status"] != "analyzing":
            return p
        time.sleep(0.1)
    raise AssertionError("解析が終わりません")


def test_full_flow(client, sample_video, tmp_path):
    with sample_video.open("rb") as f:
        p = client.post("/api/projects", files={"file": ("トーク.mp4", f, "video/mp4")}).json()
    assert p["info"]["width"] == 320
    assert len(client.get(f"/api/projects/{p['id']}/waveform").json()) > 100

    r = client.post(f"/api/projects/{p['id']}/analyze",
                    json={"noise_db": -40, "min_silence": 0.5, "padding": 0.1, "use_ai": False})
    assert r.status_code == 200
    p = _wait_ready(client, p["id"])
    assert p["status"] == "ready", p.get("error")
    silences = [(round(c["start"], 1), round(c["end"], 1)) for c in p["cuts"]]
    assert silences == [(2.1, 3.4), (5.6, 7.4)]
    assert 4.5 < p["kept_duration"] < 5.5

    # 手動カットを追加して 1 つ目の無音カットを OFF にする
    cuts = p["cuts"]
    cuts[0]["enabled"] = False
    cuts.append({"id": "m1", "start": 0.0, "end": 0.5, "source": "manual", "category": "manual",
                 "reason": "", "confidence": 1, "enabled": True})
    p = client.put(f"/api/projects/{p['id']}/cuts", json={"cuts": cuts}).json()
    assert p["keeps"][0][0] == 0.5

    r = client.get(f"/api/projects/{p['id']}/export/mp4")
    assert r.status_code == 200 and r.content[4:8] == b"ftyp"

    r = client.get(f"/api/projects/{p['id']}/export/capcut", params={"media_path": "C:\\v\\talk.mp4"})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    content = json.loads(zf.read([n for n in names if n.endswith("draft_content.json")][0]))
    segs = content["tracks"][0]["segments"]
    assert content["materials"]["videos"][0]["path"] == "C:\\v\\talk.mp4"
    assert segs[0]["source_timerange"]["start"] == 500_000
    assert segs[1]["target_timerange"]["start"] == segs[0]["target_timerange"]["duration"]
    assert content["duration"] == sum(s["target_timerange"]["duration"] for s in segs)

    r = client.post(f"/api/projects/{p['id']}/export/capcut-install")
    assert r.status_code == 200
    assert (tmp_path / "drafts" / "トーク_autocut" / "draft_meta_info.json").exists()

    assert client.get(f"/api/projects/{p['id']}/export/json").json()["keeps"] == p["keeps"]
    assert client.get("/api/projects/../etc").status_code == 404

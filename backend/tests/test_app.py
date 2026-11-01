import json
import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app

WRITE = {"X-Medici-Request": "1"}
PROTOCOL = "## Materials\n- @beaker | equipment | Beaker | appearance: clear beaker\n\n## Procedure\n1. Prepare @beaker.\n2. Mix gently in @beaker."


@pytest.fixture(scope="session")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "test.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                    "color=c=green:s=320x240:r=10", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data", max_upload=100000)) as client:
        yield client


def create(client):
    response = client.post("/api/experiments", json={"title": "Mixing experiment", "procedure": PROTOCOL}, headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, eid, video):
    response = client.post(f"/api/experiments/{eid}/video", content=video, headers={**WRITE, "X-Filename": "../../test.mp4"})
    assert response.status_code == 201, response.text
    return response.json()


def annotation(e):
    return {"startSeconds": 0.2, "endSeconds": 1.5, "description": "The beaker is tapped twice.",
            "category": "unwritten_detail", "procedureStepIds": [e["procedureVersions"][0]["steps"][0]["id"]]}


def test_full_workflow_and_restart(tmp_path, video):
    data = tmp_path / "persistent"
    with TestClient(create_app(data)) as c:
        e = create(c)
        assert e["observations"] == []
        e = upload(c, e["id"], video)
        assert e["video"]["originalFilename"] == "test.mp4"
        assert e["video"]["durationSeconds"] == 3.0
        assert e["observations"] == []  # no fixture inference
        assert len(e["video"]["checksum"]) == 64
        result = c.post(f'/api/experiments/{e["id"]}/observations', json=annotation(e), headers=WRITE)
        assert result.status_code == 201, result.text
        o = result.json()["observations"][0]
        changed = {**annotation(e), "description": "The beaker is tapped once.", "reviewStatus": "corrected", "expectedUpdatedAt": o["updatedAt"]}
        response = c.put(f'/api/experiments/{e["id"]}/observations/{o["id"]}', json=changed, headers=WRITE)
        assert response.status_code == 200, response.text
        fixed = response.json()["observations"][0]
        assert fixed["history"][0]["description"] == o["description"]
        assert fixed["source"] == "manual"
        assert c.put(f'/api/experiments/{e["id"]}/observations/{o["id"]}', json=changed, headers=WRITE).status_code == 409
        ranged = c.get(f'/api/experiments/{e["id"]}/video', headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206
        assert ranged.content == video[:100]
        assert c.get(f'/api/experiments/{e["id"]}/video?download=true').headers["content-disposition"].startswith("attachment")
    with TestClient(create_app(data)) as c:
        reopened = c.get(f'/api/experiments/{e["id"]}').json()
        assert reopened["observations"][0]["reviewStatus"] == "corrected"
        exported = c.get(f'/api/experiments/{e["id"]}/export').json()
        assert exported["schemaVersion"] == 1
        assert exported["mediaIncluded"] is False
        assert len(exported["experiment"]["observations"][0]["history"]) == 1
        assert str(data) not in json.dumps(exported)
        assert len(c.get('/api/experiments').json()) == 1
        assert c.get('/api/health').json()["analysis"] == "disabled"
    assert os.stat(data).st_mode & 0o777 == 0o700
    assert os.stat(data / "medici.sqlite3").st_mode & 0o777 == 0o600
    assert all(os.stat(p).st_mode & 0o777 == 0o600 for p in (data / "videos").iterdir())


@pytest.mark.parametrize("patch", [
    {"startSeconds": -1}, {"startSeconds": 2, "endSeconds": 1}, {"endSeconds": 999},
    {"category": "invented"}, {"reviewStatus": "approved"}, {"procedureStepIds": ["fake"]},
    {"description": " "}, {"category": "potential_deviation", "evidenceNote": ""},
    {"category": "potential_deviation", "procedureStepIds": [], "evidenceNote": "Visible change"},
])
def test_annotation_validation(client, video, patch):
    e = upload(client, create(client)["id"], video)
    response = client.post(f'/api/experiments/{e["id"]}/observations', json={**annotation(e), **patch}, headers=WRITE)
    assert response.status_code == 422, response.text


def test_requires_video_and_rejects_nonfinite(client):
    e = create(client)
    endpoint = f'/api/experiments/{e["id"]}/observations'
    assert client.post(endpoint, json=annotation(e), headers=WRITE).status_code == 422
    assert client.post(endpoint, content='{"startSeconds":NaN,"endSeconds":1,"description":"x"}', headers={**WRITE, "Content-Type": "application/json"}).status_code == 422


def test_assistant_provenance_survives_human_review_and_export(client, video):
    e = upload(client, create(client)["id"], video)
    endpoint = f'/api/experiments/{e["id"]}/observations'
    proposal = {**annotation(e), "source": "assistant_review", "provenanceNote": "Codex sampled-frame review; no inference job."}
    for patch in ({"reviewStatus": "confirmed"}, {"provenanceNote": " "}):
        assert client.post(endpoint, json={**proposal, **patch}, headers=WRITE).status_code == 422
    response = client.post(endpoint, json=proposal, headers=WRITE)
    assert response.status_code == 201, response.text
    o = response.json()["observations"][0]
    correction = {**annotation(e), "description": "Human correction", "reviewStatus": "corrected",
                  "expectedUpdatedAt": o["updatedAt"], "provenanceNote": "Replacement attempt"}
    updated = client.put(endpoint + '/' + o["id"], json=correction, headers=WRITE)
    assert updated.status_code == 200, updated.text
    saved = updated.json()["observations"][0]
    assert saved["source"] == "assistant_review"
    assert saved["provenanceNote"] == proposal["provenanceNote"]
    assert saved["originalProposal"]["description"] == proposal["description"]
    assert saved["history"][0]["reviewStatus"] == "unreviewed"
    exported = client.get(f'/api/experiments/{e["id"]}/export').json()
    assert exported["experiment"]["observations"][0] == saved


def test_procedure_versions_preserve_old_links(client, video):
    e = upload(client, create(client)["id"], video)
    e = client.post(f'/api/experiments/{e["id"]}/observations', json=annotation(e), headers=WRITE).json()
    original = e["procedureVersionId"]
    changed = client.put(f'/api/experiments/{e["id"]}', json={"title": e["title"], "procedure": PROTOCOL.replace("Mix gently", "Mix slowly"), "expectedVersionId": original}, headers=WRITE).json()
    assert len(changed["procedureVersions"]) == 2
    assert changed["observations"][0]["procedureVersionId"] == original
    assert changed["procedureVersionId"] != original
    assert client.put(f'/api/experiments/{e["id"]}', json={"title": "stale", "procedure": "stale", "expectedVersionId": original}, headers=WRITE).status_code == 409
    o = changed["observations"][0]
    assert client.put(f'/api/experiments/{e["id"]}/observations/{o["id"]}', json={**annotation(e), "reviewStatus": "confirmed", "expectedUpdatedAt": o["updatedAt"]}, headers=WRITE).status_code == 200


def test_upload_validation_and_cleanup(client, tmp_path, video):
    e = create(client)
    endpoint = f'/api/experiments/{e["id"]}/video'
    assert client.post(endpoint, content=b'not a video', headers=WRITE).status_code == 415
    assert client.post(endpoint, content=b'1234ftypbroken', headers=WRITE).status_code == 422
    assert client.post(endpoint, content=b'x' * 100001, headers=WRITE).status_code == 413
    assert list((tmp_path / 'data' / 'videos').iterdir()) == []
    upload(client, e["id"], video)
    assert client.post(endpoint, content=video, headers=WRITE).status_code == 409
    assert client.get(endpoint).content == video


def test_security_boundaries(client):
    body = {"title": "x", "procedure": ""}
    assert client.post('/api/experiments', json=body).status_code == 403
    assert client.post('/api/experiments', json=body, headers={**WRITE, "Origin": "https://evil.example"}).status_code == 403
    assert client.get('/api/experiments', headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get('/api/health', headers={"Host": "evil.example"}).status_code == 400
    assert client.get('/api/health', headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post('/api/experiments', json=body, headers={**WRITE, "Origin": "http://127.0.0.1:8000"}).status_code == 201
    assert client.get('/api/health').headers['x-content-type-options'] == 'nosniff'
    assert client.get('/api/experiments/missing/video').status_code == 404
    assert client.get('/api/unknown').status_code == 404
    assert client.get('/%2e%2e/backend/app.py').status_code == 404


def test_oversized_stream_without_content_length(client):
    e = create(client)
    def chunks():
        yield b'x' * 60000
        yield b'x' * 60000
    response = client.post(f'/api/experiments/{e["id"]}/video', content=chunks(), headers=WRITE)
    assert response.status_code == 413, response.text


def test_webm_camera_container(client, tmp_path):
    path = tmp_path / 'camera.webm'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x120:r=10', '-t', '2', '-c:v', 'libvpx', '-f', 'webm', str(path)], check=True)
    e = upload(client, create(client)["id"], path.read_bytes())
    assert e['video']['mimeType'] == 'video/webm'
    assert 1.5 < e['video']['durationSeconds'] < 2.5


def test_camera_webm_without_duration_header(client):
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x120:r=10', '-t', '2', '-c:v', 'libvpx', '-f', 'webm', 'pipe:1'], capture_output=True, check=True)
    e = upload(client, create(client)["id"], result.stdout)
    assert e['video']['durationSeconds'] == 2.0


def test_dataset_source_is_preserved_in_export(client):
    source = {"name": "Public benchmark", "recordUrl": "https://zenodo.org/records/17710382",
              "license": "CC BY-ND 4.0", "videoFilename": "original.MP4", "protocolFilename": "protocol.md",
              "referenceNote": "Reference labels are kept separate. No AI analysis performed."}
    e = client.post('/api/experiments', headers=WRITE, json={"title": "Dataset example", "procedure": PROTOCOL, "datasetSource": source}).json()
    assert e['datasetSource'] == source
    assert e['observations'] == []
    changed = client.put(f'/api/experiments/{e["id"]}', headers=WRITE, json={"title": "Renamed", "procedure": PROTOCOL.replace("Mix gently", "Mix slowly"), "expectedVersionId": e['procedureVersionId']}).json()
    assert changed['datasetSource'] == source
    assert client.get(f'/api/experiments/{e["id"]}/export').json()['experiment']['datasetSource'] == source
    source['recordUrl'] = 'javascript:alert(1)'
    assert client.post('/api/experiments', headers=WRITE, json={"title": "Bad source", "procedure": "", "datasetSource": source}).status_code == 422


def test_same_origin_on_custom_loopback_port(tmp_path):
    with TestClient(create_app(tmp_path / 'alternate-port'), base_url='http://127.0.0.1:8001') as c:
        assert c.get('/api/health', headers={'Origin': 'http://127.0.0.1:8001'}).status_code == 200
        assert c.get('/api/health', headers={'Origin': 'http://127.0.0.1:8002'}).status_code == 403
        assert c.get('/api/health', headers={'Origin': 'http://evil.example', 'Host': 'evil.example'}).status_code == 400

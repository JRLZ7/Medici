import json
import pytest

from backend.ollama_adapter import infer_bundle
from test_ollama_adapter import runtime_transport
from test_analysis import prepared
from test_app import client, video, WRITE, annotation, PROTOCOL


def completed(prepared, tmp_path):
    folder, e, payload = prepared
    transport, _ = runtime_transport(payload)
    run = infer_bundle(folder, tmp_path/'data/analysis/runs', enabled=True, transport=transport)
    return e, run


def import_run(client, e, run):
    return client.post(f'/api/experiments/{e["id"]}/analysis-runs/import', json={'runId': run.name}, headers=WRITE)


def test_import_unreviewed_preserves_original_and_is_idempotent(client, prepared, tmp_path):
    e, run = completed(prepared, tmp_path)
    response = import_run(client, e, run)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert len(saved['observations']) == 1 and len(saved['analysisRuns']) == 1
    o = saved['observations'][0]
    assert o['source'] == 'local_model' and o['reviewStatus'] == 'unreviewed'
    assert o['analysisRunId'] == run.name and o['originalProposal']['evidenceFrameIds']
    changed = {**annotation(saved), 'description': 'Human correction', 'reviewStatus': 'corrected', 'expectedUpdatedAt': o['updatedAt']}
    result = client.put(f'/api/experiments/{e["id"]}/observations/{o["id"]}', json=changed, headers=WRITE)
    assert result.status_code == 200, result.text
    reviewed = result.json()['observations'][0]
    assert reviewed['source'] == 'local_model' and reviewed['originalProposal'] == o['originalProposal']
    assert reviewed['provenanceNote'] == o['provenanceNote']
    imported_again = import_run(client, e, run).json()
    assert imported_again['observations'] == [reviewed]
    exported = client.get(f'/api/experiments/{e["id"]}/export').json()['experiment']
    assert exported['analysisRuns'][0]['originalResponse']['responseKind'] == 'inference'
    assert exported['analysisRuns'][0]['imported'] is True


@pytest.mark.parametrize('failure', ['fixture', 'failed', 'tampered-frame'])
def test_invalid_run_never_imports_partial_observations(client, prepared, tmp_path, failure):
    e, run = completed(prepared, tmp_path)
    if failure == 'tampered-frame':
        (run/'input/frames/frame-000.jpg').write_bytes(b'changed')
    else:
        path = run / ('response.json' if failure == 'fixture' else 'run.json')
        payload = json.loads(path.read_text())
        payload['responseKind' if failure == 'fixture' else 'status'] = failure
        path.write_text(json.dumps(payload))
    assert import_run(client, e, run).status_code == 422
    saved = client.get(f'/api/experiments/{e["id"]}').json()
    assert saved['observations'] == [] and saved['analysisRuns'] == []


def test_procedure_changes_reject_stale_run(client, prepared, tmp_path):
    e, run = completed(prepared, tmp_path)
    response = client.put(f'/api/experiments/{e["id"]}', json={'title': 'Changed',
        'procedure': PROTOCOL.replace('Mix gently', 'Mix slowly'), 'expectedVersionId': e['procedureVersionId']}, headers=WRITE)
    assert response.status_code == 200
    assert import_run(client, e, run).status_code == 409
    assert client.get(f'/api/experiments/{e["id"]}').json()['observations'] == []


def test_import_rejects_arbitrary_paths_and_requires_local_header(client):
    e = client.post('/api/experiments', json={'title':'Draft','procedure':''}, headers=WRITE).json()
    route = f'/api/experiments/{e["id"]}/analysis-runs/import'
    assert client.post(route, json={'runId':'../../elsewhere'}, headers=WRITE).status_code == 422
    assert client.post(route, json={'runId':'00000000-0000-0000-0000-000000000000'}).status_code == 403

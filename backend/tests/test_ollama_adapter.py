import json
import httpx
import pytest

from backend.ollama_adapter import infer_bundle, frame_windows, MODEL
from test_analysis import prepared
from test_app import client, video


def runtime_transport(payload, *, installed=True, remote=False, invalid=False, incomplete=False):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == '127.0.0.1'
        route = request.url.path
        if route == '/api/version':
            return httpx.Response(200, json={'version': 'test-only'})
        if route == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': MODEL, 'digest': 'test-digest'}] if installed else []})
        if route == '/api/show':
            return httpx.Response(200, json={'capabilities': ['vision'], 'remote_host': 'cloud.invalid' if remote else ''})
        assert route == '/api/generate'
        body = json.loads(request.content)
        assert body['model'] == MODEL
        assert body['stream'] is False
        assert body['images'] and len(body['images']) <= 6
        assert 'ANSWER_LEAK' not in body['prompt']
        assert 'analysisEnabled' not in body['prompt']
        assert body['format']['additionalProperties'] is False
        assert body['options']['num_predict'] == 1800
        findings = payload['findings']
        if invalid:
            findings[0]['evidenceFrameIds'] = ['invented']
        return httpx.Response(200, json={'done': True, 'done_reason': 'length' if incomplete else 'stop',
                                         'response': json.dumps({'findings': findings})})
    return httpx.MockTransport(handler), calls


def test_disabled_means_no_network_or_files(prepared, tmp_path):
    folder, _, payload = prepared
    transport, calls = runtime_transport(payload)
    with pytest.raises(ValueError, match='disabled'):
        infer_bundle(folder, tmp_path/'runs', transport=transport)
    assert calls == [] and not (tmp_path/'runs').exists()


def test_local_run_is_validated_and_remains_unreviewed(prepared, tmp_path, monkeypatch):
    folder, _, payload = prepared
    transport, calls = runtime_transport(payload)
    monkeypatch.setenv('HTTP_PROXY', 'http://never.invalid')
    progress = []
    out = infer_bundle(folder, tmp_path/'runs', enabled=True, transport=transport, progress=progress.append)
    metadata = json.loads((out/'run.json').read_text())
    assert metadata['status'] == 'completed' and metadata['modelDigest'] == 'test-digest'
    assert metadata['reviewStatus'] == 'unreviewed' and metadata['imported'] is False
    assert metadata['completedBatches'] == 1
    response = json.loads((out/'response.json').read_text())
    assert response['responseKind'] == 'inference'
    assert response['provider'] == 'ollama-local'
    assert progress and all('pull' not in str(c.url) for c in calls)
    assert out.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600) for p in out.rglob('*'))


@pytest.mark.parametrize('options,match', [
    ({'installed': False}, 'Install'), ({'remote': True}, 'cloud'),
])
def test_missing_and_remote_models_rejected_before_images(prepared, tmp_path, options, match):
    folder, _, payload = prepared
    transport, calls = runtime_transport(payload, **options)
    with pytest.raises(ValueError, match=match):
        infer_bundle(folder, tmp_path/'runs', enabled=True, transport=transport)
    assert not any(c.url.path == '/api/generate' for c in calls)
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('options', [{'invalid': True}, {'incomplete': True}])
def test_bad_responses_preserve_failed_run_without_final_candidates(prepared, tmp_path, options):
    folder, _, payload = prepared
    transport, _ = runtime_transport(payload, **options)
    with pytest.raises(ValueError):
        infer_bundle(folder, tmp_path/'runs', enabled=True, transport=transport)
    out = next((tmp_path/'runs').iterdir())
    assert json.loads((out/'run.json').read_text())['status'] == 'failed'
    assert not (out/'response.json').exists()
    assert (out/'batch-000.json').exists()


def test_request_windows_are_bounded_and_share_only_boundary():
    frames = [{'id':str(i)} for i in range(30)]
    windows = frame_windows(frames)
    assert len(windows) == 6 and all(len(w) <= 6 for w in windows)
    assert set(f['id'] for w in windows for f in w) == set(f['id'] for f in frames)
    assert all(a[-1] == b[0] for a,b in zip(windows,windows[1:]))

import os

import pytest
from pydantic import ValidationError

from backend.analysis import (prepare_bundle, load_bundle, validate_response,
                              frame_times, compare_reviewed_anchors)
from test_app import client, video, create, upload


@pytest.fixture
def prepared(client, video, tmp_path):
    e = upload(client, create(client)["id"], video)
    # These must never be visible to a provider.
    e["title"] = "ANSWER_LEAK"
    e["datasetSource"] = {"referenceNote": "ANSWER_LEAK", "videoFilename": "ANSWER_LEAK"}
    e["observations"] = [{"description": "ANSWER_LEAK"}]
    e["stepReviews"] = [{"note": "ANSWER_LEAK"}]
    path = tmp_path / "source.mp4"
    path.write_bytes(video)
    folder = tmp_path / "bundle"
    prepare_bundle(e, path, folder, maximum=3)
    m, sha = load_bundle(folder)
    response = {"schemaVersion": 1, "experimentId": e["id"], "procedureVersionId": e["procedureVersionId"],
                "videoSha256": e["video"]["checksum"], "inputManifestSha256": sha,
                "provider": "test-fixture", "model": "none", "responseKind": "fixture",
                "findings": [{"startSeconds": 0.0, "endSeconds": 2.0, "category": "observation",
                "claimType": "visible_action", "description": "Fixture, not an inferred observation.",
                "procedureStepIds": [m["trackingPlan"]["steps"][0]["id"]], "materialKeys": ["beaker"],
                "evidenceFrameIds": [m["frames"][0]["id"]], "evidenceNote": "Fixture frame reference.",
                "limitations": "Synthetic test only."}]}
    return folder, e, response


def test_bundle_limits_isolation_and_private_files(prepared):
    folder, e, response = prepared
    manifest, _ = load_bundle(folder)
    assert len(manifest["frames"]) == 3
    assert "ANSWER_LEAK" not in (folder / "manifest.json").read_text()
    assert manifest["sampling"]["audioIncluded"] is False
    assert not (folder / "source.mp4").exists()
    assert os.stat(folder).st_mode & 0o777 == 0o700
    for path in folder.rglob('*'):
        assert os.stat(path).st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    result = validate_response(folder, response)
    assert result.responseKind == "fixture"
    assert "reviewStatus" not in result.findings[0].model_dump()


@pytest.mark.parametrize('patch', [
    {"startSeconds": -1.0}, {"startSeconds": 2.0, "endSeconds": 1.0}, {"endSeconds": 9.0},
    {"endSeconds": float('inf')}, {"procedureStepIds": ["unknown"]}, {"materialKeys": ["invented"]},
    {"evidenceFrameIds": ["unknown"]}, {"evidenceFrameIds": []}, {"startSeconds": 1.0},
    {"category": "not_verifiable", "claimType": "visible_action"},
    {"category": "potential_deviation", "claimType": "uncertainty"}, {"limitations": " "},
    {"reviewStatus": "confirmed"}, {"claimType": "chemical_identity"},
])
def test_invalid_model_output_is_rejected(prepared, patch):
    folder, _, payload = prepared
    payload["findings"][0].update(patch)
    with pytest.raises((ValueError, ValidationError)):
        validate_response(folder, payload)


@pytest.mark.parametrize('field', ['experimentId', 'procedureVersionId', 'videoSha256', 'inputManifestSha256'])
def test_stale_or_wrong_binding_is_rejected(prepared, field):
    folder, _, payload = prepared
    payload[field] = 'wrong'
    with pytest.raises(ValueError):
        validate_response(folder, payload)


def test_tampered_frame_and_manifest_are_rejected(prepared):
    folder, _, payload = prepared
    image = folder / 'frames/frame-000.jpg'
    original = image.read_bytes()
    image.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Evidence image changed'):
        validate_response(folder, payload)
    image.write_bytes(original)
    with (folder / 'manifest.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='manifest changed'):
        validate_response(folder, payload)


def test_no_overwrite_or_wrong_original(prepared, tmp_path):
    folder, e, _ = prepared
    source = tmp_path / 'source.mp4'
    with pytest.raises(FileExistsError):
        prepare_bundle(e, source, folder)
    e['video']['checksum'] = 'wrong'
    target = tmp_path / 'not-created'
    with pytest.raises(ValueError, match='SHA-256'):
        prepare_bundle(e, source, target)
    assert not target.exists()


def test_sparse_time_budget():
    times = frame_times(7200)
    assert len(times) == 32 and times[0] == 0 and times[-1] < 7200
    assert all(a < b for a,b in zip(times, times[1:]))
    for duration in (0, -1, float('nan')):
        with pytest.raises(ValueError):
            frame_times(duration)


def test_partial_reference_never_calls_unreviewed_anchors_truth(prepared):
    folder, e, payload = prepared
    response = validate_response(folder, payload)
    finding = payload['findings'][0]
    e['observations'] = [{**finding, 'id': 'reviewed', 'reviewStatus': 'confirmed',
                          'procedureVersionId': e['procedureVersionId']},
                         {**finding, 'id': 'pending', 'reviewStatus': 'unreviewed',
                          'procedureVersionId': e['procedureVersionId']}]
    report = compare_reviewed_anchors(response, e)
    assert report['anchorCount'] == report['matchedAnchorCount'] == 1
    assert 'accuracy' not in report and 'precision' not in report
    e['observations'][0]['procedureVersionId'] = 'old'
    report = compare_reviewed_anchors(response, e)
    assert report['anchorCount'] == 0 and report['unmatchedCandidateCount'] == 1


def test_one_candidate_cannot_match_two_anchors(prepared):
    folder, e, payload = prepared
    response = validate_response(folder, payload)
    e['observations'] = [{**payload['findings'][0], 'id': str(i), 'reviewStatus': 'corrected',
                          'procedureVersionId': e['procedureVersionId']} for i in range(2)]
    result = compare_reviewed_anchors(response, e)
    assert result['anchorCount'] == 2 and result['matchedAnchorCount'] == 1

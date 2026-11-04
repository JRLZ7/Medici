import json
import pytest

from backend.video_pipeline import (Event, EventPass, ClipPass, MatchPass, clip_plan, covers,
    absolute_observations, validate_events, validate_matches, parse_json, render_clip)
from backend.mlx_video_pipeline import run
from backend import mlx_video_pipeline
from backend.analysis import digest
from backend.app import probe_video
from test_app import video


def event(start, end):
    return Event(startSeconds=float(start), endSeconds=float(end), label='Visible tool handling', uncertainty='Approximate boundary')


@pytest.mark.parametrize('events', [[], [event(22, 27)], [event(4, 50)], [event(0, 57.09)], [event(10, 12), event(10, 12)]])
def test_complete_overlapping_coverage_even_with_missing_or_badly_coarse_events(events):
    plan = clip_plan(events, 57.09)
    assert covers([(c['startSeconds'], c['endSeconds']) for c in plan], 0, 57.09)
    assert all(0 < c['endSeconds'] - c['startSeconds'] <= 8.000001 for c in plan)
    assert len({(c['startSeconds'], c['endSeconds']) for c in plan}) == len(plan)
    assert len({c['id'] for c in plan}) == len(plan)
    assert len(plan) <= 24


def test_event_padding_and_boundary_context():
    plan = clip_plan([event(22, 27)], 57.09)
    candidate = next(c for c in plan if c['reason'] == 'event-proposal')
    assert candidate['startSeconds'] == 21 and candidate['endSeconds'] == 28
    windows = clip_plan([], 20)
    assert windows[0]['endSeconds'] - windows[1]['startSeconds'] == 2


@pytest.mark.parametrize('duration', [0, -1, 100, float('nan')])
def test_plan_bounds(duration):
    with pytest.raises(ValueError):
        clip_plan([], duration)


def test_reject_event_times_and_partial_json():
    with pytest.raises(ValueError):
        validate_events(EventPass(events=[event(4, 90)]), 57.09)
    with pytest.raises(ValueError):
        validate_events(EventPass(events=[event(4, 2)]), 57.09)
    with pytest.raises(ValueError):
        parse_json('{"events": [', EventPass)
    assert parse_json('```json\n{"events": []}\n```', EventPass).events == []


def test_local_timestamps_map_to_original_recording():
    parsed = ClipPass.model_validate({'observations': [{'startSeconds': 0.5, 'endSeconds': 2.0,
        'action': 'Tool moves', 'visibleLabels': [], 'uncertainty': 'Setting unreadable'}]})
    rows = absolute_observations(parsed, {'id': 'c001', 'startSeconds': 21.0, 'endSeconds': 29.0})
    assert rows[0]['startSeconds'] == 21.5 and rows[0]['endSeconds'] == 23
    assert rows[0]['clipId'] == 'c001'
    parsed.observations[0].endSeconds = 99
    with pytest.raises(ValueError):
        absolute_observations(parsed, {'id':'c001', 'startSeconds':21.0, 'endSeconds':29.0})


def test_step_numbers_are_mapped_without_inventing_ids():
    observations = [{'id': 'o000'}, {'id': 'o001'}]
    steps = [{'order': 4, 'id': 'real-step-id'}]
    parsed = MatchPass.model_validate({'matches': [{'observationId': 'o000', 'stepNumber':4,'reason':'Transfer action'},
                                                 {'observationId': 'o001','stepNumber':None,'reason':'No correspondence'}]})
    result = validate_matches(parsed, observations, steps)
    assert result[0]['procedureStepId'] == 'real-step-id'
    assert result[1]['procedureStepId'] is None
    assert all(m['reviewStatus'] == 'unreviewed' for m in result)
    parsed.matches[0].stepNumber = 99
    with pytest.raises(ValueError):
        validate_matches(parsed, observations, steps)


def test_matching_cannot_drop_or_duplicate_observations():
    parsed = MatchPass.model_validate({'matches': []})
    with pytest.raises(ValueError):
        validate_matches(parsed, [{'id':'o000'}], [])
    row = {'observationId':'o000','stepNumber':None,'reason':'No match'}
    parsed = MatchPass.model_validate({'matches':[row,row]})
    with pytest.raises(ValueError):
        validate_matches(parsed, [{'id':'o000'}], [])


def test_disabled_pipeline_never_loads_a_model_or_writes(tmp_path):
    with pytest.raises(ValueError, match='enable-local-inference'):
        run({}, tmp_path/'missing.mp4', tmp_path/'missing-model', tmp_path/'runs')
    assert not (tmp_path/'runs').exists()


def test_real_derived_clip_preserves_original_and_refuses_overwrite(video, tmp_path):
    source, out = tmp_path/'original.mp4', tmp_path/'clip.mp4'
    source.write_bytes(video)
    checksum = render_clip(source, out, 0.5, 2.5, fps=2, width=320, height=240)
    assert len(checksum) == 64 and out.stat().st_mode & 0o777 == 0o600
    assert probe_video(out) == pytest.approx(2.0, abs=0.1)
    assert source.read_bytes() == video
    with pytest.raises(ValueError):
        render_clip(source, out, 0, 1, fps=2, width=320, height=240)


@pytest.mark.parametrize('resume_mode', [None, 'resume', 'tampered-clip', 'changed-procedure'])
def test_two_pass_separates_visual_evidence_from_protocol_and_covers_empty_event_pass(tmp_path, monkeypatch, resume_mode):
    source = tmp_path/'source.mp4'
    source.write_bytes(b'synthetic test source')
    model = tmp_path/'model'
    model.mkdir()
    (model/'model.safetensors').write_bytes(b'fixture weights')
    (model/'medici-model-source.json').write_text('{"revision":"test-only"}')
    experiment = {'id':'e1', 'procedureVersionId':'p1', 'video':{'durationSeconds':12.0,'checksum':digest(source)},
        'trackingPlan':{'available':True,'procedureVersionId':'p1',
            'steps':[{'order':1,'id':'step-1','text':'SECRET_PROTOCOL_TEXT'}]},
        'observations':[{'description':'DO_NOT_LEAK_PREVIOUS_FINDINGS'}]}
    requests = []
    failed_once = False
    class FakeModel:
        def __init__(self, folder):
            pass
        def ask(self, prompt, schema, destination, **kwargs):
            nonlocal failed_once
            requests.append((prompt, schema, kwargs))
            assert 'DO_NOT_LEAK_PREVIOUS_FINDINGS' not in prompt
            if schema == EventPass:
                assert 'SECRET_PROTOCOL_TEXT' not in prompt and kwargs['video'].suffix == '.mp4'
                result = EventPass(events=[])
                destination.with_suffix('.json').write_text(result.model_dump_json())
                return result
            if schema == ClipPass:
                assert 'SECRET_PROTOCOL_TEXT' not in prompt and kwargs['fps'] == 2
                if resume_mode and destination.name == 'analysis-c001' and not failed_once:
                    failed_once = True
                    raise ValueError('Synthetic interrupted generation')
                result = ClipPass(observations=[{'startSeconds':0.0,'endSeconds':1.0,
                    'action':'Tool moves','visibleLabels':[],'uncertainty':'Identity unclear'}])
                destination.with_suffix('.json').write_text(result.model_dump_json())
                return result
            assert schema == MatchPass and 'SECRET_PROTOCOL_TEXT' in prompt and 'video' not in kwargs
            batch = json.loads(prompt[prompt.index('{"steps"'):])['observations']
            return MatchPass(matches=[{'observationId':o['id'],'stepNumber':None,'reason':'No clear correspondence'} for o in batch])
    def fake_render(video, destination, *args, **kwargs):
        destination.write_bytes(b'fixture clip, not real inference')
        destination.chmod(0o600)
        return digest(destination)
    monkeypatch.setattr(mlx_video_pipeline, 'NativeVideoModel', FakeModel)
    monkeypatch.setattr(mlx_video_pipeline, 'render_clip', fake_render)
    monkeypatch.setattr(mlx_video_pipeline.importlib.metadata, 'version', lambda name:'fixture-runtime')
    if resume_mode:
        with pytest.raises(ValueError, match='Synthetic interrupted'):
            run(experiment, source, model, tmp_path/'runs', enabled=True, progress=lambda *a,**k:None)
        folder = next((tmp_path/'runs').iterdir())
        assert json.loads((folder/'run.json').read_text())['completedClips'] == 1
        original_analysis = (folder/'analysis-c000.json').read_bytes()
        if resume_mode == 'tampered-clip':
            (folder/'clips/c000.mp4').write_bytes(b'changed evidence')
            with pytest.raises(ValueError, match='evidence clip changed'):
                run(experiment, source, model, tmp_path/'runs', enabled=True, resume=folder)
            return
        if resume_mode == 'changed-procedure':
            experiment['procedureVersionId'] = 'p2'
            experiment['trackingPlan']['procedureVersionId'] = 'p2'
            with pytest.raises(ValueError, match='matching video, procedure, and model'):
                run(experiment, source, model, tmp_path/'runs', enabled=True, resume=folder)
            return
        run(experiment, source, model, tmp_path/'runs', enabled=True, resume=folder, progress=lambda *a,**k:None)
        assert (folder/'analysis-c000.json').read_bytes() == original_analysis
        assert (folder/'clips/c001.mp4').exists() and (folder/'clips/c001-attempt-2.mp4').exists()
        assert sum(schema == EventPass for _,schema,_ in requests) == 1
        assert sum(schema == ClipPass for _,schema,_ in requests) == 3
        assert [o['id'] for o in json.loads((folder/'observations.json').read_text())] == ['o000', 'o001']
    else:
        folder = run(experiment, source, model, tmp_path/'runs', enabled=True, progress=lambda *a,**k:None)
    metadata = json.loads((folder/'run.json').read_text())
    assert metadata['status'] == 'completed' and metadata['eventCount'] == 0
    assert metadata['clipCount'] == metadata['completedClips'] == 2
    assert metadata['imported'] is False
    assert len(json.loads((folder/'observations.json').read_text())) == 2
    assert (folder/'REVIEW.md').exists()
    assert requests[0][1] == EventPass and requests[-1][1] == MatchPass

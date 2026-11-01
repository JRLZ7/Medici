from fastapi.testclient import TestClient

from backend.app import create_app
from backend.protocol import parse_protocol

WRITE = {'X-Medici-Request': '1'}
VALID = '## Materials\n- @pipette | equipment | Pipette | appearance: gray handheld pipette\n## Procedure\n1. Set down @pipette.'


def test_paste_spacing_bullets_and_code_fence_keep_original_line_numbers():
    text = '```text\n## Materials\n•  @pipette|Equipment|Pipette|appearance : gray handheld pipette\n\n## Procedure\n1. Set down @pipette.\n```'
    result = parse_protocol(text)
    assert result['valid'], result
    assert result['document']['materials'][0]['sourceLine'] == 3
    assert result['document']['steps'][0]['sourceLine'] == 6
    assert result['document']['materials'][0]['key'] == 'pipette'


def test_material_root_error_does_not_cascade_to_each_reference():
    text = VALID.replace('| equipment |', '| tool |') + '\n2. Pick up @pipette.\n3. Set down @pipette.'
    result = parse_protocol(text)
    assert not result['valid']
    assert any("unknown kind 'tool'" in error['message'] for error in result['errors'])
    assert not any('Undeclared material @pipette' in error['message'] for error in result['errors'])
    missing = parse_protocol(VALID.replace('@pipette.', '@missing.') + '\n2. Pick up @missing.')
    assert sum('Undeclared material @missing' in e['message'] for e in missing['errors']) == 1


def test_invalid_draft_saves_and_reopens_without_creating_tracking_plan(tmp_path):
    bad = VALID.replace('| equipment |', '| tool |')
    with TestClient(create_app(tmp_path)) as client:
        response = client.post('/api/experiments', headers=WRITE, json={'title': 'Draft', 'procedure': bad, 'procedureFormat': 'draft'})
        assert response.status_code == 201, response.text
        saved = response.json()
        assert not saved['trackingPlan']['available']
        assert saved['procedureVersions'][0]['structure']['status'] == 'draft'
        assert saved['procedureVersions'][0]['structure']['validationErrors']
        assert saved['procedureVersions'][0]['text'] == bad
    with TestClient(create_app(tmp_path)) as client:
        reopened = client.get('/api/experiments/' + saved['id']).json()
        assert reopened['procedureVersions'][0]['text'] == bad
        response = client.put('/api/experiments/' + saved['id'], headers=WRITE, json={'title': 'Draft', 'procedure': bad, 'expectedVersionId': saved['procedureVersionId']})
        assert response.status_code == 422
        response = client.put('/api/experiments/' + saved['id'], headers=WRITE, json={'title': 'Valid', 'procedure': VALID, 'expectedVersionId': saved['procedureVersionId']})
        assert response.status_code == 200, response.text
        assert response.json()['trackingPlan']['available']
        assert response.json()['procedureVersions'][0]['text'] == bad


def test_valid_text_can_be_promoted_from_draft_without_text_edits(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        e = client.post('/api/experiments', headers=WRITE, json={'title': 'Draft', 'procedure': VALID, 'procedureFormat': 'draft'}).json()
        assert not e['trackingPlan']['available']
        promoted = client.put('/api/experiments/' + e['id'], headers=WRITE, json={'title': 'Valid', 'procedure': VALID, 'expectedVersionId': e['procedureVersionId']}).json()
        assert promoted['trackingPlan']['available']
        assert len(promoted['procedureVersions']) == 2
        demoted = client.put('/api/experiments/' + e['id'], headers=WRITE, json={'title': 'Draft again', 'procedure': VALID, 'expectedVersionId': promoted['procedureVersionId'], 'procedureFormat': 'draft'}).json()
        assert not demoted['trackingPlan']['available']
        assert demoted['procedureVersions'][1]['structure']['status'] == 'structured'

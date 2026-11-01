import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.protocol import parse_protocol

WRITE = {"X-Medici-Request": "1"}
TEXT = """# Mixing review
## Purpose
Document a transfer.
## Materials
- @cup | equipment | Cup | appearance: transparent cup
- @water | reagent | Water | label: WATER
- @spoon | equipment | Spoon | appearance: metal spoon
## Procedure
1. Pour @water into @cup.
  Detail: Keep the printed label facing the camera.
  Expect: @water is transferred into @cup.
2. Set down @cup.
## Notes
A pause is not automatically a deviation.
## Expected results
The declared transfer is complete.
"""


def test_sections_and_tracking_scope(tmp_path):
    result = parse_protocol(TEXT)
    assert result['valid'], result
    doc = result['document']
    assert len(doc['steps']) == 2
    assert len(doc['materials']) == 3
    assert doc['steps'][0]['materialKeys'] == ['water', 'cup']
    assert len(doc['steps'][0]['details']) == 1
    assert len(doc['steps'][0]['expectations']) == 1
    assert doc['sections']['Notes'][0]['text'].startswith('A pause')
    with TestClient(create_app(tmp_path)) as c:
        e = c.post('/api/experiments', json={'title': 'Review', 'procedure': TEXT}, headers=WRITE).json()
        plan = c.get(f'/api/experiments/{e["id"]}/tracking-plan').json()
        assert plan['available'] is True
        assert plan['analysisEnabled'] is False
        assert {m['key'] for m in plan['materials']} == {'water', 'cup'}  # unused spoon is not a target
        assert plan['steps'][0]['id'] == e['procedureVersions'][0]['steps'][0]['id']
        assert 'details' not in plan['steps'][0]
        exported = c.get(f'/api/experiments/{e["id"]}/export').json()
        assert exported['experiment']['trackingPlan'] == plan
        assert e['procedureVersions'][0]['text'] == TEXT
        assert len(plan['sourceSha256']) == 64


@pytest.mark.parametrize('text', [
    'Mix water',
    TEXT.replace('## Materials', '## Stuff'),
    TEXT.replace('## Materials', '## Materials\n## Materials'),
    TEXT.replace('2. Set', '3. Set'),
    TEXT.replace('1. Pour @water into @cup.', '1. Pour liquid.'),
    TEXT.replace('@water into @cup', '@unknown into @cup'),
    TEXT.replace('label: WATER', 'appearance: clear liquid'),
    TEXT.replace('- @water | reagent', '- @cup | reagent'),
    TEXT.replace('  Detail:', 'Detail:'),
    TEXT.replace('  Detail:', '  Random:'),
    TEXT.replace('  Expect: @water', '  Expect: @spoon'),
    TEXT.replace('@water into', '@Water into'),
    TEXT.replace('transparent cup', ' '),
    TEXT.replace('## Procedure', '### Procedure'),
    TEXT.replace('## Procedure\n', '## Procedure\n  Detail: orphan\n'),
])
def test_invalid_syntax_is_rejected_with_line_errors(text, tmp_path):
    result = parse_protocol(text)
    assert not result['valid']
    assert result['document'] is None  # partial results never become tracking scope
    assert all('line' in e and e['message'] for e in result['errors'])
    with TestClient(create_app(tmp_path)) as c:
        response = c.post('/api/experiments', json={'title': 'Bad', 'procedure': text}, headers=WRITE)
        assert response.status_code == 422
        assert c.get('/api/experiments').json() == []  # no partial experiment commits


def test_draft_and_unverifiable_materials(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        draft = c.post('/api/experiments', json={'title': 'Draft', 'procedure': ''}, headers=WRITE).json()
        assert draft['trackingPlan']['available'] is False
        body = TEXT.replace('label: WATER', 'unverifiable: no readable identity on recording')
        e = c.post('/api/experiments', json={'title': 'Unclear', 'procedure': body}, headers=WRITE).json()
        water = next(m for m in e['trackingPlan']['materials'] if m['key'] == 'water')
        assert water['identityVerifiable'] is False
        assert c.post('/api/procedures/parse', json={'text': TEXT}, headers=WRITE).json()['valid']


def test_legacy_versions_and_links_survive(tmp_path):
    # Simulate an existing line-based procedure; startup must not reparse its IDs.
    with TestClient(create_app(tmp_path)) as c:
        e = c.post('/api/experiments', json={'title': 'Old', 'procedure': ''}, headers=WRITE).json()
    pid, eid = e['procedureVersionId'], e['id']
    with sqlite3.connect(tmp_path / 'medici.sqlite3') as db:
        db.execute('DELETE FROM procedure_structures WHERE procedure_id=?', (pid,))
        db.execute('UPDATE procedures SET text=?, steps=? WHERE id=?', ('Old source', json.dumps([{'id': 'old-step', 'order': 1, 'text': 'Old source'}]), pid))
        db.execute('INSERT INTO observations VALUES (?,?,?)', ('old-observation', eid, json.dumps({'id': 'old-observation', 'procedureVersionId': pid, 'procedureStepIds': ['old-step']})))
    with TestClient(create_app(tmp_path)) as c:
        old = c.get(f'/api/experiments/{eid}').json()
        assert old['procedureVersions'][0]['steps'][0]['id'] == 'old-step'
        assert old['trackingPlan']['available'] is False
        renamed = c.put(f'/api/experiments/{eid}', json={'title': 'Renamed', 'procedure': 'Old source', 'expectedVersionId': pid}, headers=WRITE).json()
        assert renamed['procedureVersionId'] == pid
        assert renamed['trackingPlan']['available'] is False
        changed = c.put(f'/api/experiments/{eid}', json={'title': 'Old', 'procedure': TEXT, 'expectedVersionId': pid}, headers=WRITE).json()
        assert changed['trackingPlan']['available'] is True
        assert changed['procedureVersions'][0]['text'] == 'Old source'
        assert changed['procedureVersions'][0]['steps'][0]['id'] == 'old-step'
        assert len(changed['procedureVersions']) == 2
        assert changed['observations'][0]['procedureStepIds'] == ['old-step']
        assert changed['observations'][0]['procedureVersionId'] == pid


def test_raw_source_requires_provenance_and_has_no_targets(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        body = {'title': 'Raw', 'procedure': 'Unstructured source', 'procedureFormat': 'source-document'}
        assert c.post('/api/experiments', json=body, headers=WRITE).status_code == 422
        body['datasetSource'] = {'name': 'Source', 'recordUrl': 'https://zenodo.org/records/17710382', 'license': 'CC BY-ND 4.0', 'videoFilename': 'video.mp4', 'protocolFilename': 'source.md', 'referenceNote': 'Source only'}
        e = c.post('/api/experiments', json=body, headers=WRITE).json()
        assert e['trackingPlan']['available'] is False
        assert e['procedureVersions'][0]['steps'] == []


def test_invalid_edit_does_not_change_saved_plan(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        original = c.post('/api/experiments', json={'title': 'Valid', 'procedure': TEXT}, headers=WRITE).json()
        response = c.put(f'/api/experiments/{original["id"]}', json={'title': 'Changed', 'procedure': TEXT.replace('@water into @cup', '@undeclared into @cup'), 'expectedVersionId': original['procedureVersionId']}, headers=WRITE)
        assert response.status_code == 422
        assert c.get(f'/api/experiments/{original["id"]}').json() == original

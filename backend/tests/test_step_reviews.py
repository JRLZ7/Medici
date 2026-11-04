from fastapi.testclient import TestClient
from backend.app import create_app
from test_app import client, video, create, upload, annotation, WRITE, PROTOCOL


def assess(c, e, conclusion="not_verifiable", **patch):
    row = e["stepSummary"][0]
    body = {"procedureVersionId": e["procedureVersionId"], "conclusion": conclusion,
            "note": "Action evidence does not verify the complete step.",
            "expectedEvidenceFingerprint": row["evidenceFingerprint"],
            "expectedUpdatedAt": row["review"]["updatedAt"] if row["review"] else "", **patch}
    return c.put(f'/api/experiments/{e["id"]}/step-reviews/{row["stepId"]}', json=body, headers=WRITE)


def add(c, e, **patch):
    r = c.post(f'/api/experiments/{e["id"]}/observations', json={**annotation(e), **patch}, headers=WRITE)
    assert r.status_code == 201, r.text
    return r.json()


def test_evidence_never_automatically_supports_step(client, video):
    e = upload(client, create(client)["id"], video)
    assert e["stepSummary"][0]["evidenceIds"] == []
    assert e["stepSummary"][0]["conclusion"] == "unassessed"
    assert assess(client, e, "supported").status_code == 422
    e = add(client, e, reviewStatus="confirmed")
    row = e["stepSummary"][0]
    assert row["conclusion"] == "unassessed" and row["reviewStatus"] == "awaiting_review"
    r = assess(client, e, "supported", note="All requirements are visible and checked by the reviewer.")
    assert r.status_code == 200, r.text
    assert r.json()["stepSummary"][0]["reviewStatus"] == "reviewed"


def test_uncertain_or_unreviewed_evidence_cannot_support(client, video):
    e = upload(client, create(client)["id"], video)
    e = add(client, e)
    assert assess(client, e, "supported").status_code == 422
    e = add(client, e, category="not_verifiable", reviewStatus="confirmed")
    assert assess(client, e, "supported").status_code == 422
    assert e["stepSummary"][0]["unreviewedCount"] == 1
    assert e["stepSummary"][0]["notVerifiableCount"] == 1


def test_open_bottles_does_not_establish_opening_step(client, video):
    e = upload(client, create(client)["id"], video)
    e = add(client, e, category="not_verifiable",
            description="Both bottles are already open at the start of the recording.")
    rejected = assess(client, e, "supported")
    assert rejected.status_code == 422
    assert "confirm supporting evidence" in rejected.json()["detail"]
    saved = client.get(f'/api/experiments/{e["id"]}').json()
    assert saved["stepSummary"][0]["conclusion"] == "unassessed"
    accepted = assess(client, saved, "not_verifiable", note="Opening occurs before this recording; the opening action cannot be assessed.")
    assert accepted.status_code == 200
    assert accepted.json()["stepSummary"][0]["conclusion"] == "not_verifiable"


def test_evidence_edits_dismissal_and_history(client, video):
    e = upload(client, create(client)["id"], video)
    e = add(client, e, category="potential_deviation", evidenceNote="Visible mismatch")
    original = e
    e = assess(client, e, "potential_deviation").json()
    assert e["stepSummary"][0]["potentialDeviationCount"] == 1
    assert assess(client, original).status_code == 409  # concurrent assessment
    o = e["observations"][0]
    r = client.put(f'/api/experiments/{e["id"]}/observations/{o["id"]}',
                   json={**annotation(e), "reviewStatus": "dismissed", "expectedUpdatedAt": o["updatedAt"]}, headers=WRITE)
    changed = r.json()
    row = changed["stepSummary"][0]
    assert row["reviewStatus"] == "needs_review"
    assert row["conclusion"] == "potential_deviation"  # previous conclusion retained, flagged stale
    assert row["evidenceIds"] == [] and row["dismissedCount"] == 1
    assert row["potentialDeviationCount"] == 0
    assert assess(client, e).status_code == 409  # evidence changed
    e = assess(client, changed).json()
    assert e["stepSummary"][0]["reviewStatus"] == "reviewed"
    assert e["stepReviews"][0]["history"][0]["conclusion"] == "potential_deviation"


def test_version_isolation_and_validation(client, video):
    e = upload(client, create(client)["id"], video)
    for patch in ({"note": " "}, {"conclusion": "complete"}):
        assert assess(client, e, **patch).status_code == 422
    e = assess(client, e).json()
    changed = client.put(f'/api/experiments/{e["id"]}', json={"title": e["title"],
        "procedure": PROTOCOL.replace("Mix gently", "Mix slowly"),
        "expectedVersionId": e["procedureVersionId"]}, headers=WRITE).json()
    assert len(changed["stepReviews"]) == 1
    assert all(s["conclusion"] == "unassessed" for s in changed["stepSummary"])
    assert assess(client, e).status_code == 409
    other = create(client)
    row = other["stepSummary"][0]
    assert client.put(f'/api/experiments/{changed["id"]}/step-reviews/{row["stepId"]}', json={
        "procedureVersionId": changed["procedureVersionId"], "conclusion": "not_verifiable", "note": "Unknown",
        "expectedEvidenceFingerprint": row["evidenceFingerprint"]}, headers=WRITE).status_code == 422


def test_review_persists_after_restart_and_in_export(tmp_path):
    path = tmp_path / "data"
    with TestClient(create_app(path)) as c:
        e = create(c)
        e = assess(c, e).json()
    with TestClient(create_app(path)) as c:
        saved = c.get(f'/api/experiments/{e["id"]}').json()
        assert saved["stepSummary"] == e["stepSummary"]
        exported = c.get(f'/api/experiments/{e["id"]}/export').json()["experiment"]
        assert exported["stepReviews"] == saved["stepReviews"]
        assert exported["stepSummary"][0]["reviewStatus"] == "reviewed"


def test_draft_has_no_step_summary(client):
    r = client.post('/api/experiments', json={"title": "Draft", "procedure": "Text",
                                             "procedureFormat": "draft"}, headers=WRITE)
    assert r.status_code == 201
    assert r.json()["stepSummary"] == []

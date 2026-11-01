"""Import one checksum-verified, local public dataset bundle. Never calls a model.

Run with the app's virtualenv while its loopback server is running.
Dataset files are obtained separately; this script does not download them.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

VIDEO = "Dilute_docuWrongSolvent.MP4"
PROTOCOL = "Diluting_protocolCorrect.md"
REFERENCES = "lab_note_all_eval_sets_all_runs.json"
CASE = "Dilute_docuWrongSolvent"


def verify(folder, record, filename):
    entry = next(f for f in record["files"] if f["key"] == filename)
    path = folder / filename
    checksum = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    if path.stat().st_size != entry["size"] or "md5:" + checksum.hexdigest() != entry["checksum"]:
        raise ValueError(f"Dataset checksum/size mismatch: {filename}")
    return path


def reference_labels(records):
    """Keep only benchmark columns; never mistake generated lab_notes for truth."""
    cases = [r for r in records if r["eval_set"] == CASE]
    if not cases:
        raise ValueError("No matching benchmark reference rows.")
    labels = []
    for case in cases:
        labels.append([{k: row[k] for k in ("Step", "Benchmark", "Class", "Skill")} for row in case["df_errors"]])
    if any(label != labels[0] for label in labels[1:]):
        raise ValueError("Benchmark labels differ across runs; inspect before importing.")
    return {"sourceFile": REFERENCES, "case": CASE,
            "notice": "Supplied step-level benchmark labels, not timestamped observations. No AI response text included.",
            "labels": labels[0]}


def chunks(path):
    with path.open("rb") as stream:
        yield from iter(lambda: stream.read(1024 * 1024), b"")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    parsed = urlparse(args.api)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise SystemExit("Use a plain loopback HTTP API origin.")
    folder = args.source_dir.resolve()
    record = json.loads((folder / "record.json").read_text())
    if record["id"] != 17710382:
        raise SystemExit("This importer supports Zenodo record 17710382 only.")
    video = verify(folder, record, VIDEO)
    protocol = verify(folder, record, PROTOCOL)
    refs = verify(folder, record, REFERENCES)
    labels = reference_labels(json.loads(refs.read_text()))
    label_path = folder / "reference-labels.json"
    label_path.write_text(json.dumps(labels, indent=2) + "\n")
    label_path.chmod(0o600)
    receipt = folder / "medici-import.json"
    headers = {"X-Medici-Request": "1"}
    with httpx.Client(base_url=args.api.rstrip("/") + "/api/", headers=headers, timeout=180, trust_env=False) as client:
        experiment = None
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            if previous.get("recordId") == record["id"]:
                response = client.get("experiments/" + previous["experimentId"])
                if response.status_code == 200:
                    experiment = response.json()
                    if (experiment.get("datasetSource") or {}).get("videoFilename") != VIDEO:
                        raise ValueError("Import receipt points to a different experiment; inspect before proceeding.")
                elif response.status_code != 404:
                    response.raise_for_status()
        if experiment is None:
            response = client.post("experiments", json={
                "title": "Public dataset · Dilution review",
                "procedure": protocol.read_text(),
                "procedureFormat": "source-document",
                "datasetSource": {
                    "name": "Mann Labs proteomics benchmark · v1.1.0",
                    "recordUrl": "https://zenodo.org/records/17710382",
                    "license": "CC BY-ND 4.0",
                    "videoFilename": VIDEO,
                    "protocolFilename": PROTOCOL,
                    "referenceNote": "External research recording. Review starts empty. Supplied step-level benchmark labels are kept separately in reference-labels.json; they are not timestamped Medici findings. No model analysis has run.",
                },
            })
            response.raise_for_status()
            experiment = response.json()
            receipt.write_text(json.dumps({"api": args.api, "experimentId": experiment["id"], "recordId": record["id"]}, indent=2) + "\n")
            receipt.chmod(0o600)
        endpoint = "experiments/" + experiment["id"]
        if experiment["video"] is None:
            response = client.post(endpoint + "/video", content=chunks(video), headers={
                "X-Filename": VIDEO, "Content-Type": "application/octet-stream", "Content-Length": str(video.stat().st_size)})
            response.raise_for_status()
            experiment = response.json()
        digest = hashlib.sha256()
        for chunk in chunks(video):
            digest.update(chunk)
        if experiment["video"]["checksum"] != digest.hexdigest():
            raise ValueError("The experiment contains a different video. No replacement performed.")
        print(json.dumps({"experimentId": experiment["id"], "title": experiment["title"],
                          "durationSeconds": experiment["video"]["durationSeconds"],
                          "observations": len(experiment["observations"]), "referenceFile": str(label_path),
                          "videoChecksumVerified": True}, indent=2))


if __name__ == "__main__":
    main()

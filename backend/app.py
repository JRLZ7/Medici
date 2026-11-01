"""Local-only experiment records. No analysis provider or outbound model calls."""
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import imageio_ffmpeg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware
from typing import Literal
from backend.protocol import parse_protocol, tracking_plan

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"observation", "potential_deviation", "unwritten_detail", "not_verifiable"}
STATUSES = {"unreviewed", "confirmed", "corrected", "dismissed"}


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


class DatasetSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300)
    recordUrl: str = Field(pattern=r"^https://zenodo\.org/records/[0-9]+$")
    license: str = Field(min_length=1, max_length=100)
    videoFilename: str = Field(min_length=1, max_length=240)
    protocolFilename: str = Field(min_length=1, max_length=240)
    referenceNote: str = Field(max_length=3000)


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    procedure: str = Field(max_length=100000)
    expectedVersionId: str = ""
    datasetSource: DatasetSource | None = None
    procedureFormat: Literal["medici-v1", "source-document", "draft"] = "medici-v1"


class ParseInput(BaseModel):
    text: str = Field(max_length=100000)


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    startSeconds: float = Field(ge=0)
    endSeconds: float = Field(ge=0)
    description: str = Field(min_length=1, max_length=10000)
    category: str = "observation"
    procedureStepIds: list[str] = Field(default_factory=list, max_length=1000)
    evidenceNote: str = Field(default="", max_length=10000)
    reviewStatus: str = "unreviewed"
    reviewerNote: str = Field(default="", max_length=10000)
    expectedUpdatedAt: str = ""
    source: Literal["manual", "assistant_review"] = "manual"
    provenanceNote: str = Field(default="", max_length=3000)


def probe_video(path):
    # Protocol restriction prevents uploaded containers from resolving remote resources.
    try:
        result = subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "info",
            "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0",
            "-an", "-c:v", "copy", "-f", "null", "-", "-progress", "pipe:1",
        ], capture_output=True, text=True, timeout=60)
        times = re.findall(r"^out_time_us=(\d+)$", result.stdout, re.M)
        duration = max((int(t) / 1_000_000 for t in times), default=0)
        metadata = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr)
        if metadata:
            duration = max(duration, int(metadata[1]) * 3600 + int(metadata[2]) * 60 + float(metadata[3]))
        elif result.returncode == 0:
            # Browser camera WebM often lacks a duration header. Decode to a null sink
            # to include the last frame's duration; packet-copy progress omits it.
            decoded = subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error",
                "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0",
                "-an", "-f", "null", "-", "-progress", "pipe:1",
            ], capture_output=True, text=True, timeout=60)
            if decoded.returncode:
                raise ValueError()
            duration = max((int(t) / 1_000_000 for t in re.findall(r"^out_time_us=(\d+)$", decoded.stdout, re.M)), default=0)
        if result.returncode or not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        return duration
    except (subprocess.SubprocessError, OSError, ValueError):
        raise HTTPException(422, "Could not read a valid video duration. Try a playable MP4 or WebM recording.")


def create_app(data_dir=None, max_upload=None):
    data = Path(data_dir or os.environ.get("MEDICI_DATA_DIR", ROOT / "data")).resolve()
    media = data / "videos"
    limit = max_upload or int(os.environ.get("MEDICI_MAX_UPLOAD_BYTES", 1024 ** 3))

    @contextmanager
    def db():
        connection = sqlite3.connect(str(data / "medici.sqlite3"), timeout=15)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @asynccontextmanager
    async def lifespan(app):
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        media.mkdir(mode=0o700, exist_ok=True)
        data.chmod(0o700)
        media.chmod(0o700)
        with db() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, version_id TEXT NOT NULL, video_id TEXT);
                CREATE TABLE IF NOT EXISTS procedures (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    text TEXT NOT NULL, steps TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL UNIQUE REFERENCES experiments(id),
                    filename TEXT NOT NULL, mime TEXT NOT NULL, duration REAL NOT NULL,
                    size INTEGER NOT NULL, checksum TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dataset_sources (
                    experiment_id TEXT PRIMARY KEY REFERENCES experiments(id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS procedure_structures (
                    procedure_id TEXT PRIMARY KEY REFERENCES procedures(id), payload TEXT NOT NULL);
                PRAGMA user_version = 3;
            """)
        (data / "medici.sqlite3").chmod(0o600)
        yield

    app = FastAPI(title="Medici local API", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8000, 5173)}

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo private input, or non-JSON NaN/Infinity, into error responses.
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse({"detail": errors}, 422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Records could not be saved or loaded. Check disk space and retry."}, 503)

    @app.middleware("http")
    async def security(request, call_next):
        origin = request.headers.get("origin")
        # Also allow this loopback server's own origin when run on another port.
        # TrustedHostMiddleware still rejects non-local Host headers downstream.
        same_origin = str(request.base_url).rstrip("/")
        if origin and origin not in origins and origin != same_origin:
            return JSONResponse({"detail": "This local app does not accept requests from that origin."}, 403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are blocked."}, 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-medici-request") != "1":
                return JSONResponse({"detail": "Missing local request header."}, 403)
        is_upload = request.url.path.endswith("/video") and request.method == "POST"
        cap = limit if is_upload else 2 * 1024 * 1024
        try:
            if int(request.headers.get("content-length", "0")) > cap:
                return JSONResponse({"detail": "Request exceeds the configured size limit."}, 413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, 400)
        # Buffer only bounded JSON; uploads enforce their limit while writing each chunk.
        if request.method not in ("GET", "HEAD", "OPTIONS") and not is_upload:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > cap:
                    return JSONResponse({"detail": "Request exceeds the configured size limit."}, 413)
                body.extend(chunk)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def experiment(c, experiment_id):
        row = c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Experiment not found.")
        return row

    def full(c, experiment_id):
        e = experiment(c, experiment_id)
        versions = [{"id": p["id"], "text": p["text"], "steps": json.loads(p["steps"]), "createdAt": p["created_at"]}
                    for p in c.execute("SELECT * FROM procedures WHERE experiment_id=? ORDER BY rowid", (experiment_id,))]
        for version in versions:
            structure = c.execute("SELECT payload FROM procedure_structures WHERE procedure_id=?", (version["id"],)).fetchone()
            version["structure"] = json.loads(structure[0]) if structure else None
        current = next(v for v in versions if v["id"] == e["version_id"])
        video = c.execute("SELECT * FROM videos WHERE experiment_id=?", (experiment_id,)).fetchone()
        source = c.execute("SELECT payload FROM dataset_sources WHERE experiment_id=?", (experiment_id,)).fetchone()
        return {"id": e["id"], "title": e["title"], "createdAt": e["created_at"], "updatedAt": e["updated_at"],
                "datasetSource": json.loads(source[0]) if source else None,
                "trackingPlan": tracking_plan(current["id"], current["structure"], current["steps"]),
                "procedureVersionId": e["version_id"], "procedureVersions": versions,
                "video": None if video is None else {"id": video["id"], "originalFilename": video["filename"],
                    "durationSeconds": video["duration"], "mimeType": video["mime"], "sizeBytes": video["size"],
                    "checksum": video["checksum"]},
                "observations": [json.loads(o[0]) for o in c.execute("SELECT payload FROM observations WHERE experiment_id=?", (experiment_id,))]}

    def make_procedure(c, eid, text, source_document=False, draft=False):
        pid = uid()
        parsed = parse_protocol(text) if not source_document else {"valid": True, "document": {"formatVersion": 1, "status": "source-document", "materials": [], "steps": [], "sections": {}}}
        if draft:
            parsed = {"valid": True, "document": {"formatVersion": 1, "status": "draft", "materials": [], "steps": [], "sections": {},
                      "sourceSha256": hashlib.sha256(text.encode()).hexdigest(), "validationErrors": parsed.get("errors", [])}}
        if not parsed["valid"]:
            detail = "; ".join((f"Line {e['line']}: " if e['line'] else "") + e["message"] for e in parsed["errors"])
            raise HTTPException(422, detail)
        document = parsed["document"]
        steps = [{**step, "id": uid()} for step in document["steps"]]
        c.execute("INSERT INTO procedures VALUES (?,?,?,?,?)", (pid, eid, text, json.dumps(steps), now()))
        document["steps"] = steps
        c.execute("INSERT INTO procedure_structures VALUES (?,?)", (pid, json.dumps(document)))
        return pid

    @app.post("/api/procedures/parse")
    def parse(body: ParseInput):
        return parse_protocol(body.text)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "analysis": "disabled", "maxUploadBytes": limit,
                "assistantReviewProvenance": True}

    @app.get("/api/experiments")
    def list_experiments():
        with db() as c:
            return [{"id": r["id"], "title": r["title"], "updatedAt": r["updated_at"]}
                    for r in c.execute("SELECT * FROM experiments ORDER BY updated_at DESC")]

    @app.post("/api/experiments", status_code=201)
    def create(body: ExperimentInput):
        title = body.title.strip()
        if not title:
            raise HTTPException(422, "Give your experiment a title.")
        eid, stamp = uid(), now()
        with db() as c:
            c.execute("INSERT INTO experiments VALUES (?,?,?,?,?,NULL)", (eid, title, stamp, stamp, ""))
            if body.procedureFormat == "source-document" and not body.datasetSource:
                raise HTTPException(422, "Source-document import requires dataset provenance. Normal procedures use Medici v1 syntax.")
            pid = make_procedure(c, eid, body.procedure, body.procedureFormat == "source-document", body.procedureFormat == "draft")
            c.execute("UPDATE experiments SET version_id=? WHERE id=?", (pid, eid))
            if body.datasetSource:
                c.execute("INSERT INTO dataset_sources VALUES (?,?)", (eid, body.datasetSource.model_dump_json()))
            return full(c, eid)

    @app.get("/api/experiments/{eid}")
    def get(eid: str):
        with db() as c:
            return full(c, eid)

    @app.put("/api/experiments/{eid}")
    def update(eid: str, body: ExperimentInput):
        if not body.title.strip():
            raise HTTPException(422, "Give your experiment a title.")
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            e = experiment(c, eid)
            if body.expectedVersionId != e["version_id"]:
                raise HTTPException(409, "Procedure changed elsewhere. Reopen the experiment before saving.")
            old = c.execute("SELECT text FROM procedures WHERE id=?", (e["version_id"],)).fetchone()[0]
            if body.procedureFormat == "source-document":
                raise HTTPException(422, "Edit using Medici v1 syntax. Existing source documents are preserved in version history.")
            old_structure = c.execute("SELECT payload FROM procedure_structures WHERE procedure_id=?", (e["version_id"],)).fetchone()
            old_status = json.loads(old_structure[0])["status"] if old_structure else None
            promote_draft = old_status == "draft" and body.procedureFormat == "medici-v1" and bool(body.procedure.strip())
            demote_to_draft = body.procedureFormat == "draft" and old_status != "draft"
            pid = make_procedure(c, eid, body.procedure, draft=body.procedureFormat == "draft") if old != body.procedure or promote_draft or demote_to_draft else e["version_id"]
            c.execute("UPDATE experiments SET title=?, version_id=?, updated_at=? WHERE id=?", (body.title.strip(), pid, now(), eid))
            return full(c, eid)

    @app.post("/api/experiments/{eid}/video", status_code=201)
    async def upload(eid: str, request: Request):
        with db() as c:
            if experiment(c, eid)["video_id"]:
                raise HTTPException(409, "This experiment already has a video. Create another experiment for a different recording.")
        vid = uid()
        temp, target = media / (vid + ".part"), media / vid
        size, digest, head = 0, hashlib.sha256(), b""
        filename = unquote(request.headers.get("x-filename", "recording"))
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename.replace("\\", "/").split("/")[-1])[:240] or "recording"
        try:
            fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, "Video exceeds the configured upload limit.")
                    head = (head + chunk)[:32]
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            mime = "video/webm" if head.startswith(b"\x1aE\xdf\xa3") else "video/mp4" if head[4:8] == b"ftyp" else None
            if not mime:
                raise HTTPException(415, "Unsupported container. Choose an MP4, MOV, or WebM video.")
            # Run blocking media inspection outside the event loop.
            from starlette.concurrency import run_in_threadpool
            duration = await run_in_threadpool(probe_video, temp)
            with db() as c:
                c.execute("BEGIN IMMEDIATE")
                if experiment(c, eid)["video_id"]:
                    raise HTTPException(409, "A video was already attached in another window.")
                temp.rename(target)
                c.execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?)", (vid, eid, filename, mime, duration, size, digest.hexdigest()))
                c.execute("UPDATE experiments SET video_id=?,updated_at=? WHERE id=?", (vid, now(), eid))
            with db() as c:
                return full(c, eid)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.Error):
            target.unlink(missing_ok=True)
            raise HTTPException(507, "Video could not be saved. Check available disk space and directory permissions, then retry.")
        finally:
            temp.unlink(missing_ok=True)

    @app.get("/api/experiments/{eid}/video")
    def serve_video(eid: str, download: bool = False):
        with db() as c:
            experiment(c, eid)
            v = c.execute("SELECT * FROM videos WHERE experiment_id=?", (eid,)).fetchone()
            if not v or not (media / v["id"]).is_file():
                raise HTTPException(404, "Original video is missing from local storage.")
            return FileResponse(media / v["id"], media_type=v["mime"], filename=v["filename"],
                                content_disposition_type="attachment" if download else "inline")

    def save_observation(eid, body, oid=None):
        if body.category not in CATEGORIES or body.reviewStatus not in STATUSES or not body.description.strip():
            raise HTTPException(422, "Choose a valid category, review status, and description.")
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            e = experiment(c, eid)
            v = c.execute("SELECT duration FROM videos WHERE experiment_id=?", (eid,)).fetchone()
            if not v or not (body.startSeconds <= body.endSeconds <= v[0]):
                raise HTTPException(422, "Observation times must be ordered and within the saved video duration.")
            previous = None
            if oid:
                row = c.execute("SELECT payload FROM observations WHERE id=? AND experiment_id=?", (oid, eid)).fetchone()
                if not row:
                    raise HTTPException(404, "Observation not found.")
                previous = json.loads(row[0])
                if previous["updatedAt"] != body.expectedUpdatedAt:
                    raise HTTPException(409, "Observation changed elsewhere. Reopen it before saving.")
            pid = previous["procedureVersionId"] if previous else e["version_id"]
            steps = json.loads(c.execute("SELECT steps FROM procedures WHERE id=?", (pid,)).fetchone()[0])
            structure = c.execute("SELECT payload FROM procedure_structures WHERE procedure_id=?", (pid,)).fetchone()
            is_structured = structure and json.loads(structure[0])["status"] == "structured"
            if not is_structured and set(body.procedureStepIds) - set(previous.get("procedureStepIds", []) if previous else []):
                raise HTTPException(422, "Define a structured procedure before linking new observations to steps. Historical links are preserved.")
            if not set(body.procedureStepIds).issubset({s["id"] for s in steps}):
                raise HTTPException(422, "Step links must belong to this observation's procedure version.")
            if body.category == "potential_deviation" and (not body.procedureStepIds or not body.evidenceNote.strip()):
                raise HTTPException(422, "A potential deviation needs a procedure step and an evidence note.")
            stamp = now()
            source = previous["source"] if previous else body.source
            provenance = previous.get("provenanceNote", "") if previous else body.provenanceNote.strip()
            if not previous and source == "assistant_review" and (body.reviewStatus != "unreviewed" or not provenance):
                raise HTTPException(422, "Assistant suggestions need provenance and must start unreviewed.")
            proposal = previous.get("originalProposal") if previous else (
                body.model_dump(exclude={"expectedUpdatedAt"}) if source == "assistant_review" else None)
            observation = {**body.model_dump(exclude={"expectedUpdatedAt"}), "id": oid or uid(), "experimentId": eid,
                           "procedureVersionId": pid, "source": source, "provenanceNote": provenance, "analysisRunId": None,
                           "originalProposal": proposal, "createdAt": previous["createdAt"] if previous else stamp,
                           "updatedAt": stamp, "history": previous["history"] + [{k: v for k, v in previous.items() if k != "history"}] if previous else []}
            c.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?)", (observation["id"], eid, json.dumps(observation)))
            c.execute("UPDATE experiments SET updated_at=? WHERE id=?", (stamp, eid))
            return full(c, eid)

    @app.post("/api/experiments/{eid}/observations", status_code=201)
    def add_observation(eid: str, body: ObservationInput):
        return save_observation(eid, body)

    @app.put("/api/experiments/{eid}/observations/{oid}")
    def edit_observation(eid: str, oid: str, body: ObservationInput):
        return save_observation(eid, body, oid)

    @app.get("/api/experiments/{eid}/export")
    def export(eid: str):
        with db() as c:
            payload = {"schemaVersion": 1, "exportedAt": now(), "mediaIncluded": False,
                       "notice": "Record export only; download the original video separately. Reimport is not yet supported.",
                       "experiment": full(c, eid)}
            return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="medici-{eid}.json"'})

    @app.get("/api/experiments/{eid}/tracking-plan")
    def get_tracking_plan(eid: str):
        with db() as c:
            return full(c, eid)["trackingPlan"]

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found.")
        dist = ROOT / "frontend" / "dist"
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / "index.html").exists() and not Path(path).suffix:
            return FileResponse(dist / "index.html")
        raise HTTPException(404, "Frontend unavailable. Run npm run build, or use the Vite development server.")

    return app


app = create_app()

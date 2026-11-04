# Medici

A local evidence workspace for scientific experiments. Record the experiment, recover the details, and review the evidence.

Medici brings an original recording, a versioned written procedure, and human-reviewed timestamped observations into one workspace. **Automatic analysis is disabled by default.** An explicitly enabled experimental command can analyze sampled frames with a local Ollama vision model. No cloud inference or external footage upload is implemented.

## Requirements

- macOS, Linux, or Windows with Python 3.11+ and Node.js 22.12+ (tested on macOS ARM64, Python 3.12, and Node 24). Use current patch releases of supported runtimes.
- A recent browser supporting your recording's codec. MP4/H.264 is a good starting format; MP4/MOV and WebM containers are accepted.
- Disk space for original recordings. Default upload limit: 1 GiB per recording.

## Quick start

Run from the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci
npm run build
npm start
```

Open **http://127.0.0.1:8000**. Stop with Ctrl+C. If your supported Python is named `python3` instead, use that to create the environment. On Windows, use `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe` in place of `.venv/bin/python` and start with `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000` from the activated environment.

Dependencies are downloaded during installation, including a bundled FFmpeg executable through `imageio-ffmpeg`. Running Medici does not need internet access. Do not expose either server on a public/network interface.

For frontend development, keep the backend running and use a second terminal:

```sh
npm run dev
```

Open http://127.0.0.1:5173. Vite forwards `/api` to the loopback backend. `npm run build` refreshes the interface served by the backend.

## First experiment

1. Create an experiment using [Medici v1 syntax](docs/PROCEDURE_FORMAT.md): declare `## Materials`, then consecutive numbered `## Procedure` steps with `@material` references. The editor includes an example and parsed preview. Leave the procedure empty only to save a draft without tracking scope.
2. Upload a recording, or grant camera permission and record video (audio is off).
3. Pause at a useful moment and add an observation with start/end times in original-video seconds.
4. Link relevant procedure steps. A potential deviation requires a step link and evidence note.
5. Click an observation's timestamp to seek to its evidence. Review/edit it and choose unreviewed, confirmed, corrected, or dismissed.
6. Reopen the experiment after reload/restart. Export the JSON record and download the original video separately.

Uploads always begin with an empty observation timeline. There is no simulated analysis or seeded finding. Optional local model runs must be explicitly enabled and imported as unreviewed suggestions. Invisible actions should be marked not verifiable; an unwritten detail is not automatically a mistake.

Explicitly prepared assistant reviews use `source: assistant_review`, require a provenance note, and start unreviewed. Human edits preserve the original proposal and provenance. This supports importing a separately prepared review; it does not enable automated video analysis.

The **Per-step review** panel groups active findings for the current structured procedure. Expand a step to seek its evidence or review a finding. Save a separate step conclusion (supported, potential deviation, or not verifiable) with a rationale. Findings never automatically establish step completion. Supported conclusions require confirmed or corrected action evidence; the reviewer must still check all requirements, quantities, and expectations. Dismissed findings are excluded, and earlier procedure versions are kept separate. Evidence edits flag previous conclusions for review again. Step conclusions and their revision history persist locally and are included in JSON exports.

## Architecture

```text
React + TypeScript UI
        | same-origin /api requests
FastAPI (127.0.0.1:8000)
        |                         |
SQLite records              Private original videos
```

- `frontend/src/`: experiment library, player, procedure, review editor, camera capture.
- `backend/app.py`: validation, records, media streaming, exports, and security boundaries.
- `backend/analysis.py`: frame-bundle preparation, model response contract, and evidence validation. `backend/ollama_adapter.py` connects an explicitly enabled local vision model. See [Local model integration](docs/MODEL_INTEGRATION.md) for preparation, inference, validation, and import commands.
- `backend/tests/`: real media and API integration tests.
- SQLite uses schema version 5 (additive source-attribution, parsed-procedure, step-review, and imported analysis-run tables preserve existing local records). IDs are UUIDs. Procedure edits create versions with independent step IDs; old observations and step conclusions retain their original version and step links. Observation and step-conclusion edits preserve prior snapshots in review history. Imported model runs preserve original responses and model provenance.
- Media inspection uses bundled FFmpeg with external protocols disabled and a 60-second timeout per pass. It checks container structure and a video stream, using container metadata for duration. Camera WebM without duration metadata is decoded to a null sink in a second pass to measure the full duration; original files are never transcoded or modified. Long camera recordings may exceed this processing timeout. Browser decoding compatibility is a separate check; a valid container may still contain a codec your browser cannot play.
- One original recording per experiment. To review another recording, create another experiment.
- Parsed procedures define a versioned tracking plan: only referenced materials, numbered actions, and explicit expectations are targets. Materials, details, and notes render separately. Old/source documents remain unparsed until explicitly converted; they never acquire invented tracking scope. Automatic analysis and continuous tracking remain disabled; optional offline local runs use sampled images.

## Storage, privacy, and security

Default private storage is `data/` in the repository:

```text
data/medici.sqlite3   # experiment/procedure/annotation records
data/videos/<uuid>   # original bytes, no user-controlled filesystem names
```

Data directories use owner-only permissions (`0700`), and database/video files use `0600` on POSIX systems. Recordings are streamed to exclusive temporary files, size limited, checked by container signature and FFmpeg, SHA-256 hashed, and renamed only after validation. Filenames are display/download metadata, sanitized and never used as storage paths. A failed request removes its partial file. Abrupt process/power failure may leave unreferenced files; these are not automatically deleted to avoid destroying recoverable footage.

The backend binds to loopback, validates Host and browser Origin/Fetch Metadata, and requires a custom header for writes. SQL uses bound parameters. UI text is rendered as text, never HTML. Responses set content-type sniffing protection, a content security policy, no-store caching, and frame restrictions. The frontend only exposes media through an experiment-scoped endpoint with range support. Paths and secrets are excluded from record exports.

This is a **single-user local app**, without authentication. Other processes or users who can access your local server may access its records. File permissions are not encryption. Use OS account security and disk encryption, and do not use shared/public hosting. Git exclusions prevent routine accidental commits; they do not protect data that someone explicitly force-adds.

Optional shell configuration (see `.env.example`; it is not loaded automatically):

```sh
export MEDICI_DATA_DIR=/absolute/path/to/private/medici-data
export MEDICI_MAX_UPLOAD_BYTES=1073741824
npm start
```

Use a dedicated local directory, not a public web folder, shared folder, or automatically synced cloud directory. The size limit applies to uploads; monitor total available disk space. No API keys are required.

## Saving and backups

Save controls report success only after the API confirms the write. Failed edits remain in the editor for retry. Unsaved edits/recordings trigger the browser's leave-page warning. Camera recordings stay in memory until saved, with a separate download option; closing/crashing the browser before saving can lose them. The app does not claim crash-proof draft recovery.

**JSON export is a record export, not a complete backup.** It contains all procedure versions, observation history, provenance, and timestamps, but not media. JSON reimport is not implemented yet. For a complete restorable backup:

1. Stop the backend and finish/stop any recording.
2. Copy the entire configured data directory to a secure backup location.
3. Restore the directory while the backend is stopped, then restart with the same `MEDICI_DATA_DIR`.

Keep the original video alongside exported records. The SHA-256 checksum in each export identifies the corresponding media.

## Verification

```sh
npm run check
npm run build
npm test
```

The API suite generates real MP4 and WebM test recordings. It covers save/reopen across app restarts, range-based media seeking, annotation correction history, versioned procedure links, timestamp and evidence validation, upload cleanup/limits, path/host/origin protection, and exports. Browser camera permissions and physical camera behavior require manual testing on the target browser.

## Remaining work

For the verified public-data example, provenance, and FineBio access requirements, see [Public datasets](docs/DATASETS.md). The dataset importer leaves the review empty and keeps reference labels separate from Medici findings.

- Validated JSON + media import/export round trip.
- Recoverable drafts and interrupted-recording recovery beyond best-effort browser memory.
- An explicitly separate sample session and richer review-history UI (history is already retained in exports).
- Evaluate and improve the experimental local Qwen/Ollama adapter on held-out, human-reviewed recordings. Automatic inference remains disabled; sparse-frame candidates require review.

An optional [native-video experiment](docs/MODEL_INTEGRATION.md#native-video-coarse-timestamps-then-overlapping-clips) tries a full-recording overview followed by overlapping clips and separate procedure matching. It uses an isolated MLX environment, saves private review artifacts, and does not change experiments in the app.

Medici helps document and investigate experiments. It does not establish causality, prove reproducibility, detect malpractice, or provide certified safety guidance.

## License

See [LICENSE](LICENSE).

"""Explicit, local-only experimental vision inference. Never pulls models."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid

import httpx
from pydantic import Field

from backend.analysis import (StrictModel, Finding, POLICY, load_bundle,
                              validate_response, write_private)

MODEL = 'qwen3-vl:4b-instruct'
ORIGIN = 'http://127.0.0.1:11434'


class FindingsPayload(StrictModel):
    findings: list[Finding] = Field(max_length=20)


def now():
    return datetime.now(timezone.utc).isoformat()


def bounded_json(client, method, path, body=None, timeout=180):
    # A fixed loopback origin, no environment proxies, and no redirects. Model
    # tags are verified locally before images are sent; there is no pull API.
    started = time.monotonic()
    with client.stream(method, path, json=body, timeout=timeout) as response:
        if response.status_code != 200:
            raise ValueError(f'Local Ollama {path} returned HTTP {response.status_code}. No automatic retry or download.')
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            if time.monotonic() - started > timeout:
                raise ValueError('Local Ollama exceeded the response time budget.')
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ValueError('Local Ollama response exceeded the 2 MB limit.')
            chunks.append(chunk)
        return json.loads(b''.join(chunks))


def inspect_runtime(client):
    version = bounded_json(client, 'GET', '/api/version', timeout=10)
    tags = bounded_json(client, 'GET', '/api/tags', timeout=10)
    installed = next((m for m in tags.get('models', []) if m.get('name') == MODEL), None)
    if not installed or not installed.get('digest'):
        raise ValueError(f'Install {MODEL} locally first. Medici will not download a model automatically.')
    info = bounded_json(client, 'POST', '/api/show', {'model': MODEL}, timeout=10)
    if any(record.get(key) for record in (installed, info) for key in ('remote_model', 'remote_host')):
        raise ValueError('Remote/cloud models are not supported by this adapter.')
    if 'vision' not in info.get('capabilities', []):
        raise ValueError('The installed model does not report vision capability.')
    return {'ollamaVersion': version.get('version'), 'modelDigest': installed['digest']}


def frame_windows(frames, size=6):
    if not 2 <= size <= 6:
        raise ValueError('Use 2–6 frames per request.')
    windows = []
    start = 0
    while start < len(frames):
        window = frames[start:start + size]
        windows.append(window)
        if start + size >= len(frames):
            break
        start += size - 1  # Shared boundary frame, no continuous tracking claim.
    return windows


def infer_bundle(bundle, runs_dir, *, enabled=False, transport=None, progress=None,
                 batch_size=6, max_batches=None, start_batch=0, deadline_seconds=900):
    if not enabled:
        raise ValueError('Local inference is disabled. Use the explicit --enable-local-inference switch.')
    if not 1 <= deadline_seconds <= 900 or (max_batches is not None and not 1 <= max_batches <= 32):
        raise ValueError('Use a 1–900 second deadline and a positive batch limit up to 32.')
    bundle = Path(bundle).resolve()
    manifest, manifest_sha = load_bundle(bundle)
    windows = frame_windows(manifest['frames'], batch_size)
    if not 0 <= start_batch < len(windows):
        raise ValueError('Start batch is outside this prepared recording.')
    windows = windows[start_batch:]
    if max_batches is not None:
        windows = windows[:max_batches]
    if not windows or any(not w for w in windows):
        raise ValueError('The prepared bundle has no frames.')
    if len(manifest['frames']) > 32 or any((bundle / f['file']).stat().st_size > 2 * 1024 * 1024 for f in manifest['frames']):
        raise ValueError('Input exceeds the frame-count or per-image size budget.')
    # Only this exact local model is allowed for the first experiment. This
    # constructor also protects against inherited HTTP_PROXY/ALL_PROXY settings.
    with httpx.Client(base_url=ORIGIN, trust_env=False, follow_redirects=False, transport=transport) as client:
        runtime = inspect_runtime(client)
        runs_dir = Path(runs_dir)
        runs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        runs_dir.chmod(0o700)
        run_id = str(uuid.uuid4())
        output = runs_dir / run_id
        output.mkdir(mode=0o700)
        binding = {k: manifest[k] for k in ('experimentId', 'procedureVersionId', 'videoSha256')}
        metadata = {'id': run_id, **binding, 'inputManifestSha256': manifest_sha,
                    'provider': 'ollama-local', 'model': MODEL, **runtime, 'status': 'running', 'adapterVersion': 2,
                    'startedAt': now(), 'completedBatches': 0, 'plannedBatches': len(windows),
                    'startBatch': start_batch,
                    'fullBundleRequested': start_batch == 0 and len(windows) == len(frame_windows(manifest['frames'], batch_size)),
                    'reviewStatus': 'unreviewed', 'imported': False, 'destination': ORIGIN,
                    'options': {'temperature': 0, 'seed': 42, 'num_ctx': 16384, 'num_predict': 1800},
                    'notice': 'Experimental sparse-frame suggestions. Human review required. No audio or continuous tracking.'}
        write_private(output / 'run.json', metadata)
        # Store the exact manifest with the run for independent validation and
        # provenance; the original bundle remains the evidence-image source.
        inputs = output / 'input'
        inputs.mkdir(mode=0o700)
        (inputs / 'frames').mkdir(mode=0o700)
        for name in ('manifest.json', 'status.json'):
            (inputs / name).write_bytes((bundle / name).read_bytes())
            (inputs / name).chmod(0o600)
        for frame in manifest['frames']:
            if not re.fullmatch(r'frames/frame-[0-9]{3}\.jpg', frame['file']):
                raise ValueError('Input uses an unexpected evidence filename.')
            target = inputs / frame['file']
            target.write_bytes((bundle / frame['file']).read_bytes())
            target.chmod(0o600)
        load_bundle(inputs)
        bundle = inputs
        write_private(output / 'policy.txt', POLICY)
        started = time.monotonic()
        findings, seen = [], set()
        try:
            for index, frames in enumerate(windows):
                remaining = deadline_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError('Local inference exceeded the total time budget.')
                if progress:
                    progress(f'Batch {index + 1}/{len(windows)}: {frames[0]["seconds"]:.1f}–{frames[-1]["seconds"]:.1f} s')
                context = {'trackingPlan': {k: manifest['trackingPlan'][k] for k in ('materials', 'steps', 'policy')},
                           'frames': [{k: f[k] for k in ('id', 'seconds')} for f in frames]}
                prompt = ('Identify the visible actions first, then link useful evidence to the closest declared step. '
                          'Partial action evidence is useful even when the whole step or its quantity cannot be verified. '
                          'For example, turning a control supports an adjustment action without proving an exact setting. '
                          'Do not require verified step completion to report an observation. '
                          'Return at most three concise findings for this window. Seeing equipment alone is not an action. '
                          'Images are supplied in the same order as the frames below. '
                          'Only describe evidence within this batch time range. Return a findings object; no metadata or prose.\n'
                          + json.dumps(context) + '\nJSON schema:\n' + json.dumps(FindingsPayload.model_json_schema()))
                request = {
                    'model': MODEL, 'system': POLICY, 'prompt': prompt,
                    'images': [base64.b64encode((bundle / f['file']).read_bytes()).decode() for f in frames],
                    'format': FindingsPayload.model_json_schema(), 'stream': False,
                    'options': metadata['options'], 'keep_alive': '2m',
                }
                write_private(output / f'request-{index:03d}.json', {
                    **{k: v for k, v in request.items() if k != 'images'}, 'imageFrameIds': [f['id'] for f in frames]})
                raw = bounded_json(client, 'POST', '/api/generate', request, timeout=min(180, remaining))
                write_private(output / f'batch-{index:03d}.json', raw)
                if raw.get('done') is not True or raw.get('done_reason') not in (None, 'stop'):
                    raise ValueError('Model response was incomplete or hit its output budget.')
                parsed = FindingsPayload.model_validate_json(raw['response'])
                selected = {f['id'] for f in frames}
                for finding in parsed.findings:
                    if not set(finding.evidenceFrameIds).issubset(selected):
                        raise ValueError('Model cited a frame outside its request batch.')
                    if not frames[0]['seconds'] <= finding.startSeconds <= finding.endSeconds <= frames[-1]['seconds']:
                        raise ValueError('Model proposed an interval outside its request batch.')
                candidate = {'schemaVersion': 1, **binding, 'inputManifestSha256': manifest_sha,
                             'provider': 'ollama-local', 'model': MODEL, 'responseKind': 'inference',
                             'findings': [f.model_dump() for f in parsed.findings]}
                validate_response(bundle, candidate)
                for finding in candidate['findings']:
                    key = json.dumps(finding, sort_keys=True)
                    if key not in seen:
                        seen.add(key)
                        findings.append(finding)
                metadata['completedBatches'] += 1
                write_private(output / 'run.json', metadata)
            # Refuse a model swap midway through a run.
            if inspect_runtime(client)['modelDigest'] != runtime['modelDigest']:
                raise ValueError('Installed model changed during inference.')
            final = {'schemaVersion': 1, **binding, 'inputManifestSha256': manifest_sha,
                     'provider': 'ollama-local', 'model': MODEL, 'responseKind': 'inference', 'findings': findings}
            validate_response(bundle, final)
            write_private(output / 'response.json', final)
            metadata.update(status='completed', finishedAt=now(), candidateCount=len(findings))
            write_private(output / 'run.json', metadata)
        except BaseException as error:
            metadata.update(status='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed', finishedAt=now())
            write_private(output / 'run.json', metadata)
            raise
        return output

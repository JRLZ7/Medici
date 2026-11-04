"""Two-pass video experiment planning. No inference, network, or record mutations."""
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
from pydantic import Field

from backend.analysis import StrictModel, digest, write_private


class Event(StrictModel):
    startSeconds: float = Field(ge=0)
    endSeconds: float = Field(gt=0)
    label: str = Field(min_length=1, max_length=300)
    uncertainty: str = Field(max_length=500)


class EventPass(StrictModel):
    events: list[Event] = Field(max_length=8)


class ClipObservation(StrictModel):
    startSeconds: float = Field(ge=0)
    endSeconds: float = Field(ge=0)
    action: str = Field(min_length=1, max_length=600)
    visibleLabels: list[str] = Field(max_length=6)
    uncertainty: str = Field(min_length=1, max_length=600)


class ClipPass(StrictModel):
    observations: list[ClipObservation] = Field(max_length=3)


class StepMatch(StrictModel):
    observationId: str
    stepNumber: int | None
    reason: str = Field(min_length=1, max_length=300)


class MatchPass(StrictModel):
    matches: list[StepMatch] = Field(max_length=10)


def parse_json(text, model):
    """Permit only an optional complete code fence, never repair factual output."""
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        lines = text.splitlines()
        if lines[0] in ('```', '```json'):
            text = '\n'.join(lines[1:-1])
    return model.model_validate_json(text)


def validate_events(result, duration):
    for event in result.events:
        if not event.startSeconds < event.endSeconds <= duration or not event.label.strip():
            raise ValueError('Event times must be ordered and within the recording.')
    return result


def covers(intervals, start, end):
    cursor = start
    for a, b in sorted(intervals):
        if b < cursor:
            continue
        if a > cursor + 1e-6:
            return False
        cursor = max(cursor, b)
        if cursor >= end - 1e-6:
            return True
    return False


def clip_plan(events, duration, *, length=8.0, overlap=2.0, padding=1.0):
    if (not math.isfinite(duration) or not 0 < duration <= 90 or
            not 0 <= overlap < length <= 12 or not 0 <= padding <= 3):
        raise ValueError('Use a recording up to 90 seconds and bounded overlapping clips.')
    validate_events(EventPass(events=events), duration)
    result = []

    def add(start, end, origin, event_index=None):
        if end <= start or covers([(c['startSeconds'], c['endSeconds']) for c in result], start, end):
            return
        result.append({'id': f'c{len(result):03d}', 'startSeconds': round(start, 6),
                       'endSeconds': round(end, 6), 'reason': origin, 'eventIndex': event_index})

    # First inspect padded event proposals. Long events are split with overlap.
    for i, event in enumerate(events):
        start = max(0, event.startSeconds - padding)
        end = min(duration, event.endSeconds + padding)
        while start < end - 1e-6:
            add(start, min(start + length, end), 'event-proposal', i)
            if start + length >= end:
                break
            start += length - overlap
    # Coverage is independent of model recall. Empty/missed proposals cannot
    # remove portions of the recording from detailed analysis.
    start = 0.0
    while start < duration - 1e-6:
        add(start, min(start + length, duration), 'coverage-window')
        start += length - overlap
    if len(result) > 24 or not covers([(c['startSeconds'], c['endSeconds']) for c in result], 0, duration):
        raise ValueError('Plan exceeds the clip budget or has a coverage gap.')
    return sorted(result, key=lambda c: (c['startSeconds'], c['endSeconds']))


def absolute_observations(parsed, clip, *, tolerance=0.1):
    duration = clip['endSeconds'] - clip['startSeconds']
    rows = []
    for o in parsed.observations:
        if not 0 <= o.startSeconds <= o.endSeconds <= duration + tolerance:
            raise ValueError('Observation falls outside its source clip.')
        if not o.action.strip() or not o.uncertainty.strip() or any(not label.strip() for label in o.visibleLabels):
            raise ValueError('Observation text cannot be blank.')
        # A documented 0.1-second tolerance handles rounded final timestamps.
        row = o.model_dump()
        row.update(startSeconds=round(clip['startSeconds'] + min(o.startSeconds, duration), 6),
                   endSeconds=round(clip['startSeconds'] + min(o.endSeconds, duration), 6), clipId=clip['id'])
        rows.append(row)
    return rows


def validate_matches(parsed, observations, steps):
    expected = {o['id'] for o in observations}
    ids = [m.observationId for m in parsed.matches]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError('Matching must address each supplied observation exactly once.')
    step_ids = {s['order']: s['id'] for s in steps}
    result = []
    for match in parsed.matches:
        if match.stepNumber is not None and match.stepNumber not in step_ids:
            raise ValueError('Matching references an undeclared procedure step.')
        result.append({**match.model_dump(), 'procedureStepId': step_ids.get(match.stepNumber), 'reviewStatus': 'unreviewed'})
    return result


def render_clip(video, destination, start, end, *, fps, width, height):
    destination = Path(destination)
    if destination.exists() or not 0 <= start < end or not 0 < fps <= 4:
        raise ValueError('Use a new output file and valid bounded clip interval/rate.')
    # Re-encode derived clips, preserving original-video offset separately.
    try:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
            '-protocol_whitelist', 'file,pipe', '-ss', str(start), '-i', str(Path(video).resolve()),
            '-t', str(end-start), '-map', '0:v:0', '-an',
            '-vf', f"fps={fps},scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2",
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart', str(destination)], check=True, capture_output=True, timeout=90)
    except subprocess.SubprocessError:
        raise ValueError('Derived video clip extraction failed or timed out.') from None
    if not destination.exists() or not destination.stat().st_size:
        raise ValueError('No derived video clip was produced.')
    destination.chmod(0o600)
    return digest(destination)


def write_review_report(folder, metadata, events, clips, observations, matches):
    folder = Path(folder)
    lines = ['# Two-pass video experiment', '',
        '**Experimental model output, not verified facts. Nothing was imported into the real experiment.**', '',
        f"Model: {metadata['model']} · native video input through MLX-VLM.",
        f"Original duration: {metadata['durationSeconds']:.2f} s. Overview sampling: 1 fps; detailed clips: 2 fps. Audio excluded.", '',
        'The event pass and clip descriptions received no written procedure, previous observations, or benchmark labels. Procedure matching was a separate text-only pass.', '',
        '## Proposed event intervals', '']
    for event in events:
        lines.append(f'- {event.startSeconds:.1f}–{event.endSeconds:.1f} s: {event.label} ({event.uncertainty or "boundaries approximate"})')
    if not events:
        lines.append('No event intervals proposed; coverage windows still inspected the entire recording.')
    lines += ['', '## Clips and candidate observations', '']
    mapping = {m['observationId']: m for m in matches}
    for clip in clips:
        lines += [f"### {clip['startSeconds']:.1f}–{clip['endSeconds']:.1f} s · {clip['reason']}", '',
                  f"[Play derived clip]({folder / clip['file']})", '']
        rows = [o for o in observations if o['clipId'] == clip['id']]
        for row in rows:
            match = mapping.get(row['id'])
            lines += [f"- **{row['startSeconds']:.1f}–{row['endSeconds']:.1f} s:** {row['action']}",
                      f"  - Visible-label claims: {', '.join(row['visibleLabels']) or 'none'}.",
                      f"  - Uncertainty: {row['uncertainty']}",
                      f"  - Proposed procedure link: {('Step ' + str(match['stepNumber'])) if match and match['stepNumber'] else 'unmatched'}; {match['reason'] if match else 'not assessed'}."]
        if not rows:
            lines.append('No observations proposed for this clip.')
        lines.append('')
    lines += ['## Limits', '',
        'Timestamp boundaries are model estimates. Overlapping clips can produce duplicate observations; candidates are retained rather than silently treated as separate actions. Labels do not establish chemical contents, and setpoints do not establish delivered volume. Sampling may miss brief movements. These results are not a blind evaluation or an accuracy score. Inspect the clips before trusting any description or step link.', '']
    write_private(folder / 'REVIEW.md', '\n'.join(lines))

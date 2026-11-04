import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock3,
  Download,
  Film,
  FlaskConical,
  FolderOpen,
  HardDrive,
  ListChecks,
  LoaderCircle,
  Plus,
  Save,
  ShieldCheck,
  Upload,
  Video,
  X,
} from 'lucide-react';
import './style.css';
import { StepSummary, type StepSummaryRow } from './StepSummary';
import {
  ProtocolDocument,
  ProtocolPreview,
  PROTOCOL_TEMPLATE,
  type Structure,
  type ParseResult,
  type ProtocolStep,
} from './Protocol';

type Procedure = {
  id: string;
  text: string;
  steps: ProtocolStep[];
  createdAt: string;
  structure?: Structure | null;
};
type Observation = {
  id: string;
  startSeconds: number;
  endSeconds: number;
  category: string;
  description: string;
  procedureStepIds: string[];
  evidenceNote: string;
  reviewStatus: string;
  reviewerNote: string;
  procedureVersionId: string;
  updatedAt: string;
  source: string;
  provenanceNote?: string;
  history: unknown[];
};
type Experiment = {
  id: string;
  title: string;
  updatedAt: string;
  procedureVersionId: string;
  procedureVersions: Procedure[];
  datasetSource?: null | {
    name: string;
    recordUrl: string;
    license: string;
    videoFilename: string;
    protocolFilename: string;
    referenceNote: string;
  };
  video: null | {
    originalFilename: string;
    durationSeconds: number;
    sizeBytes: number;
  };
  observations: Observation[];
  stepSummary?: StepSummaryRow[];
  analysisRuns?: {
    id: string;
    model: string;
    modelDigest: string;
    candidateCount: number;
    importedAt: string;
  }[];
};
type Summary = { id: string; title: string; updatedAt: string };
type Draft = {
  startSeconds: string;
  endSeconds: string;
  description: string;
  category: string;
  procedureStepIds: string[];
  evidenceNote: string;
  reviewStatus: string;
  reviewerNote: string;
};
const categories: Record<string, string> = {
  observation: 'Observation',
  potential_deviation: 'Potential deviation',
  unwritten_detail: 'Unwritten detail',
  not_verifiable: 'Not verifiable',
};
const statuses = ['unreviewed', 'confirmed', 'corrected', 'dismissed'];
const time = (n: number) =>
  `${Math.floor(n / 60)
    .toString()
    .padStart(2, '0')}:${(n % 60).toFixed(1).padStart(4, '0')}`;
const date = (s: string) =>
  new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      'X-Medici-Request': '1',
      ...(options?.body && typeof options.body === 'string'
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      typeof payload.detail === 'string'
        ? payload.detail
        : 'Unable to save. Check your input and try again.',
    );
  }
  return response.json();
}

function App() {
  const [experiments, setExperiments] = useState<Summary[]>([]);
  const [active, setActive] = useState<Experiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveState, setSaveState] = useState('All changes saved locally');
  const [creating, setCreating] = useState(false);
  const [editingProcedure, setEditingProcedure] = useState(false);
  const [title, setTitle] = useState('');
  const [procedure, setProcedure] = useState('');
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [parseError, setParseError] = useState('');
  const [editor, setEditor] = useState<Draft | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [selected, setSelected] = useState<string | null>(null);
  const [position, setPosition] = useState(0);
  const [maxUpload, setMaxUpload] = useState(1024 ** 3);
  const [recording, setRecording] = useState(false);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [recorded, setRecorded] = useState<{ blob: Blob; url: string } | null>(
    null,
  );
  const player = useRef<HTMLVideoElement>(null);
  const camera = useRef<HTMLVideoElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const recordingChunks = useRef<Blob[]>([]);
  const currentStream = useRef<MediaStream | null>(null);
  const recordingUrl = useRef<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<Summary[]>('/experiments'),
      api<{ maxUploadBytes: number }>('/health'),
    ])
      .then(([list, health]) => {
        setExperiments(list);
        setMaxUpload(health.maxUploadBytes);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    return () => {
      currentStream.current?.getTracks().forEach((t) => t.stop());
      if (recordingUrl.current) URL.revokeObjectURL(recordingUrl.current);
    };
  }, []);
  useEffect(() => {
    if (camera.current && cameraStream) camera.current.srcObject = cameraStream;
  }, [cameraStream]);
  useEffect(() => {
    const beforeUnload = (e: BeforeUnloadEvent) => {
      if (
        editor ||
        editingProcedure ||
        creating ||
        busy ||
        recording ||
        recorded
      ) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [editor, editingProcedure, creating, busy, recording, recorded]);
  useEffect(() => {
    if (!editor && !creating && !editingProcedure) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const keydown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        setEditor(null);
        setCreating(false);
        setEditingProcedure(false);
      }
      if (e.key !== 'Tab' || !dialog) return;
      const items = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea,select,a[href]',
        ),
      );
      const first = items[0],
        last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('keydown', keydown);
      previous?.focus();
    };
  }, [!!editor, creating, editingProcedure, busy]);

  const update = (experiment: Experiment) => {
    setActive(experiment);
    setExperiments((list) => [
      {
        id: experiment.id,
        title: experiment.title,
        updatedAt: experiment.updatedAt,
      },
      ...list.filter((e) => e.id !== experiment.id),
    ]);
    setSaveState('All changes saved locally');
  };
  async function run(action: () => Promise<void>, propagateError = false) {
    setBusy(true);
    setError('');
    setSaveState('Saving…');
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Something went wrong. Please retry.',
      );
      setSaveState('Not saved — retry');
      if (propagateError) throw e;
    } finally {
      setBusy(false);
    }
  }
  async function open(id: string) {
    setError('');
    setLoading(true);
    try {
      const e = await api<Experiment>(`/experiments/${id}`);
      update(e);
      setSelected(null);
      setPosition(0);
      setFilter('all');
      setCategoryFilter('all');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  const currentProcedure = active?.procedureVersions.find(
    (p) => p.id === active.procedureVersionId,
  );
  useEffect(() => {
    if (!creating && !editingProcedure) return;
    setParseResult(null);
    setParseError('');
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api<ParseResult>('/procedures/parse', {
        method: 'POST',
        body: JSON.stringify({ text: procedure }),
        signal: controller.signal,
      })
        .then(setParseResult)
        .catch((e) => {
          if (!controller.signal.aborted) setParseError(e.message);
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [procedure, creating, editingProcedure]);
  const editingObservation = active?.observations.find(
    (o) => o.id === editingId,
  );
  const editorProcedure = editingObservation
    ? active?.procedureVersions.find(
        (p) => p.id === editingObservation.procedureVersionId,
      )
    : currentProcedure;
  const selectedObservation = active?.observations.find(
    (o) => o.id === selected,
  );
  const selectedProcedure = selectedObservation
    ? active?.procedureVersions.find(
        (p) => p.id === selectedObservation.procedureVersionId,
      )
    : null;
  const locked =
    busy || recording || !!recorded || !!editor || editingProcedure || creating;

  function beginCreate() {
    setTitle('');
    setProcedure('');
    setCreating(true);
    setError('');
  }
  async function saveExperiment(e: React.FormEvent, draft = false) {
    e.preventDefault();
    const unchangedSource =
      !creating &&
      procedure === currentProcedure?.text &&
      currentProcedure?.structure?.status !== 'draft';
    if (!draft && !unchangedSource && !parseResult?.valid) return;
    await run(async () => {
      const result = await api<Experiment>(
        creating ? '/experiments' : `/experiments/${active!.id}`,
        {
          method: creating ? 'POST' : 'PUT',
          body: JSON.stringify({
            title,
            procedure,
            expectedVersionId: active?.procedureVersionId || '',
            procedureFormat: draft ? 'draft' : 'medici-v1',
          }),
        },
      );
      update(result);
      if (draft) setSaveState('Draft saved locally · tracking disabled');
      setCreating(false);
      setEditingProcedure(false);
    });
  }
  async function attachVideo(file: Blob, filename: string) {
    if (!active) return;
    if (file.size > maxUpload) {
      setError(
        `This recording exceeds the ${Math.round(maxUpload / 1024 ** 2)} MB upload limit. Your recording is still available to download.`,
      );
      return;
    }
    await run(async () => {
      update(
        await api<Experiment>(`/experiments/${active.id}/video`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-Filename': encodeURIComponent(filename),
          },
          body: file,
        }),
      );
      clearRecording();
    });
  }
  function seek(observation: Observation) {
    setSelected(observation.id);
    if (player.current) {
      player.current.currentTime = observation.startSeconds;
      player.current.pause();
      setPosition(observation.startSeconds);
    }
  }
  function beginObservation(observation?: Observation) {
    setEditingId(observation?.id || null);
    setEditor(
      observation
        ? {
            ...observation,
            startSeconds: String(observation.startSeconds),
            endSeconds: String(observation.endSeconds),
          }
        : {
            startSeconds: position.toFixed(2),
            endSeconds: position.toFixed(2),
            description: '',
            category: 'observation',
            procedureStepIds: [],
            evidenceNote: '',
            reviewStatus: 'unreviewed',
            reviewerNote: '',
          },
    );
  }
  async function saveObservation(e: React.FormEvent) {
    e.preventDefault();
    if (!editor || !active) return;
    await run(async () => {
      if (
        editingObservation &&
        ['assistant_review', 'local_model'].includes(editingObservation.source)
      ) {
        const health = await api<{
          assistantReviewProvenance?: boolean;
          localModelImport?: boolean;
        }>('/health');
        if (
          !health.assistantReviewProvenance ||
          (editingObservation.source === 'local_model' &&
            !health.localModelImport)
        ) {
          throw new Error(
            'Restart Medici in your terminal (Ctrl+C, then npm start) before reviewing assistant suggestions. Your edits are still here.',
          );
        }
      }
      const {
        startSeconds,
        endSeconds,
        description,
        category,
        procedureStepIds,
        evidenceNote,
        reviewStatus,
        reviewerNote,
      } = editor;
      update(
        await api<Experiment>(
          `/experiments/${active.id}/observations${editingId ? `/${editingId}` : ''}`,
          {
            method: editingId ? 'PUT' : 'POST',
            body: JSON.stringify({
              startSeconds: Number(startSeconds),
              endSeconds: Number(endSeconds),
              description,
              category,
              procedureStepIds,
              evidenceNote,
              reviewStatus,
              reviewerNote,
              expectedUpdatedAt: editingObservation?.updatedAt || '',
              ...(editingObservation?.source === 'assistant_review'
                ? {
                    source: editingObservation.source,
                    provenanceNote: editingObservation.provenanceNote || '',
                  }
                : {}),
            }),
          },
        ),
      );
      setEditor(null);
      setEditingId(null);
    });
  }
  function clearRecording() {
    if (recordingUrl.current) URL.revokeObjectURL(recordingUrl.current);
    recordingUrl.current = null;
    setRecorded(null);
  }
  async function startRecording() {
    setError('');
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === 'undefined'
      )
        throw new Error(
          'Camera recording is unavailable in this browser. Upload an existing video instead.',
        );
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      currentStream.current = stream;
      setCameraStream(stream);
      const mime = ['video/webm;codecs=vp8', 'video/mp4', 'video/webm'].find(
        (m) => MediaRecorder.isTypeSupported(m),
      );
      const rec = new MediaRecorder(
        stream,
        mime ? { mimeType: mime } : undefined,
      );
      recordingChunks.current = [];
      let recordedBytes = 0;
      rec.ondataavailable = (e) => {
        if (e.data.size) {
          recordingChunks.current.push(e.data);
          recordedBytes += e.data.size;
        }
        if (recordedBytes >= maxUpload && rec.state !== 'inactive') {
          setError(
            'Recording stopped at the upload limit. Download it to preserve the footage.',
          );
          rec.stop();
        }
      };
      rec.onstop = () => {
        const blob = new Blob(recordingChunks.current, { type: rec.mimeType });
        const url = URL.createObjectURL(blob);
        recordingUrl.current = url;
        setRecorded({ blob, url });
        stream.getTracks().forEach((t) => t.stop());
        currentStream.current = null;
        setCameraStream(null);
        setRecording(false);
      };
      rec.onerror = () => {
        setError(
          'Recording was interrupted. Download any recovered footage before leaving this page.',
        );
        if (rec.state !== 'inactive') rec.stop();
      };
      stream.getVideoTracks()[0].onended = () => {
        if (rec.state !== 'inactive') rec.stop();
      };
      recorder.current = rec;
      rec.start(1000);
      setRecording(true);
    } catch (e) {
      currentStream.current?.getTracks().forEach((t) => t.stop());
      setCameraStream(null);
      setError((e as Error).message);
    }
  }

  const visible =
    active?.observations
      .filter(
        (o) =>
          (filter === 'all' || o.reviewStatus === filter) &&
          (categoryFilter === 'all' || o.category === categoryFilter),
      )
      .sort((a, b) => a.startSeconds - b.startSeconds) || [];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          href="/"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            if (!locked) setActive(null);
          }}
        >
          <span className="brand-mark">
            <FlaskConical size={23} />
          </span>
          medici<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <button
          className={`nav-item ${!active ? 'active' : ''}`}
          disabled={locked}
          onClick={() => setActive(null)}
        >
          <FolderOpen size={17} /> Experiments <span>{experiments.length}</span>
        </button>
        <div className="sidebar-heading">
          RECENT EXPERIMENTS
          <button
            aria-label="New experiment"
            disabled={locked}
            onClick={beginCreate}
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="recent-list">
          {experiments.slice(0, 12).map((e) => (
            <button
              disabled={locked}
              className={active?.id === e.id ? 'selected' : ''}
              key={e.id}
              onClick={() => open(e.id)}
            >
              <span className="tiny-dot" />
              <span>{e.title}</span>
            </button>
          ))}
          {experiments.length === 0 && (
            <p>Your experiments will appear here.</p>
          )}
        </div>
        <div className="local-card">
          <HardDrive size={19} />
          <div>
            <strong>Local workspace</strong>
            <p>Stored on this computer</p>
          </div>
          <span className="online-dot" />
        </div>
        <div className="sidebar-footer">RECORD. RECOVER. REVIEW.</div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={14} />{' '}
            <strong>{active ? 'Experiment review' : 'Experiments'}</strong>
          </span>
          <span className="privacy">
            <ShieldCheck size={14} /> Local & private
          </span>
        </header>
        {error && (
          <div role="alert" className="error-banner">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError('')}>
              <X size={16} />
            </button>
          </div>
        )}
        {loading ? (
          <div className="loading">
            <LoaderCircle className="spin" /> Loading workspace…
          </div>
        ) : !active ? (
          <div className="overview">
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  THE EXPERIMENT NOTEBOOK, WITH EVIDENCE
                </div>
                <h1>Your experiments</h1>
                <p>A clearer record of what actually happened.</p>
              </div>
              <button
                className="primary"
                disabled={locked}
                onClick={beginCreate}
              >
                <Plus size={17} /> New experiment
              </button>
            </div>
            <div className="intro-card">
              <div>
                <span className="pill">
                  <span className="online-dot" /> MANUAL REVIEW · READY
                </span>
                <h2>
                  Small details.
                  <br />
                  Better understanding.
                </h2>
                <p>
                  Keep your recording, procedure, and observations together.
                  Follow each finding back to the moment it happened.
                </p>
                <button
                  className="text-button"
                  disabled={locked}
                  onClick={beginCreate}
                >
                  Start an experiment <ArrowUpRight size={17} />
                </button>
              </div>
              <div className="evidence-art" aria-hidden="true">
                <div className="art-film">
                  <Film size={34} />
                  <span>THE RECORDING</span>
                  <div className="waveform">
                    {Array.from({ length: 25 }, (_, i) => (
                      <i
                        key={i}
                        style={{ height: `${12 + ((i * 17) % 35)}px` }}
                      />
                    ))}
                  </div>
                </div>
                <div className="art-note">
                  <span className="art-check">
                    <Check size={14} />
                  </span>
                  <div>
                    <strong>Every detail, connected.</strong>
                    <small>Observation → video evidence</small>
                  </div>
                </div>
              </div>
            </div>
            <div className="section-heading">
              <h2>
                Experiment library <span>{experiments.length}</span>
              </h2>
              <span>Saved on this device</span>
            </div>
            {experiments.length ? (
              <div className="experiment-grid">
                {experiments.map((e) => (
                  <button
                    className="experiment-card"
                    key={e.id}
                    onClick={() => open(e.id)}
                  >
                    <span className="experiment-icon">
                      <FlaskConical size={23} />
                    </span>
                    <span className="experiment-title">{e.title}</span>
                    <span className="experiment-meta">
                      Updated {date(e.updatedAt)} <ArrowUpRight size={15} />
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="empty-library">
                <span className="empty-icon">
                  <FolderOpen size={28} />
                </span>
                <h3>A place for your next discovery</h3>
                <p>
                  Create an experiment, add your procedure, and upload a
                  recording.
                  <br />
                  Your observations start with what you can see.
                </p>
                <button className="secondary" onClick={beginCreate}>
                  <Plus size={16} /> Create your first experiment
                </button>
              </div>
            )}
            <div className="honesty-note">
              <ShieldCheck size={17} />
              <p>
                <strong>Evidence first. Always.</strong> Automatic analysis is
                disabled. Review manual findings and explicitly imported local
                model suggestions here.
              </p>
            </div>
          </div>
        ) : (
          <div className="review-page">
            <button
              className="back-button"
              disabled={locked}
              onClick={() => setActive(null)}
            >
              <ArrowLeft size={14} /> All experiments
            </button>
            <div className="review-heading">
              <div>
                <div className="eyebrow">EXPERIMENT WORKSPACE</div>
                <h1>{active.title}</h1>
                <span className="save-status" role="status">
                  <span
                    className={
                      saveState.startsWith('All') ? 'online-dot' : 'pending-dot'
                    }
                  />
                  {busy ? 'Saving…' : saveState}
                </span>
              </div>
              <div className="heading-actions">
                <a
                  className="secondary"
                  href={`/api/experiments/${active.id}/export`}
                >
                  <Download size={15} /> Export record
                </a>
              </div>
            </div>
            {active.datasetSource && (
              <aside
                className="dataset-notice"
                aria-label="Public dataset provenance"
              >
                <strong>Public dataset · {active.datasetSource.name}</strong>
                <p>
                  {active.analysisRuns?.length
                    ? active.datasetSource.referenceNote.replace(
                        'No model analysis has run.',
                        'Imported local model runs are recorded separately below.',
                      )
                    : active.datasetSource.referenceNote}
                </p>
                <p>
                  Source video: {active.datasetSource.videoFilename} · Protocol:{' '}
                  {active.datasetSource.protocolFilename}
                </p>
                <a
                  href={active.datasetSource.recordUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Original dataset ↗
                </a>
                <span> · {active.datasetSource.license}</span>
              </aside>
            )}
            {!!active.analysisRuns?.length && (
              <aside
                className="dataset-notice"
                aria-label="Imported local model runs"
              >
                <strong>
                  Experimental local model suggestions · human review required
                </strong>
                {active.analysisRuns.map((r) => (
                  <p key={r.id}>
                    {r.model} · {r.candidateCount} suggestions · run{' '}
                    {r.id.slice(0, 8)} · model digest{' '}
                    {r.modelDigest.slice(0, 16)}
                  </p>
                ))}
                <p>
                  Sparse sampled frames, no audio or continuous tracking. These
                  runs do not establish step completion.
                </p>
              </aside>
            )}
            <div className="review-columns">
              <div className="video-column">
                <section className="panel video-panel">
                  <div className="panel-heading">
                    <h2>
                      <Video size={16} /> Recording
                    </h2>
                    <span>ORIGINAL FOOTAGE</span>
                  </div>
                  {active.video ? (
                    <>
                      <video
                        key={active.id}
                        ref={player}
                        controls
                        preload="metadata"
                        src={`/api/experiments/${active.id}/video`}
                        onTimeUpdate={(e) =>
                          setPosition(e.currentTarget.currentTime)
                        }
                        onError={() =>
                          setError(
                            'This browser could not play the recording. Download the original or try a supported MP4/WebM codec in a new experiment.',
                          )
                        }
                      />
                      <div className="video-meta">
                        <span>{active.video.originalFilename}</span>
                        <span>
                          {time(active.video.durationSeconds)} ·{' '}
                          {(active.video.sizeBytes / 1024 ** 2).toFixed(1)} MB
                        </span>
                        <a
                          href={`/api/experiments/${active.id}/video?download=true`}
                          aria-label="Download original video"
                        >
                          <Download size={16} />
                        </a>
                      </div>
                    </>
                  ) : (
                    <div className="upload-area">
                      {cameraStream ? (
                        <video
                          className="camera-preview"
                          ref={camera}
                          muted
                          autoPlay
                          playsInline
                        />
                      ) : recorded ? (
                        <video src={recorded.url} controls />
                      ) : (
                        <>
                          <span className="upload-icon">
                            <Film size={30} />
                          </span>
                          <h3>Bring your experiment into focus</h3>
                          <p>
                            Upload a recording to start reviewing the evidence.
                          </p>
                        </>
                      )}
                      {recording ? (
                        <>
                          <button
                            className="danger"
                            onClick={() => recorder.current?.stop()}
                          >
                            Stop recording
                          </button>
                          <p>Recording video only · Keep this tab open</p>
                        </>
                      ) : recorded ? (
                        <>
                          <p>
                            Recording is in memory. Save it or download it
                            before leaving.
                          </p>
                          <div className="upload-buttons">
                            <button
                              className="primary"
                              disabled={busy}
                              onClick={() =>
                                attachVideo(
                                  recorded.blob,
                                  `recording.${recorded.blob.type.includes('mp4') ? 'mp4' : 'webm'}`,
                                )
                              }
                            >
                              <Save size={16} /> Save recording
                            </button>
                            <a
                              className="secondary"
                              href={recorded.url}
                              download={`recording.${recorded.blob.type.includes('mp4') ? 'mp4' : 'webm'}`}
                            >
                              <Download size={16} /> Download
                            </a>
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    'Discard the unsaved recording?',
                                  )
                                )
                                  clearRecording();
                              }}
                            >
                              Discard
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="upload-buttons">
                            <button
                              className="primary"
                              disabled={busy}
                              onClick={() => fileInput.current?.click()}
                            >
                              {busy ? (
                                <LoaderCircle className="spin" size={16} />
                              ) : (
                                <Upload size={16} />
                              )}{' '}
                              Upload video
                            </button>
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={startRecording}
                            >
                              <Video size={16} /> Record
                            </button>
                          </div>
                          <small>
                            MP4, MOV, WebM · up to{' '}
                            {Math.round(maxUpload / 1024 ** 2)} MB
                          </small>
                        </>
                      )}
                      <input
                        ref={fileInput}
                        type="file"
                        accept="video/mp4,video/quicktime,video/webm,.mov"
                        hidden
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) attachVideo(f, f.name);
                          e.target.value = '';
                        }}
                      />
                    </div>
                  )}
                </section>
                <StepSummary
                  rows={active.stepSummary}
                  observations={active.observations}
                  versionId={active.procedureVersionId}
                  structured={
                    currentProcedure?.structure?.status === 'structured'
                  }
                  disabled={locked}
                  historicalCount={
                    active.observations.filter(
                      (o) => o.procedureVersionId !== active.procedureVersionId,
                    ).length
                  }
                  onSeek={(id) => {
                    const o = active.observations.find((o) => o.id === id);
                    if (o) seek(o);
                  }}
                  onReview={(id) => {
                    const o = active.observations.find((o) => o.id === id);
                    if (o) {
                      seek(o);
                      beginObservation(o);
                    }
                  }}
                  onSave={async (id, body) => {
                    await run(
                      async () =>
                        update(
                          await api<Experiment>(
                            `/experiments/${active.id}/step-reviews/${id}`,
                            { method: 'PUT', body: JSON.stringify(body) },
                          ),
                        ),
                      true,
                    );
                  }}
                />
                <section className="panel procedure-panel">
                  <div className="panel-heading">
                    <h2>
                      <ListChecks size={16} /> Written procedure
                    </h2>
                    <button
                      className="text-button"
                      disabled={locked}
                      onClick={() => {
                        setTitle(active.title);
                        setProcedure(currentProcedure?.text || '');
                        setEditingProcedure(true);
                      }}
                    >
                      Edit procedure
                    </button>
                  </div>
                  <div className="procedure-caption">
                    Version {active.procedureVersions.length} ·{' '}
                    {currentProcedure?.structure?.status === 'structured'
                      ? 'Medici v1 · validated syntax'
                      : 'Original text preserved'}
                  </div>
                  <ProtocolDocument
                    procedure={currentProcedure}
                    selectedIds={
                      selectedObservation?.procedureVersionId ===
                      active.procedureVersionId
                        ? selectedObservation.procedureStepIds
                        : []
                    }
                  />
                  {selectedObservation &&
                    selectedObservation.procedureVersionId !==
                      active.procedureVersionId && (
                      <div className="version-note">
                        <strong>
                          This observation references an earlier procedure.
                        </strong>
                        {selectedProcedure?.steps
                          .filter((s) =>
                            selectedObservation.procedureStepIds.includes(s.id),
                          )
                          .map((s) => (
                            <p key={s.id}>
                              {selectedProcedure?.structure?.status ===
                              'structured'
                                ? 'Step'
                                : 'Historical reference'}{' '}
                              {s.order}: {s.text}
                            </p>
                          ))}
                      </div>
                    )}
                </section>
              </div>
              <section className="panel observations-panel">
                <div className="panel-heading">
                  <h2>
                    <Clock3 size={16} /> Observation timeline{' '}
                    <span className="count">{active.observations.length}</span>
                  </h2>
                  <button
                    className="add-button"
                    disabled={!active.video || locked}
                    onClick={() => beginObservation()}
                  >
                    <Plus size={15} /> Add observation
                  </button>
                </div>
                <div className="timeline-note">
                  Click a timestamp to inspect the evidence.
                </div>
                <div className="filters">
                  <select
                    aria-label="Filter by review status"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">All review statuses</option>
                    {statuses.map((s) => (
                      <option key={s} value={s}>
                        {s[0].toUpperCase() + s.slice(1)}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Filter by category"
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                  >
                    <option value="all">All categories</option>
                    {Object.entries(categories).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="timeline">
                  {visible.length ? (
                    visible.map((o) => (
                      <article
                        className={`observation ${selected === o.id ? 'focused' : ''} ${o.reviewStatus === 'dismissed' ? 'dismissed' : ''}`}
                        key={o.id}
                      >
                        <div className="observation-top">
                          <button className="timestamp" onClick={() => seek(o)}>
                            <Clock3 size={12} />
                            {time(o.startSeconds)} – {time(o.endSeconds)}
                          </button>
                          <span className={`status ${o.reviewStatus}`}>
                            {o.reviewStatus}
                          </span>
                        </div>
                        <span className={`category ${o.category}`}>
                          {categories[o.category]}
                        </span>
                        <p className="observation-description">
                          {o.description}
                        </p>
                        {o.evidenceNote && (
                          <p className="evidence-note">
                            Evidence: {o.evidenceNote}
                          </p>
                        )}
                        {o.procedureStepIds.length > 0 && (
                          <p className="step-links">
                            {active.procedureVersions
                              .find((p) => p.id === o.procedureVersionId)
                              ?.steps.filter((s) =>
                                o.procedureStepIds.includes(s.id),
                              )
                              .map((s) => `Step ${s.order}`)
                              .join(' · ')}
                            {o.procedureVersionId !== active.procedureVersionId
                              ? ' · Earlier procedure'
                              : ''}
                          </p>
                        )}
                        {o.reviewerNote && (
                          <p className="evidence-note">
                            Reviewer: {o.reviewerNote}
                          </p>
                        )}
                        {o.provenanceNote && (
                          <p className="evidence-note">
                            Source: {o.provenanceNote}
                          </p>
                        )}
                        <div className="observation-footer">
                          <span>
                            {o.source === 'local_model'
                              ? 'Local model suggestion'
                              : o.source === 'assistant_review'
                                ? 'Assistant-prepared suggestion'
                                : 'Added manually'}
                            {o.history.length > 0
                              ? ` · ${o.history.length} revision${o.history.length === 1 ? '' : 's'}`
                              : ''}
                          </span>
                          <button
                            className="text-button"
                            disabled={locked}
                            onClick={() => {
                              seek(o);
                              beginObservation(o);
                            }}
                          >
                            Review / edit <ArrowUpRight size={13} />
                          </button>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-timeline">
                      <span className="empty-icon">
                        <Clock3 size={25} />
                      </span>
                      <h3>
                        {active.observations.length
                          ? 'No matching observations'
                          : 'The details start here'}
                      </h3>
                      <p>
                        {active.video
                          ? 'Pause at an interesting moment and add an observation. Link it to a step when relevant.'
                          : 'Add a recording, then document what you can see. Your timeline begins empty.'}
                      </p>
                      {!!active.video && !active.observations.length && (
                        <button
                          className="text-button"
                          disabled={locked}
                          onClick={() => beginObservation()}
                        >
                          <Plus size={15} /> Add your first observation
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="analysis-off">
                  <ShieldCheck size={16} />
                  <div>
                    <strong>You are the reviewer</strong>
                    <p>
                      Automatic analysis is disabled. Imported local model
                      suggestions require your review.
                    </p>
                  </div>
                </div>
              </section>
            </div>
            <p className="export-note">
              Record exports include procedure versions and review history.
              Media is downloaded separately. Record reimport is not yet
              supported.
            </p>
          </div>
        )}
      </main>
      {(creating || editingProcedure) && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="experiment-modal-title"
          >
            <form onSubmit={saveExperiment}>
              <div className="modal-heading">
                <h2 id="experiment-modal-title">
                  {creating ? 'New experiment' : 'Edit experiment & procedure'}
                </h2>
                <button
                  type="button"
                  aria-label="Close editor"
                  disabled={busy}
                  onClick={() => {
                    setCreating(false);
                    setEditingProcedure(false);
                  }}
                >
                  <X size={19} />
                </button>
              </div>
              <p className="modal-intro">
                Start with what you plan to do. The recording captures what
                happens.
              </p>
              <label>
                Experiment title
                <input
                  autoFocus
                  required
                  maxLength={200}
                  value={title}
                  placeholder="e.g. Mixing rate and reaction time"
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>
              <label>
                Written procedure
                <textarea
                  rows={9}
                  maxLength={100000}
                  value={procedure}
                  placeholder={PROTOCOL_TEMPLATE}
                  onChange={(e) => setProcedure(e.target.value)}
                />
              </label>
              <p className="field-note">
                Required: Materials declarations and consecutive numbered
                Procedure steps. Use @id to reference materials. Changes create
                a new version and preserve historical observation links. Leave
                empty to save a draft without tracking scope.
              </p>
              <details className="syntax-guide">
                <summary>Syntax rules & example</summary>
                <p>
                  Materials:{' '}
                  <code>
                    - @id | equipment/reagent/sample | name |
                    label/appearance/unverifiable: cue
                  </code>
                  . Appearance cues are allowed only for equipment. Steps start
                  at 1. and reference declared @ids. Indent Detail: or Expect:
                  by two spaces. Optional sections: Purpose, Notes, Expected
                  results. Notes never become extra steps.
                </p>
                <pre>{PROTOCOL_TEMPLATE}</pre>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    if (
                      !procedure.trim() ||
                      window.confirm(
                        'Replace the current editor text with the syntax example? Saved versions remain preserved.',
                      )
                    )
                      setProcedure(PROTOCOL_TEMPLATE);
                  }}
                >
                  Use this example
                </button>
              </details>
              <ProtocolPreview result={parseResult} error={parseError} />
              <p className="field-note">
                Save draft preserves this text even with syntax errors and
                disables its tracking plan. Save changes requires valid syntax.
              </p>
              <div className="modal-actions">
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setCreating(false);
                    setEditingProcedure(false);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || !title.trim()}
                  onClick={(e) => saveExperiment(e, true)}
                >
                  <Save size={16} /> Save draft
                </button>
                <button
                  className="primary"
                  disabled={
                    busy ||
                    !title.trim() ||
                    (!parseResult?.valid &&
                      (creating ||
                        procedure !== currentProcedure?.text ||
                        currentProcedure?.structure?.status === 'draft'))
                  }
                >
                  <Save size={16} />
                  {busy
                    ? 'Saving…'
                    : creating
                      ? 'Create experiment'
                      : 'Save changes'}
                </button>
              </div>
              {error && (
                <p role="alert" className="inline-error">
                  {error}
                </p>
              )}
            </form>
          </section>
        </div>
      )}
      {editor && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="observation-modal-title"
          >
            <form onSubmit={saveObservation}>
              <div className="modal-heading">
                <h2 id="observation-modal-title">
                  {editingId ? 'Review observation' : 'Add observation'}
                </h2>
                <button
                  type="button"
                  aria-label="Close editor"
                  disabled={busy}
                  onClick={() => setEditor(null)}
                >
                  <X size={19} />
                </button>
              </div>
              <p className="modal-intro">
                Describe visible evidence. Keep interpretations and uncertainty
                explicit.
              </p>
              <div className="form-row">
                <label>
                  Start (seconds)
                  <input
                    type="number"
                    required
                    min="0"
                    max={active?.video?.durationSeconds}
                    step="any"
                    value={editor.startSeconds}
                    onChange={(e) =>
                      setEditor({ ...editor, startSeconds: e.target.value })
                    }
                  />
                </label>
                <label>
                  End (seconds)
                  <input
                    type="number"
                    required
                    min={Number(editor.startSeconds) || 0}
                    max={active?.video?.durationSeconds}
                    step="any"
                    value={editor.endSeconds}
                    onChange={(e) =>
                      setEditor({ ...editor, endSeconds: e.target.value })
                    }
                  />
                </label>
              </div>
              <label>
                Category
                <select
                  value={editor.category}
                  onChange={(e) =>
                    setEditor({ ...editor, category: e.target.value })
                  }
                >
                  {Object.entries(categories).map(([k, v]) => (
                    <option value={k} key={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Description
                <textarea
                  autoFocus
                  required
                  rows={3}
                  maxLength={10000}
                  value={editor.description}
                  placeholder="What is visible during this interval?"
                  onChange={(e) =>
                    setEditor({ ...editor, description: e.target.value })
                  }
                />
              </label>
              <fieldset>
                <legend>
                  Link procedure steps
                  {editingObservation?.procedureVersionId !==
                    active?.procedureVersionId && editingId
                    ? ' · original version'
                    : ''}
                </legend>
                {editorProcedure?.steps.length &&
                (editorProcedure.structure?.status === 'structured' ||
                  editingId) ? (
                  editorProcedure.steps
                    .filter(
                      (s) =>
                        editorProcedure.structure?.status === 'structured' ||
                        editingObservation?.procedureStepIds.includes(s.id),
                    )
                    .map((s) => (
                      <label className="checkbox-label" key={s.id}>
                        <input
                          type="checkbox"
                          checked={editor.procedureStepIds.includes(s.id)}
                          onChange={(e) =>
                            setEditor({
                              ...editor,
                              procedureStepIds: e.target.checked
                                ? [...editor.procedureStepIds, s.id]
                                : editor.procedureStepIds.filter(
                                    (id) => id !== s.id,
                                  ),
                            })
                          }
                        />
                        <span>
                          {editorProcedure.structure?.status === 'structured'
                            ? ''
                            : 'Historical reference '}
                          {s.order}. {s.text}
                        </span>
                      </label>
                    ))
                ) : (
                  <p className="field-note">
                    Save a valid Medici v1 procedure to enable step links.
                    Original source lines are not treated as steps.
                  </p>
                )}
              </fieldset>
              <label>
                Evidence note{' '}
                {editor.category === 'potential_deviation'
                  ? '(required)'
                  : '(optional)'}
                <textarea
                  rows={2}
                  required={editor.category === 'potential_deviation'}
                  maxLength={10000}
                  value={editor.evidenceNote}
                  onChange={(e) =>
                    setEditor({ ...editor, evidenceNote: e.target.value })
                  }
                />
              </label>
              <div className="form-row">
                <label>
                  Review status
                  <select
                    value={editor.reviewStatus}
                    onChange={(e) =>
                      setEditor({ ...editor, reviewStatus: e.target.value })
                    }
                  >
                    {statuses.map((s) => (
                      <option value={s} key={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Reviewer note
                  <input
                    maxLength={10000}
                    value={editor.reviewerNote}
                    onChange={(e) =>
                      setEditor({ ...editor, reviewerNote: e.target.value })
                    }
                  />
                </label>
              </div>
              <p className="field-note">
                A deviation needs a linked step and evidence note. An unseen
                action is not proof that it was skipped.
              </p>
              <div className="modal-actions">
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => setEditor(null)}
                >
                  Cancel
                </button>
                <button
                  className="primary"
                  disabled={busy || !editor.description.trim()}
                >
                  <Save size={16} />
                  {busy ? 'Saving…' : 'Save observation'}
                </button>
              </div>
              {error && (
                <p role="alert" className="inline-error">
                  {error}
                </p>
              )}
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

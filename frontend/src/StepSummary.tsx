import { useState } from 'react';
import { ListChecks } from 'lucide-react';

type Conclusion = 'supported' | 'potential_deviation' | 'not_verifiable';
export type StepReview = {
  conclusion: Conclusion;
  note: string;
  updatedAt: string;
};
export type StepSummaryRow = {
  stepId: string;
  order: number;
  text: string;
  evidenceIds: string[];
  dismissedCount: number;
  unreviewedCount: number;
  potentialDeviationCount: number;
  notVerifiableCount: number;
  evidenceFingerprint: string;
  conclusion: Conclusion | 'unassessed';
  reviewStatus: 'awaiting_review' | 'reviewed' | 'needs_review';
  review: StepReview | null;
};
type Evidence = {
  id: string;
  startSeconds: number;
  endSeconds: number;
  description: string;
  category: string;
  reviewStatus: string;
};
export type StepReviewBody = {
  procedureVersionId: string;
  conclusion: Conclusion;
  note: string;
  expectedEvidenceFingerprint: string;
  expectedUpdatedAt: string;
};
const conclusions = {
  unassessed: 'Unassessed',
  supported: 'Supported',
  potential_deviation: 'Potential deviation',
  not_verifiable: 'Not verifiable',
};
const statuses = {
  awaiting_review: 'Awaiting review',
  reviewed: 'Reviewed by you',
  needs_review: 'Evidence changed · review again',
};
const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toFixed(1).padStart(4, '0')}`;

function StepRow({
  row,
  evidence,
  versionId,
  disabled,
  onSeek,
  onReview,
  onSave,
}: {
  row: StepSummaryRow;
  evidence: Evidence[];
  versionId: string;
  disabled: boolean;
  onSeek: (id: string) => void;
  onReview: (id: string) => void;
  onSave: (id: string, body: StepReviewBody) => Promise<void>;
}) {
  const [conclusion, setConclusion] = useState<Conclusion>(
    row.review?.conclusion || 'not_verifiable',
  );
  const [note, setNote] = useState(row.review?.note || '');
  const [saveError, setSaveError] = useState('');
  const canSupport = evidence.some(
    (o) =>
      ['confirmed', 'corrected'].includes(o.reviewStatus) &&
      ['observation', 'unwritten_detail'].includes(o.category),
  );
  const supportBlocked = conclusion === 'supported' && !canSupport;
  return (
    <details className="step-summary-row">
      <summary>
        <span className="step-summary-number">{row.order}</span>
        <span className="step-summary-title">
          {row.text}
          <span className="step-summary-meta">
            {evidence.length
              ? `${evidence.length} linked finding${evidence.length === 1 ? '' : 's'}`
              : 'No active evidence'}
            {' · '}
            {statuses[row.reviewStatus]}
            {!!row.potentialDeviationCount && ' · Deviation flagged'}
            {!!row.notVerifiableCount && ' · Uncertainty recorded'}
          </span>
        </span>
        <span
          className={`step-conclusion ${row.reviewStatus === 'needs_review' ? 'stale' : row.conclusion}`}
        >
          {row.reviewStatus === 'needs_review'
            ? `Previous: ${conclusions[row.conclusion]}`
            : conclusions[row.conclusion]}
        </span>
      </summary>
      <div className="step-summary-body">
        <h3>Evidence</h3>
        {!evidence.length && (
          <p>
            No active findings link to this step. This does not establish that
            it was omitted.
          </p>
        )}
        {evidence.map((o) => (
          <div className="step-evidence" key={o.id}>
            <button
              type="button"
              className="text-button"
              disabled={disabled}
              onClick={() => onSeek(o.id)}
            >
              {time(o.startSeconds)} – {time(o.endSeconds)}
            </button>
            <span>
              {o.category.replaceAll('_', ' ')} · {o.reviewStatus}
            </span>
            <p>{o.description}</p>
            <button
              type="button"
              className="text-button"
              disabled={disabled}
              onClick={() => onReview(o.id)}
            >
              Review finding
            </button>
          </div>
        ))}
        {!!row.dismissedCount && (
          <p>
            {row.dismissedCount} dismissed finding(s) excluded. They remain in
            the timeline and export.
          </p>
        )}
        {!!row.unreviewedCount && (
          <p className="step-caution">
            {row.unreviewedCount} linked suggestion(s) still await observation
            review.
          </p>
        )}
        {!!row.potentialDeviationCount && (
          <p className="step-caution">
            Linked evidence flags a potential deviation; it does not establish
            an error.
          </p>
        )}
        {!!row.notVerifiableCount && (
          <p>Some linked evidence explicitly records uncertainty.</p>
        )}
        {row.reviewStatus === 'needs_review' && (
          <p className="step-caution">
            Evidence changed after this conclusion was saved. Reassess it before
            relying on the previous conclusion.
          </p>
        )}
        {row.review && (
          <p className="saved-step-note">
            <strong>Saved rationale:</strong> {row.review.note}
          </p>
        )}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setSaveError('');
            if (supportBlocked) return;
            try {
              await onSave(row.stepId, {
                procedureVersionId: versionId,
                conclusion,
                note,
                expectedEvidenceFingerprint: row.evidenceFingerprint,
                expectedUpdatedAt: row.review?.updatedAt || '',
              });
            } catch (error) {
              setSaveError(
                error instanceof Error
                  ? error.message
                  : 'Unable to save this conclusion. Please retry.',
              );
            }
          }}
        >
          <label>
            Step {row.order} conclusion
            <select
              value={conclusion}
              disabled={disabled}
              onChange={(e) => {
                setConclusion(e.target.value as Conclusion);
                setSaveError('');
              }}
              aria-describedby={
                supportBlocked ? `step-support-${row.stepId}` : undefined
              }
            >
              <option value="not_verifiable">Not verifiable</option>
              <option value="potential_deviation">Potential deviation</option>
              <option value="supported">Supported</option>
            </select>
          </label>
          {supportBlocked && (
            <p
              className="step-caution"
              role="alert"
              id={`step-support-${row.stepId}`}
            >
              Supported cannot be saved yet: this step has no confirmed or
              corrected action observation. Use Review finding to check its
              evidence. Confirming a “Not verifiable” finding does not establish
              that the action happened. If the recording does not show the
              action, choose Not verifiable and explain why.
            </p>
          )}
          <label>
            Step {row.order} rationale and limits
            <textarea
              value={note}
              maxLength={10000}
              required
              disabled={disabled}
              rows={3}
              placeholder="Explain what the evidence supports and what remains uncertain."
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <p>
            “Supported” is your assessment of the whole step, including its
            stated quantities and expectations. First confirm or correct
            supporting observations. An observed action alone does not verify
            completion.
          </p>
          <button
            className="secondary"
            disabled={disabled || !note.trim() || supportBlocked}
            type="submit"
          >
            Save step conclusion
          </button>
          {saveError && (
            <p className="step-caution" role="alert">
              Not saved: {saveError}
            </p>
          )}
        </form>
      </div>
    </details>
  );
}

export function StepSummary({
  rows,
  observations,
  versionId,
  structured,
  disabled,
  historicalCount,
  onSeek,
  onReview,
  onSave,
}: {
  rows?: StepSummaryRow[];
  observations: Evidence[];
  versionId: string;
  structured: boolean;
  disabled: boolean;
  historicalCount: number;
  onSeek: (id: string) => void;
  onReview: (id: string) => void;
  onSave: (id: string, body: StepReviewBody) => Promise<void>;
}) {
  const reviewed =
    rows?.filter((s) => s.reviewStatus === 'reviewed').length || 0;
  return (
    <section
      className="panel step-summary-panel"
      aria-label="Per-step review summary"
    >
      <div className="panel-heading">
        <h2>
          <ListChecks size={16} /> Per-step review
        </h2>
        <span>CURRENT PROCEDURE</span>
      </div>
      <div className="step-summary-intro">
        <p>
          Evidence, conclusions, and review status are separate. Findings never
          automatically mark a step supported.
        </p>
        {!structured ? (
          <p>
            Save a valid structured procedure to review its steps. Earlier
            findings remain in the timeline.
          </p>
        ) : !rows ? (
          <p>
            Restart Medici in your terminal (Ctrl+C, then npm start) and reopen
            this experiment to load step summaries.
          </p>
        ) : (
          <p>
            <strong>
              {reviewed} of {rows.length} step conclusions reviewed
            </strong>{' '}
            · This is review progress, not a compliance score.
          </p>
        )}
        {!!historicalCount && (
          <p>
            {historicalCount} finding(s) belong to earlier procedures and are
            excluded from this summary. Their conclusions remain in the record
            export.
          </p>
        )}
      </div>
      {structured &&
        rows?.map((row) => (
          <StepRow
            key={`${row.stepId}:${row.review?.updatedAt || ''}`}
            row={row}
            evidence={observations
              .filter((o) => row.evidenceIds.includes(o.id))
              .sort((a, b) => a.startSeconds - b.startSeconds)}
            versionId={versionId}
            disabled={disabled}
            onSeek={onSeek}
            onReview={onReview}
            onSave={onSave}
          />
        ))}
    </section>
  );
}

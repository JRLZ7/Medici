# Project decisions and deferred ideas

## Deferred: LLM-assisted procedure formatting

Jason requested retaining this idea for future work: accept a natural protocol or pasted document and propose a conversion into Medici's required materials/numbered-step syntax. Do not implement or enable it yet.

- Treat this as a formatting assistant, separate from video analysis.
- Preserve the source document and show a reviewable conversion before submission.
- Validate the result with the existing deterministic parser.
- Do not invent materials, identity cues, quantities, expectations, or missing actions. Mark unresolved fields for the user.
- Keep inference disabled until explicitly enabled. Meta credits remain unconfirmed; do not substitute a paid provider or upload footage implicitly.

## Zenodo review pass completed, human confirmation pending

Jason authorized this pass on 2026-10-31. His already formatted procedure was preserved. Experiment `538a1433-9d30-439d-8ebc-0055e33f28ab` now has 11 unreviewed, explicitly assistant-prepared suggestions: 4 observations, 2 label-based container order mismatch candidates (steps 4/8), and 5 not-verifiable entries. Review used sampled images, no audio or inference job. Benchmark labels were known beforehand; this is not a blind accuracy evaluation. Their omission labels for steps 10/11 were not promoted to observed facts. Private report/export/evidence are in the actual repository's ignored `data/reviews/zenodo-dilution/` folder. Save/reopen/export and unchanged original checksums/procedure history were verified.

Assistant suggestions preserve provenance and original proposals on human correction. The backend running before this change must be restarted once from Jason's terminal before editing them; the frontend guards against saving to that older backend.

Potential follow-up: version-bound material links on observations, a per-step evidence review summary with explicit uncertainty, then a restorable record-and-media backup/import workflow.

The main app is run by Jason from his terminal on port 8000. Avoid leaving a second background instance on that port or handing off a stopped temporary preview as the working app.

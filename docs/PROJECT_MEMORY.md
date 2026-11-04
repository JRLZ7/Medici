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

Implemented 2026-11-04: per-step evidence review summary for the current structured procedure. Conclusions are explicit human assessments with rationale, independent of observation review status. No finding automatically supports a step; supported assessments require reviewed action evidence. Dismissed findings are excluded, old versions remain separate, and evidence changes flag previous assessments as needing review. Conclusions/history persist in schema v4 and JSON exports. UI save/seek was checked on an isolated database copy; no conclusions were added to Jason's actual experiment.

Potential follow-up: restorable record-and-media backup/import workflow, then a second human-reviewed recording and evaluation checklist before experimental model integration. Version-bound material links on observations remain a later option.

Jason asked to move past the confusing review UI and get closer to model integration. On 2026-11-04 added offline input preparation, a provider-independent candidate schema, checksum/version/time/scope/frame validation, and a partial reviewed-anchor evaluation checker. Actual Zenodo footage was prepared into 30 private frames and a clearly synthetic fixture exercised the pipeline. No inference ran, no suggestions were imported, and real records were unchanged. Snapshot had two confirmed/corrected anchors. Do not report fixture match counts as model performance. See MODEL_INTEGRATION.md. Next priority is selecting a local vision runtime/model, connecting a disabled-by-default adapter, and version-safe unreviewed proposal import. Backup/restore remains deferred; do not keep expanding the review UI first.

The main app is run by Jason from his terminal on port 8000. Avoid leaving a second background instance on that port or handing off a stopped temporary preview as the working app.

Local adapter integration, 2026-11-04: Homebrew Ollama 0.34.2 installed, with qwen3-vl:4b-instruct (~3.3 GB) in actual repo data/ollama/models/. Mac is arm64 with 24 GB RAM. Agent-started runtime used loopback and OLLAMA_NO_CLOUD=1; no login service was installed. Adapter explicitly gated by --enable-local-inference, batches at most 6 sparse frames, validates schema/bindings/evidence, records private raw responses and model digest, and never pulls models itself. API import accepts completed local inference runs, preserves provenance/originals, is idempotent, and rejects stale/fixture/incomplete output. Additive schema v5 stores imported run history; UI distinguishes local_model suggestions. A real partial run 531dd0e0-3869-4a16-b2b3-55850ba88904 produced 3 candidates around 20–30 s, but semantic step matching and some visual/label claims were poor. Imported ONLY into isolated QA copy, NOT the real experiment. Earlier overly conservative run 599b73bd-5fc8-466f-856c-11a368f68293 cancelled after 4 empty batches. Source artifacts/qualitative report in data/analysis/runs/. Next priority is improving action extraction, step matching, and close-up evidence before trusting/importing generated suggestions. Runtime/QA processes stopped at handoff; user owns regular app server.

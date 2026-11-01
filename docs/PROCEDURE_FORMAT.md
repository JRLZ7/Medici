# Medici procedure format v1

A submitted procedure is a declared review scope. Medici parses this format deterministically, without a model. It does not infer entities, quantities, actions, or scientific meaning from prose. Empty procedures can be saved as drafts, but have no tracking plan.

## Example

```text
# Water transfer

## Purpose
Review the visible transfer and mixing actions.

## Materials
- @cup-a | equipment | Cup A | label: A
- @cup-b | equipment | Cup B | label: B
- @water | reagent | Water | label: WATER on the source container
- @spoon | equipment | Spoon | appearance: metal spoon

## Procedure
1. Pour @water from @cup-a into @cup-b.
  Detail: Keep both cup labels visible to the camera.
  Expect: @water is transferred into @cup-b.
2. Stir the contents of @cup-b with @spoon for five complete circles.
  Expect: Five stirring circles are visible.

## Notes
A declared label still needs to be readable in the recording.

## Expected results
The transfer and stirring can be reviewed from the recording.
```

## Syntax rules

- Optional title: one `# Title` before all sections.
- Required sections, exact spelling/capitalization: `## Materials` and `## Procedure`.
- Optional sections: `## Purpose`, `## Notes`, `## Expected results`. Sections cannot repeat. Unknown headings and content outside sections are errors.
- Material entries have four fields: `- @id | kind | name | cue-type: cue`. Spaces around `|` and `:` are flexible; copied nonbreaking spaces and `-`, `*`, or `•` list bullets are accepted. A complete outer Markdown code fence is also accepted when pasting from a chat. Original text and line numbers are preserved.
- IDs begin with a lowercase letter, contain lowercase letters/numbers/hyphens, and are at most 40 characters. IDs must be unique within the procedure version. `@` is reserved for references, and `|` separates material fields.
- Material kinds: `equipment`, `reagent`, `sample`.
- Cue types: `label`, `appearance`, `unverifiable`. Appearance is allowed only for equipment. Reagents/samples require a declared label cue or an explicit reason their identity is unverifiable. Names and cues cannot be empty.
- Numbered steps must start at `1.` and be consecutive. Each step occupies one source line and must contain at least one declared `@id`. The editor wraps long lines visually without introducing source newlines.
- `  Detail: text` and `  Expect: text` attach to the preceding step, using exactly two leading spaces. They do not receive step numbers. Multiple entries are allowed.
- Every reference must be declared, including references inside notes/details. An `Expect:` entry can reference only materials named in its parent step.
- No more than 200 materials, 1,000 steps, or 100,000 characters. Invalid input returns line-specific errors and cannot create a partial protocol or partial tracking plan.

## What becomes a tracking target

The server builds and exports a versioned tracking plan containing:

1. Materials explicitly referenced in numbered steps, with declared identity cues.
2. Numbered steps, each with a stable stored step ID and explicit material references.
3. Explicit `Expect:` entries attached to those steps.

Titles, materials-list headings, purpose, general notes, `Detail:` entries, and expected-results prose are preserved as context but never silently become extra actions or tracking targets. Unused materials remain visible in the materials section and are marked "Not targeted". Ordinary words in prose are not automatically extracted as additional material identities; use `@id` for a material that should be part of tracking scope.

An `unverifiable:` material remains a declared reference with `identityVerifiable: false`; it does not authorize chemical or sample identification. Even a label-based identity is only an expectation until the recording supplies readable evidence. A visible container is not proof of its contents. Expected amounts/times in the procedure are not observed measurements, and unseen actions are not automatically omissions.

Manual observations of unexpected events remain available. They do not expand the automatic tracking plan. Future analysis must consume the saved parsed plan, pin it to the procedure version/source hash, reject unknown target IDs, and preserve uncertainty. **This change does not enable any model or active video tracking.**

## Preview, storage, and existing records

The editor requests a local parse preview, shows materials and actual steps separately, and disables **Save changes** for changed invalid procedures. **Save draft** preserves text even when syntax is invalid; it explicitly disables tracking for that version. The backend independently validates normal submissions. Original source text is preserved exactly alongside the parsed structure; edits create new versions with new IDs. Exports include the parsed structure and the current tracking plan. A valid draft can be promoted with Save changes without editing its text again.

Malformed declarations produce targeted messages about the offending fields. References to a material with an already-reported declaration error are not repeated as additional undeclared-material errors. Truly undeclared IDs are reported once at their first use.

Existing line-based procedures are not automatically reinterpreted or relinked. They display as source documents with tracking scope undefined until the user submits a valid new version. Their historical step IDs and observation links are retained; new observations cannot link to unvalidated source lines. Renaming an experiment without changing its original procedure remains possible.

Dataset importers can explicitly preserve a raw source document using `procedureFormat: "source-document"` with dataset provenance. These imports have no parsed steps or tracking scope. They are not an alternate path for creating an automatic plan from invalid syntax.

## Local API

- `POST /api/procedures/parse`, body `{"text": "..."}`: returns `valid`, line-numbered `errors`, and a structured `document` only if valid. Requires the normal local write header.
- `GET /api/experiments/{id}/tracking-plan`: returns the current declared plan or `available: false`. `analysisEnabled` remains false.
- Normal experiment create/update defaults to `procedureFormat: "medici-v1"`. Explicit `procedureFormat: "draft"` stores raw text with tracking disabled, even when it is not valid procedure syntax.

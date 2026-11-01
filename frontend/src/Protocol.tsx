export type Entry = { text: string; sourceLine: number };
export type Material = {
  key: string;
  kind: string;
  name: string;
  cueType: string;
  cue: string;
  identityVerifiable: boolean;
  sourceLine: number;
};
export type ProtocolStep = {
  id: string;
  order: number;
  text: string;
  materialKeys?: string[];
  details?: Entry[];
  expectations?: Entry[];
  sourceLine?: number;
};
export type Structure = {
  formatVersion: number;
  status: string;
  title?: string;
  materials: Material[];
  steps: ProtocolStep[];
  sections: Record<string, Entry[]>;
};
export type ParseResult = {
  valid: boolean;
  errors: { line: number; message: string }[];
  document: Structure | null;
};

export const PROTOCOL_TEMPLATE = `# Water transfer

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
The transfer and stirring can be reviewed from the recording.`;

function References({ text }: { text: string }) {
  return (
    <>
      {text.split(/(@[a-z][a-z0-9-]*)/g).map((part, i) =>
        part.startsWith('@') ? (
          <code className="material-ref" key={i}>
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

export function ProtocolDocument({
  procedure,
  selectedIds = [],
}: {
  procedure?: {
    text: string;
    structure?: Structure | null;
    steps: ProtocolStep[];
  };
  selectedIds?: string[];
}) {
  const doc = procedure?.structure;
  if (!doc || doc.status !== 'structured')
    return (
      <div className="source-procedure">
        <div className="scope-warning">
          <strong>
            {doc?.status === 'draft'
              ? 'Procedure draft · tracking disabled'
              : procedure?.text
                ? 'Source document · tracking scope undefined'
                : 'Procedure draft'}
          </strong>
          <p>
            {doc?.status === 'draft'
              ? 'Your text is saved. Fix the syntax and use Save changes to define tracking scope.'
              : procedure?.text
                ? 'Original text is preserved. Edit it into Medici v1 syntax to declare materials and actual steps. Historical observation links remain intact.'
                : 'Add Materials and Procedure sections to define what can be reviewed.'}
          </p>
        </div>
        {!!procedure?.text && <pre>{procedure.text}</pre>}
      </div>
    );
  const used = new Set(procedure?.steps.flatMap((s) => s.materialKeys || []));
  return (
    <div className="structured-procedure">
      <div className="scope-summary">
        <strong>Tracking scope defined</strong>
        <p>
          {used.size} referenced materials · {procedure?.steps.length} explicit
          steps · AI disabled
        </p>
        <small>
          Identity cues and expected quantities must be verified in footage.
        </small>
      </div>
      {doc.title && <h3 className="protocol-title">{doc.title}</h3>}
      {!!doc.sections.Purpose?.length && (
        <section className="protocol-prose">
          <h3>Purpose</h3>
          {doc.sections.Purpose.map((e, i) => (
            <p key={i}>{e.text}</p>
          ))}
        </section>
      )}
      <section className="materials-section">
        <h3>
          Materials <span>{doc.materials.length}</span>
        </h3>
        <p className="field-note">
          Only materials referenced in a numbered step enter the tracking plan.
        </p>
        <div className="material-list">
          {doc.materials.map((m) => (
            <article className="material-item" key={m.key}>
              <div>
                <code>@{m.key}</code>
                <span className="material-kind">{m.kind}</span>
                {!used.has(m.key) && (
                  <span className="material-kind">Not targeted</span>
                )}
              </div>
              <strong>{m.name}</strong>
              <p>
                {m.cueType === 'unverifiable'
                  ? 'Identity not verifiable'
                  : `Declared ${m.cueType} cue`}
                : {m.cue}
              </p>
            </article>
          ))}
        </div>
      </section>
      <section>
        <h3 className="protocol-section-title">Procedure</h3>
        <ol className="steps">
          {procedure?.steps.map((s) => (
            <li
              key={s.id}
              className={selectedIds.includes(s.id) ? 'linked-step' : ''}
            >
              <span>{s.order}</span>
              <div>
                <p>
                  <References text={s.text} />
                </p>
                {s.details?.map((e, i) => (
                  <p className="step-detail" key={i}>
                    <strong>Detail</strong> <References text={e.text} />
                  </p>
                ))}
                {s.expectations?.map((e, i) => (
                  <p className="step-expectation" key={i}>
                    <strong>Expect</strong> <References text={e.text} />
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </section>
      {['Notes', 'Expected results'].map(
        (name) =>
          !!doc.sections[name]?.length && (
            <section className="protocol-prose" key={name}>
              <h3>{name}</h3>
              {doc.sections[name].map((e, i) => (
                <p key={i}>
                  <References text={e.text} />
                </p>
              ))}
            </section>
          ),
      )}
    </div>
  );
}

export function ProtocolPreview({
  result,
  error,
}: {
  result: ParseResult | null;
  error: string;
}) {
  return (
    <div className="protocol-preview" aria-live="polite">
      {error ? (
        <p className="inline-error">{error}</p>
      ) : !result ? (
        <p className="field-note">Checking procedure syntax…</p>
      ) : !result.valid ? (
        <>
          <strong className="validation-heading">
            Fix these lines to define tracking scope
          </strong>
          <ul className="syntax-errors">
            {result.errors.slice(0, 25).map((e, i) => (
              <li key={i}>
                {e.line ? `Line ${e.line}: ` : ''}
                {e.message}
              </li>
            ))}
          </ul>
        </>
      ) : result.document?.status === 'draft' ? (
        <p className="scope-warning">
          Empty draft: no tracking plan will be created.
        </p>
      ) : (
        <>
          <strong className="validation-heading valid">
            Syntax valid · preview of submitted scope
          </strong>
          <ProtocolDocument
            procedure={{
              text: '',
              structure: result.document!,
              steps: result.document!.steps.map((s, i) => ({
                ...s,
                id: `preview-${i}`,
              })),
            }}
          />
        </>
      )}
    </div>
  );
}

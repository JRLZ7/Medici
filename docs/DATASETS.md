# Public datasets for Medici

## First local example: Mann Labs proteomics benchmark

- Canonical release inspected: [Zenodo 17710382](https://zenodo.org/records/17710382), version 1.1.0.
- The concept record [17253028](https://zenodo.org/records/17253028) resolves to this release through Zenodo's API. These are not two unrelated datasets.
- Creator: Patricia Skowronek, Department of Proteomics and Signal Transduction, Max Planck Institute of Biochemistry.
- Dataset license declared by the release: **CC BY-ND 4.0**. This is separate from the associated code repository's Apache license. Preserve attribution and original files. Reassess the release terms before distributing modified dataset material or bundling it into a public product/demo.
- Associated [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12954122/) and [code](https://github.com/MannLabs/proteomics_lab_agent).

### Selected recording

`Dilute_docuWrongSolvent.MP4` (430,756,295 bytes) is a physical pipetting/dilution recording. Its matching reference procedure is `Diluting_protocolCorrect.md`. The procedure's eleven actions agree with the Diluting section in the original `Ground_truth_protocol.pdf`, pages 3–4 (formatting and spelling differ). It includes materials, reagents, setup, actions, timing, and expected results, making it a useful example of why a procedure should be treated as a document.

The source filenames reveal intended mistakes. Do not expose those filenames or reference labels to a model during future blind evaluation. Do not infer a visible deviation merely from a filename.

### What the annotations actually are

`lab_note_all_eval_sets_all_runs.json` includes **AI-generated lab notes**, evaluation metadata, and step-level benchmark comparisons across repeated runs. Its generated `lab_notes` are **not human ground truth**.

For the selected case, the `df_errors` entries provide columns `Step`, `Benchmark`, `Class`, and `Skill` separately from the model's answers. The importer extracts only those benchmark columns, verifies agreement across runs, and saves `reference-labels.json` alongside the untouched source files. Those labels do not provide start/end timestamps. They are not automatically converted into Medici observations, nor are they claimed to be verified by us from video.

The Markdown lab note for `Dilute_docuWrongVolume_PipettTipNotChanged` belongs to a **different video** and is not a reference for the wrong-solvent recording. Likewise, `AI_generated_protocol.pdf` must not be mistaken for `Ground_truth_protocol.pdf`.

### Storage and import

Downloaded originals are local-only under `data/datasets/zenodo-17710382/`, excluded from Git. Keep the original Zenodo `record.json` manifest and verify file sizes and MD5 checksums before use. Medici adds its own SHA-256 checksum to the uploaded original video.

With the files present and the app running:

```sh
.venv/bin/python scripts/import_zenodo_example.py \
  --source-dir data/datasets/zenodo-17710382
```

The command accepts only a loopback API origin, uploads the original recording, preserves the source procedure, attaches dataset attribution to the experiment/export, and leaves observations empty. A local receipt lets a repeated import resume after upload failure without recreating the experiment. The source files and the app's stored video occupy approximately 862 MB together. No model is invoked.

## FineBio: complementary benchmark

[FineBio](https://github.com/aistairc/FineBio) is a strong candidate for detailed action recognition and temporal evaluation: it includes protocol/step/atomic-operation annotations and multiple views of laboratory work. It complements the proteomics benchmark's focus on protocol differences.

The public repository's code license is MIT; the **dataset has a separate agreement**. The maintainers require a signed [license agreement](https://github.com/aistairc/FineBio/blob/main/FineBio_License_Agreement.pdf) submitted through their [access form](https://forms.gle/Ts64vrG6n2i1fEWCA). They state noncommercial research/development use and normally review requests within two or three business days. The requester must provide their actual affiliation, purpose, and signature. Medici has not submitted or accepted that agreement on anyone's behalf.

Once access is granted, retain the assigned splits and participant/recording boundaries. Start with one protocol and a small number of recordings rather than downloading or training on the entire dataset.

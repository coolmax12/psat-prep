# Source PDF Folder

Place local source PDFs here before running `scripts/import_sources.py`.

Expected file paths:

```text
sources/vocabulary/SAT_VOCAB.pdf
sources/math/math_full_bank.pdf
sources/reading and writing/reading_and_writing_full_bank.pdf
```

Suggested sources:

- Vocabulary: download `https://img.sparknotes.com/content/testprep/pdf/sat.vocab.pdf` and save it as `sources/vocabulary/SAT_VOCAB.pdf`.
- Math: use `https://satsuiteeducatorquestionbank.collegeboard.org/digital/search`, choose `PSAT/NMSQT and PSAT 10`, filter to Math, export to PDF, and save it as `sources/math/math_full_bank.pdf`.
- Reading and Writing: use the same College Board question bank, choose `PSAT/NMSQT and PSAT 10`, filter to Reading and Writing, export to PDF, and save it as `sources/reading and writing/reading_and_writing_full_bank.pdf`.

The importer reads those PDFs, builds the SQLite question bank, stores source-page text, and renders prompt images under `data/assets/`.

Run the importer from the project root:

```bash
python3 scripts/import_sources.py
```

Do not commit copyrighted or licensed PDFs unless you have permission to redistribute them. The repository is intended to share the app code and importer, not third-party source material.

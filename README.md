# PSAT Prep

PSAT Prep is a lightweight local web app for PSAT/SAT practice. It runs with a small Python HTTP server, SQLite, and vanilla HTML/CSS/JavaScript.

The app helps students practice:

- Vocabulary tests and flashcards
- Math practice by topic and difficulty
- Reading and Writing practice by topic and difficulty
- Review of missed questions
- Saved in-progress tests
- Completed test history with full result review
- Progress tracking, reset controls, answers, explanations, and source tracing

## Important Sharing Note

This repository is meant to share the application code and importer. Do not publish copyrighted PDFs, generated question images, or a populated database unless you have permission to redistribute that material.

By default, `.gitignore` excludes:

- `data/`, including the SQLite database and generated prompt images
- `sources/**/*.pdf`, including source PDFs
- Python caches, virtual environments, and local environment files

Each user should add their own allowed source PDFs locally and run the importer on their own machine.

## Requirements

- Python 3.9 or newer
- PyMuPDF for PDF text/image extraction

Install the Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

Optional macOS/Homebrew install:

```bash
brew install pymupdf
```

If using Homebrew's PyMuPDF package, run the app with Homebrew Python:

```bash
/opt/homebrew/bin/python3.14 app.py
```

## Quick Start

Clone the project:

```bash
git clone https://github.com/YOUR_USERNAME/psat-prep.git
cd psat-prep
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Start the app:

```bash
python3 app.py
```

Open:

```text
http://localhost:8080
```

The app creates its SQLite database at `data/psat_prep.sqlite3`.

## Complete Manual Setup

Use these steps when setting up the app without any AI assistance.

### 1. Install System Packages

On Debian/Ubuntu Linux:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
```

On macOS with Homebrew:

```bash
brew install python git
```

### 2. Download The App Code

Clone from GitHub:

```bash
git clone https://github.com/YOUR_USERNAME/psat-prep.git
cd psat-prep
```

If you downloaded a ZIP instead, unzip it, open a terminal, and `cd` into the extracted `psat-prep` folder.

### 3. Create A Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Confirm PyMuPDF is installed:

```bash
python3 -c "import fitz; print(fitz.__version__)"
```

If that command fails, rerun:

```bash
python3 -m pip install -r requirements.txt
```

### 4. Create The Source Folders

```bash
mkdir -p sources/vocabulary
mkdir -p sources/math
mkdir -p "sources/reading and writing"
```

### 5. Add The Vocabulary PDF

Download the SparkNotes SAT vocabulary PDF:

```bash
curl -L "https://img.sparknotes.com/content/testprep/pdf/sat.vocab.pdf" \
  -o sources/vocabulary/SAT_VOCAB.pdf
```

If `curl` is not available, open the URL in a browser and save the file exactly as:

```text
sources/vocabulary/SAT_VOCAB.pdf
```

### 6. Export The College Board Question PDFs

Open this URL in a browser:

```text
https://satsuiteeducatorquestionbank.collegeboard.org/digital/search
```

Create the Math PDF:

1. Choose `PSAT/NMSQT and PSAT 10`.
2. Filter to Math questions.
3. Export or download the filtered question bank as a PDF.
4. Save the file exactly as `sources/math/math_full_bank.pdf`.

Create the Reading and Writing PDF:

1. Return to the same College Board question bank.
2. Choose `PSAT/NMSQT and PSAT 10`.
3. Filter to Reading and Writing questions.
4. Export or download the filtered question bank as a PDF.
5. Save the file exactly as `sources/reading and writing/reading_and_writing_full_bank.pdf`.

Keep Math and Reading/Writing separate. The importer expects two different PDFs.

### 7. Verify The Source Files

Run:

```bash
ls -lh sources/vocabulary/SAT_VOCAB.pdf
ls -lh sources/math/math_full_bank.pdf
ls -lh "sources/reading and writing/reading_and_writing_full_bank.pdf"
```

All three commands should show a PDF file. If any command says `No such file or directory`, fix the file name or folder path before importing.

### 8. Import The Question Bank

Run:

```bash
python3 scripts/import_sources.py
```

This creates `data/psat_prep.sqlite3` and generated question images under `data/assets/`.

Typical successful output looks like:

```text
vocabulary: imported 991, skipped 0
math: imported 1741, skipped 0
reading/writing: imported 1838, skipped 0
```

Exact counts can change if the source PDFs change, but skipped counts should usually be `0`.

To test the importer quickly before a full run:

```bash
IMPORT_LIMIT_VOCABULARY=20 IMPORT_LIMIT_MATH=10 IMPORT_LIMIT_ENGLISH=10 python3 scripts/import_sources.py
```

Then run the full import command again when ready.

### 9. Start The App

For use on the same computer:

```bash
python3 app.py
```

Open:

```text
http://localhost:8080
```

For use from another device on the same home network:

```bash
PSAT_HOST=0.0.0.0 PSAT_PORT=8080 python3 app.py
```

Open this from the other device:

```text
http://SERVER_IP_ADDRESS:8080
```

Replace `SERVER_IP_ADDRESS` with the IP address of the computer running the app.

### 10. Confirm It Worked

In the app:

1. Open the Dashboard.
2. Confirm Vocabulary, Math, and Reading/Writing show nonzero totals.
3. Start a 10-question Math test.
4. Start Vocabulary Flashcards.
5. After completing a test, open History and confirm the completed result is listed.
6. Open Settings and confirm each section shows Fresh as `fresh/total`.

## Troubleshooting

`ModuleNotFoundError: No module named 'fitz'`

Run:

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

`Missing source files`

Check that the three PDF paths exactly match:

```text
sources/vocabulary/SAT_VOCAB.pdf
sources/math/math_full_bank.pdf
sources/reading and writing/reading_and_writing_full_bank.pdf
```

Port `8080` is already in use:

```bash
PSAT_PORT=8081 python3 app.py
```

Cannot reach the app from another device:

- Start with `PSAT_HOST=0.0.0.0`.
- Use the server's LAN IP address, not `localhost`.
- Check that the server firewall allows the selected port.

Want to rebuild from scratch:

```bash
python3 scripts/import_sources.py
```

That command resets the imported question bank and progress for the configured database.

## Run On A Home Linux Server

Run on all network interfaces:

```bash
PSAT_HOST=0.0.0.0 PSAT_PORT=8080 python3 app.py
```

Then open this from another device on the same network:

```text
http://SERVER_IP_ADDRESS:8080
```

Use a custom database path:

```bash
PSAT_DB=/srv/psat/psat_prep.sqlite3 PSAT_HOST=0.0.0.0 PSAT_PORT=8080 python3 app.py
```

### Optional systemd Service

Create `/etc/systemd/system/psat-prep.service`:

```ini
[Unit]
Description=PSAT Prep local web app
After=network.target

[Service]
Type=simple
WorkingDirectory=/srv/psat-prep
Environment=PSAT_HOST=0.0.0.0
Environment=PSAT_PORT=8080
Environment=PSAT_DB=/srv/psat-prep/data/psat_prep.sqlite3
ExecStart=/srv/psat-prep/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now psat-prep
sudo systemctl status psat-prep
```

## Add Source PDFs

Use source files that you have permission to use locally. The importer currently expects these local file paths:

```text
sources/vocabulary/SAT_VOCAB.pdf
sources/math/math_full_bank.pdf
sources/reading and writing/reading_and_writing_full_bank.pdf
```

Recommended source workflow:

1. Vocabulary: download the SparkNotes SAT vocabulary PDF from `https://img.sparknotes.com/content/testprep/pdf/sat.vocab.pdf` and save it as `sources/vocabulary/SAT_VOCAB.pdf`.
2. Math questions: open the College Board SAT Suite Educator Question Bank at `https://satsuiteeducatorquestionbank.collegeboard.org/digital/search`, choose `PSAT/NMSQT and PSAT 10`, filter to Math, export the results as a PDF, and save it as `sources/math/math_full_bank.pdf`.
3. Reading and Writing questions: use the same College Board question bank, choose `PSAT/NMSQT and PSAT 10`, filter to Reading and Writing, export the results as a separate PDF, and save it as `sources/reading and writing/reading_and_writing_full_bank.pdf`.

Keep Math and Reading/Writing as separate PDFs. The importer uses the file path and the PDF's domain/topic metadata to build the right question banks.

## Build The Question Bank

After the PDFs are in place, run:

```bash
python3 scripts/import_sources.py
```

This command is destructive for the configured database. It clears:

- sources
- source pages
- items
- attempts
- saved practice sessions
- generated question images

Then it imports vocabulary, Math, and Reading/Writing questions from `sources/`.

The importer stores:

- question prompts
- answer choices
- correct answers
- explanations/rationales
- top-level topics
- extracted subtopics
- Easy/Medium/Hard difficulty
- question identifiers from the source PDFs
- source page text
- rendered prompt images for graph/table/formula-heavy questions

Use a custom database path:

```bash
PSAT_DB=/srv/psat/psat_prep.sqlite3 python3 scripts/import_sources.py
```

Parser test limits:

```bash
IMPORT_LIMIT_VOCABULARY=20 IMPORT_LIMIT_MATH=10 IMPORT_LIMIT_ENGLISH=10 python3 scripts/import_sources.py
```

## App Workflow

1. Start from the Dashboard.
2. Pick Vocabulary, Math, or Reading and Writing.
3. For Math and Reading/Writing, choose one or more topics and difficulties.
4. Choose a test size: 10, 20, or 30 questions.
5. Complete the test before seeing score, correct answers, selected wrong answers, and explanations.
6. Review missed questions from Review Incorrect.
7. Use History to revisit completed tests and all questions in each test, right or wrong.
8. Use Vocabulary Flashcards in word-to-definition, definition-to-word, or mixed mode.
9. Use Settings to reset progress counters for one section without deleting questions, sources, or completed test history.

## Scheduling And Progress

Tests prefer fresh material first. If a test asks for more items than remain fresh, the app adds due review items, then older seen items.

Missed questions stay flagged for Review Incorrect and are also randomly reinjected into future normal tests. Normal tests reserve a small slice for missed-review items when available, while still prioritizing broad coverage of fresh source material.

For Math and Reading/Writing, the sampler rotates across selected top-level topics so broad tests cover a range of skills.

Correct answers increase mastery and push the item farther into the future. Wrong answers reset mastery, mark the item for review, and make it due again soon.

Saved tests and review sessions can be resumed later from the Dashboard.

Completed tests are available from History. The history view preserves the completed results page, including the score, every question, selected answers, correct answers, explanations, and source metadata.

Vocabulary flashcards load the active vocabulary deck into browser memory and cycle through the full list before reshuffling.

## Topics

Math:

- Algebra
- Advanced Math
- Problem-Solving and Data Analysis
- Geometry and Trigonometry

Reading and Writing:

- Information and Ideas
- Craft and Structure
- Expression of Ideas
- Standard English Conventions

## Manual And Batch Imports

You can add items manually from the Sources page, or batch import text.

Vocabulary lines:

```text
austere - severe or plain
mitigate: make less severe
```

Vocabulary TSV:

```text
austere	severe or plain	example or note
```

Math and Reading/Writing TSV:

```text
prompt	choice A	choice B	choice C	choice D	A	explanation
```

Optional TSV columns:

```text
prompt	choice A	choice B	choice C	choice D	A	explanation	topic	subtopic	difficulty	prompt image paths	choice image paths	question identifier
```

Use `|` to separate multiple prompt images or choice images.

Question JSON:

```json
[
  {
    "prompt": "What is 2 + 2?",
    "choices": ["3", "4", "5", "6"],
    "answer": "4",
    "explanation": "2 + 2 = 4.",
    "topic": "Algebra",
    "subtopic": "Linear equations",
    "difficulty": "Easy",
    "question_identifier": "ABC123XYZ789",
    "prompt_images": ["data/assets/source_3/page-004.png"],
    "choice_images": ["", "", "", ""]
  }
]
```

JSON import also accepts `question_id`, `source_question_id`, or `external_id` as aliases for `question_identifier`.

## Project Layout

```text
app.py                    Python HTTP server and SQLite backend
index.html                App shell
static/app.js             Browser UI and client-side behavior
static/styles.css         Styling
scripts/import_sources.py PDF-to-question-bank importer
sources/                  Local source PDFs, ignored by git
data/                     SQLite DB and generated images, ignored by git
requirements.txt          Python dependencies
```

## Privacy And Security

This app is designed for trusted local/home-network use. It does not include login, accounts, HTTPS, or multi-user permissions.

Do not expose it directly to the public internet without adding authentication and HTTPS through a reverse proxy or another access-control layer.

## GitHub Publishing Checklist

Before pushing:

```bash
git status --ignored
```

Confirm these are not staged:

- `data/`
- `sources/**/*.pdf`
- `__pycache__/`
- `.venv/`
- `.DS_Store`

Then publish:

```bash
git init
git add .
git status
git commit -m "Add PSAT Prep app"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/psat-prep.git
git push -u origin main
```

Choose and add a license before publishing publicly. If you want others to freely use and modify the app code, common choices are MIT or Apache-2.0.

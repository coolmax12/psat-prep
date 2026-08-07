#!/usr/bin/env python3
"""Flush the local database and import questions from source PDFs."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

try:
    import fitz  # type: ignore
except ImportError as exc:  # pragma: no cover - user-facing setup path.
    raise SystemExit(
        "PyMuPDF is required. Install dependencies with: "
        "python3 -m pip install -r requirements.txt"
    ) from exc


SOURCE_FILES = {
    "vocabulary": ROOT / "sources" / "vocabulary" / "SAT_VOCAB.pdf",
    "math": ROOT / "sources" / "math" / "math_full_bank.pdf",
    "english": ROOT / "sources" / "reading and writing" / "reading_and_writing_full_bank.pdf",
}

DIFFICULTIES = set(app.DIFFICULTIES)
MATH_TOPICS = app.TOPICS["math"]
ENGLISH_TOPICS = app.TOPICS["english"]
VOCAB_TRANSLATION = str.maketrans(
    {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
    }
)


def import_limit(name: str) -> int | None:
    value = os.environ.get(f"IMPORT_LIMIT_{name.upper()}", "").strip()
    if not value:
        return None
    try:
        limit = int(value)
    except ValueError as exc:
        raise SystemExit(f"IMPORT_LIMIT_{name.upper()} must be a number.") from exc
    return max(0, limit)


def clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def page_lines(page: fitz.Page) -> list[str]:
    return [clean_line(line) for line in (page.get_text("text") or "").splitlines() if clean_line(line)]


def compact_text(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def create_source(conn: Any, title: str, domain: str, pdf_path: Path) -> int:
    cur = conn.execute(
        """
        INSERT INTO sources (title, domain, kind, locator, notes, created_at)
        VALUES (?, ?, 'pdf', ?, '', ?)
        """,
        (title, domain, str(pdf_path.relative_to(ROOT)), app.iso()),
    )
    return int(cur.lastrowid)


def flush_database(conn: Any) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in (
        "practice_session_items",
        "practice_sessions",
        "attempts",
        "items",
        "source_pages",
        "sources",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        "DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?, ?)",
        (
            "practice_session_items",
            "practice_sessions",
            "attempts",
            "items",
            "source_pages",
            "sources",
        ),
    )
    conn.execute("PRAGMA foreign_keys = ON")
    shutil.rmtree(app.DB_PATH.parent / "assets", ignore_errors=True)


def detect_qid(text: str) -> str:
    match = re.search(r"Question ID:\s*([A-Za-z0-9_-]+)", text)
    return app.clean_question_identifier(match.group(1)) if match else ""


def group_question_pages(doc: fitz.Document) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page_index, page in enumerate(doc):
        text = page.get_text("text") or ""
        qid = detect_qid(text)
        if qid:
            if current:
                groups.append(current)
            current = {"qid": qid, "pages": []}
        if current:
            current["pages"].append(
                {
                    "page_index": page_index,
                    "page_number": page_index + 1,
                    "text": text,
                    "lines": [clean_line(line) for line in text.splitlines() if clean_line(line)],
                }
            )
    if current:
        groups.append(current)
    return groups


def match_topic(tokens: list[str], topics: tuple[str, ...]) -> tuple[str, list[str]]:
    if not tokens:
        return "", []
    joined = compact_text(tokens)
    normalized_joined = app.normalize_choice(joined)
    for topic in sorted(topics, key=len, reverse=True):
        normalized_topic = app.normalize_choice(topic)
        if normalized_joined == normalized_topic:
            return topic, []
        if normalized_joined.startswith(normalized_topic + " "):
            rest = joined[len(topic) :].strip()
            return topic, [rest] if rest else []
    if tokens[0] in topics:
        return tokens[0], tokens[1:]
    return tokens[0], tokens[1:]


def metadata_from_lines(lines: list[str], domain: str, q_index: int) -> tuple[str, str, str]:
    domain_label = "Math" if domain == "math" else "Reading and Writing"
    topics = MATH_TOPICS if domain == "math" else ENGLISH_TOPICS
    try:
        domain_index = lines.index(domain_label)
    except ValueError:
        return "", "", "Medium"

    metadata = lines[domain_index + 1 : q_index]
    difficulty_index = -1
    for index, value in enumerate(metadata):
        if value in DIFFICULTIES:
            difficulty_index = index
    if difficulty_index < 0:
        return "", compact_text(metadata), "Medium"

    difficulty = metadata[difficulty_index]
    topic_tokens = metadata[:difficulty_index]
    topic, subtopic_tokens = match_topic(topic_tokens, topics)
    return topic, compact_text(subtopic_tokens), difficulty


def find_line_index(lines: list[str], pattern: str, start: int = 0) -> int:
    regex = re.compile(pattern, re.IGNORECASE)
    for index in range(start, len(lines)):
        if regex.fullmatch(lines[index]) or regex.search(lines[index]):
            return index
    return -1


def correct_answer_from_line(lines: list[str], correct_index: int) -> str:
    line = lines[correct_index]
    answer = line.split(":", 1)[1].strip() if ":" in line else ""
    if not answer and correct_index + 1 < len(lines):
        answer = lines[correct_index + 1].strip()
    return answer


def answer_from_rationale(lines: list[str], rationale_index: int) -> str:
    if rationale_index < 0:
        return ""
    text = compact_text(lines[rationale_index + 1 : rationale_index + 12])
    choice_match = re.search(r"\bChoice ([A-D]) is correct\b", text)
    if choice_match:
        return choice_match.group(1)

    answer_match = re.search(
        r"\bThe correct answer is\s+(.+?)(?:\.(?=\s+[A-Z])|$)",
        text,
        re.IGNORECASE,
    )
    answer = answer_match.group(1).strip() if answer_match else ""
    if answer in {"", "."}:
        note_match = re.search(
            r"\bNote that ([^.;]+?) (?:and|or) [^.;]+ are examples\b",
            text,
            re.IGNORECASE,
        )
        answer = note_match.group(1).strip() if note_match else ""
    return answer.strip(" .")


def parse_choices(lines: list[str]) -> dict[str, str]:
    choices: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        match = re.match(r"^([A-D])\.\s*(.*)$", line)
        if match:
            current = match.group(1)
            choices[current] = [match.group(2).strip()] if match.group(2).strip() else []
        elif current:
            choices[current].append(line)
    return {label: compact_text(parts) for label, parts in choices.items()}


def marker_y(page: fitz.Page) -> float | None:
    result: float | None = None
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            text = clean_line(" ".join(span.get("text", "") for span in line.get("spans", [])))
            if "Correct Answer" in text or text == "Rationale":
                y = float(line["bbox"][1])
                result = y if result is None else min(result, y)
    return result


def save_pixmap(page: fitz.Page, output_path: Path, bottom: float | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clip = None
    if bottom is not None:
        clip = fitz.Rect(0, 0, page.rect.width, max(72, min(bottom, page.rect.height)))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False, clip=clip)
    pixmap.save(str(output_path))


def render_question_images(doc: fitz.Document, group: dict[str, Any], domain: str) -> list[str]:
    qid = group["qid"]
    image_paths: list[str] = []
    output_dir = app.DB_PATH.parent / "assets" / "questions" / domain
    saw_answer_marker = False

    for sequence, page_info in enumerate(group["pages"], start=1):
        if saw_answer_marker:
            break
        page = doc[page_info["page_index"]]
        y = marker_y(page)
        output_path = output_dir / f"{qid}-{sequence:02d}.png"
        if y is None:
            save_pixmap(page, output_path)
            image_paths.append(app.media_reference(output_path))
        else:
            if y > 120:
                save_pixmap(page, output_path, y - 8)
                image_paths.append(app.media_reference(output_path))
            saw_answer_marker = True
            break

    if not image_paths and group["pages"]:
        page = doc[group["pages"][0]["page_index"]]
        output_path = output_dir / f"{qid}-01.png"
        save_pixmap(page, output_path)
        image_paths.append(app.media_reference(output_path))

    return image_paths


def insert_source_pages(conn: Any, group: dict[str, Any], source_id: int) -> None:
    for page_info in group["pages"]:
        conn.execute(
            """
            INSERT INTO source_pages (
                source_id, page_number, question_identifier, text, image_path, created_at
            ) VALUES (?, ?, ?, ?, '', ?)
            ON CONFLICT(source_id, page_number)
            DO UPDATE SET
                question_identifier = excluded.question_identifier,
                text = excluded.text
            """,
            (
                source_id,
                page_info["page_number"],
                group["qid"],
                page_info["text"],
                app.iso(),
            ),
        )


def parse_question_group(
    doc: fitz.Document,
    group: dict[str, Any],
    domain: str,
    source_id: int,
) -> dict[str, Any] | None:
    lines: list[str] = []
    for page_info in group["pages"]:
        lines.extend(page_info["lines"])
    question_index = find_line_index(lines, r"^Question$")
    correct_index = find_line_index(lines, r"^Correct Answer:")
    rationale_index = find_line_index(
        lines,
        r"^Rationale$",
        correct_index + 1 if correct_index >= 0 else question_index + 1,
    )
    if question_index < 0 or (correct_index < 0 and rationale_index < 0):
        return None

    topic, subtopic, difficulty = metadata_from_lines(lines, domain, question_index)
    answer_index = find_line_index(lines, r"^Answer$", question_index + 1)
    answer_end_index = correct_index if correct_index >= 0 else rationale_index
    if answer_end_index >= 0 and answer_index >= answer_end_index:
        answer_index = -1

    question_end_index = answer_index if answer_index >= 0 else answer_end_index
    question_lines = lines[question_index + 1 : question_end_index]
    choice_lines = lines[answer_index + 1 : answer_end_index] if answer_index >= 0 else []
    choices_by_label = parse_choices(choice_lines)

    correct_raw = (
        correct_answer_from_line(lines, correct_index)
        if correct_index >= 0
        else answer_from_rationale(lines, rationale_index)
    )
    if not correct_raw:
        return None
    explanation_lines = lines[rationale_index + 1 :] if rationale_index >= 0 else lines[correct_index + 1 :]

    labels = ["A", "B", "C", "D"]
    choices: list[str] = []
    if choices_by_label:
        for label in labels:
            if label in choices_by_label:
                choices.append(choices_by_label[label] or label)
    elif correct_raw in labels:
        choices = labels[:]

    if correct_raw in labels and choices:
        answer_index_for_label = labels.index(correct_raw)
        answer = choices[answer_index_for_label] if answer_index_for_label < len(choices) else correct_raw
    else:
        answer = correct_raw

    prompt = compact_text(question_lines)
    if not prompt:
        prompt = f"See source image for question {group['qid']}."

    image_paths = render_question_images(doc, group, domain)
    return {
        "domain": domain,
        "source_id": source_id,
        "item_type": "multiple_choice",
        "prompt": prompt,
        "answer": answer,
        "choices": choices,
        "explanation": compact_text(explanation_lines),
        "topic": topic,
        "subtopic": subtopic,
        "difficulty": difficulty,
        "question_identifier": group["qid"],
        "prompt_images": image_paths,
        "media": {"source_pages": [page["page_number"] for page in group["pages"]]},
    }


def import_question_pdf(
    conn: Any, domain: str, title: str, pdf_path: Path, limit: int | None = None
) -> tuple[int, int, int]:
    source_id = create_source(conn, title, domain, pdf_path)
    doc = fitz.open(str(pdf_path))
    groups = group_question_pages(doc)
    if limit is not None:
        groups = groups[:limit]
    imported = 0
    skipped = 0

    for index, group in enumerate(groups, start=1):
        insert_source_pages(conn, group, source_id)
        payload = parse_question_group(doc, group, domain, source_id)
        if not payload:
            skipped += 1
            continue
        app.create_item(conn, payload)
        imported += 1
        if imported % 100 == 0:
            print(f"{domain}: imported {imported}/{len(groups)} questions", flush=True)

    return source_id, imported, skipped


def is_vocab_word(line: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-zA-Z\-']{1,28}", line)) and line not in {
        "and",
        "or",
        "to",
        "the",
    }


def is_pos(line: str) -> bool:
    return bool(re.fullmatch(r"\((?:v|n|adj|adv|prep|conj|interj)\.\)", line))


def vocab_definition_from_body(body: str) -> str:
    body = re.sub(r"\([^)]*\)", " ", body)
    body = re.sub(r"\b\d+\.\s*", "; ", body)
    body = re.sub(r"\s+", " ", body)
    body = re.sub(r"\s*;\s*", "; ", body).strip(" ;")
    return body


def parse_vocabulary_entries(lines: list[str]) -> dict[str, list[str]]:
    ignored = {"SAT Vocabulary", "The 1000 Most", "Common SAT", "Words"}
    cleaned = [
        line.translate(VOCAB_TRANSLATION)
        for line in lines
        if line not in ignored and not re.fullmatch(r"[A-Z]", line)
    ]
    text = re.sub(r"\s+", " ", " ".join(cleaned)).strip()
    pos = r"(?:v|n|adj|adv|prep|conj|interj)\."
    entry_pattern = re.compile(
        rf"(?<![A-Za-z])([a-z][a-zA-Z-]{{1,28}})\s+(?:\d+\.\s*)?\(({pos})\)\s*"
    )
    matches = list(entry_pattern.finditer(text))
    entries: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        word = match.group(1)
        definition = vocab_definition_from_body(text[match.end() : next_start])
        if definition:
            entries.setdefault(word, []).append(definition)
    return entries


def import_vocabulary_pdf(conn: Any, pdf_path: Path, limit: int | None = None) -> tuple[int, int, int]:
    source_id = create_source(conn, "SAT Vocabulary", "vocabulary", pdf_path)
    doc = fitz.open(str(pdf_path))
    lines: list[str] = []
    for page_index, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        conn.execute(
            """
            INSERT INTO source_pages (
                source_id, page_number, question_identifier, text, image_path, created_at
            ) VALUES (?, ?, '', ?, '', ?)
            """,
            (source_id, page_index, text, app.iso()),
        )
        lines.extend(page_lines(page))

    entries = parse_vocabulary_entries(lines)

    imported = 0
    for word, definitions in entries.items():
        if limit is not None and imported >= limit:
            break
        answer = "; ".join(dict.fromkeys(definitions))
        app.create_item(
            conn,
            {
                "domain": "vocabulary",
                "source_id": source_id,
                "item_type": "vocab",
                "prompt": word,
                "answer": answer,
            },
        )
        imported += 1
    return source_id, imported, 0


def main() -> None:
    missing = [str(path) for path in SOURCE_FILES.values() if not path.exists()]
    if missing:
        raise SystemExit("Missing source files:\n" + "\n".join(missing))

    app.init_db()
    with app.get_db() as conn:
        limits = {
            "vocabulary": import_limit("vocabulary"),
            "math": import_limit("math"),
            "english": import_limit("english"),
        }
        limited = {key: value for key, value in limits.items() if value is not None}
        if limited:
            print(f"Import limits active: {limited}", flush=True)

        print(f"Flushing database at {app.DB_PATH}", flush=True)
        flush_database(conn)

        print("Importing vocabulary...", flush=True)
        vocab_source, vocab_count, vocab_skipped = import_vocabulary_pdf(
            conn, SOURCE_FILES["vocabulary"], limits["vocabulary"]
        )
        print(f"vocabulary: imported {vocab_count}, skipped {vocab_skipped}", flush=True)

        print("Importing math question bank...", flush=True)
        math_source, math_count, math_skipped = import_question_pdf(
            conn,
            "math",
            "Math Full Question Bank",
            SOURCE_FILES["math"],
            limits["math"],
        )
        print(f"math: imported {math_count}, skipped {math_skipped}", flush=True)

        print("Importing reading and writing question bank...", flush=True)
        english_source, english_count, english_skipped = import_question_pdf(
            conn,
            "english",
            "Reading and Writing Full Question Bank",
            SOURCE_FILES["english"],
            limits["english"],
        )
        print(f"reading/writing: imported {english_count}, skipped {english_skipped}", flush=True)

        print(
            json.dumps(
                {
                    "sources": {
                        "vocabulary": vocab_source,
                        "math": math_source,
                        "english": english_source,
                    },
                    "items": {
                        "vocabulary": vocab_count,
                        "math": math_count,
                        "english": english_count,
                    },
                    "skipped": {
                        "vocabulary": vocab_skipped,
                        "math": math_skipped,
                        "english": english_skipped,
                    },
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()

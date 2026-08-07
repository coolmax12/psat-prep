#!/usr/bin/env python3
"""Portable PSAT/SAT prep web app.

Runs with the Python standard library only:
    python3 app.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PSAT_DB", ROOT / "data" / "psat_prep.sqlite3"))
HOST = os.environ.get("PSAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("PSAT_PORT", "8080"))
DOMAINS = ("vocabulary", "math", "english")
ITEM_TYPES = ("vocab", "multiple_choice")
DIFFICULTIES = ("Easy", "Medium", "Hard")
TOPICS = {
    "math": (
        "Algebra",
        "Advanced Math",
        "Problem-Solving and Data Analysis",
        "Geometry and Trigonometry",
    ),
    "english": (
        "Information and Ideas",
        "Craft and Structure",
        "Expression of Ideas",
        "Standard English Conventions",
    ),
    "vocabulary": (),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_json(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def as_string_list(value: Any) -> list[str]:
    if value in (None, "", "null"):
        return []
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    if isinstance(value, str):
        delimiter = "|" if "|" in value else "\n"
        return [part.strip() for part in value.split(delimiter) if part.strip()]
    return []


def normalize_media(payload: dict[str, Any], choice_count: int = 0) -> dict[str, Any]:
    media = payload.get("media")
    if isinstance(media, str):
        media = parse_json(media, {})
    if not isinstance(media, dict):
        media = {}

    prompt_images = as_string_list(payload.get("prompt_images", media.get("prompt_images")))
    choice_images_raw = payload.get("choice_images", media.get("choice_images"))
    if isinstance(choice_images_raw, str):
        delimiter = "|" if "|" in choice_images_raw else "\n"
        choice_images = [part.strip() for part in choice_images_raw.split(delimiter)]
    elif isinstance(choice_images_raw, list):
        choice_images = [
            str(part).strip() if part not in (None, "null") else ""
            for part in choice_images_raw
        ]
    else:
        choice_images = []

    if choice_count:
        choice_images = (choice_images + [""] * choice_count)[:choice_count]
    else:
        choice_images = []

    source_pages = [
        int(page)
        for page in media.get("source_pages", [])
        if str(page).strip().isdigit()
    ]
    return {
        "prompt_images": prompt_images,
        "choice_images": choice_images,
        "source_pages": source_pages,
    }


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate_db(conn: sqlite3.Connection) -> None:
    columns = table_columns(conn, "items")
    if "topic" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN topic TEXT NOT NULL DEFAULT ''")
    if "subtopic" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN subtopic TEXT NOT NULL DEFAULT ''")
    if "difficulty" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN difficulty TEXT NOT NULL DEFAULT ''")
    if "media_json" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN media_json TEXT NOT NULL DEFAULT '{}'")
    if "question_identifier" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN question_identifier TEXT NOT NULL DEFAULT ''")
    page_columns = table_columns(conn, "source_pages") if "source_pages" in {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    } else set()
    if page_columns and "question_identifier" not in page_columns:
        conn.execute("ALTER TABLE source_pages ADD COLUMN question_identifier TEXT NOT NULL DEFAULT ''")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_items_topic ON items(domain, topic);
        CREATE INDEX IF NOT EXISTS idx_items_difficulty ON items(domain, difficulty);
        CREATE INDEX IF NOT EXISTS idx_items_question_identifier
            ON items(question_identifier);
        CREATE TABLE IF NOT EXISTS source_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            question_identifier TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(source_id, page_number)
        );

        CREATE TABLE IF NOT EXISTS practice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            requested_count INTEGER NOT NULL DEFAULT 10,
            filters_json TEXT NOT NULL DEFAULT '{}',
            direction TEXT NOT NULL DEFAULT 'mixed',
            score INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS practice_session_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            card_json TEXT NOT NULL,
            selected_answer TEXT NOT NULL DEFAULT '',
            correct INTEGER,
            answered_at TEXT,
            UNIQUE(session_id, position)
        );

        CREATE INDEX IF NOT EXISTS idx_source_pages_source ON source_pages(source_id);
        CREATE INDEX IF NOT EXISTS idx_practice_sessions_active
            ON practice_sessions(status, mode, updated_at);
        CREATE INDEX IF NOT EXISTS idx_practice_session_items_session
            ON practice_session_items(session_id, position);
        """
    )


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                domain TEXT NOT NULL CHECK (domain IN ('vocabulary', 'math', 'english')),
                kind TEXT NOT NULL DEFAULT 'link',
                locator TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL CHECK (domain IN ('vocabulary', 'math', 'english')),
                source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
                item_type TEXT NOT NULL CHECK (item_type IN ('vocab', 'multiple_choice')),
                prompt TEXT NOT NULL,
                answer TEXT NOT NULL,
                choices_json TEXT NOT NULL DEFAULT '[]',
                explanation TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL DEFAULT '',
                subtopic TEXT NOT NULL DEFAULT '',
                difficulty TEXT NOT NULL DEFAULT '',
                question_identifier TEXT NOT NULL DEFAULT '',
                media_json TEXT NOT NULL DEFAULT '{}',
                tags TEXT NOT NULL DEFAULT '',
                seen_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                mastery INTEGER NOT NULL DEFAULT 0,
                needs_review INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT,
                next_due_at TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                domain TEXT NOT NULL,
                mode TEXT NOT NULL,
                selected_answer TEXT NOT NULL DEFAULT '',
                correct INTEGER NOT NULL,
                attempted_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_items_domain_active ON items(domain, active);
            CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);
            CREATE INDEX IF NOT EXISTS idx_items_review ON items(domain, needs_review);
            CREATE INDEX IF NOT EXISTS idx_items_due ON items(domain, next_due_at);
            CREATE INDEX IF NOT EXISTS idx_attempts_item ON attempts(item_id);
            """
        )
        migrate_db(conn)


def validate_domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError("Unknown practice area.")
    return domain


def canonical_lookup(value: str, options: tuple[str, ...]) -> Optional[str]:
    wanted = normalize_choice(value)
    for option in options:
        if normalize_choice(option) == wanted:
            return option
    return None


def validate_topic(domain: str, topic: str) -> str:
    topic = (topic or "").strip()
    if domain == "vocabulary":
        return ""
    canonical = canonical_lookup(topic, TOPICS[domain])
    if canonical is None:
        raise ValueError(f"Choose a valid {domain} topic.")
    return canonical


def validate_difficulty(domain: str, difficulty: str) -> str:
    difficulty = (difficulty or "").strip()
    if domain == "vocabulary":
        return ""
    if not difficulty:
        return "Medium"
    canonical = canonical_lookup(difficulty, DIFFICULTIES)
    if canonical is None:
        raise ValueError("Difficulty must be Easy, Medium, or Hard.")
    return canonical


def clean_subtopic(domain: str, subtopic: str) -> str:
    if domain == "vocabulary":
        return ""
    return re.sub(r"\s+", " ", subtopic or "").strip()


def clean_question_identifier(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def question_identifier_from_payload(payload: dict[str, Any]) -> str:
    for key in ("question_identifier", "source_question_id", "question_id", "external_id"):
        value = clean_question_identifier(payload.get(key))
        if value:
            return value
    return ""


def list_payload(value: Any) -> list[str]:
    if value in (None, "", "null"):
        return []
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def validate_filter_values(
    domain: str, topics: list[str], difficulties: list[str]
) -> tuple[list[str], list[str]]:
    validate_domain(domain)
    selected_topics: list[str] = []
    if domain != "vocabulary":
        for topic in topics:
            canonical = validate_topic(domain, topic)
            if canonical not in selected_topics:
                selected_topics.append(canonical)

    selected_difficulties: list[str] = []
    if domain != "vocabulary":
        for difficulty in difficulties:
            canonical = validate_difficulty(domain, difficulty)
            if canonical not in selected_difficulties:
                selected_difficulties.append(canonical)
    return selected_topics, selected_difficulties


def taxonomy() -> dict[str, Any]:
    return {
        "topics": TOPICS,
        "difficulties": DIFFICULTIES,
    }


def row_to_source(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "domain": row["domain"],
        "kind": row["kind"],
        "locator": row["locator"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "item_count": row["item_count"] if "item_count" in row.keys() else 0,
        "page_count": row["page_count"] if "page_count" in row.keys() else 0,
    }


def row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "domain": row["domain"],
        "source_id": row["source_id"],
        "item_type": row["item_type"],
        "prompt": row["prompt"],
        "answer": row["answer"],
        "choices": parse_json(row["choices_json"], []),
        "explanation": row["explanation"],
        "topic": row["topic"],
        "subtopic": row["subtopic"],
        "difficulty": row["difficulty"],
        "question_identifier": row["question_identifier"],
        "media": parse_json(row["media_json"], {}),
        "tags": row["tags"],
        "seen_count": row["seen_count"],
        "correct_count": row["correct_count"],
        "wrong_count": row["wrong_count"],
        "mastery": row["mastery"],
        "needs_review": bool(row["needs_review"]),
        "last_seen_at": row["last_seen_at"],
        "next_due_at": row["next_due_at"],
        "created_at": row["created_at"],
    }


def normalize_choice(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def source_exists(conn: sqlite3.Connection, source_id: Optional[int], domain: str) -> bool:
    if source_id is None:
        return True
    row = conn.execute(
        "SELECT id FROM sources WHERE id = ? AND domain = ?", (source_id, domain)
    ).fetchone()
    return row is not None


def create_item(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    domain = validate_domain(str(payload.get("domain", "")))
    item_type = str(payload.get("item_type") or ("vocab" if domain == "vocabulary" else "multiple_choice"))
    if item_type not in ITEM_TYPES:
        raise ValueError("Unknown item type.")

    prompt = str(payload.get("prompt", "")).strip()
    answer = str(payload.get("answer", "")).strip()
    explanation = str(payload.get("explanation", "")).strip()
    topic = validate_topic(domain, str(payload.get("topic", "")))
    subtopic = clean_subtopic(domain, str(payload.get("subtopic", "")))
    difficulty = validate_difficulty(domain, str(payload.get("difficulty", "")))
    question_identifier = question_identifier_from_payload(payload)
    tags = str(payload.get("tags", "")).strip()
    source_id_raw = payload.get("source_id")
    source_id = int(source_id_raw) if source_id_raw not in (None, "", "null") else None

    if not prompt or not answer:
        raise ValueError("Prompt and answer are required.")
    if not source_exists(conn, source_id, domain):
        raise ValueError("Selected source does not match that practice area.")

    choices = payload.get("choices") or []
    if isinstance(choices, str):
        choices = [part.strip() for part in choices.splitlines() if part.strip()]
    choices = [str(choice).strip() for choice in choices if str(choice).strip()]

    if item_type == "vocab":
        choices = []
    elif len(choices) == 1:
        raise ValueError("Questions need either zero choices for typed answers or at least two choices.")
    elif len(choices) >= 2:
        key = answer.upper()
        if answer in choices:
            pass
        elif key in ("A", "B", "C", "D") and len(choices) > ord(key) - ord("A"):
            answer = choices[ord(key) - ord("A")]
        elif key in ("1", "2", "3", "4") and len(choices) >= int(key):
            answer = choices[int(key) - 1]
        elif answer not in choices:
            choices.append(answer)

    media = normalize_media(payload, len(choices) if item_type != "vocab" else 0)

    cur = conn.execute(
        """
        INSERT INTO items (
            domain, source_id, item_type, prompt, answer, choices_json,
            explanation, topic, subtopic, difficulty, question_identifier,
            media_json, tags, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            domain,
            source_id,
            item_type,
            prompt,
            answer,
            json.dumps(choices),
            explanation,
            topic,
            subtopic,
            difficulty,
            question_identifier,
            json.dumps(media),
            tags,
            iso(),
        ),
    )
    return row_to_item(
        conn.execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()
    )


def parse_vocab_import(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t")]
            word = parts[0] if len(parts) > 0 else ""
            definition = parts[1] if len(parts) > 1 else ""
            explanation = parts[2] if len(parts) > 2 else ""
        else:
            parts = re.split(r"\s+-\s+|:\s*", line, maxsplit=1)
            if len(parts) < 2:
                errors.append(f"Line {line_no}: use 'word - definition' or tab-separated columns.")
                continue
            word, definition = parts[0].strip(), parts[1].strip()
            explanation = ""
        if not word or not definition:
            errors.append(f"Line {line_no}: word and definition are required.")
            continue
        items.append(
            {
                "domain": "vocabulary",
                "item_type": "vocab",
                "prompt": word,
                "answer": definition,
                "explanation": explanation,
            }
        )
    return items, errors


def parse_questions_tsv(text: str, domain: str) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    labels = ("A", "B", "C", "D")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) < 6:
            errors.append(
                f"Line {line_no}: expected prompt, four choices, and answer key separated by tabs."
            )
            continue
        prompt, choices, answer_key = parts[0], parts[1:5], parts[5]
        explanation = parts[6] if len(parts) > 6 else ""
        topic = parts[7] if len(parts) > 7 else ""
        subtopic = parts[8] if len(parts) > 8 else ""
        difficulty = parts[9] if len(parts) > 9 else ""
        prompt_images = parts[10] if len(parts) > 10 else ""
        choice_images = parts[11] if len(parts) > 11 else ""
        question_identifier = parts[12] if len(parts) > 12 else ""
        key = answer_key.strip().upper()
        if key in labels:
            answer = choices[labels.index(key)]
        elif key in ("1", "2", "3", "4"):
            answer = choices[int(key) - 1]
        else:
            answer = answer_key.strip()
        if not prompt or not all(choices) or not answer:
            errors.append(f"Line {line_no}: prompt, choices, and answer are required.")
            continue
        items.append(
            {
                "domain": domain,
                "item_type": "multiple_choice",
                "prompt": prompt,
                "choices": choices,
                "answer": answer,
                "explanation": explanation,
                "topic": topic,
                "subtopic": subtopic,
                "difficulty": difficulty,
                "prompt_images": prompt_images,
                "choice_images": choice_images,
                "question_identifier": question_identifier,
            }
        )
    return items, errors


def parse_questions_json(text: str, domain: str) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"JSON parse error: {exc.msg}."]
    rows = parsed.get("items", []) if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        return [], ["JSON import must be an array or an object with an items array."]

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"Item {index}: expected an object.")
            continue
        prompt = str(row.get("prompt", "")).strip()
        choices = [str(choice).strip() for choice in row.get("choices", []) if str(choice).strip()]
        answer = str(row.get("answer", "")).strip()
        explanation = str(row.get("explanation", "")).strip()
        topic = str(row.get("topic", "")).strip()
        subtopic = str(row.get("subtopic", "")).strip()
        difficulty = str(row.get("difficulty", "")).strip()
        prompt_images = row.get("prompt_images", [])
        choice_images = row.get("choice_images", [])
        media = row.get("media", {})
        question_identifier = question_identifier_from_payload(row)
        if not prompt or len(choices) < 2 or not answer:
            errors.append(f"Item {index}: prompt, choices, and answer are required.")
            continue
        items.append(
            {
                "domain": domain,
                "item_type": "multiple_choice",
                "prompt": prompt,
                "choices": choices,
                "answer": answer,
                "explanation": explanation,
                "topic": topic,
                "subtopic": subtopic,
                "difficulty": difficulty,
                "prompt_images": prompt_images,
                "choice_images": choice_images,
                "media": media,
                "question_identifier": question_identifier,
            }
        )
    return items, errors


def import_items(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    domain = validate_domain(str(payload.get("domain", "")))
    mode = str(payload.get("mode", "vocabulary")).strip()
    text = str(payload.get("text", ""))
    default_topic = str(payload.get("topic", "")).strip()
    default_subtopic = str(payload.get("subtopic", "")).strip()
    default_difficulty = str(payload.get("difficulty", "")).strip()
    source_id_raw = payload.get("source_id")
    source_id = int(source_id_raw) if source_id_raw not in (None, "", "null") else None

    if not text.strip():
        raise ValueError("Import text is required.")
    if not source_exists(conn, source_id, domain):
        raise ValueError("Selected source does not match that practice area.")

    if mode == "vocabulary":
        if domain != "vocabulary":
            raise ValueError("Vocabulary import can only be used with the vocabulary area.")
        items, errors = parse_vocab_import(text)
    elif mode == "questions_tsv":
        items, errors = parse_questions_tsv(text, domain)
    elif mode == "questions_json":
        items, errors = parse_questions_json(text, domain)
    else:
        raise ValueError("Unknown import format.")

    created: list[dict[str, Any]] = []
    for item in items:
        item["source_id"] = source_id
        if domain != "vocabulary":
            item["topic"] = item.get("topic") or default_topic
            item["subtopic"] = item.get("subtopic") or default_subtopic
            item["difficulty"] = item.get("difficulty") or default_difficulty
        created.append(create_item(conn, item))
    return {"created": len(created), "items": created, "errors": errors}


def list_sources(conn: sqlite3.Connection, domain: Optional[str] = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if domain:
        validate_domain(domain)
        where = "WHERE s.domain = ?"
        params.append(domain)
    rows = conn.execute(
        f"""
        SELECT s.*,
               COUNT(DISTINCT i.id) AS item_count,
               COUNT(DISTINCT sp.id) AS page_count
        FROM sources s
        LEFT JOIN items i ON i.source_id = s.id AND i.active = 1
        LEFT JOIN source_pages sp ON sp.source_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.created_at DESC, s.id DESC
        """,
        params,
    ).fetchall()
    return [row_to_source(row) for row in rows]


def list_items(conn: sqlite3.Connection, domain: Optional[str] = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "WHERE active = 1"
    if domain:
        validate_domain(domain)
        where += " AND domain = ?"
        params.append(domain)
    rows = conn.execute(
        f"""
        SELECT *
        FROM items
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT 250
        """,
        params,
    ).fetchall()
    return [row_to_item(row) for row in rows]


def app_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    now = iso()
    stats: dict[str, Any] = {}
    for domain in DOMAINS:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN seen_count = 0 THEN 1 ELSE 0 END) AS unseen,
                SUM(CASE WHEN needs_review = 1 THEN 1 ELSE 0 END) AS review,
                SUM(CASE WHEN next_due_at IS NOT NULL AND next_due_at <= ? THEN 1 ELSE 0 END) AS due,
                SUM(seen_count) AS seen_attempts,
                SUM(correct_count) AS correct_answers,
                SUM(wrong_count) AS wrong_answers
            FROM items
            WHERE domain = ? AND active = 1
            """,
            (now, domain),
        ).fetchone()
        source_row = conn.execute(
            "SELECT COUNT(*) AS total FROM sources WHERE domain = ?", (domain,)
        ).fetchone()
        topic_stats: dict[str, Any] = {}
        for topic in TOPICS[domain]:
            topic_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN seen_count = 0 THEN 1 ELSE 0 END) AS unseen,
                    SUM(CASE WHEN needs_review = 1 THEN 1 ELSE 0 END) AS review,
                    SUM(CASE WHEN next_due_at IS NOT NULL AND next_due_at <= ? THEN 1 ELSE 0 END) AS due
                FROM items
                WHERE domain = ? AND active = 1 AND topic = ?
                """,
                (now, domain, topic),
            ).fetchone()
            topic_stats[topic] = {
                "total": topic_row["total"] or 0,
                "unseen": topic_row["unseen"] or 0,
                "review": topic_row["review"] or 0,
                "due": topic_row["due"] or 0,
            }
        difficulty_rows = conn.execute(
            """
            SELECT difficulty, COUNT(*) AS total
            FROM items
            WHERE domain = ? AND active = 1 AND difficulty != ''
            GROUP BY difficulty
            """,
            (domain,),
        ).fetchall()
        stats[domain] = {
            "total": row["total"] or 0,
            "unseen": row["unseen"] or 0,
            "review": row["review"] or 0,
            "due": row["due"] or 0,
            "seen_attempts": row["seen_attempts"] or 0,
            "correct_answers": row["correct_answers"] or 0,
            "wrong_answers": row["wrong_answers"] or 0,
            "sources": source_row["total"] or 0,
            "topics": topic_stats,
            "difficulties": {row["difficulty"]: row["total"] for row in difficulty_rows},
        }
    attempts = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM attempts
        """
    ).fetchone()
    return {
        "domains": stats,
        "attempts": {
            "total": attempts["total"] or 0,
            "correct": attempts["correct"] or 0,
        },
        "database": str(DB_PATH),
        "taxonomy": taxonomy(),
    }


def fetch_bucket(
    conn: sqlite3.Connection,
    domain: str,
    limit: int,
    where: str,
    params: tuple[Any, ...] = (),
    exclude: Optional[set[int]] = None,
    topics: Optional[list[str]] = None,
    difficulties: Optional[list[str]] = None,
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []
    exclude = exclude or set()
    topics = topics or []
    difficulties = difficulties or []
    exclude_sql = ""
    bind: list[Any] = [domain, *params]
    topic_sql = ""
    if topics:
        placeholders = ",".join("?" for _ in topics)
        topic_sql = f" AND topic IN ({placeholders})"
        bind.extend(topics)
    difficulty_sql = ""
    if difficulties:
        placeholders = ",".join("?" for _ in difficulties)
        difficulty_sql = f" AND difficulty IN ({placeholders})"
        bind.extend(difficulties)
    if exclude:
        placeholders = ",".join("?" for _ in exclude)
        exclude_sql = f" AND id NOT IN ({placeholders})"
        bind.extend(exclude)
    return conn.execute(
        f"""
        SELECT *
        FROM items
        WHERE domain = ?
          AND active = 1
          AND {where}
          {topic_sql}
          {difficulty_sql}
          {exclude_sql}
        ORDER BY source_id IS NULL, source_id, id
        LIMIT ?
        """,
        (*bind, limit),
    ).fetchall()


def fetch_balanced_bucket(
    conn: sqlite3.Connection,
    domain: str,
    limit: int,
    where: str,
    params: tuple[Any, ...] = (),
    exclude: Optional[set[int]] = None,
    topics: Optional[list[str]] = None,
    difficulties: Optional[list[str]] = None,
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []
    if not TOPICS[domain]:
        return fetch_bucket(conn, domain, limit, where, params, exclude, topics, difficulties)

    selected: list[sqlite3.Row] = []
    selected_ids = set(exclude or set())
    topic_pool = list(topics or TOPICS[domain])

    made_progress = True
    while len(selected) < limit and made_progress and topic_pool:
        made_progress = False
        round_topics = topic_pool[:]
        random.shuffle(round_topics)
        for topic in round_topics:
            rows = fetch_bucket(
                conn,
                domain,
                1,
                where,
                params,
                selected_ids,
                [topic],
                difficulties,
            )
            if not rows:
                continue
            selected.append(rows[0])
            selected_ids.add(rows[0]["id"])
            made_progress = True
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        fallback_topics = topics if topics else None
        rows = fetch_bucket(
            conn,
            domain,
            limit - len(selected),
            where,
            params,
            selected_ids,
            fallback_topics,
            difficulties,
        )
        selected.extend(rows)
    return selected


def choose_items(
    conn: sqlite3.Connection,
    domain: str,
    count: int,
    mode: str,
    topics: Optional[list[str]] = None,
    difficulties: Optional[list[str]] = None,
) -> list[sqlite3.Row]:
    validate_domain(domain)
    count = max(1, min(count, 50))
    now = iso()
    topics = topics or []
    difficulties = difficulties or []

    if mode == "review":
        rows = fetch_balanced_bucket(
            conn,
            domain,
            count,
            "needs_review = 1",
            (),
            None,
            topics,
            difficulties,
        )
        rows = list(rows)
        random.shuffle(rows)
        return rows

    selected: list[sqlite3.Row] = []
    selected_ids: set[int] = set()

    for where, params in (
        ("seen_count = 0", ()),
        ("next_due_at IS NOT NULL AND next_due_at <= ?", (now,)),
        ("seen_count > 0", ()),
    ):
        rows = fetch_balanced_bucket(
            conn,
            domain,
            count - len(selected),
            where,
            params,
            selected_ids,
            topics,
            difficulties,
        )
        selected.extend(rows)
        selected_ids.update(row["id"] for row in rows)
        if len(selected) >= count:
            break

    if not TOPICS[domain]:
        random.shuffle(selected)
    return selected


def choose_flashcards(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM items
        WHERE domain = 'vocabulary' AND active = 1
        ORDER BY
            CASE WHEN seen_count = 0 THEN 0 ELSE 1 END,
            COALESCE(next_due_at, ''),
            source_id IS NULL,
            source_id,
            id
        """
    ).fetchall()


def vocab_distractors(
    conn: sqlite3.Connection, item_id: int, field: str, answer: str, limit: int = 3
) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT {field} AS value
        FROM items
        WHERE domain = 'vocabulary'
          AND active = 1
          AND id != ?
        ORDER BY RANDOM()
        LIMIT 20
        """,
        (item_id,),
    ).fetchall()
    seen = {normalize_choice(answer)}
    values: list[str] = []
    for row in rows:
        value = str(row["value"]).strip()
        norm = normalize_choice(value)
        if value and norm not in seen:
            values.append(value)
            seen.add(norm)
        if len(values) >= limit:
            break
    return values


def session_card(
    conn: sqlite3.Connection, row: sqlite3.Row, mode: str, direction: str
) -> dict[str, Any]:
    item = row_to_item(row)
    if item["item_type"] == "vocab":
        actual_direction = direction
        if actual_direction == "mixed":
            actual_direction = random.choice(("word_to_definition", "definition_to_word"))

        if mode == "flashcards":
            if actual_direction == "definition_to_word":
                item["front"] = item["answer"]
                item["back"] = item["prompt"]
                item["front_label"] = "Definition"
                item["back_label"] = "Word"
            else:
                item["front"] = item["prompt"]
                item["back"] = item["answer"]
                item["front_label"] = "Word"
                item["back_label"] = "Definition"
            item["direction"] = actual_direction
            return item

        if actual_direction == "definition_to_word":
            answer = item["prompt"]
            choices = [answer, *vocab_distractors(conn, item["id"], "prompt", answer)]
            prompt = f"Choose the word that matches this definition:\n\n{item['answer']}"
        else:
            answer = item["answer"]
            choices = [answer, *vocab_distractors(conn, item["id"], "answer", answer)]
            prompt = f"Choose the best meaning for:\n\n{item['prompt']}"
        random.shuffle(choices)
        item.update(
            {
                "question_prompt": prompt,
                "answer": answer,
                "choices": choices if len(choices) >= 3 else [],
                "self_grade": len(choices) < 3,
                "direction": actual_direction,
            }
        )
        return item

    choices = item["choices"]
    media = item.get("media", {})
    choice_images = list(media.get("choice_images", []))
    choice_images = (choice_images + [""] * len(choices))[: len(choices)]
    choice_pairs = list(zip(choices, choice_images))
    label_only_choices = choices == ["A", "B", "C", "D"]
    if not label_only_choices:
        random.shuffle(choice_pairs)
    item["choices"] = [choice for choice, _image in choice_pairs]
    item["media"]["choice_images"] = [image for _choice, image in choice_pairs]
    item["question_prompt"] = item["prompt"]
    item["self_grade"] = len(item["choices"]) < 2
    return item


def public_card(card: dict[str, Any], include_results: bool = False) -> dict[str, Any]:
    visible = dict(card)
    if not include_results:
        visible.pop("answer", None)
        visible.pop("explanation", None)
    return visible


def first_unanswered_position(items: list[dict[str, Any]]) -> int:
    for item in items:
        if not item.get("answered"):
            return int(item["position"])
    return len(items)


def session_response(
    conn: sqlite3.Connection,
    session_id: int,
    include_results: bool = False,
) -> dict[str, Any]:
    session = conn.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError("Practice session was not found.")

    include_results = include_results or session["status"] == "completed"
    item_rows = conn.execute(
        """
        SELECT *
        FROM practice_session_items
        WHERE session_id = ?
        ORDER BY position
        """,
        (session_id,),
    ).fetchall()

    items: list[dict[str, Any]] = []
    answered_count = 0
    for item_row in item_rows:
        card = parse_json(item_row["card_json"], {})
        if item_row["answered_at"]:
            answered_count += 1
        card["position"] = item_row["position"]
        card["session_item_id"] = item_row["id"]
        card["selected_answer"] = item_row["selected_answer"]
        card["answered"] = bool(item_row["answered_at"])
        if include_results:
            card["correct"] = bool(item_row["correct"])
        items.append(public_card(card, include_results))

    filters = parse_json(session["filters_json"], {})
    return {
        "session_id": session["id"],
        "domain": session["domain"],
        "mode": session["mode"],
        "status": session["status"],
        "count": len(items),
        "requested_count": session["requested_count"],
        "answered_count": answered_count,
        "current_position": first_unanswered_position(items),
        "score": session["score"] if include_results else None,
        "endless": False,
        "filters": filters,
        "direction": session["direction"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "completed_at": session["completed_at"],
        "items": items,
    }


def store_session(
    conn: sqlite3.Connection,
    domain: str,
    mode: str,
    count: int,
    direction: str,
    filters: dict[str, Any],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    now = iso()
    cur = conn.execute(
        """
        INSERT INTO practice_sessions (
            domain, mode, status, requested_count, filters_json, direction,
            created_at, updated_at
        ) VALUES (?, ?, 'in_progress', ?, ?, ?, ?, ?)
        """,
        (domain, mode, count, json.dumps(filters), direction, now, now),
    )
    session_id = int(cur.lastrowid)
    for position, card in enumerate(cards):
        conn.execute(
            """
            INSERT INTO practice_session_items (
                session_id, position, item_id, card_json
            ) VALUES (?, ?, ?, ?)
            """,
            (session_id, position, card["id"], json.dumps(card)),
        )
    return session_response(conn, session_id)


def save_session_answer(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = int(payload.get("session_id") or 0)
    position = int(payload.get("position") or 0)
    selected_answer = str(payload.get("selected_answer", "")).strip()
    if not selected_answer:
        raise ValueError("Choose or enter an answer before continuing.")

    session = conn.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError("Practice session was not found.")
    if session["status"] != "in_progress":
        raise ValueError("This practice session is already complete.")

    item_row = conn.execute(
        """
        SELECT *
        FROM practice_session_items
        WHERE session_id = ? AND position = ?
        """,
        (session_id, position),
    ).fetchone()
    if item_row is None:
        raise ValueError("Practice question was not found.")

    card = parse_json(item_row["card_json"], {})
    correct = normalize_choice(selected_answer) == normalize_choice(str(card.get("answer", "")))
    answered_at = iso()
    conn.execute(
        """
        UPDATE practice_session_items
        SET selected_answer = ?, correct = ?, answered_at = ?
        WHERE id = ?
        """,
        (selected_answer, int(correct), answered_at, item_row["id"]),
    )
    conn.execute(
        "UPDATE practice_sessions SET updated_at = ? WHERE id = ?",
        (answered_at, session_id),
    )
    return session_response(conn, session_id)


def complete_session(conn: sqlite3.Connection, session_id: int) -> dict[str, Any]:
    session = conn.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError("Practice session was not found.")
    if session["status"] == "completed":
        return session_response(conn, session_id, include_results=True)

    rows = conn.execute(
        """
        SELECT *
        FROM practice_session_items
        WHERE session_id = ?
        ORDER BY position
        """,
        (session_id,),
    ).fetchall()
    if any(row["answered_at"] is None for row in rows):
        raise ValueError("Answer every question before finishing the test.")

    score = 0
    for row in rows:
        correct = bool(row["correct"])
        score += int(correct)
        update_after_attempt(
            conn,
            {
                "item_id": row["item_id"],
                "mode": session["mode"],
                "selected_answer": row["selected_answer"],
                "correct": correct,
            },
        )

    completed_at = iso()
    conn.execute(
        """
        UPDATE practice_sessions
        SET status = 'completed', score = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (score, completed_at, completed_at, session_id),
    )
    return session_response(conn, session_id, include_results=True)


def active_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ps.*,
               COUNT(psi.id) AS item_count,
               SUM(CASE WHEN psi.answered_at IS NOT NULL THEN 1 ELSE 0 END) AS answered_count
        FROM practice_sessions ps
        JOIN practice_session_items psi ON psi.session_id = ps.id
        WHERE ps.status = 'in_progress' AND ps.mode IN ('test', 'review')
        GROUP BY ps.id
        ORDER BY ps.updated_at DESC
        LIMIT 8
        """
    ).fetchall()
    return [
        {
            "session_id": row["id"],
            "domain": row["domain"],
            "mode": row["mode"],
            "requested_count": row["requested_count"],
            "count": row["item_count"],
            "answered_count": row["answered_count"] or 0,
            "filters": parse_json(row["filters_json"], {}),
            "updated_at": row["updated_at"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def resolve_local_file(locator: str) -> Path:
    locator = locator.strip()
    if not locator:
        raise ValueError("Source has no file path.")
    if locator.startswith(("http://", "https://")):
        raise ValueError("PDF extraction needs a local PDF path, not a web URL.")
    path = Path(locator).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    target = path.resolve()
    if not target.exists() or not target.is_file():
        raise ValueError(f"PDF file was not found: {locator}")
    return target


def media_reference(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def detect_question_identifier(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()][:20]
    preferred = re.compile(
        r"(?:question\s*)?(?:id|identifier)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9_-]{7,})",
        re.IGNORECASE,
    )
    token = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")
    for line in lines:
        match = preferred.search(line)
        if match:
            return clean_question_identifier(match.group(1))
    for line in lines:
        for candidate in token.findall(line):
            if any(char.isalpha() for char in candidate) and any(char.isdigit() for char in candidate):
                return clean_question_identifier(candidate)
    return ""


def extract_pdf_source(conn: sqlite3.Connection, source_id: int) -> dict[str, Any]:
    source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        raise ValueError("Source was not found.")
    if source["kind"] != "pdf":
        raise ValueError("Only PDF sources can be extracted.")

    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "PDF extraction requires PyMuPDF. Install dependencies with: python3 -m pip install -r requirements.txt"
        ) from exc

    pdf_path = resolve_local_file(source["locator"])
    asset_dir = DB_PATH.parent / "assets" / f"source_{source_id}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    page_count = 0
    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc, start=1):
            image_path = asset_dir / f"page-{page_index:03d}.png"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(str(image_path))
            text = page.get_text("text") or ""
            question_identifier = detect_question_identifier(text)
            conn.execute(
                """
                INSERT INTO source_pages (
                    source_id, page_number, question_identifier, text, image_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, page_number)
                DO UPDATE SET
                    question_identifier = excluded.question_identifier,
                    text = excluded.text,
                    image_path = excluded.image_path
                """,
                (
                    source_id,
                    page_index,
                    question_identifier,
                    text,
                    media_reference(image_path),
                    iso(),
                ),
            )
            page_count += 1

    return {
        "source_id": source_id,
        "pages": page_count,
        "asset_dir": media_reference(asset_dir),
    }


def resolve_media_target(raw_path: str) -> Path:
    if not raw_path.strip():
        raise ValueError("Media path is required.")
    path = Path(raw_path).expanduser()
    target = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    allowed_roots = [ROOT.resolve(), DB_PATH.parent.resolve()]
    for root in allowed_roots:
        try:
            target.relative_to(root)
            if target.exists() and target.is_file():
                return target
        except ValueError:
            continue
    raise ValueError("Media file is outside the allowed app directories or does not exist.")


def create_session(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    domain = validate_domain(str(payload.get("domain", "")))
    mode = str(payload.get("mode", "test"))
    count = int(payload.get("count") or 10)
    direction = str(payload.get("direction", "mixed"))
    selected_topics, selected_difficulties = validate_filter_values(
        domain,
        list_payload(payload.get("topics")),
        list_payload(payload.get("difficulties")),
    )
    if direction not in ("mixed", "word_to_definition", "definition_to_word"):
        raise ValueError("Unknown vocabulary direction.")
    if mode == "flashcards":
        domain = "vocabulary"
        selected_topics, selected_difficulties = [], []
    if mode not in ("test", "review", "flashcards"):
        raise ValueError("Unknown session mode.")

    rows = (
        choose_flashcards(conn)
        if mode == "flashcards"
        else choose_items(conn, domain, count, mode, selected_topics, selected_difficulties)
    )
    cards = [session_card(conn, row, mode, direction) for row in rows]
    filters = {
        "topics": selected_topics,
        "difficulties": selected_difficulties,
    }
    if mode in ("test", "review") and cards:
        return store_session(conn, domain, mode, count, direction, filters, cards)

    return {
        "domain": domain,
        "mode": mode,
        "count": len(rows),
        "endless": mode == "flashcards",
        "filters": filters,
        "items": cards,
    }


def update_after_attempt(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = int(payload.get("item_id") or 0)
    mode = str(payload.get("mode", "test"))
    selected_answer = str(payload.get("selected_answer", "")).strip()
    correct = bool(payload.get("correct"))

    row = conn.execute("SELECT * FROM items WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if row is None:
        raise ValueError("Practice item was not found.")

    old_mastery = int(row["mastery"])
    attempted_at = iso()
    if correct:
        mastery = min(old_mastery + 1, 5)
        intervals = (1, 3, 7, 14, 30)
        next_due = iso(utcnow() + timedelta(days=intervals[mastery - 1]))
        needs_review = 0 if mode == "review" or payload.get("clear_review") else row["needs_review"]
        conn.execute(
            """
            UPDATE items
            SET seen_count = seen_count + 1,
                correct_count = correct_count + 1,
                mastery = ?,
                needs_review = ?,
                last_seen_at = ?,
                next_due_at = ?
            WHERE id = ?
            """,
            (mastery, int(needs_review), attempted_at, next_due, item_id),
        )
    else:
        next_due = iso(utcnow() + timedelta(days=1))
        conn.execute(
            """
            UPDATE items
            SET seen_count = seen_count + 1,
                wrong_count = wrong_count + 1,
                mastery = 0,
                needs_review = 1,
                last_seen_at = ?,
                next_due_at = ?
            WHERE id = ?
            """,
            (attempted_at, next_due, item_id),
        )

    conn.execute(
        """
        INSERT INTO attempts (item_id, domain, mode, selected_answer, correct, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, row["domain"], mode, selected_answer, int(correct), attempted_at),
    )
    updated = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row_to_item(updated)


def clear_review(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM items WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if row is None:
        raise ValueError("Practice item was not found.")
    conn.execute("UPDATE items SET needs_review = 0 WHERE id = ?", (item_id,))
    return row_to_item(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def reset_domain_progress(conn: sqlite3.Connection, domain: str) -> dict[str, Any]:
    domain = validate_domain(domain)
    item_count = conn.execute(
        "SELECT COUNT(*) AS total FROM items WHERE domain = ?",
        (domain,),
    ).fetchone()["total"]
    attempt_count = conn.execute(
        "SELECT COUNT(*) AS total FROM attempts WHERE domain = ?",
        (domain,),
    ).fetchone()["total"]
    session_count = conn.execute(
        "SELECT COUNT(*) AS total FROM practice_sessions WHERE domain = ?",
        (domain,),
    ).fetchone()["total"]

    conn.execute("DELETE FROM attempts WHERE domain = ?", (domain,))
    conn.execute(
        """
        DELETE FROM practice_session_items
        WHERE session_id IN (
            SELECT id FROM practice_sessions WHERE domain = ?
        )
        """,
        (domain,),
    )
    conn.execute("DELETE FROM practice_sessions WHERE domain = ?", (domain,))
    conn.execute(
        """
        UPDATE items
        SET seen_count = 0,
            correct_count = 0,
            wrong_count = 0,
            mastery = 0,
            needs_review = 0,
            last_seen_at = NULL,
            next_due_at = NULL
        WHERE domain = ?
        """,
        (domain,),
    )
    return {
        "ok": True,
        "domain": domain,
        "items_reset": item_count,
        "attempts_deleted": attempt_count,
        "sessions_deleted": session_count,
    }


class PrepHandler(BaseHTTPRequestHandler):
    server_version = "PSATPrep/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, rel_path: str) -> None:
        target = (ROOT / rel_path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN.value)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_media(self, raw_path: str) -> None:
        target = resolve_media_target(raw_path)
        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path in ("", "/"):
            self.send_static("index.html")
            return
        if path.startswith("/static/"):
            self.send_static(path.lstrip("/"))
            return
        if path == "/api/media":
            self.send_media(query.get("path", [""])[0])
            return

        with get_db() as conn:
            if path == "/api/stats":
                self.send_json(app_stats(conn))
            elif path == "/api/taxonomy":
                self.send_json(taxonomy())
            elif path == "/api/sessions/active":
                self.send_json({"sessions": active_sessions(conn)})
            elif path == "/api/session":
                self.send_json(
                    session_response(conn, int(query.get("session_id", ["0"])[0]))
                )
            elif path == "/api/sources":
                domain = query.get("domain", [None])[0]
                self.send_json({"sources": list_sources(conn, domain)})
            elif path == "/api/items":
                domain = query.get("domain", [None])[0]
                self.send_json({"items": list_items(conn, domain)})
            elif path == "/api/export":
                self.send_json(
                    {
                        "exported_at": iso(),
                        "sources": list_sources(conn),
                        "items": list_items(conn),
                    }
                )
            else:
                self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def route_post(self, path: str) -> None:
        payload = self.read_json()
        with get_db() as conn:
            if path == "/api/sources":
                domain = validate_domain(str(payload.get("domain", "")))
                title = str(payload.get("title", "")).strip()
                if not title:
                    raise ValueError("Source title is required.")
                cur = conn.execute(
                    """
                    INSERT INTO sources (title, domain, kind, locator, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title,
                        domain,
                        str(payload.get("kind", "link")).strip() or "link",
                        str(payload.get("locator", "")).strip(),
                        str(payload.get("notes", "")).strip(),
                        iso(),
                    ),
                )
                source = conn.execute(
                    "SELECT *, 0 AS item_count, 0 AS page_count FROM sources WHERE id = ?",
                    (cur.lastrowid,),
                ).fetchone()
                self.send_json(row_to_source(source), HTTPStatus.CREATED)
            elif path == "/api/items":
                self.send_json(create_item(conn, payload), HTTPStatus.CREATED)
            elif path == "/api/import":
                self.send_json(import_items(conn, payload), HTTPStatus.CREATED)
            elif path == "/api/session":
                self.send_json(create_session(conn, payload))
            elif path == "/api/session/answer":
                self.send_json(save_session_answer(conn, payload))
            elif path == "/api/session/complete":
                self.send_json(complete_session(conn, int(payload.get("session_id") or 0)))
            elif path == "/api/attempts":
                self.send_json(update_after_attempt(conn, payload))
            elif path == "/api/review/clear":
                self.send_json(clear_review(conn, int(payload.get("item_id") or 0)))
            elif path == "/api/progress/reset":
                self.send_json(reset_domain_progress(conn, str(payload.get("domain", ""))))
            elif path == "/api/sources/extract":
                self.send_json(extract_pdf_source(conn, int(payload.get("source_id") or 0)))
            else:
                self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            self.route_get(parsed.path, parse_qs(parsed.query))
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - keeps local server debuggable.
            self.send_json({"error": f"Server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self.route_post(parsed.path)
        except json.JSONDecodeError:
            self.send_json({"error": "Request body must be valid JSON."}, HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - keeps local server debuggable.
            self.send_json({"error": f"Server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), PrepHandler)
    print(f"PSAT Prep is running at http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()

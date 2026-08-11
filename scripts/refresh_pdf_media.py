#!/usr/bin/env python3
"""Refresh rendered PDF prompt and choice images without resetting progress."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import app  # noqa: E402
from import_sources import (  # noqa: E402
    SOURCE_FILES,
    group_question_pages,
    render_question_media,
)

try:
    import pymupdf as fitz  # type: ignore
except ImportError:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - user-facing setup path.
        raise SystemExit(
            "PyMuPDF is required. Install dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc
except Exception as exc:  # pragma: no cover - user-facing setup path.
    raise SystemExit(
        "PyMuPDF is required. Install dependencies with: "
        "python3 -m pip install -r requirements.txt"
    ) from exc


QUESTION_DOMAINS = {
    "math": SOURCE_FILES["math"],
    "english": SOURCE_FILES["english"],
}


def merge_pdf_media(
    existing_media: dict[str, Any],
    source_pages: list[int],
    prompt_images: list[str],
    choice_images: list[str],
    choice_count: int,
) -> dict[str, Any]:
    media = dict(existing_media)
    media["source_pages"] = source_pages
    media["prompt_images"] = prompt_images
    media["choice_images"] = (choice_images + [""] * choice_count)[:choice_count]
    if prompt_images:
        media["prompt_image_mode"] = "primary"
    else:
        media.pop("prompt_image_mode", None)
    if any(choice_images):
        media["choice_image_mode"] = "primary"
    else:
        media.pop("choice_image_mode", None)
    return media


def refresh_domain(conn: Any, domain: str, pdf_path: Path) -> tuple[int, int]:
    if not pdf_path.exists():
        raise SystemExit(f"Missing source PDF: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    groups = group_question_pages(doc)
    updated = 0
    missing = 0

    for index, group in enumerate(groups, start=1):
        rows = conn.execute(
            """
            SELECT id, choices_json, media_json
            FROM items
            WHERE domain = ? AND question_identifier = ?
            """,
            (domain, group["qid"]),
        ).fetchall()
        if not rows:
            missing += 1
            continue

        max_choice_count = max(
            len(app.parse_json(row["choices_json"], []))
            for row in rows
        )
        prompt_images, choice_images = render_question_media(
            doc,
            group,
            domain,
            max_choice_count,
        )
        source_pages = [int(page["page_number"]) for page in group["pages"]]

        for row in rows:
            choice_count = len(app.parse_json(row["choices_json"], []))
            media = merge_pdf_media(
                app.parse_json(row["media_json"], {}),
                source_pages,
                prompt_images,
                choice_images,
                choice_count,
            )
            conn.execute(
                "UPDATE items SET media_json = ? WHERE id = ?",
                (json.dumps(media), row["id"]),
            )
            updated += 1

        if index % 100 == 0:
            print(f"{domain}: refreshed media for {index}/{len(groups)} PDF questions", flush=True)

    return updated, missing


def main() -> None:
    app.init_db()
    results: dict[str, dict[str, int]] = {}
    with app.get_db() as conn:
        for domain, pdf_path in QUESTION_DOMAINS.items():
            updated, missing = refresh_domain(conn, domain, pdf_path)
            results[domain] = {"updated": updated, "missing": missing}
            print(f"{domain}: updated {updated}, missing {missing}", flush=True)

    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from scripts import import_sources


class ExtractedTextCleanupTests(unittest.TestCase):
    def test_removes_math_output_error_markers_and_repairs_punctuation(self) -> None:
        text = import_sources.compact_text(
            [
                "The area is Math output error, where",
                "MATH OUTPUT ERROR is the length.",
            ]
        )

        self.assertEqual(text, "The area is, where is the length.")

    def test_removes_marker_split_across_lines(self) -> None:
        text = import_sources.remove_pdf_error_markers(
            "The formula has a Math output\nerror placeholder."
        )

        self.assertEqual(text, "The formula has a  placeholder.")

    def test_preserves_legitimate_error_language(self) -> None:
        text = import_sources.clean_line(
            "Choice B may result from conceptual or calculation errors."
        )

        self.assertEqual(
            text,
            "Choice B may result from conceptual or calculation errors.",
        )


class ChoiceCropTests(unittest.TestCase):
    def test_choice_top_expands_for_formula_image_above_label(self) -> None:
        marker = {"bbox": import_sources.fitz.Rect(18.03, 232.03, 28.50, 241.32)}
        formula = import_sources.fitz.Rect(28.50, 218.25, 125.25, 260.25)

        top = import_sources.choice_top_for_marker(
            marker,
            minimum_top=215.89,
            visual_rects=[formula],
        )

        self.assertAlmostEqual(top, 215.89, places=2)
        self.assertLess(top, 232.03 - import_sources.PDF_CLIP_MARGIN)

    def test_choice_top_ignores_previous_choice_image(self) -> None:
        marker = {"bbox": import_sources.fitz.Rect(18.30, 273.28, 28.50, 282.57)}
        previous_formula = import_sources.fitz.Rect(28.50, 218.25, 125.25, 260.25)
        current_formula = import_sources.fitz.Rect(28.50, 269.25, 123.00, 291.75)

        top = import_sources.choice_top_for_marker(
            marker,
            minimum_top=242.32,
            visual_rects=[previous_formula, current_formula],
        )

        self.assertAlmostEqual(top, 263.25, places=2)


class SourceFileDiscoveryTests(unittest.TestCase):
    def test_accepts_any_pdf_filename_in_section_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            expected = source_dir / "college-board-sat-export.PDF"
            expected.touch()
            with mock.patch.dict(
                import_sources.SOURCE_DIRECTORIES, {"math": source_dir}
            ):
                self.assertEqual(import_sources.resolve_source_file("math"), expected)

    def test_rejects_ambiguous_section_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "one.pdf").touch()
            (source_dir / "two.pdf").touch()
            with mock.patch.dict(
                import_sources.SOURCE_DIRECTORIES, {"english": source_dir}
            ):
                with self.assertRaisesRegex(ValueError, "Multiple PDF sources"):
                    import_sources.resolve_source_file("english")


class SectionFlushTests(unittest.TestCase):
    def test_flushes_selected_sections_and_preserves_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with mock.patch.object(import_sources.app, "DB_PATH", db_path):
                setup_conn = sqlite3.connect(db_path)
                setup_conn.row_factory = sqlite3.Row
                setup_conn.execute("PRAGMA foreign_keys = ON")
                with mock.patch.object(
                    import_sources.app, "get_db", return_value=setup_conn
                ):
                    import_sources.app.init_db()
                setup_conn.close()
                with closing(import_sources.app.get_db()) as conn:
                    ids = self._seed_domains(conn)
                    assets = db_path.parent / "assets"
                    for domain in import_sources.app.DOMAINS:
                        (assets / "questions" / domain).mkdir(parents=True)
                        (assets / "questions" / domain / "image.png").touch()
                        (assets / f"source_{ids[domain][0]}").mkdir()

                    import_sources.flush_sections(conn, {"math", "english"})

                    for table in ("items", "attempts", "practice_sessions", "sources"):
                        rows = [
                            tuple(row)
                            for row in conn.execute(
                                f"SELECT domain, COUNT(*) FROM {table} GROUP BY domain"
                            )
                        ]
                        self.assertEqual(rows, [("vocabulary", 1)])
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0], 1
                    )
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM practice_session_items").fetchone()[0],
                        1,
                    )
                    self.assertTrue((assets / "questions" / "vocabulary").exists())
                    self.assertFalse((assets / "questions" / "math").exists())
                    self.assertFalse((assets / "questions" / "english").exists())
                    self.assertTrue((assets / f"source_{ids['vocabulary'][0]}").exists())

    @staticmethod
    def _seed_domains(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
        ids: dict[str, tuple[int, int]] = {}
        for domain in import_sources.app.DOMAINS:
            source_id = conn.execute(
                """
                INSERT INTO sources (title, domain, kind, locator, notes, created_at)
                VALUES (?, ?, 'pdf', ?, '', ?)
                """,
                (domain, domain, f"sources/{domain}/source.pdf", import_sources.app.iso()),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO source_pages
                    (source_id, page_number, question_identifier, text, image_path, created_at)
                VALUES (?, 1, '', '', '', ?)
                """,
                (source_id, import_sources.app.iso()),
            )
            payload = {
                "domain": domain,
                "source_id": source_id,
                "item_type": "vocab" if domain == "vocabulary" else "multiple_choice",
                "prompt": f"{domain} prompt",
                "answer": "definition" if domain == "vocabulary" else "A",
            }
            if domain != "vocabulary":
                payload["choices"] = ["A", "B", "C", "D"]
                payload["topic"] = import_sources.app.TOPICS[domain][0]
                payload["difficulty"] = "Easy"
            item_id = import_sources.app.create_item(conn, payload)["id"]
            conn.execute(
                """
                INSERT INTO attempts
                    (item_id, domain, mode, selected_answer, correct, attempted_at)
                VALUES (?, ?, 'test', '', 0, ?)
                """,
                (item_id, domain, import_sources.app.iso()),
            )
            session_id = conn.execute(
                """
                INSERT INTO practice_sessions
                    (domain, mode, status, requested_count, created_at, updated_at)
                VALUES (?, 'test', 'completed', 1, ?, ?)
                """,
                (domain, import_sources.app.iso(), import_sources.app.iso()),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO practice_session_items
                    (session_id, position, item_id, card_json)
                VALUES (?, 1, ?, '{}')
                """,
                (session_id, item_id),
            )
            ids[domain] = (int(source_id), int(item_id))
        return ids


class FlushConfirmationTests(unittest.TestCase):
    def test_confirmation_defaults_to_no(self) -> None:
        with mock.patch("builtins.input", return_value=""):
            self.assertFalse(import_sources.confirm_flush(("math", "english")))

    def test_confirmation_accepts_yes(self) -> None:
        with mock.patch("builtins.input", return_value="yes"):
            self.assertTrue(import_sources.confirm_flush(("math",)))


if __name__ == "__main__":
    unittest.main()

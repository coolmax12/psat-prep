import json
import sqlite3
import unittest

import app


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            source_id INTEGER,
            item_type TEXT NOT NULL DEFAULT 'multiple_choice',
            prompt TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
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
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            mode TEXT NOT NULL,
            selected_answer TEXT NOT NULL DEFAULT '',
            correct INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE practice_sessions (
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE practice_session_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            card_json TEXT NOT NULL,
            selected_answer TEXT NOT NULL DEFAULT '',
            correct INTEGER,
            answered_at TEXT,
            UNIQUE(session_id, position)
        )
        """
    )
    return conn


def add_item(
    conn: sqlite3.Connection,
    domain: str,
    topic: str,
    difficulty: str = "Medium",
    seen_count: int = 0,
    correct_count: int = 0,
    wrong_count: int = 0,
    needs_review: int = 0,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO items (
            domain, prompt, answer, topic, difficulty, seen_count,
            correct_count, wrong_count, needs_review
        ) VALUES (?, ?, 'A', ?, ?, ?, ?, ?, ?)
        """,
        (
            domain,
            f"{topic} {difficulty}",
            topic,
            difficulty,
            seen_count,
            correct_count,
            wrong_count,
            needs_review,
        ),
    )
    return int(cur.lastrowid)


class ChooseItemsTests(unittest.TestCase):
    def test_math_test_includes_each_fresh_topic_before_extra_hard_items(self) -> None:
        conn = make_conn()
        add_item(conn, "math", "Algebra", "Hard")
        for _ in range(4):
            add_item(conn, "math", "Algebra", "Hard")
        for topic in app.TOPICS["math"]:
            if topic != "Algebra":
                add_item(conn, "math", topic, "Medium")

        rows = app.choose_items(conn, "math", 4, "test")

        self.assertEqual({row["topic"] for row in rows}, set(app.TOPICS["math"]))

    def test_reading_writing_test_skips_exhausted_topic_for_coverage(self) -> None:
        conn = make_conn()
        exhausted_topic = "Expression of Ideas"
        for topic in app.TOPICS["english"]:
            add_item(
                conn,
                "english",
                topic,
                "Medium",
                seen_count=1 if topic == exhausted_topic else 0,
            )

        rows = app.choose_items(conn, "english", 3, "test")

        self.assertEqual(len(rows), 3)
        self.assertNotIn(exhausted_topic, {row["topic"] for row in rows})

    def test_topic_filter_limits_required_coverage(self) -> None:
        conn = make_conn()
        selected_topics = ["Information and Ideas", "Craft and Structure"]
        for topic in app.TOPICS["english"]:
            add_item(conn, "english", topic, "Medium")
            add_item(conn, "english", topic, "Hard")

        rows = app.choose_items(conn, "english", 4, "test", selected_topics, [])
        topics = {row["topic"] for row in rows}

        self.assertEqual(topics, set(selected_topics))

    def test_hard_target_still_counts_coverage_items(self) -> None:
        conn = make_conn()
        for topic in app.TOPICS["math"]:
            add_item(conn, "math", topic, "Medium")
        for _ in range(10):
            add_item(conn, "math", "Algebra", "Hard")

        rows = app.choose_items(conn, "math", 10, "test")
        hard_count = sum(1 for row in rows if row["difficulty"] == "Hard")

        self.assertGreaterEqual(hard_count, 4)
        self.assertEqual(set(app.TOPICS["math"]), {row["topic"] for row in rows})

    def test_normal_test_holds_correct_seen_items_until_pool_is_exhausted(self) -> None:
        conn = make_conn()
        correct_seen_id = add_item(
            conn,
            "math",
            "Algebra",
            "Hard",
            seen_count=1,
            correct_count=1,
        )
        fresh_id = add_item(conn, "math", "Advanced Math", "Medium")

        rows = app.choose_items(conn, "math", 4, "test")
        selected_ids = {row["id"] for row in rows}

        self.assertEqual(selected_ids, {fresh_id})
        self.assertNotIn(correct_seen_id, selected_ids)

    def test_normal_test_reuses_seen_items_after_pool_is_exhausted(self) -> None:
        conn = make_conn()
        item_ids = {
            add_item(conn, "math", "Algebra", "Medium", seen_count=1, correct_count=1),
            add_item(conn, "math", "Advanced Math", "Hard", seen_count=1, correct_count=1),
        }

        rows = app.choose_items(conn, "math", 2, "test")

        self.assertEqual({row["id"] for row in rows}, item_ids)


class ProgressUpdateTests(unittest.TestCase):
    def test_correct_test_attempt_clears_review_flag(self) -> None:
        conn = make_conn()
        item_id = add_item(
            conn,
            "math",
            "Algebra",
            seen_count=1,
            wrong_count=1,
            needs_review=1,
        )

        item = app.update_after_attempt(
            conn,
            {
                "item_id": item_id,
                "mode": "test",
                "selected_answer": "A",
                "correct": True,
            },
        )

        self.assertFalse(item["needs_review"])

    def test_migration_clears_stale_review_when_latest_attempt_is_correct(self) -> None:
        conn = make_conn()
        item_id = add_item(
            conn,
            "math",
            "Algebra",
            seen_count=2,
            correct_count=1,
            wrong_count=1,
            needs_review=1,
        )
        conn.executemany(
            """
            INSERT INTO attempts (item_id, domain, mode, selected_answer, correct, attempted_at)
            VALUES (?, 'math', 'test', 'A', ?, ?)
            """,
            [
                (item_id, 0, "2026-01-01T00:00:00Z"),
                (item_id, 1, "2026-01-02T00:00:00Z"),
            ],
        )

        app.migrate_db(conn)

        needs_review = conn.execute(
            "SELECT needs_review FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()["needs_review"]
        self.assertEqual(needs_review, 0)


class SessionCompletionTests(unittest.TestCase):
    def test_unanswered_questions_are_scored_incorrect_when_submitted(self) -> None:
        conn = make_conn()
        answered_id = add_item(conn, "math", "Algebra")
        unanswered_id = add_item(conn, "math", "Advanced Math")
        session_id = int(
            conn.execute(
                """
                INSERT INTO practice_sessions (
                    domain, mode, requested_count, created_at, updated_at
                ) VALUES ('math', 'test', 2, ?, ?)
                """,
                ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            ).lastrowid
        )
        for position, item_id in enumerate((answered_id, unanswered_id)):
            card = {
                "id": item_id,
                "domain": "math",
                "prompt": f"Question {position + 1}",
                "answer": "A",
                "choices": ["A", "B", "C", "D"],
            }
            conn.execute(
                """
                INSERT INTO practice_session_items (
                    session_id, position, item_id, card_json,
                    selected_answer, correct, answered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    position,
                    item_id,
                    json.dumps(card),
                    "A" if position == 0 else "",
                    1 if position == 0 else None,
                    "2026-01-01T00:01:00Z" if position == 0 else None,
                ),
            )

        session = app.complete_session(conn, session_id)

        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["score"], 1)
        self.assertTrue(session["items"][0]["correct"])
        self.assertFalse(session["items"][1]["correct"])
        unanswered = conn.execute(
            "SELECT wrong_count, needs_review FROM items WHERE id = ?",
            (unanswered_id,),
        ).fetchone()
        self.assertEqual((unanswered["wrong_count"], unanswered["needs_review"]), (1, 1))


class MediaTests(unittest.TestCase):
    def test_create_item_preserves_pdf_media_modes(self) -> None:
        conn = make_conn()

        item = app.create_item(
            conn,
            {
                "domain": "math",
                "item_type": "multiple_choice",
                "prompt": "Fallback text",
                "answer": "B",
                "choices": ["A", "B", "C", "D"],
                "topic": "Algebra",
                "difficulty": "Easy",
                "prompt_images": ["data/assets/questions/math/q-prompt-01.png"],
                "choice_images": ["data/assets/questions/math/q-choice-A.png"],
                "explanation_images": ["data/assets/questions/math/q-explanation-01.png"],
                "media": {
                    "source_pages": [12],
                    "prompt_image_mode": "primary",
                    "choice_image_mode": "primary",
                    "explanation_image_mode": "primary",
                },
            },
        )

        self.assertEqual(item["media"]["prompt_image_mode"], "primary")
        self.assertEqual(item["media"]["choice_image_mode"], "primary")
        self.assertEqual(item["media"]["explanation_image_mode"], "primary")
        self.assertEqual(item["media"]["source_pages"], [12])
        self.assertEqual(
            item["media"]["choice_images"],
            ["data/assets/questions/math/q-choice-A.png", "", "", ""],
        )
        self.assertEqual(
            item["media"]["explanation_images"],
            ["data/assets/questions/math/q-explanation-01.png"],
        )


class AnswerMatchingTests(unittest.TestCase):
    def test_typed_answer_accepts_comma_separated_numeric_variants(self) -> None:
        card = {"answer": "8.6, 43/5", "choices": []}

        self.assertTrue(app.answer_is_correct("8.6", card))
        self.assertTrue(app.answer_is_correct("43/5", card))

    def test_typed_answer_accepts_equivalent_variants_from_answer_list(self) -> None:
        card = {"answer": "10.33, 31/3", "choices": []}

        self.assertTrue(app.answer_is_correct("10.33", card))
        self.assertTrue(app.answer_is_correct("31/3", card))

    def test_typed_answer_accepts_equivalent_decimals_and_fractions(self) -> None:
        self.assertTrue(app.answer_is_correct("1.80", {"answer": "1.8, 9/5", "choices": []}))
        self.assertTrue(app.answer_is_correct("0.32", {"answer": ".32, 8/25", "choices": []}))
        self.assertTrue(app.answer_is_correct("31/3", {"answer": "10.33, 31/3", "choices": []}))

    def test_typed_answer_accepts_either_or_numeric_answers(self) -> None:
        card = {"answer": "either 2 or 8", "choices": []}

        self.assertTrue(app.answer_is_correct("2", card))
        self.assertTrue(app.answer_is_correct("8", card))
        self.assertFalse(app.answer_is_correct("5", card))

    def test_typed_answer_accepts_serial_numeric_answer_list(self) -> None:
        card = {"answer": "either 7, 8, or 13", "choices": []}

        self.assertTrue(app.answer_is_correct("7", card))
        self.assertTrue(app.answer_is_correct("8", card))
        self.assertTrue(app.answer_is_correct("13", card))
        self.assertFalse(app.answer_is_correct("12", card))

    def test_typed_answer_uses_explanation_numeric_examples_as_fallback(self) -> None:
        card = {
            "answer": "One method for solving the system is to add corresponding sides",
            "choices": [],
            "explanation": (
                "The correct answer is . One method is to add corresponding sides. "
                "Note that 3/2 and 1.5 are examples of ways to enter a correct answer."
            ),
        }

        self.assertTrue(app.answer_is_correct("3/2", card))
        self.assertTrue(app.answer_is_correct("1.5", card))
        self.assertFalse(app.answer_is_correct("2", card))

    def test_typed_answer_accepts_precise_decimal_approximation_to_fraction(self) -> None:
        card = {"answer": "2/3", "choices": []}

        self.assertTrue(app.answer_is_correct(".666", card))
        self.assertTrue(app.answer_is_correct(".667", card))
        self.assertFalse(app.answer_is_correct(".66", card))

    def test_text_answer_with_comma_is_not_split_into_partial_answers(self) -> None:
        card = {"answer": "red, blue, and green", "choices": []}

        self.assertTrue(app.answer_is_correct("red, blue, and green", card))
        self.assertFalse(app.answer_is_correct("red", card))

    def test_multiple_choice_accepts_label_or_choice_text(self) -> None:
        card = {"answer": "B", "choices": ["linear", "quadratic", "exponential", "constant"]}

        self.assertTrue(app.answer_is_correct("B", card))
        self.assertTrue(app.answer_is_correct("quadratic", card))
        self.assertFalse(app.answer_is_correct("linear", card))


if __name__ == "__main__":
    unittest.main()

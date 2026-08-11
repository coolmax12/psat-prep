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
    return conn


def add_item(
    conn: sqlite3.Connection,
    domain: str,
    topic: str,
    difficulty: str = "Medium",
    seen_count: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO items (
            domain, prompt, answer, topic, difficulty, seen_count
        ) VALUES (?, ?, 'A', ?, ?, ?)
        """,
        (domain, f"{topic} {difficulty}", topic, difficulty, seen_count),
    )


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
                "media": {
                    "source_pages": [12],
                    "prompt_image_mode": "primary",
                    "choice_image_mode": "primary",
                },
            },
        )

        self.assertEqual(item["media"]["prompt_image_mode"], "primary")
        self.assertEqual(item["media"]["choice_image_mode"], "primary")
        self.assertEqual(item["media"]["source_pages"], [12])
        self.assertEqual(
            item["media"]["choice_images"],
            ["data/assets/questions/math/q-choice-A.png", "", "", ""],
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

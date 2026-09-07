import unittest

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


if __name__ == "__main__":
    unittest.main()

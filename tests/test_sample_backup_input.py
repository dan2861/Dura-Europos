import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_sample_backup import read_requested_qids

class InputTests(unittest.TestCase):
    def test_reads_qids_in_source_order(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            path.write_bytes(b"Q42\r\nQ1\nQ5")

            self.assertEqual(
                read_requested_qids(path),
                ["Q42", "Q1", "Q5"])

    def test_rejects_non_q_prefix(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"

            for invalid_qid in ("P42", "q42"):
                with self.subTest(qid=invalid_qid):
                    path.write_text(invalid_qid + "\n", encoding="utf-8")

                    with self.assertRaises(ValueError):
                        read_requested_qids(path)

    def test_reports_blank_line(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            path.write_bytes(b"Q42\n\nQ5\n")

            with self.assertRaises(ValueError) as caught:
                read_requested_qids(path)

            message = str(caught.exception)
            self.assertIn("Line 2", message)
            self.assertIn("blank", message.lower())

    def test_rejects_invalid_numeric_part(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"

            for invalid_qid in ("Q", "Qabc", "Q42x", "Q4.2"):
                with self.subTest(qid=invalid_qid):
                    path.write_text(invalid_qid + "\n", encoding="utf-8")

                    with self.assertRaises(ValueError):
                        read_requested_qids(path)

    def test_reports_duplicate_qid(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            path.write_bytes(b"Q42\nQ1\nQ42\n")

            with self.assertRaises(ValueError) as caught:
                read_requested_qids(path)

            message = str(caught.exception)
            self.assertIn("duplicate", message.lower())
            self.assertIn("Q42", message)
            self.assertIn("Line 3", message)

    def test_rejects_surrounding_whitespace(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            for invalid_qid in (" Q42", "Q42 ", "\tQ42", "Q42\t"):
                with self.subTest(qid=invalid_qid):
                    path.write_text(invalid_qid + "\n", encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_requested_qids(path)

    def test_rejects_unicode_digits_and_non_line_separators(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            for content in ("Q٤٢\n", "Q４２\n", "Q42\u2028Q1", "Q42\x0bQ1"):
                with self.subTest(content=content):
                    original = content.encode("utf-8")
                    path.write_bytes(original)
                    with self.assertRaises(ValueError):
                        read_requested_qids(path)
                    self.assertEqual(path.read_bytes(), original)

    def test_accepts_only_line_terminators_as_separators(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            for ending in (b"\n", b"\r\n", b"\r"):
                with self.subTest(ending=ending):
                    content = ending.join((b"Q42", b"Q1", b""))
                    path.write_bytes(content)
                    self.assertEqual(read_requested_qids(path), ["Q42", "Q1"])
                    self.assertEqual(path.read_bytes(), content)

    def test_rejects_zero_and_padded_qids_without_normalizing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.txt"
            for invalid_qid in ("Q0", "Q00", "Q042"):
                with self.subTest(qid=invalid_qid):
                    content = (invalid_qid + "\n").encode("utf-8")
                    path.write_bytes(content)
                    with self.assertRaises(ValueError):
                        read_requested_qids(path)
                    self.assertEqual(path.read_bytes(), content)

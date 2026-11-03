"""Invented WDQS graph results; no live query is made by these tests."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.selection import freeze_fixture_responses


def result(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + qid}}
        for qid in qids]}}).encode()


class SelectionTests(unittest.TestCase):
    def test_rejects_malformed_graph_results_without_publishing_qids(self):
        invalid = [b'{}', b'{"head":{"vars":["other"]},"results":{"bindings":[]}}',
                   result("Q01"), result("Q0"), result("Qabc"),
                   result("Q1").replace(b'"uri"', b'"literal"'),
                   result("Q1").replace(b'http://www.wikidata.org/entity/', b'https://example.org/'),
                   b'{"head":{"vars":["item"]},"results":{"bindings":[{}]}}']
        for body in invalid:
            with self.subTest(body=body), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                with self.assertRaises(ValueError):
                    freeze_fixture_responses(body, result("Q2"), root)
                self.assertEqual((root / "sources/main.json").read_bytes(), body)
                self.assertFalse((root / "qids.txt").exists())
                metadata = json.loads((root / "selection.json").read_bytes())
                self.assertIsNone(metadata["frozen_at"])

    def test_empty_scholarly_is_valid_but_empty_union_is_not(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "one"
            freeze_fixture_responses(result("Q2", "Q2"), result(), root)
            self.assertEqual((root / "qids.txt").read_bytes(), b"Q2\n")
            with self.assertRaisesRegex(ValueError, "Empty"):
                freeze_fixture_responses(result(), result(), Path(directory) / "empty")

    def test_full_selection_can_exceed_batch_limit_and_never_overwrites(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            freeze_fixture_responses(result(*(f"Q{i}" for i in range(60, 0, -1))), result(), root)
            self.assertEqual(len((root / "qids.txt").read_text().splitlines()), 60)
            before = (root / "selection.json").read_bytes()
            with self.assertRaises(FileExistsError):
                freeze_fixture_responses(result("Q99"), result(), root)
            self.assertEqual((root / "selection.json").read_bytes(), before)

    def test_freezes_numeric_union_and_retains_sources(self):
        main, scholarly = result("Q10", "Q2"), result("Q2", "Q1")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            freeze_fixture_responses(main, scholarly, root)
            self.assertEqual((root / "qids.txt").read_bytes(), b"Q1\nQ2\nQ10\n")
            self.assertEqual((root / "sources/main.json").read_bytes(), main)
            self.assertEqual((root / "sources/scholarly.json").read_bytes(), scholarly)
            metadata = json.loads((root / "selection.json").read_bytes())
            self.assertEqual(metadata["kind"], "synthetic")
            self.assertEqual(metadata["selected_count"], 3)
            self.assertEqual([row["graph"] for row in metadata["sources"]], ["main", "scholarly"])

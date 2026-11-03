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

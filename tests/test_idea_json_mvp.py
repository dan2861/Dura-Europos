import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.mvp import preserve_batch


class PreservationTests(unittest.TestCase):
    def test_preserves_source_and_complete_entity(self):
        # Invented fixture, not retrieved Wikidata data.
        entity = {
            "id": "Q1",
            "type": "item",
            "lastrevid": 7,
            "modified": "2026-10-28T12:00:00Z",
            "claims": {},
            "future_field": {"identifier": "0007"},
        }
        body = json.dumps({
            "success": 1,
            "entities": {"Q1": entity},
        }).encode("utf-8")

        with TemporaryDirectory() as directory:
            output = Path(directory) / "run"

            preserve_batch(body, ["Q1"], output)

            source = output / "source.json"
            self.assertTrue(
                source.is_file(),
                "Original response must be saved",
            )
            self.assertEqual(source.read_bytes(), body)

            saved = json.loads(
                (output / "items" / "Q1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved, entity)

    def test_rejects_mismatched_entity_id_and_retains_source(self):
        # Invented response: mapping key and entity ID disagree.
        entity = {
            "id": "Q2",
            "type": "item",
            "lastrevid": 7,
            "modified": "2026-10-28T12:00:00Z",
            "claims": {},
        }
        body = json.dumps({
            "success": 1,
            "entities": {"Q1": entity},
        }).encode("utf-8")

        with TemporaryDirectory() as directory:
            output = Path(directory) / "run"

            with self.assertRaises(ValueError) as caught:
                preserve_batch(body, ["Q1"], output)

            message = str(caught.exception)
            self.assertIn("Q1", message)
            self.assertIn("Q2", message)
            self.assertEqual(
                (output / "source.json").read_bytes(),
                body,
            )
            self.assertFalse(
                (output / "items" / "Q1.json").exists()
            )
            self.assertFalse(
                (output / "items" / "Q2.json").exists()
            )

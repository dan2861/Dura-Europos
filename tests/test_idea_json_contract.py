"""Invented Action API responses; these tests never retrieve data."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.mvp import preserve_batch


def item(qid="Q1", **changes):
    value = {"id": qid, "type": "item", "lastrevid": 7,
             "modified": "2026-11-02T12:00:00Z", "claims": {}}
    value.update(changes)
    return value


def response(entity):
    return json.dumps({"success": 1, "entities": {"Q1": entity}}).encode()


class ContractTests(unittest.TestCase):
    def assert_rejected(self, body, message):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaisesRegex(ValueError, message):
                preserve_batch(body, ["Q1"], output)
            self.assertEqual((output / "source.json").read_bytes(), body)
            self.assertEqual(list((output / "items").glob("*.json")), [])

    def test_requires_item_object_and_type(self):
        for entity in (None, [], "item", item(type="property"), item(type=None)):
            with self.subTest(entity=entity):
                self.assert_rejected(response(entity), "Q1.*item")

    def test_requires_positive_integer_revision_and_utc_modified(self):
        for revision in (None, True, 0, -1, 7.0, "7"):
            with self.subTest(revision=revision):
                self.assert_rejected(response(item(lastrevid=revision)), "Q1.*revision")
        for modified in (None, "yesterday", "2026-02-30T12:00:00Z",
                         "2026-11-02T12:00:00", "2026-11-02T12:00:00+01:00"):
            with self.subTest(modified=modified):
                self.assert_rejected(response(item(modified=modified)), "Q1.*modified")

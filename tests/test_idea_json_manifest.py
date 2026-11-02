"""Synthetic preservation runs and interrupted writes, never live retrieval."""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.idea_json_backup.mvp import preserve_batch
from scripts.idea_json_backup.verify import verify_run


BODY = (b'{"success":1,"entities":{"Q1":{"id":"Q1","type":"item",'
        b'"lastrevid":7,"modified":"2026-11-02T12:00:00Z",'
        b'"unknown":{"id":"0007","number":1.23000000000000000001,"flag":true}}}}')
SYNTHETIC = {"kind": "synthetic", "description": "Invented offline test",
             "retrieved_at": None}


class ManifestTests(unittest.TestCase):
    def test_manifest_records_scope_provenance_revision_and_checksums(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            preserve_batch(BODY, ["Q1"], root, provenance=SYNTHETIC)
            manifest = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(manifest["format"], "idea-json-backup-mvp")
            self.assertEqual(manifest["requested_qids"], ["Q1"])
            self.assertEqual(manifest["provenance"], SYNTHETIC)
            self.assertEqual(manifest["status"], "collected")
            self.assertEqual(manifest["items"][0]["revision"], 7)
            self.assertEqual(manifest["source"]["sha256"], hashlib.sha256(BODY).hexdigest())
            self.assertEqual(verify_run(root), {"status": "passed", "findings": []})
            self.assertIn(b'1.23000000000000000001', (root / "items/Q1.json").read_bytes())

    def test_failure_accounts_for_all_requested_qids(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with self.assertRaises(ValueError):
                preserve_batch(BODY, ["Q1", "Q2"], root, provenance=SYNTHETIC)
            manifest = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(manifest["status"], "incomplete")
            self.assertEqual([entry["qid"] for entry in manifest["items"]], ["Q1", "Q2"])
            self.assertEqual([entry["status"] for entry in manifest["items"]], ["saved", "unresolved"])
            self.assertIn("Q2", manifest["items"][1]["error"])
            self.assertEqual((root / "source.json").read_bytes(), BODY)
            self.assertEqual(verify_run(root)["status"], "failed")

    def test_provenance_cannot_invent_fixture_retrieval_time(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with self.assertRaisesRegex(ValueError, "provenance"):
                preserve_batch(BODY, ["Q1"], root, provenance=dict(
                    SYNTHETIC, retrieved_at="2026-11-02T12:00:00Z"))
            self.assertFalse(root.exists())

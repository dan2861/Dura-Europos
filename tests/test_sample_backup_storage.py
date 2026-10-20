"""Synthetic filesystem cases; all artifacts live under TemporaryDirectory."""
import csv
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.sample_backup import storage


class StorageTests(unittest.TestCase):
    def test_initial_run_snapshots_scope_and_pending_state(self):
        with TemporaryDirectory() as directory:
            qids = ["Q42", "Q1"]
            store = storage.RunStore.create(Path(directory), qids, "synthetic.txt")
            qids.append("Q5")
            manifest = json.loads((store.root / "manifest.json").read_text())
            self.assertEqual(manifest["scope"]["requested_qids"], ["Q42", "Q1"])
            self.assertEqual(manifest["scope"]["requested_count"], 2)
            self.assertIsNone(manifest["finished_at"])
            self.assertEqual(len(manifest["items"]), 2)
            self.assertEqual(len(manifest["validation_summary"]["checks"]), 6)
            for item in manifest["items"]:
                self.assertEqual(item["retrieval_status"], "pending")
                self.assertEqual(item["validation_status"], "not_checked")
                self.assertEqual(item["http_trace"], [])
                self.assertIsNone(item["source_json"])
            self.assertEqual(manifest["validation_summary"]["status"], "not_checked")
            expected = {
                "items.csv": "qid,lastrevid,modified,label_en,description_en,labels_json,descriptions_json,aliases_json,sitelinks_json\r\n",
                "statements.csv": "qid,statement_id,property_id,statement_order,statement_type,rank,snak_hash,snaktype,datatype,value_text,datavalue_json,commons_file_url\r\n",
                "qualifiers.csv": "qid,statement_id,property_id,property_order,snak_order,snak_hash,snaktype,datatype,value_text,datavalue_json\r\n",
                "references.csv": "reference_id,property_id,property_order,snak_order,snak_hash,snaktype,datatype,value_text,datavalue_json\r\n",
                "statement_references.csv": "qid,statement_id,reference_id,reference_order,source_reference_hash\r\n",
            }
            for name, header in expected.items():
                self.assertEqual((store.root / name).read_bytes(), header.encode())
            self.assertEqual({o["path"] for o in manifest["outputs"]}, set(expected))

    def test_exclusive_creation_and_original_preservation(self):
        with TemporaryDirectory() as directory:
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            store = storage.RunStore.create(Path(directory), ["Q42"], "synthetic.txt",
                                            started=start, suffix="fixed")
            body = b'{ "entities": {"Q42": {"id":"Q42"}} }\r\n'
            self.assertEqual(store.save_original("Q42", body), "original/Q42.json")
            with self.assertRaises(FileExistsError):
                store.save_original("Q42", b"replacement")
            with self.assertRaises(FileExistsError):
                storage.RunStore.create(Path(directory), ["Q42"], "synthetic.txt",
                                        started=start, suffix="fixed")
            self.assertEqual((store.root / "original/Q42.json").read_bytes(), body)
            self.assertIsNone(store.save_failure("Q42", b""))
            self.assertEqual(list((store.root / "failures").iterdir()), [])

    def test_failed_checkpoint_keeps_previous_manifest(self):
        with TemporaryDirectory() as directory:
            store = storage.RunStore.create(Path(directory), ["Q42"], "synthetic.txt")
            previous = (store.root / "manifest.json").read_bytes()
            store.manifest["finished_at"] = "synthetic failure simulation"
            with patch.object(storage.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    store.checkpoint()
            self.assertEqual((store.root / "manifest.json").read_bytes(), previous)

    def test_invalid_preflight_creates_no_run(self):
        with TemporaryDirectory() as directory:
            for qids in (["Q42", "Q42"], ["../Q42"], [" Q42"], ["Q0"]):
                with self.subTest(qids=qids):
                    with self.assertRaises(ValueError):
                        storage.RunStore.create(Path(directory) / "uncreated", qids, "synthetic")
                    self.assertFalse((Path(directory) / "uncreated").exists())

    def test_artifact_paths_cannot_escape_or_follow_symlinks(self):
        with TemporaryDirectory() as directory:
            store = storage.RunStore.create(Path(directory), ["Q42"], "synthetic.txt")
            for path in ("../outside", "/absolute"):
                with self.assertRaises(ValueError):
                    store._write(path, b"bad")
            (store.root / "evil").symlink_to(Path(directory), target_is_directory=True)
            with self.assertRaises(ValueError):
                store._write("evil/outside", b"bad")

"""Verifier fixtures are constructed independently of preservation code."""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.verify import verify_run


class VerifyTests(unittest.TestCase):
    def make_run(self, root):
        (root / "items").mkdir()
        entity = (b'{"id":"Q1","type":"item","lastrevid":7,'
                  b'"modified":"2026-11-02T12:00:00Z","claims":{},'
                  b'"future":{"identifier":"0007","number":1.2300e+2},'
                  b'"values":[true,1,"1",null]}')
        (root / "source.json").write_bytes(
            b'{"success":1,"entities":{"Q1":' + entity + b'}}')
        (root / "items/Q1.json").write_bytes(entity)
        manifest = {
            "format": "idea-json-backup-mvp", "version": 1,
            "status": "collected", "requested_qids": ["Q1"],
            "provenance": {"kind": "synthetic", "description": "invented fixture",
                           "retrieved_at": None},
            "source": self.descriptor(root, "source.json"),
            "items": [{"qid": "Q1", "status": "saved", "revision": 7,
                       "modified": "2026-11-02T12:00:00Z",
                       "file": self.descriptor(root, "items/Q1.json"), "error": None}],
            "error": None, "evidence": [],
        }
        self.save_manifest(root, manifest)
        return manifest

    def descriptor(self, root, name):
        body = (root / name).read_bytes()
        return {"path": name, "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()}

    def save_manifest(self, root, manifest):
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_verifies_without_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_run(root)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(verify_run(root), {"status": "passed", "findings": []})
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*")
                                      if p.is_file()})

    def test_changed_content_fails_even_after_recomputed_item_checksum(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_run(root)
            item = root / "items/Q1.json"
            item.write_bytes(item.read_bytes().replace(b'"0007"', b'"0008"'))
            manifest["items"][0]["file"] = self.descriptor(root, "items/Q1.json")
            self.save_manifest(root, manifest)
            result = verify_run(root)
            self.assertEqual(result["status"], "failed")
            self.assertIn("content", " ".join(result["findings"]))

    def test_number_lexeme_and_boolean_type_changes_fail(self):
        for before, after in ((b'1.2300e+2', b'123.00'), (b'[true,', b'[1,')):
            with self.subTest(after=after), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                item = root / "items/Q1.json"
                item.write_bytes(item.read_bytes().replace(before, after))
                manifest["items"][0]["file"] = self.descriptor(root, "items/Q1.json")
                self.save_manifest(root, manifest)
                self.assertEqual(verify_run(root)["status"], "failed")

    def test_missing_unexpected_and_damaged_files_fail(self):
        for change in ("missing", "unexpected", "damage"):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_run(root)
                if change == "missing":
                    (root / "items/Q1.json").unlink()
                elif change == "unexpected":
                    (root / "unexpected.json").write_bytes(b'{}')
                else:
                    (root / "source.json").write_bytes(b'{}')
                self.assertEqual(verify_run(root)["status"], "failed")

    def test_scope_provenance_status_and_revision_fail_closed(self):
        changes = (
            lambda m: m.update(requested_qids=["Q1", "Q2"]),
            lambda m: m.update(requested_qids=["Q1", "Q1"]),
            lambda m: m.update(items=[]),
            lambda m: m.update(status="incomplete"),
            lambda m: m.update(error="interrupted"),
            lambda m: m["provenance"].update(retrieved_at="2026-11-02T12:00:00Z"),
            lambda m: m["items"][0].update(revision=True),
            lambda m: m["items"][0].update(modified="2026-11-03T12:00:00Z"),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                change(manifest)
                self.save_manifest(root, manifest)
                self.assertEqual(verify_run(root)["status"], "failed")

    def test_unsafe_and_symlink_paths_fail(self):
        for name in ("../outside.json", "/tmp/outside.json", "items/../source.json"):
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                manifest["items"][0]["file"]["path"] = name
                self.save_manifest(root, manifest)
                self.assertEqual(verify_run(root)["status"], "failed")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_run(root)
            body = (root / "items/Q1.json").read_bytes()
            (root / "item-copy").write_bytes(body)
            (root / "items/Q1.json").unlink()
            (root / "items/Q1.json").symlink_to(root / "item-copy")
            self.assertEqual(verify_run(root)["status"], "failed")

    def test_evidence_files_are_checked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_run(root)
            (root / "encoded.body").write_bytes(b'encoded fixture')
            manifest["evidence"] = [self.descriptor(root, "encoded.body")]
            self.save_manifest(root, manifest)
            self.assertEqual(verify_run(root)["status"], "passed")
            (root / "encoded.body").write_bytes(b'changed')
            self.assertEqual(verify_run(root)["status"], "failed")

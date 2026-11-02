"""Verifier fixtures are constructed independently of preservation code."""
import hashlib
import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

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

    def make_receipt(self, root, manifest, *, compressed=False, kind="live"):
        source = (root / "source.json").read_bytes()
        encoded = gzip.compress(source, mtime=0) if compressed else source
        request = {
            "method": "GET",
            "url": "https://www.wikidata.org/w/api.php?" + urlencode({
                "action": "wbgetentities", "ids": "Q1", "format": "json",
                "formatversion": "2", "redirects": "no", "maxlag": "5"}),
            "headers": {"Accept": "application/json", "Accept-Encoding": "gzip, identity",
                        "User-Agent": "IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)"},
            "timeout_seconds": 60,
        }
        receipt = {
            "status": 200, "headers": {"content-length": str(len(encoded)),
                                      "content-encoding": "gzip" if compressed else "identity"},
            "complete": True, "error": None, "interrupted": False,
            "started_at": "2026-11-02T12:00:00Z",
            "headers_received_at": "2026-11-02T12:00:01Z",
            "received_at": "2026-11-02T12:00:02Z", "encoded_path": "encoded.body",
        }
        (root / "encoded.body").write_bytes(encoded)
        manifest["provenance"].update(kind=kind, retrieved_at=(
            receipt["received_at"] if kind == "live" else None))
        self.save_receipt(root, manifest, request, receipt)
        return request, receipt

    def save_receipt(self, root, manifest, request, receipt):
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (root / "transport.json").write_text(json.dumps(receipt), encoding="utf-8")
        manifest["evidence"] = [self.descriptor(root, name) for name in
                                ("request.json", "transport.json", "encoded.body")]
        self.save_manifest(root, manifest)

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

    def test_live_provenance_requires_protocol_receipts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_run(root)
            (root / "arbitrary.body").write_bytes(b'unrelated')
            manifest["evidence"] = [self.descriptor(root, "arbitrary.body")]
            manifest["provenance"].update(kind="live", retrieved_at="2026-11-02T12:00:02Z")
            self.save_manifest(root, manifest)
            self.assertEqual(verify_run(root)["status"], "failed")

    def test_independent_identity_and_gzip_receipts_pass(self):
        for compressed, kind in ((False, "live"), (True, "live"), (True, "synthetic")):
            with self.subTest(compressed=compressed, kind=kind), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                self.make_receipt(root, manifest, compressed=compressed, kind=kind)
                self.assertEqual(verify_run(root), {"status": "passed", "findings": []})

    def test_shortened_deadline_is_valid_despite_wall_clock_span(self):
        # The runtime supervisor uses monotonic time; wall clocks can adjust.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_run(root)
            request, receipt = self.make_receipt(root, manifest)
            request["timeout_seconds"] = 0.5
            self.save_receipt(root, manifest, request, receipt)
            self.assertEqual(verify_run(root), {"status": "passed", "findings": []})

    def test_tampered_receipt_fails_after_recomputed_hashes(self):
        changes = (
            lambda q, r: q.update(method="POST"),
            lambda q, r: q.update(url=q["url"].replace("www.wikidata.org", "example.org")),
            lambda q, r: q.update(url=q["url"].replace("ids=Q1", "ids=Q2")),
            lambda q, r: q.update(url=q["url"] + "&props=claims"),
            lambda q, r: q.update(timeout_seconds=True),
            lambda q, r: q.update(timeout_seconds=61),
            lambda q, r: q["headers"].update({"User-Agent": ""}),
            lambda q, r: r.update(status=503),
            lambda q, r: r.update(complete=False),
            lambda q, r: r.update(error="interrupted"),
            lambda q, r: r.update(interrupted=True),
            lambda q, r: r.update(received_at="2026-11-02T11:59:59Z"),
            lambda q, r: r.update(received_at="2026-11-02T12:00:03Z"),
            lambda q, r: r.update(headers_received_at=None),
            lambda q, r: r.update(encoded_path="source.json"),
            lambda q, r: r["headers"].update({"content-length": "1"}),
            lambda q, r: r["headers"].update({"content-encoding": "br"}),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                request, receipt = self.make_receipt(root, manifest)
                change(request, receipt)
                self.save_receipt(root, manifest, request, receipt)
                self.assertEqual(verify_run(root)["status"], "failed")

    def test_receipt_encoded_body_must_decode_to_source(self):
        for compressed, replacement in ((False, b'changed'), (True, b'not gzip')):
            with self.subTest(compressed=compressed), TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.make_run(root)
                request, receipt = self.make_receipt(root, manifest, compressed=compressed)
                (root / "encoded.body").write_bytes(replacement)
                receipt["headers"]["content-length"] = str(len(replacement))
                self.save_receipt(root, manifest, request, receipt)
                self.assertEqual(verify_run(root)["status"], "failed")

"""One-batch orchestration using invented captures only."""
import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from scripts.idea_json_backup.collector import collect_batch
from scripts.idea_json_backup.transport import Capture
from scripts.idea_json_backup.verify import verify_run

BODY = (b'{"success":1,"entities":{"Q1":{"id":"Q1","type":"item",'
        b'"lastrevid":7,"modified":"2026-11-02T12:00:00Z","claims":{}}}}')


def captured(body=BODY, *, status=200, complete=True, error=None, compressed=False):
    encoded = gzip.compress(body, mtime=0) if compressed else body
    return Capture(encoded, body if complete else None, status,
                   {"content-length": str(len(encoded)), "content-encoding": "gzip" if compressed else "identity"},
                   complete, error, "2026-11-02T12:00:00Z", "2026-11-02T12:00:01Z",
                   "2026-11-02T12:00:02Z" if complete else None)


class CollectionTests(unittest.TestCase):
    def test_one_capture_is_preserved_with_request_and_encoded_evidence(self):
        capture = Mock(return_value=captured(compressed=True))
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            collect_batch(["Q1"], root, capture=capture, provenance_kind="synthetic",
                          description="Invented compressed capture", timeout_seconds=0.5)
            capture.assert_called_once()
            self.assertEqual(capture.call_args.kwargs["capture_directory"], root / "capture")
            self.assertEqual((root / "source.json").read_bytes(), BODY)
            self.assertEqual(gzip.decompress((root / "encoded.body").read_bytes()), BODY)
            self.assertEqual(verify_run(root), {"status": "passed", "findings": []})
            manifest = json.loads((root / "manifest.json").read_bytes())
            self.assertIsNone(manifest["provenance"]["retrieved_at"])

    def test_http_api_and_incomplete_captures_cannot_become_collected(self):
        cases = [captured(status=503, error="HTTP status 503"),
                 captured(b'{"error":{"code":"maxlag"}}'),
                 captured(complete=False, error="total response deadline exceeded")]
        for value in cases:
            with self.subTest(value=value), TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                capture = Mock(return_value=value)
                with self.assertRaises(ValueError):
                    collect_batch(["Q1"], root, capture=capture, provenance_kind="synthetic")
                capture.assert_called_once()
                manifest = json.loads((root / "manifest.json").read_bytes())
                self.assertEqual(manifest["status"], "incomplete")
                self.assertEqual((root / "encoded.body").read_bytes(), value.encoded)
                self.assertEqual(list((root / "items").iterdir()), [])
                self.assertEqual(verify_run(root)["status"], "failed")

    def test_interruption_retains_capture_files_and_incomplete_manifest(self):
        def interrupted(qids, **options):
            capture = options["capture_directory"]
            capture.mkdir()
            (capture / "encoded.body").write_bytes(b"partial")
            raise KeyboardInterrupt("invented capture interruption")

        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with self.assertRaises(KeyboardInterrupt):
                collect_batch(["Q1"], root, capture=interrupted, provenance_kind="synthetic")
            self.assertEqual((root / "capture/encoded.body").read_bytes(), b"partial")
            manifest = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(manifest["status"], "incomplete")
            self.assertIn("KeyboardInterrupt", manifest["error"])

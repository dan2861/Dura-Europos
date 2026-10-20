"""Command/orchestration unit tests with synthetic inputs; never invoke the live export command."""
import contextlib
import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import export_sample_backup as app
from scripts.sample_backup import jsoncodec as codec, retrieval, transform, validation
from scripts.sample_backup.storage import RunStore, utc_now
from scripts.sample_backup.schema import ENDPOINT
from test_sample_backup_validation import attempt


class IntegrationTests(unittest.TestCase):
    def test_verify_command_is_offline_and_unfinished_has_nonzero_exit(self):
        with TemporaryDirectory() as directory:
            store, _ = attempt(directory)
            before = (store.root / "manifest.json").read_bytes()
            with patch.object(retrieval, "retrieve", side_effect=AssertionError("network forbidden")), contextlib.redirect_stdout(io.StringIO()) as output:
                code = app.main(["verify", str(store.root)])
            self.assertEqual(code, 2)
            self.assertIn("not_checked", output.getvalue())
            self.assertEqual((store.root / "manifest.json").read_bytes(), before)
            self.assertIn("export", app.build_parser().format_help())

    def test_synthetic_attempt_saves_projects_verifies_and_withholds_identity_collisions(self):
        with TemporaryDirectory() as directory:
            fixture, _ = attempt(Path(directory) / "fixture")
            source = codec.loads((fixture.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            input_path = Path(directory) / "synthetic-items.txt"
            input_path.write_bytes(b"Q42\n")
            calls = []
            def fetch(qid):
                calls.append(qid)
                body = codec.dumps({"entities": {"Q42": source}}).encode()
                return retrieval.Result(body, [{"url": ENDPOINT.format(qid=qid), "status_code": 200, "location": None}],
                                        True, None, utc_now(), source)
            store, report = app.export_attempt(input_path, Path(directory) / "output", fetch=fetch)
            self.assertEqual(calls, ["Q42"])
            self.assertEqual(report["status"], "not_checked", report)
            self.assertIsNotNone(codec.loads((store.root / "manifest.json").read_bytes())["finished_at"])
            with (store.root / "statements.csv").open(newline="") as stream:
                self.assertGreater(len(list(csv.DictReader(stream))), 0)
            input_path.write_bytes(b"Q42\nQ1\n")
            store, report = app.export_attempt(input_path, Path(directory) / "colliding", fetch=fetch)
            self.assertEqual(report["status"], "not_checked", report)
            self.assertEqual((store.root / "original/Q42.json").read_bytes(), (store.root / "original/Q1.json").read_bytes())
            with (store.root / "items.csv").open(newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])

    def test_invalid_input_table_failure_and_early_interrupt_remain_honest(self):
        with TemporaryDirectory() as directory:
            fixture, _ = attempt(Path(directory) / "fixture")
            source = codec.loads((fixture.root / "original/Q42.json").read_bytes())["entities"]["Q42"]
            input_path = Path(directory) / "synthetic.txt"
            input_path.write_bytes(b"Q42\nQ42\n")
            fetch = lambda qid: retrieval.Result(
                codec.dumps({"entities": {"Q42": source}}).encode(),
                [{"url": ENDPOINT.format(qid=qid), "status_code": 200, "location": None}],
                True, None, utc_now(), source)
            output = Path(directory) / "must-not-exist"
            with patch.object(retrieval, "retrieve", side_effect=AssertionError("network forbidden")):
                with self.assertRaises(ValueError):
                    app.export_attempt(input_path, output)
            self.assertFalse(output.exists())
            input_path.write_bytes(b"Q42\n")
            original_write = RunStore.write_table
            def fail_table(store, table, rows):
                if rows:
                    raise OSError("synthetic table-saving failure")
                return original_write(store, table, rows)
            with patch.object(RunStore, "write_table", new=fail_table):
                store, report = app.export_attempt(input_path, Path(directory) / "failed", fetch=fetch)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(store.manifest["items"][0]["retrieval_status"], "succeeded")
            self.assertTrue((store.root / "original/Q42.json").exists())
            self.assertTrue(any("run_note" in d for c in report["checks"] for d in c["details"]))
            with patch.object(app, "collect_requests", side_effect=KeyboardInterrupt()):
                store, report = app.export_attempt(input_path, Path(directory) / "interrupted", fetch=fetch)
            self.assertEqual(report["status"], "not_checked")
            self.assertEqual(store.manifest["items"][0]["retrieval_status"], "pending")

    def test_direct_script_import_and_help_never_invoke_retrieval(self):
        import runpy
        with patch.object(retrieval, "retrieve", side_effect=AssertionError("network forbidden")):
            namespace = runpy.run_path(str(Path(app.__file__)), run_name="offline_import_check")
            self.assertIn("verify", namespace["build_parser"]().format_help())

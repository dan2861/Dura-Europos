"""Production discovery commands with invented results and mocked operations."""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.export_idea_json import main
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.selection import new_selection
from scripts.idea_json_backup.state import RunState
from test_idea_json_pilot_selection import parent_fixture


def result(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}} for q in qids]}}).encode()


class ProductionCommandTests(unittest.TestCase):
    def test_deposit_exit_codes_preserve_separate_byte_and_provenance_outcomes(self):
        for byte_status, deposit_status, expected in (("passed", "passed", 0), ("passed", "not_checked", 2),
                                                     ("failed", "not_checked", 1), ("passed", "failed", 1)):
            with self.subTest(byte=byte_status, provenance=deposit_status):
                report = self.deposit_report(byte_status, deposit_status)
                with patch("scripts.export_idea_json.verify_deposit", create=True, return_value=report) as checker:
                    code, actual = self.invoke(["verify-deposit", "--package", "package", "--downloads", "downloads"])
                self.assertEqual((code, actual), (expected, report))
                self.assertNotIn("status", actual)
                checker.assert_called_once_with(Path("package"), Path("downloads"), acquisition=None)

    def test_deposit_receipt_is_exact_and_reports_must_be_external_to_both_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("package", "downloads"):
                (root / name).mkdir()
            receipt = {"dataset_url": "https://example.org/dataset", "persistent_id": "doi:00'~01",
                       "dataset_version": "DRAFT", "downloaded_at": None, "files": [],
                       "recorded_by": "Invented Operator", "evidence_kind": "operator_recorded"}
            (root / "acquisition.json").write_text(json.dumps(receipt))
            report = self.deposit_report("passed", "not_checked")
            with patch("scripts.export_idea_json.verify_deposit", create=True, return_value=report) as checker:
                code, actual = self.invoke(["verify-deposit", "--package", str(root / "package"),
                                            "--downloads", str(root / "downloads"),
                                            "--acquisition", str(root / "acquisition.json"),
                                            "--report", str(root / "deposit-verification.json")])
            self.assertEqual((code, actual), (2, report))
            self.assertEqual(checker.call_args.kwargs["acquisition"], receipt)
            self.assertEqual(json.loads((root / "deposit-verification.json").read_bytes()), report)
            for target in ("package", "downloads"):
                with patch("scripts.export_idea_json.verify_deposit", create=True) as checker:
                    code, actual = self.invoke(["verify-deposit", "--package", str(root / "package"),
                                                "--downloads", str(root / "downloads"),
                                                "--report", str(root / target / "report.json")])
                self.assertEqual(code, 1)
                checker.assert_not_called()
                self.assertEqual(list((root / target).iterdir()), [])

    def deposit_report(self, byte_status, deposit_status):
        return {"format_version": "1.0.0", "package_id": "invented", "checked_at": "2026-11-08T12:00:00.000000Z",
                "acquisition": None, "byte_status": byte_status, "deposit_status": deposit_status,
                "findings": [], "publication": None}

    def test_deposit_receipt_must_be_external_regular_evidence_before_audit(self):
        for case in ("inside_package", "inside_downloads", "alias", "fifo"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                package, downloads = base / "package", base / "downloads"
                package.mkdir()
                downloads.mkdir()
                if case.startswith("inside"):
                    receipt = (package if case == "inside_package" else downloads) / "acquisition.json"
                elif case == "alias":
                    (base / "alias").symlink_to(downloads, target_is_directory=True)
                    receipt = base / "alias/acquisition.json"
                else:
                    receipt = base / "acquisition.json"
                    os.mkfifo(receipt)
                if case != "fifo":
                    receipt.write_text("{}")
                forbidden = patch.object(Path, "read_bytes", side_effect=AssertionError("FIFO must not be opened")) if case == "fifo" else contextlib.nullcontext()
                with forbidden, patch("scripts.export_idea_json.verify_deposit", return_value=self.deposit_report("passed", "passed")) as checker:
                    code, report = self.invoke(["verify-deposit", "--package", str(package), "--downloads", str(downloads),
                                                "--acquisition", str(receipt)])
                self.assertEqual(code, 1)
                checker.assert_not_called()
                self.assertEqual(report["status"], "failed")

    def test_saved_deposit_report_cannot_adopt_changed_inputs_or_receipt(self):
        from scripts.idea_json_backup import external_report
        for case in ("during_audit", "during_staging", "receipt"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                package, downloads = base / "package", base / "downloads"
                package.mkdir()
                downloads.mkdir()
                (package / "baseline").write_bytes(b"original")
                artifact = downloads / "received"
                artifact.write_bytes(b"original")
                receipt = base / "acquisition.json"
                receipt.write_text("{}")
                target = base / "deposit-verification.json"

                def checker(*args, **kwargs):
                    if case == "during_audit":
                        artifact.write_bytes(b"changed during audit")
                    elif case == "receipt":
                        receipt.write_text('{"recorded_by":"changed operator"}')
                    return self.deposit_report("passed", "passed")

                original = external_report._write

                def stage(*args):
                    original(*args)
                    if case == "during_staging":
                        artifact.write_bytes(b"changed during staging")

                with patch("scripts.export_idea_json.verify_deposit", side_effect=checker), patch.object(
                        external_report, "_write", side_effect=stage):
                    code, report = self.invoke(["verify-deposit", "--package", str(package), "--downloads", str(downloads),
                                                "--acquisition", str(receipt), "--report", str(target)])
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")
                self.assertFalse(target.exists())
                self.assertEqual(len(list(base.glob(".deposit-verification.json.*.pending"))),
                                 1 if case == "during_staging" else 0)

    def test_malformed_receipt_parse_error_never_echoes_supplied_secrets(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            receipt = base / "receipt.json"
            receipt.write_text('{"TOP_SECRET_fixture":1,"TOP_SECRET_fixture":2}')
            with patch("scripts.export_idea_json.verify_deposit") as checker:
                code, report = self.invoke(["verify-deposit", "--package", str(base / "package"),
                                            "--downloads", str(base / "downloads"), "--acquisition", str(receipt)])
            self.assertEqual(code, 1)
            self.assertNotIn("TOP_SECRET_fixture", json.dumps(report))
            checker.assert_not_called()

    def test_package_uses_explicit_profile_then_independent_check_and_report(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            profile = {"format": "tar.gz", "max_members": 5000,
                       "max_payload_bytes_per_part": 268435456, "gzip_level": 6,
                       "gzip_mtime": 0, "tar_header_policy": "uid=0,gid=0,uname=,gname=,mode=0644,mtime=0",
                       "retention_evidence": None}
            (base / "profile.json").write_text(json.dumps(profile))
            report = {"status": "passed", "findings": [], "package_id": "invented"}
            calls = []

            def produce(run, output, *, profile):
                calls.append("produce")
                output.mkdir()
                return {"package_id": "invented"}

            def audit(output):
                calls.append("audit")
                return report

            def save(output, value, *, expected_inventory):
                calls.append("report")
                self.assertEqual(expected_inventory, {"package_id": "invented"})
                (output / "package-verification.json").write_text(json.dumps(value))

            with patch("scripts.export_idea_json.package_collection", create=True, side_effect=produce) as producer, patch(
                    "scripts.export_idea_json.verify_package", create=True, side_effect=audit), patch(
                    "scripts.export_idea_json.write_package_report", create=True, side_effect=save):
                code, actual = self.invoke(["package", "--run", "run", "--output", str(base / "package"),
                                            "--profile", str(base / "profile.json")])
            self.assertEqual((code, actual), (0, report))
            self.assertEqual(calls, ["produce", "audit", "report"])
            producer.assert_called_once_with(Path("run"), (base / "package").resolve(), profile=profile)
            self.assertEqual(json.loads((base / "package/package-verification.json").read_bytes()), report)

    def test_verify_package_is_read_only_and_profile_parse_is_strict(self):
        report = {"status": "passed", "findings": []}
        with patch("scripts.export_idea_json.verify_package", create=True, return_value=report) as audit, patch(
                "scripts.export_idea_json.package_collection", create=True) as producer:
            self.assertEqual(self.invoke(["verify-package", "package"]), (0, report))
            audit.assert_called_once_with(Path("package"))
            producer.assert_not_called()
        with TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            for body in ('{"format":"tar.gz","format":"tar.gz"}', '{"gzip_level":6.0}'):
                profile.write_text(body)
                with patch("scripts.export_idea_json.package_collection", create=True) as producer:
                    code, report = self.invoke(["package", "--run", "run", "--output", "output", "--profile", str(profile)])
                self.assertEqual(code, 1)
                producer.assert_not_called()

    def test_invented_finalized_collection_packages_and_reaudits_through_cli(self):
        from test_idea_json_finalize import fixture
        from scripts.idea_json_backup.finalize import finalize
        with TemporaryDirectory() as directory:
            base = Path(directory)
            run = fixture(directory)
            self.assertEqual(finalize(run)["status"], "passed")
            source = {p.relative_to(run): p.read_bytes() for p in run.rglob("*")
                      if p.is_file() and ".state" not in p.relative_to(run).parts}
            profile = Path(__file__).resolve().parents[1] / "docs/idea-json-backup/candidate-archive-profile.json"
            output = base / "package"
            with patch("socket.socket.connect", side_effect=AssertionError("Offline package CLI cannot retrieve")):
                code, report = self.invoke(["package", "--run", str(run), "--output", str(output),
                                            "--profile", str(profile)])
                self.assertEqual(code, 0, report)
                self.assertEqual(report["status"], "passed")
                before = {p.relative_to(output): p.read_bytes() for p in output.iterdir()}
                code, audit = self.invoke(["verify-package", str(output)])
            self.assertEqual(code, 0, audit)
            self.assertEqual(audit["status"], "passed")
            self.assertEqual(before, {p.relative_to(output): p.read_bytes() for p in output.iterdir()})
            self.assertEqual(source, {p.relative_to(run): p.read_bytes() for p in run.rglob("*")
                                     if p.is_file() and ".state" not in p.relative_to(run).parts})

    def test_looped_package_output_is_reported_before_producer_runs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loop").symlink_to("loop")
            with patch("scripts.export_idea_json.package_collection") as producer:
                code, report = self.invoke(["package", "--run", "run", "--output", str(root / "loop"),
                                            "--profile", "profile.json"])
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "failed")
            producer.assert_not_called()

    def test_write_readme_is_an_explicit_offline_handler(self):
        report = {"status": "passed", "findings": [], "created": True}
        with patch("scripts.export_idea_json.write_readme", create=True, return_value=report) as writer, patch(
                "scripts.export_idea_json.resume", side_effect=AssertionError("no retrieval")):
            code, actual = self.invoke(["write-readme", "--run", "run"])
        self.assertEqual((code, actual), (0, report))
        writer.assert_called_once_with(Path("run"))

    def test_status_reads_journal_without_mutating_payload_or_fetching(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            freeze_fixture_responses(result("Q1"), result(), base / "selection")
            with RunState.create(base / "selection", base / "run"):
                pass
            before = {p.relative_to(base / "run"): p.read_bytes() for p in (base / "run").rglob("*")
                      if p.is_file() and '.state' not in p.relative_to(base / "run").parts}
            with patch("scripts.export_idea_json.collect", side_effect=AssertionError("no live call")), patch(
                    "scripts.export_idea_json.resume", side_effect=AssertionError("no live call")):
                code, report = self.invoke(["status", "--run", str(base / "run")])
            self.assertEqual(code, 0)
            self.assertEqual(report["phase"], "initialized")
            self.assertEqual(report["counts"]["pending"], 1)
            after = {p.relative_to(base / "run"): p.read_bytes() for p in (base / "run").rglob("*")
                     if p.is_file() and '.state' not in p.relative_to(base / "run").parts}
            self.assertEqual(before, after)

    def test_pilot_selection_command_copies_parent_and_declared_subset(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            parent_fixture(base / "parent")
            (base / "qids.txt").write_text("Q10\nQ1\n")
            code, report = self.invoke(["pilot-selection", "--parent", str(base / "parent"),
                                       "--qids", str(base / "qids.txt"), "--output", str(base / "pilot")])
            self.assertEqual(code, 0)
            self.assertEqual(report["selected_count"], 2)
            self.assertEqual((base / "pilot/qids.txt").read_bytes(), b"Q1\nQ10\n")

    def test_collection_resume_and_write_verify_are_explicit_handlers(self):
        report = {"status": "passed", "findings": []}
        with patch("scripts.export_idea_json.collect") as collect, patch(
                "scripts.export_idea_json.resume") as resume, patch(
                "scripts.export_idea_json.verify_collection", return_value=report) as audit, patch(
                "scripts.export_idea_json.finalize", return_value=report) as finalize:
            self.assertEqual(self.invoke(["collect", "--selection", "selection", "--run", "run", "--kind", "pilot"])[0], 0)
            self.assertEqual(collect.call_args.kwargs["expected_kind"], "pilot")
            self.assertEqual(self.invoke(["resume", "--run", "run"])[0], 0)
            resume.assert_called_once()
            self.assertEqual(self.invoke(["verify", "--run", "run"])[0], 0)
            finalize.assert_not_called()
            self.assertEqual(self.invoke(["verify", "--run", "run", "--write"])[0], 0)
            finalize.assert_called_once()

    def test_external_report_cannot_mutate_run_payload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            with patch("scripts.export_idea_json.finalize") as finalizer:
                code, report = self.invoke(["verify", "--run", str(root), "--write", "--report", str(root / "extra.json")])
            self.assertEqual(code, 1)
            finalizer.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_corrupt_pending_selection_is_failure_not_unfinished(self):
        for corruption in ("format", "criterion", "query"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                new_selection(root)
                path = root / "selection.json"
                metadata = json.loads(path.read_bytes())
                if corruption == "format":
                    metadata["format"] = "wrong-format"
                elif corruption == "criterion":
                    metadata["criterion"]["value_id"] = "Q1"
                else:
                    (root / "query.rq").write_text("SELECT * WHERE {}")
                path.write_text(json.dumps(metadata))
                code, report = self.invoke(["verify-selection", str(root)])
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")

    def test_unfinished_selection_has_unfinished_exit_code(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            new_selection(root)
            code, report = self.invoke(["verify-selection", str(root)])
            self.assertEqual(code, 2)
            self.assertEqual(report["status"], "not_checked")

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_verify_selection_is_read_only_and_reports_corruption(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            freeze_fixture_responses(result("Q2"), result("Q1"), root)
            before = (root / "selection.json").read_bytes()
            with patch("scripts.export_idea_json.discover", side_effect=AssertionError("no network")):
                code, report = self.invoke(["verify-selection", str(root)])
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "passed")
            self.assertEqual((root / "selection.json").read_bytes(), before)
            (root / "qids.txt").write_text("Q99\n")
            self.assertEqual(self.invoke(["verify-selection", str(root)])[0], 1)

    def test_discover_uses_explicit_handler_then_independent_audit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"

            def invented(output, **options):
                return freeze_fixture_responses(result("Q10", "Q2"), result("Q1"), output)

            with patch("scripts.export_idea_json.discover", side_effect=invented) as operation:
                code, report = self.invoke(["discover", "--output", str(root)])
            operation.assert_called_once()
            self.assertEqual(code, 0)
            self.assertEqual(report["selected_count"], 3)
            self.assertEqual(report["status"], "passed")

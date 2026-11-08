"""External report publication over invented temporary inputs only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.sample_backup import jsoncodec as codec


class ExternalReportTests(unittest.TestCase):
    def test_exact_report_is_published_without_changing_protected_inputs(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            before = self.files(base)
            report = {"byte_status": "passed", "deposit_status": "not_checked", "publication": None}
            target = base / "audit.json"
            with ExternalReport(target, protected_roots=(package, downloads)) as sink:
                self.assertFalse(target.exists())  # entering precedes the audit
                sink.write(report)
            self.assertEqual(target.read_bytes(), (codec.dumps(report) + "\n").encode())
            after = self.files(base)
            self.assertEqual(set(after) - set(before), {"audit.json"})
            self.assertEqual(before, {path: body for path, body in after.items() if path != "audit.json"})

    def test_inside_or_aliased_input_destination_is_rejected_before_audit(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            (base / "alias").symlink_to(downloads, target_is_directory=True)
            for target in (package / "audit.json", downloads / "audit.json", base / "alias/audit.json"):
                with self.subTest(target=target):
                    with self.assertRaises(ValueError):
                        with ExternalReport(target, protected_roots=(package, downloads)):
                            self.fail("Protected report destination reached the audit")
            self.assertFalse((package / "audit.json").exists())
            self.assertFalse((downloads / "audit.json").exists())

    def test_replaced_parent_or_alias_between_audit_and_write_cannot_redirect_output(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        for replacement in ("symlink", "new_directory", "alias"):
            with self.subTest(replacement=replacement), TemporaryDirectory() as directory:
                base = Path(directory)
                package, downloads = self.inputs(base)
                protected = (self.files(package), self.files(downloads))
                reports = base / "reports"
                reports.mkdir()
                alias = base / "alias"
                alias.symlink_to(reports, target_is_directory=True)
                target = (alias if replacement == "alias" else reports) / "audit.json"
                with ExternalReport(target, protected_roots=(package, downloads)) as sink:
                    if replacement == "alias":
                        alias.unlink()
                        alias.symlink_to(downloads, target_is_directory=True)
                    else:
                        reports.rename(base / "held-reports")
                        if replacement == "symlink":
                            reports.symlink_to(downloads, target_is_directory=True)
                        else:
                            reports.mkdir()
                    with self.assertRaises(ValueError):
                        sink.write({"byte_status": "passed"})
                self.assertEqual(protected, (self.files(package), self.files(downloads)))
                self.assertFalse((downloads / "audit.json").exists())
                self.assertFalse((reports / "audit.json").exists())
                self.assertEqual(list((base / "held-reports").iterdir()) if replacement != "alias"
                                 else list(reports.iterdir()), [])

    def test_parent_replaced_after_staging_preserves_only_the_owned_pending_report(self):
        from scripts.idea_json_backup import external_report
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            protected = (self.files(package), self.files(downloads))
            reports = base / "reports"
            reports.mkdir()
            original = external_report._write
            report = {"byte_status": "passed"}

            def change_parent(output, name, body):
                original(output, name, body)
                reports.rename(base / "held-reports")
                reports.symlink_to(downloads, target_is_directory=True)

            with external_report.ExternalReport(reports / "audit.json", protected_roots=(package, downloads)) as sink:
                with patch.object(external_report, "_write", side_effect=change_parent):
                    with self.assertRaises(ValueError):
                        sink.write(report)
            self.assertEqual(protected, (self.files(package), self.files(downloads)))
            pending = list((base / "held-reports").glob(".audit.json.*.pending"))
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].read_bytes(), (codec.dumps(report) + "\n").encode())
            self.assertFalse((base / "held-reports/audit.json").exists())

    def test_existing_or_concurrently_created_destination_is_never_replaced(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            target = base / "audit.json"
            target.write_bytes(b"previous report")
            with self.assertRaises(FileExistsError):
                with ExternalReport(target, protected_roots=(package, downloads)):
                    self.fail("Existing report reached the audit")
            self.assertEqual(target.read_bytes(), b"previous report")
            target.unlink()
            target.symlink_to(package / "source.bin")
            with self.assertRaises(FileExistsError):
                with ExternalReport(target, protected_roots=(package, downloads)):
                    self.fail("Linked report reached the audit")
            self.assertEqual((package / "source.bin").read_bytes(), b"local baseline")
            target.unlink()
            with ExternalReport(target, protected_roots=(package, downloads)) as sink:
                target.write_bytes(b"concurrent report")
                with self.assertRaises(FileExistsError):
                    sink.write({"byte_status": "passed"})
            self.assertEqual(target.read_bytes(), b"concurrent report")
            self.assertEqual(list(base.glob(".audit.json.*.pending")), [])

    def test_looped_parent_or_protected_alias_is_a_validation_failure(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            loop = base / "loop"
            loop.symlink_to("loop", target_is_directory=True)
            for target, roots in ((loop / "audit.json", (package, downloads)),
                                  (base / "audit.json", (package, loop))):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    with ExternalReport(target, protected_roots=roots):
                        self.fail("Looped input reached the audit")
            self.assertFalse((base / "audit.json").exists())

    def test_failed_write_or_publication_keeps_owned_pending_evidence(self):
        from scripts.idea_json_backup import external_report
        for stage in ("write", "publish"):
            with self.subTest(stage=stage), TemporaryDirectory() as directory:
                base = Path(directory)
                package, downloads = self.inputs(base)
                protected = (self.files(package), self.files(downloads))
                target = base / "audit.json"

                def partial(output, name, body):
                    with output.open(name, write=True) as stream:
                        stream.write(body[:7])
                    raise OSError("Invented partial write")

                failure = patch.object(external_report, "_write", side_effect=partial) if stage == "write" else patch.object(
                    external_report, "_publish", side_effect=OSError("Invented publication failure"))
                report = {"byte_status": "passed"}
                with external_report.ExternalReport(target, protected_roots=(package, downloads)) as sink:
                    with failure, self.assertRaises(OSError):
                        sink.write(report)
                pending = list(base.glob(".audit.json.*.pending"))
                self.assertEqual(len(pending), 1)
                expected = (codec.dumps(report) + "\n").encode()
                self.assertEqual(pending[0].read_bytes(), expected[:7] if stage == "write" else expected)
                self.assertFalse(target.exists())
                self.assertEqual(protected, (self.files(package), self.files(downloads)))

    def test_validation_checks_inputs_before_staging_before_and_after_publication(self):
        from scripts.idea_json_backup.external_report import ExternalReport
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            protected = (self.files(package), self.files(downloads))
            target = base / "audit.json"
            observations = []

            def validate():
                self.assertEqual(protected, (self.files(package), self.files(downloads)))
                observations.append((target.exists(), len(list(base.glob(".audit.json.*.pending")))))

            report = {"byte_status": "passed"}
            with ExternalReport(target, protected_roots=(package, downloads)) as sink:
                sink.write(report, validate=validate)
            self.assertEqual(observations, [(False, 0), (False, 1), (True, 0)])
            self.assertEqual(target.read_bytes(), (codec.dumps(report) + "\n").encode())

    def test_input_change_during_staging_stops_publication_and_retains_pending(self):
        from scripts.idea_json_backup import external_report
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, downloads = self.inputs(base)
            protected = (self.files(package), self.files(downloads))
            target = base / "audit.json"
            original = external_report._write

            def validate():
                if protected != (self.files(package), self.files(downloads)):
                    raise ValueError("Invented input changed")

            def change_download(output, name, body):
                original(output, name, body)
                (downloads / "received.bin").write_bytes(b"changed during report staging")

            report = {"byte_status": "passed"}
            with external_report.ExternalReport(target, protected_roots=(package, downloads)) as sink:
                with patch.object(external_report, "_write", side_effect=change_download):
                    with self.assertRaisesRegex(ValueError, "Invented input changed"):
                        sink.write(report, validate=validate)
            pending = list(base.glob(".audit.json.*.pending"))
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].read_bytes(), (codec.dumps(report) + "\n").encode())
            self.assertFalse(target.exists())
            self.assertEqual(protected[0], self.files(package))
            self.assertEqual((downloads / "received.bin").read_bytes(), b"changed during report staging")

    def inputs(self, base):
        package, downloads = base / "package", base / "downloads"
        package.mkdir()
        downloads.mkdir()
        (package / "source.bin").write_bytes(b"local baseline")
        (downloads / "received.bin").write_bytes(b"received evidence")
        return package, downloads

    def files(self, base):
        return {path.relative_to(base).as_posix(): path.read_bytes() for path in base.rglob("*") if path.is_file()}


if __name__ == "__main__":
    unittest.main()

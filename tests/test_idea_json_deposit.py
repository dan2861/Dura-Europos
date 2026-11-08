"""Invented downloaded files and operator receipts; no actual Dataverse transfer."""
from pathlib import Path
import copy
import json
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch

from scripts.idea_json_backup.package_verify import verify_package
from test_idea_json_package_verify import fixture


class DepositTests(unittest.TestCase):
    def receipt(self, inventory):
        return {"dataset_url": "https://dataverse.yale.edu/dataset.xhtml?persistentId=doi:10.9999/IDEA0007&version=DRAFT",
                "persistent_id": "doi:10.9999/IDEA'0007~01", "dataset_version": "DRAFT",
                "downloaded_at": "2026-11-08T12:00:00.000000Z", "recorded_by": "Invented Danu's fixture~01",
                "evidence_kind": "operator_recorded",
                "files": [{"remote_file_id": f"{index:04d}", "download_url":
                           f"https://dataverse.yale.edu/api/access/datafile/{index:04d}?format=original",
                           "local_path": name, "downloaded_at": "2026-11-08T11:59:59Z"}
                          for index, name in enumerate(["package-inventory.json"] +
                              [part["path"] for part in inventory["archives"]], 7)]}

    def downloaded(self, base):
        package, inventory = fixture(base)
        downloads = base / "downloads"
        downloads.mkdir()
        for name in ["package-inventory.json"] + [part["path"] for part in inventory["archives"]]:
            (downloads / name).write_bytes((package / name).read_bytes())
        return package, downloads, inventory

    def files(self, root):
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_identical_invented_downloads_are_only_byte_verified_without_receipt(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline only")):
            package, downloads, inventory = self.downloaded(Path(directory))
            before = self.files(package), self.files(downloads)
            report = verify_deposit(package, downloads)
            self.assertEqual(set(report), {"format_version", "package_id", "checked_at", "acquisition",
                                           "byte_status", "deposit_status", "findings", "publication"})
            self.assertEqual(report["package_id"], inventory["package_id"])
            self.assertEqual(report["byte_status"], "passed")
            self.assertEqual(report["deposit_status"], "not_checked")
            self.assertIsNone(report["acquisition"])
            self.assertIsNone(report["publication"])
            self.assertEqual(before, (self.files(package), self.files(downloads)))

    def test_downloaded_inventory_must_match_exact_baseline_before_archive_trust(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, _ = self.downloaded(Path(directory))
            path = downloads / "package-inventory.json"
            path.write_bytes(path.read_bytes() + b" ")  # equivalent parsed JSON is insufficient
            before = self.files(package), self.files(downloads)
            with patch("scripts.idea_json_backup.deposit.verify_package", wraps=verify_package) as audit:
                report = verify_deposit(package, downloads)
            self.assertEqual(report["byte_status"], "failed")
            self.assertEqual(report["deposit_status"], "not_checked")
            self.assertEqual(report["findings"][0]["code"], "downloaded_inventory_mismatch")
            self.assertEqual(audit.call_args_list, [call(package)])
            self.assertEqual(before, (self.files(package), self.files(downloads)))

    def test_nonregular_inventory_is_rejected_before_open_can_block(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, _ = self.downloaded(Path(directory))
            path = package / "package-inventory.json"
            path.unlink()
            os.mkfifo(path)
            original = os.open

            def opened(name, *args, **kwargs):
                if str(name) == "package-inventory.json":
                    self.fail("A nonregular inventory must be rejected before opening it")
                return original(name, *args, **kwargs)

            before = self.files(downloads)
            with patch("scripts.idea_json_backup.deposit.os.open", side_effect=opened):
                report = verify_deposit(package, downloads)
            self.assertEqual(report["byte_status"], "failed")
            self.assertEqual(report["findings"][0]["code"], "unsafe_input")
            self.assertEqual(before, self.files(downloads))

    def test_complete_operator_receipt_is_retained_exactly_and_never_publishes(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, inventory = self.downloaded(Path(directory))
            receipt = self.receipt(inventory)
            before = copy.deepcopy(receipt), self.files(package), self.files(downloads)
            report = verify_deposit(package, downloads, receipt)
            self.assertEqual(report["byte_status"], "passed")
            self.assertEqual(report["deposit_status"], "passed")
            self.assertEqual(report["acquisition"], receipt)
            self.assertEqual(report["acquisition"]["files"][0]["remote_file_id"], "0007")
            self.assertEqual(report["findings"], [])
            self.assertIsNone(report["publication"])
            self.assertEqual(before, (receipt, self.files(package), self.files(downloads)))

    def test_safe_incomplete_operator_receipt_cannot_claim_deposit_verified(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        for case in ("null_fields", "files_empty", "files_null", "partial_coverage", "unknown_file_id"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                package, downloads, inventory = self.downloaded(Path(directory))
                receipt = self.receipt(inventory)
                if case == "null_fields":
                    for key in ("dataset_url", "persistent_id", "dataset_version", "downloaded_at", "recorded_by"):
                        receipt[key] = None
                elif case == "files_empty":
                    receipt["files"] = []
                elif case == "files_null":
                    receipt["files"] = None
                elif case == "partial_coverage":
                    receipt["files"].pop()
                else:
                    receipt["files"][0]["remote_file_id"] = None
                report = verify_deposit(package, downloads, receipt)
                self.assertEqual(report["byte_status"], "passed")
                self.assertEqual(report["deposit_status"], "not_checked")
                self.assertEqual(report["acquisition"], receipt)
                self.assertEqual(report["findings"][0]["code"], "acquisition_incomplete")

    def test_unsafe_supplied_urls_are_rejected_even_in_incomplete_receipts_without_echo(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        unsafe = ("https://name:TOP_SECRET_fixture@dataverse.yale.edu/dataset.xhtml",
                  "https://dataverse.yale.edu/dataset.xhtml?%61pi%4Bey=TOP_SECRET_fixture",
                  "https://dataverse.yale.edu/api/access/datafile/0007?X-Amz-Signature=TOP_SECRET_fixture")
        for field in ("dataset_url", "download_url"):
            for url in unsafe:
                with self.subTest(field=field, url=url), TemporaryDirectory() as directory:
                    package, downloads, inventory = self.downloaded(Path(directory))
                    receipt = self.receipt(inventory)
                    receipt["persistent_id"] = None  # all provided URLs still need validation
                    if field == "dataset_url":
                        receipt[field] = url
                    else:
                        receipt["files"][0][field] = url
                    report = verify_deposit(package, downloads, receipt)
                    self.assertEqual(report["byte_status"], "passed")
                    self.assertEqual(report["deposit_status"], "failed")
                    self.assertIsNone(report["acquisition"])
                    self.assertEqual(report["findings"][0]["code"], "invalid_acquisition")
                    self.assertNotIn("TOP_SECRET_fixture", json.dumps(report))

    def test_input_changes_during_underlying_audits_are_not_adopted_as_new_baselines(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        for change in ("baseline_extra_after_audit", "received_part_after_audit"):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                package, downloads, inventory = self.downloaded(Path(directory))
                changed = []

                def audit(path):
                    result = verify_package(path)
                    if not changed and Path(path) == (package if change.startswith("baseline") else downloads):
                        target = package / "unexpected.txt" if change.startswith("baseline") else downloads / inventory["archives"][0]["path"]
                        body = b"new unexpected evidence" if change.startswith("baseline") else target.read_bytes() + b"changed"
                        target.write_bytes(body)
                        changed.append((target, body))
                    return result

                with patch("scripts.idea_json_backup.deposit.verify_package", side_effect=audit):
                    report = verify_deposit(package, downloads)
                self.assertEqual(report["byte_status"], "failed")
                self.assertEqual(report["findings"][0]["code"], "input_changed")
                self.assertEqual(changed[0][0].read_bytes(), changed[0][1])

    def test_private_preview_token_urls_are_never_retained(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        urls = ("https://dataverse.yale.edu/dataset.xhtml?privateUrlToken=TOP_SECRET_fixture",
                "https://dataverse.yale.edu/dataset.xhtml?previewUrlToken=TOP_SECRET_fixture",
                "https://dataverse.yale.edu/dataset.xhtml?%70rivateUrl%54oken=TOP_SECRET_fixture",
                "https://dataverse.yale.edu/api/datasets/privateUrlDatasetVersion/TOP_SECRET_fixture",
                "https://dataverse.yale.edu/api/datasets/previewUrlDatasetVersion/TOP_SECRET_fixture",
                "https://dataverse.yale.edu/api/datasets/%70reviewUrlDatasetVersion/TOP_SECRET_fixture")
        for field in ("dataset_url", "download_url"):
            for url in urls:
                with self.subTest(field=field, url=url), TemporaryDirectory() as directory:
                    package, downloads, inventory = self.downloaded(Path(directory))
                    receipt = self.receipt(inventory)
                    if field == "dataset_url":
                        receipt[field] = url
                    else:
                        receipt["persistent_id"] = None
                        receipt["files"][0][field] = url
                    report = verify_deposit(package, downloads, receipt)
                    self.assertEqual(report["deposit_status"], "failed")
                    self.assertIsNone(report["acquisition"])
                    self.assertEqual(report["findings"][0]["code"], "invalid_acquisition")
                    self.assertNotIn("TOP_SECRET_fixture", json.dumps(report))

    def test_damaged_or_missing_downloads_never_claim_deposit_verified(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        for damage in ("part_changed", "part_missing", "extra_file", "local_report_copied"):
            for receipt_kind in ("absent", "incomplete", "complete"):
                with self.subTest(damage=damage, receipt=receipt_kind), TemporaryDirectory() as directory:
                    package, downloads, inventory = self.downloaded(Path(directory))
                    part = downloads / inventory["archives"][0]["path"]
                    if damage == "part_changed":
                        part.write_bytes(part.read_bytes() + b"changed")
                    elif damage == "part_missing":
                        part.unlink()
                    else:
                        (downloads / ("extra.txt" if damage == "extra_file" else "package-verification.json")).write_bytes(b"unrequested")
                    receipt = None if receipt_kind == "absent" else self.receipt(inventory)
                    if receipt_kind == "incomplete":
                        receipt["files"].pop()
                    before = self.files(package), self.files(downloads)
                    report = verify_deposit(package, downloads, receipt)
                    self.assertEqual(report["byte_status"], "failed")
                    self.assertEqual(report["deposit_status"], "failed" if receipt_kind == "complete" else "not_checked")
                    self.assertEqual(report["acquisition"], receipt)
                    self.assertIsNone(report["publication"])
                    self.assertEqual(before, (self.files(package), self.files(downloads)))

    def test_malformed_operator_receipts_fail_without_mutating_any_evidence(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        cases = ("missing_key", "unknown_key", "wrong_kind", "numeric_identifier", "blank_identifier",
                 "files_not_list", "file_missing_key", "duplicate_id", "duplicate_path", "unexpected_path",
                 "traversal_path", "ambiguous_path", "invalid_calendar", "non_utc_time", "file_invalid_time")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                package, downloads, inventory = self.downloaded(Path(directory))
                receipt = self.receipt(inventory)
                if case == "missing_key":
                    del receipt["persistent_id"]
                elif case == "unknown_key":
                    receipt["unrecognized"] = None
                elif case == "wrong_kind":
                    receipt["evidence_kind"] = "independently_observed"
                elif case == "numeric_identifier":
                    receipt["files"][0]["remote_file_id"] = 7
                elif case == "blank_identifier":
                    receipt["persistent_id"] = "  "
                elif case == "files_not_list":
                    receipt["files"] = {}
                elif case == "file_missing_key":
                    del receipt["files"][0]["downloaded_at"]
                elif case == "duplicate_id":
                    receipt["files"][1]["remote_file_id"] = receipt["files"][0]["remote_file_id"]
                elif case == "duplicate_path":
                    receipt["files"][1]["local_path"] = receipt["files"][0]["local_path"]
                elif case in ("unexpected_path", "traversal_path", "ambiguous_path"):
                    receipt["files"][0]["local_path"] = {"unexpected_path": "part-99999.tar.gz",
                            "traversal_path": "../package-inventory.json", "ambiguous_path": "./package-inventory.json"}[case]
                elif case == "invalid_calendar":
                    receipt["downloaded_at"] = "2026-02-30T12:00:00Z"
                elif case == "non_utc_time":
                    receipt["downloaded_at"] = "2026-11-08T12:00:00+00:00"
                else:
                    receipt["files"][0]["downloaded_at"] = "2026-11-08T25:00:00Z"
                before = copy.deepcopy(receipt), self.files(package), self.files(downloads)
                report = verify_deposit(package, downloads, receipt)
                self.assertEqual(report["byte_status"], "passed")
                self.assertEqual(report["deposit_status"], "failed")
                self.assertIsNone(report["acquisition"])
                self.assertEqual(report["findings"][0]["code"], "invalid_acquisition")
                self.assertEqual(before, (receipt, self.files(package), self.files(downloads)))

    def test_overlapping_linked_or_nonregular_inputs_are_rejected(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        for case in ("same_directory", "nested", "linked_root", "looped_root", "linked_part", "hardlinked_part", "part_directory"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                package, downloads, inventory = self.downloaded(base)
                part = downloads / inventory["archives"][0]["path"]
                if case == "same_directory":
                    downloads = package
                elif case == "nested":
                    downloads = package / "nested"
                    downloads.mkdir()
                elif case in ("linked_root", "looped_root"):
                    alias = base / "alias"
                    alias.symlink_to(downloads if case == "linked_root" else alias, target_is_directory=True)
                    downloads = alias
                else:
                    part.unlink()
                    source = package / inventory["archives"][0]["path"]
                    if case == "linked_part":
                        part.symlink_to(source)
                    elif case == "hardlinked_part":
                        os.link(source, part)
                    else:
                        part.mkdir()
                report = verify_deposit(package, downloads)
                self.assertEqual(report["byte_status"], "failed")
                self.assertEqual(report["deposit_status"], "not_checked")
                self.assertTrue(report["findings"])
                self.assertIsNone(report["publication"])

    def test_acquisition_snapshot_is_bound_before_auditing_files(self):
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, inventory = self.downloaded(Path(directory))
            receipt = self.receipt(inventory)
            original = copy.deepcopy(receipt)

            def audit(path):
                receipt["files"][0]["remote_file_id"] = "changed_by_caller"
                receipt["persistent_id"] = "changed_by_caller"
                return verify_package(path)

            with patch("scripts.idea_json_backup.deposit.verify_package", side_effect=audit):
                report = verify_deposit(package, downloads, receipt)
            self.assertEqual(report["byte_status"], "passed")
            self.assertEqual(report["deposit_status"], "passed")
            self.assertEqual(report["acquisition"], original)
            self.assertNotEqual(receipt, original)

    def test_archive_hashing_uses_bounded_stream_reads(self):
        from scripts.idea_json_backup.deposit import Directory, verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, inventory = self.downloaded(Path(directory))
            open_file = Directory.open
            reads = []

            class Reader:
                def __init__(self, stream):
                    self.stream = stream

                def read(self, size=-1):
                    self_test.assertTrue(0 < size <= 65536, "Archive input must be streamed with bounded reads")
                    reads.append(size)
                    return self.stream.read(size)

            from contextlib import contextmanager
            self_test = self

            @contextmanager
            def opened(directory, name):
                with open_file(directory, name) as source:
                    yield Reader(source) if name.endswith(".tar.gz") else source

            with patch.object(Directory, "open", opened):
                report = verify_deposit(package, downloads, self.receipt(inventory))
            self.assertEqual(report["byte_status"], "passed")
            self.assertEqual(report["deposit_status"], "passed")
            self.assertTrue(reads)

    def test_oversized_downloaded_inventory_is_rejected_without_reading_untrusted_tail(self):
        from contextlib import contextmanager
        from scripts.idea_json_backup.deposit import Directory, verify_deposit
        with TemporaryDirectory() as directory:
            package, downloads, _ = self.downloaded(Path(directory))
            original = (package / "package-inventory.json").read_bytes()
            path = downloads / "package-inventory.json"
            path.write_bytes(original + b"untrusted tail" * 20000)
            open_file = Directory.open
            reads = []

            class Reader:
                def __init__(self, stream):
                    self.stream = stream

                def read(self, size=-1):
                    body = self.stream.read(size)
                    reads.append((size, len(body)))
                    return body

            @contextmanager
            def opened(root, name):
                with open_file(root, name) as source:
                    yield Reader(source) if root.path == downloads and name == "package-inventory.json" else source

            with patch.object(Directory, "open", opened):
                report = verify_deposit(package, downloads)
            self.assertEqual(report["byte_status"], "failed")
            self.assertEqual(report["findings"][0]["code"], "downloaded_inventory_mismatch")
            self.assertTrue(reads)
            self.assertLessEqual(sum(size for _, size in reads), len(original) + 1)
            self.assertTrue(all(0 < size <= min(65536, len(original) + 1) for size, _ in reads))
            self.assertEqual(path.stat().st_size, len(original) + len(b"untrusted tail") * 20000)


if __name__ == "__main__":
    unittest.main()

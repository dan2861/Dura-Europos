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


if __name__ == "__main__":
    unittest.main()

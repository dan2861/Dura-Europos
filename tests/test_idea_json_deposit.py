"""Invented downloaded files and operator receipts; no actual Dataverse transfer."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch

from scripts.idea_json_backup.package_verify import verify_package
from test_idea_json_package_verify import fixture


class DepositTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

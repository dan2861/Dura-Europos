"""Invented resolved releases through archives and supplied-download audit."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_idea_json_release_verify import fixture


class ReleasePackageTests(unittest.TestCase):
    def test_release_roundtrips_with_explicit_version_and_no_new_deposit_claim(self):
        from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_release, write_package_report
        from scripts.idea_json_backup.package_verify import verify_package
        from scripts.idea_json_backup.deposit import verify_deposit
        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline only")):
            base = Path(directory)
            release = base / "release"
            fixture(release)
            before = {p.relative_to(release).as_posix(): p.read_bytes() for p in release.rglob("*") if p.is_file()}
            package = (base / "package").resolve()
            inventory = package_release(release, package, profile=dict(DEFAULT_PROFILE, max_members=7))
            self.assertEqual(inventory["format_version"], "1.1.0")
            self.assertEqual(inventory["payload_kind"], "resolved_release")
            self.assertEqual({row["path"] for row in inventory["payload"]}, set(before))
            report = verify_package(package)
            self.assertEqual(report["status"], "passed", report)
            write_package_report(package, report, expected_inventory=inventory)
            self.assertEqual(verify_package(package)["status"], "passed")
            self.assertEqual(before, {p.relative_to(release).as_posix(): p.read_bytes() for p in release.rglob("*") if p.is_file()})
            downloads = base / "invented-downloads"
            downloads.mkdir()
            for name in ["package-inventory.json"] + [row["path"] for row in inventory["archives"]]:
                (downloads / name).write_bytes((package / name).read_bytes())
            compared = verify_deposit(package, downloads)
            self.assertEqual((compared["byte_status"], compared["deposit_status"]), ("passed", "not_checked"))
            self.assertIsNone(compared["publication"])

    def test_package_cannot_downgrade_or_mislabel_the_release_payload(self):
        from scripts.idea_json_backup.package import package_release
        from scripts.idea_json_backup.package_verify import verify_package
        for field, value in (("format_version", "1.0.0"), ("payload_kind", "ordinary_collection")):
            with self.subTest(field=field), TemporaryDirectory() as directory:
                base = Path(directory)
                fixture(base / "release")
                inventory = package_release(base / "release", base / "package")
                inventory[field] = value
                (base / "package/package-inventory.json").write_text(json.dumps(inventory))
                self.assertEqual(verify_package(base / "package")["status"], "failed")


if __name__ == "__main__":
    unittest.main()

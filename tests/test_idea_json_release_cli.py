"""Actual CLI handlers on invented local data with network blocked."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.export_idea_json import main
from scripts.idea_json_backup.package import DEFAULT_PROFILE
from test_idea_json_release import source_fixture, public_files


def command(arguments):
    output = io.StringIO()
    with redirect_stdout(output):
        code = main(arguments)
    return code, json.loads(output.getvalue())


class ReleaseCLITests(unittest.TestCase):
    def test_create_verify_package_and_simulated_download_keep_completion_basis_separate(self):
        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline only")):
            base = Path(directory)
            run, request = source_fixture(base)
            before = public_files(run)
            requested = base / "redirect-request.json"
            requested.write_text(json.dumps(request))
            release = base / "release"
            code, report = command(["create-release", "--run", str(run), "--output", str(release), "--request", str(requested)])
            self.assertEqual((code, report["status"]), (0, "passed"), report)
            self.assertEqual(report["counts"]["usable_items"], 1)
            self.assertEqual(report["counts"]["redirected"], 1)
            self.assertEqual(command(["verify-release", str(release)])[0], 0)
            profile = base / "profile.json"
            profile.write_text(json.dumps(dict(DEFAULT_PROFILE, max_members=7)))
            package = base / "package"
            code, report = command(["package-release", "--release", str(release), "--output", str(package), "--profile", str(profile)])
            self.assertEqual((code, report["status"]), (0, "passed"), report)
            self.assertEqual(command(["verify-package", str(package)])[0], 0)
            inventory = json.loads((package / "package-inventory.json").read_bytes())
            downloads = base / "invented-downloads"
            downloads.mkdir()
            for name in ["package-inventory.json"] + [part["path"] for part in inventory["archives"]]:
                (downloads / name).write_bytes((package / name).read_bytes())
            code, report = command(["verify-deposit", "--package", str(package), "--downloads", str(downloads)])
            self.assertEqual((code, report["byte_status"], report["deposit_status"]), (2, "passed", "not_checked"))
            self.assertIsNone(report["publication"])
            self.assertEqual(public_files(run), before)

    def test_request_must_be_outside_protected_source_before_release_creation(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            run, request = source_fixture(base)
            path = run / "request.json"
            path.write_text(json.dumps(request))
            with patch("scripts.idea_json_backup.release.create_release") as produce:
                code, report = command(["create-release", "--run", str(run), "--output", str(base / "release"), "--request", str(path)])
            self.assertEqual(code, 1)
            produce.assert_not_called()
            self.assertFalse((base / "release").exists())


if __name__ == "__main__":
    unittest.main()

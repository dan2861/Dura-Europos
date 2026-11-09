"""Invented selection, retry/local recovery, finalization and archive roundtrip."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.idea_json_backup.finalize import finalize
from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_collection, write_package_report
from scripts.idea_json_backup.package_verify import verify_package
from scripts.idea_json_backup.production import collect, resume
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.state import RunState
from scripts.sample_backup import jsoncodec as codec
from scripts.export_idea_json import main
from test_idea_json_production import Clock, graph, item


class ArchiveIntegrationTests(unittest.TestCase):
    def test_cli_historical_profile_never_supplies_the_new_deposits_receipt(self):
        from test_idea_json_finalize import fixture
        from test_idea_json_retention import evidence
        for complete in (False, True):
            with self.subTest(complete=complete), TemporaryDirectory() as directory, patch(
                    "socket.socket.connect", side_effect=AssertionError("Offline fixture only")):
                base = Path(directory)
                root = fixture(directory)
                self.assertEqual(finalize(root)["status"], "passed")
                source = self.files(root, exclude_state=True)
                historical = evidence(complete=complete)
                profile = base / "profile.json"
                profile.write_text(json.dumps(dict(DEFAULT_PROFILE, retention_evidence=historical)))
                profile_before = profile.read_bytes()
                output = base / "historical-package"
                code, report = self.command(["package", "--run", str(root), "--output", str(output),
                                             "--profile", str(profile)])
                self.assertEqual((code, report["status"]), (0, "passed"), report)
                self.assertEqual(self.command(["verify-package", str(output)])[0], 0)
                inventory = json.loads((output / "package-inventory.json").read_bytes())
                self.assertEqual(inventory["profile"]["retention_evidence"], historical)
                downloads = base / "invented-downloads"
                downloads.mkdir()
                for name in ["package-inventory.json"] + [part["path"] for part in inventory["archives"]]:
                    (downloads / name).write_bytes((output / name).read_bytes())
                code, report = self.command(["verify-deposit", "--package", str(output), "--downloads", str(downloads)])
                self.assertEqual((code, report["byte_status"], report["deposit_status"]),
                                 (2, "passed", "not_checked"))
                self.assertIsNone(report["acquisition"])
                self.assertIsNone(report["publication"])
                self.assertEqual([finding["code"] for finding in report["findings"]], ["acquisition_missing"])
                self.assertEqual(profile.read_bytes(), profile_before)
                self.assertEqual(self.files(root, exclude_state=True), source)

    def test_retry_committed_source_recovery_and_simulated_download_roundtrip(self):
        clock, calls = Clock(), []

        def capture(request, directory, **options):
            qids = request["parameters"]["ids"].split("|")
            calls.append((clock.seconds, qids))
            if len(calls) == 1:
                return clock.result(b'{"error":{"code":"maxlag","info":"Invented lag"}}',
                                    headers={"retry-after": ["5"]})
            return clock.result(json.dumps({"success": 1, "entities": {
                qid: item(qid) for qid in reversed(qids)}}).encode())

        accept = RunState.accept

        def crash_after_source(store, qid, *args):
            if qid == "Q51":
                raise KeyboardInterrupt("Invented crash after committed source, before item")
            return accept(store, qid, *args)

        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline fixture")):
            base = Path(directory)
            qids = [f"Q{number}" for number in range(1, 52)]
            freeze_fixture_responses(graph(*qids), graph(), base / "selection")
            with patch.object(RunState, "accept", crash_after_source), self.assertRaises(KeyboardInterrupt):
                collect(base / "selection", base / "run", fetcher=capture, sleep=clock.sleep,
                        now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual([stamp for stamp, ids in calls], [0, 5, 6])
            self.assertEqual([len(ids) for stamp, ids in calls], [50, 50, 1])
            resume(base / "run", fetcher=lambda *args, **kwargs: self.fail("Committed source must recover locally"),
                   sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual(verify_collection(base / "run")["status"], "passed")
            self.assertEqual(finalize(base / "run")["status"], "passed")
            source = self.files(base / "run", exclude_state=True)
            profile = dict(DEFAULT_PROFILE, max_members=7, max_payload_bytes_per_part=50000)
            output = (base / "package").resolve()
            inventory = package_collection(base / "run", output, profile=profile)
            report = verify_package(output)
            self.assertEqual(report["status"], "passed", report["findings"])
            write_package_report(output, report, expected_inventory=inventory)
            self.assertEqual(verify_package(output)["status"], "passed")
            self.assertEqual(source, self.files(base / "run", exclude_state=True))
            self.assertIn("responses/A000001.decoded", {row["path"] for row in inventory["payload"]})

            downloads = base / "invented-downloads"
            downloads.mkdir()
            names = ["package-inventory.json"] + [row["path"] for row in inventory["archives"]]
            for name in names:
                (downloads / name).write_bytes((output / name).read_bytes())
            self.assertEqual((downloads / "package-inventory.json").read_bytes(),
                             (output / "package-inventory.json").read_bytes())
            self.assertEqual(verify_package(downloads)["status"], "passed")
            acquired = self.files(downloads)
            arguments = ["verify-deposit", "--package", str(output), "--downloads", str(downloads)]
            code, comparison = self.command(arguments)
            self.assertEqual((code, comparison["byte_status"], comparison["deposit_status"]),
                             (2, "passed", "not_checked"))
            receipt = {"dataset_url": "https://example.org/dataset.xhtml?persistentId=doi:10.9999/fixture&version=DRAFT",
                       "persistent_id": "doi:10.9999/invented'~01", "dataset_version": "DRAFT",
                       "downloaded_at": comparison["checked_at"], "recorded_by": "Invented operator",
                       "evidence_kind": "operator_recorded",
                       "files": [{"remote_file_id": f"{index:04d}", "download_url":
                                  f"https://example.org/api/access/datafile/{index:04d}?format=original",
                                  "local_path": name, "downloaded_at": comparison["checked_at"]}
                                 for index, name in enumerate(names, 7)]}
            acquisition = base / "acquisition.json"
            acquisition.write_text(codec.dumps(receipt) + "\n")
            recorded = base / "deposit-verification.json"
            code, comparison = self.command(arguments + ["--acquisition", str(acquisition), "--report", str(recorded)])
            self.assertEqual((code, comparison["byte_status"], comparison["deposit_status"]), (0, "passed", "passed"))
            self.assertEqual(comparison["acquisition"], receipt)
            self.assertIsNone(comparison["publication"])
            self.assertEqual(codec.loads(recorded.read_bytes()), comparison)
            self.assertEqual(acquired, self.files(downloads))
            part = downloads / inventory["archives"][0]["path"]
            damaged = part.read_bytes()[:-4]
            part.write_bytes(damaged)
            self.assertEqual(verify_package(downloads)["status"], "failed")
            code, comparison = self.command(arguments + ["--acquisition", str(acquisition)])
            self.assertEqual((code, comparison["byte_status"], comparison["deposit_status"]), (1, "failed", "failed"))
            self.assertEqual(part.read_bytes(), damaged)

    def command(self, arguments):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(arguments)
        return code, codec.loads(stream.getvalue())

    def files(self, root, *, exclude_state=False):
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
                if path.is_file() and (not exclude_state or ".state" not in path.relative_to(root).parts)}


if __name__ == "__main__":
    unittest.main()

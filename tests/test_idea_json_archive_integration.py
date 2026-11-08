"""Invented selection, retry/local recovery, finalization and archive roundtrip."""
import json
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
from test_idea_json_production import Clock, graph, item


class ArchiveIntegrationTests(unittest.TestCase):
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
            for name, body in self.files(output).items():
                (downloads / name).write_bytes(body)
            self.assertEqual((downloads / "package-inventory.json").read_bytes(),
                             (output / "package-inventory.json").read_bytes())
            self.assertEqual(verify_package(downloads)["status"], "passed")
            part = downloads / inventory["archives"][0]["path"]
            damaged = part.read_bytes()[:-4]
            part.write_bytes(damaged)
            self.assertEqual(verify_package(downloads)["status"], "failed")
            self.assertEqual(part.read_bytes(), damaged)

    def files(self, root, *, exclude_state=False):
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
                if path.is_file() and (not exclude_state or ".state" not in path.relative_to(root).parts)}


if __name__ == "__main__":
    unittest.main()

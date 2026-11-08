"""Instrumented synthetic scale exercise, with real journal/files and no network.

Set IDEA_BACKUP_SCALE_COUNT=33000 for the approved full-scale exercise.
The ordinary suite uses 151 invented entities; durability calls are not bypassed.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup import collection_verify
from scripts.idea_json_backup.production import collect, resume
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.state import RunState
from test_idea_json_production import Clock, graph, item


class ScaleTests(unittest.TestCase):
    def test_real_journal_population_has_bounded_payload_passes_and_snapshots(self):
        count = int(os.environ.get("IDEA_BACKUP_SCALE_COUNT", "151"))
        self.assertGreaterEqual(count, 51)
        batches = (count + 49) // 50
        clock, metrics = Clock(), {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "run"
            qids = [f"Q{number}" for number in range(1, count + 1)]
            freeze_fixture_responses(graph(*qids), graph(), base / "selection")
            reads, hashes, snapshots, calls = Counter(), Counter(), Counter(), []
            phase = "collection"
            read_bytes = Path.read_bytes
            sha256 = hashlib.sha256
            snapshot = RunState.snapshot

            def read(path):
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    pass
                else:
                    if relative.parts[0] in ("items", "responses"):
                        reads[phase, relative.parts[0]] += 1
                return read_bytes(path)

            def digest(body=b"", *args, **kwargs):
                if body.startswith(b'{"id":"Q'):
                    hashes[phase] += 1
                return sha256(body, *args, **kwargs)

            def project(store):
                snapshots[phase] += 1
                return snapshot(store)

            def fetcher(request, directory, **options):
                batch = request["parameters"]["ids"].split("|")
                calls.append(batch)
                if "IDEA_BACKUP_SCALE_COUNT" in os.environ and len(calls) % 20 == 0:
                    print(f"Synthetic batch {len(calls)}/{batches}", flush=True)
                return clock.result(json.dumps({"success": 1, "entities": {
                    qid: item(qid) for qid in reversed(batch)}}).encode())

            with patch.object(Path, "read_bytes", read), patch.object(hashlib, "sha256", digest), patch.object(
                    collection_verify, "sha256", digest), patch.object(RunState, "snapshot", project), patch(
                    "socket.socket.connect", side_effect=AssertionError("Invented scale exercise cannot use network")):
                collect(base / "selection", root, fetcher=fetcher, sleep=clock.sleep,
                        now_fn=clock.utc, monotonic=clock.monotonic)
                self.assertEqual([qid for batch in calls for qid in batch], qids)
                self.assertEqual(len(calls), batches)
                self.assertEqual(snapshots[phase], 2)
                self.assertEqual(reads[phase, "items"], 0)
                self.assertLessEqual(reads[phase, "responses"], batches * 3)
                self.assertGreaterEqual(hashes[phase], count)
                self.assertLessEqual(hashes[phase], count * 2)

                phase = "resume"
                resume(root, fetcher=lambda *args, **kwargs: self.fail("Accepted items cannot be refetched"),
                       sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
                self.assertEqual(reads[phase, "items"], count)
                self.assertGreaterEqual(hashes[phase], count)
                self.assertLessEqual(reads[phase, "responses"], batches * 3)
                self.assertEqual(snapshots[phase], 1)

                phase = "verification"
                report = collection_verify.verify_collection(root)
                self.assertEqual(report["status"], "passed", report["findings"])
                self.assertEqual(report["counts"]["accepted"], count)
                self.assertEqual(reads[phase, "items"], count)
                self.assertGreaterEqual(hashes[phase], count)
                self.assertLessEqual(reads[phase, "responses"], batches * 2)
                self.assertEqual(snapshots[phase], 0)
            metrics = {"selected": count, "batches": batches,
                       "phases": {name: {"item_reads": reads[name, "items"],
                                         "response_reads": reads[name, "responses"],
                                         "item_hashes": hashes[name], "snapshots": snapshots[name]}
                                  for name in ("collection", "resume", "verification")}}
        if "IDEA_BACKUP_SCALE_COUNT" in os.environ:
            print(json.dumps(metrics, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()

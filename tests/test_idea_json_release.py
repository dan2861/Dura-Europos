"""Invented journal-backed sources; no actual backup or network operations."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.production import collect
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.collection_verify import verify_collection
from test_idea_json_production import Clock, graph, item


def source_fixture(base):
    clock = Clock()
    selection, run = base / "selection", base / "run"
    freeze_fixture_responses(graph("Q1", "Q2"), graph(), selection)
    body = json.dumps({"success": 1, "entities": {"Q1": item("Q1"), "Q2": {"id": "Q2", "missing": ""}}}).encode()
    collect(selection, run, fetcher=lambda *args, **kwargs: clock.result(body),
            sleep=clock.sleep, now_fn=clock.utc, monotonic=clock.monotonic)
    manifest = json.loads((run / "manifest.json").read_bytes())
    request = {"format": "idea-json-backup-redirect-request", "format_version": "1.0.0",
               "run_id": manifest["run_id"], "state_sequence": manifest["state_sequence"],
               "qid_list_sha256": manifest["selection"]["qid_list"]["sha256"], "recorded_by": "Invented operator~01",
               "redirects": [{"requested_qid": "Q2", "target_qid": "Q1", "unavailable_attempt_id": "A000001",
                              "page_url": "https://www.wikidata.org/wiki/Q2?redirect=no", "observed_at": None}]}
    return run, request


def public_files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and ".state" not in path.relative_to(root).parts}


class ReleaseProducerTests(unittest.TestCase):
    def test_copy_or_report_change_after_audit_holds_the_final_marker(self):
        from scripts.idea_json_backup.release import create_release
        for phase in ("after_audit", "after_report"):
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                base = Path(directory)
                run, request = source_fixture(base)
                source_before = public_files(run)
                output = base / "release"

                def damage(event):
                    if event == phase:
                        name = "collection/items/Q1.json" if phase == "after_audit" else "verification.json"
                        (output / name).write_bytes(b"Invented changed copy")

                with self.assertRaises(ValueError): create_release(run, output, request, hook=damage)
                self.assertFalse((output / "release.json").exists())
                self.assertEqual(public_files(run), source_before)

    def test_output_swap_cannot_redirect_subsequent_copy_writes(self):
        from scripts.idea_json_backup import release
        with TemporaryDirectory() as directory:
            base = Path(directory)
            run, request = source_fixture(base)
            output, outside = base / "release", base / "outside"
            outside.mkdir()
            (outside / "keep").write_bytes(b"External bytes")
            original = release._copy
            calls = []

            def redirect(*args):
                original(*args)
                if not calls:
                    calls.append(True)
                    output.rename(base / "owned-copy")
                    output.symlink_to(outside, target_is_directory=True)

            with patch.object(release, "_copy", side_effect=redirect), self.assertRaises((OSError, ValueError)):
                release.create_release(run, output, request)
            self.assertEqual({p.name: p.read_bytes() for p in outside.iterdir()}, {"keep": b"External bytes"})

    def test_creates_separate_verified_release_without_changing_source_or_claiming_old_qid_json(self):
        from scripts.idea_json_backup.release import create_release
        from scripts.idea_json_backup.release_verify import verify_release
        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline only")):
            base = Path(directory)
            run, request = source_fixture(base)
            original = public_files(run)
            before = copy.deepcopy(request)
            output = base / "release"
            metadata = create_release(run, output, request)
            self.assertEqual(metadata["counts"], {"selected": 2, "usable_items": 1, "redirected": 1, "pending": 0, "unresolved": 0})
            self.assertEqual(verify_release(output)["status"], "passed")
            self.assertEqual(public_files(run), original)
            self.assertEqual(public_files(output / "collection"), original)
            self.assertEqual(request, before)
            self.assertFalse((output / "collection/items/Q2.json").exists())
            self.assertEqual(verify_collection(run)["status"], "failed")
            receipt = json.loads((output / "redirect-resolutions.json").read_bytes())
            self.assertIsNone(receipt["redirects"][0]["evidence"]["observed_at"])
            self.assertEqual(json.loads((output / "strict-verification.json").read_bytes())["status"], "failed")

    def test_stale_or_unrelated_request_holds_before_output_creation(self):
        from scripts.idea_json_backup.release import create_release
        for case in ("generation", "list", "target", "attempt"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                run, request = source_fixture(base)
                if case == "generation": request["state_sequence"] += 1
                elif case == "list": request["qid_list_sha256"] = "0" * 64
                elif case == "target": request["redirects"][0]["target_qid"] = "Q3"
                else: request["redirects"][0]["unavailable_attempt_id"] = "A000002"
                with self.assertRaises(ValueError): create_release(run, base / "release", request)
                self.assertFalse((base / "release").exists())

    def test_source_change_after_copy_or_copy_interruption_retains_failed_output(self):
        from scripts.idea_json_backup.release import create_release
        for case in ("source", "interrupt"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                run, request = source_fixture(base)
                output = base / "release"

                def change(event):
                    if event == "after_copy":
                        if case == "source": (run / "items/Q1.json").write_bytes(b"Invented changed source")
                        else: raise KeyboardInterrupt("Invented copy interruption")

                with self.assertRaises((ValueError, KeyboardInterrupt)):
                    create_release(run, output, request, hook=change)
                self.assertTrue(output.exists())
                self.assertFalse((output / "release.json").exists())

    def test_no_overwrite_overlap_or_redirected_output_writes(self):
        from scripts.idea_json_backup.release import create_release
        with TemporaryDirectory() as directory:
            base = Path(directory)
            run, request = source_fixture(base)
            output = base / "existing"
            output.mkdir()
            (output / "keep").write_bytes(b"Existing evidence")
            with self.assertRaises(FileExistsError): create_release(run, output, request)
            with self.assertRaises(ValueError): create_release(run, run / "nested", request)
            self.assertEqual((output / "keep").read_bytes(), b"Existing evidence")


if __name__ == "__main__":
    unittest.main()

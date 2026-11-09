"""Invented finalized collections packaged offline; no actual backup operations."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import tarfile
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.finalize import finalize
from test_idea_json_finalize import fixture


class PackageTests(unittest.TestCase):
    def test_caller_changes_cannot_replace_the_validated_historical_evidence(self):
        import copy
        from scripts.idea_json_backup import package
        from test_idea_json_retention import evidence
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            historical = evidence()
            expected = copy.deepcopy(historical)
            profile = dict(package.DEFAULT_PROFILE, retention_evidence=historical)
            original = package.verify_collection

            def change_caller_after_validation(path):
                historical.update(deposit_status="passed", findings=[])
                return original(path)

            output = Path(directory) / "package"
            with patch.object(package, "verify_collection", side_effect=change_caller_after_validation):
                inventory = package.package_collection(root, output, profile=profile)
            self.assertEqual(inventory["profile"]["retention_evidence"], expected)
            self.assertEqual(json.loads((output / "package-inventory.json").read_bytes())[
                "profile"]["retention_evidence"], expected)

    def test_historical_evidence_is_carried_without_changing_old_status_or_source(self):
        import copy
        from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_collection
        from test_idea_json_retention import evidence
        for complete in (False, True):
            with self.subTest(complete=complete), TemporaryDirectory() as directory:
                root = fixture(directory)
                self.assertEqual(finalize(root)["status"], "passed")
                before = self.public(root)
                historical = evidence(complete=complete)
                original = copy.deepcopy(historical)
                profile = dict(DEFAULT_PROFILE, retention_evidence=historical)
                output = Path(directory) / "evidence-package"
                inventory = package_collection(root, output, profile=profile)
                saved = json.loads((output / "package-inventory.json").read_bytes())
                self.assertEqual(saved["profile"]["retention_evidence"], original)
                self.assertEqual(inventory["profile"]["retention_evidence"], original)
                self.assertEqual(historical, original)
                self.assertEqual(self.public(root), before)
                self.assertNotIn("deposit_status", inventory)

    def test_failed_report_retains_damaged_missing_or_unsafe_archive_evidence(self):
        from scripts.idea_json_backup.package import package_collection, write_package_report
        for damage in ("changed", "missing", "symlink"):
            with self.subTest(damage=damage), TemporaryDirectory() as directory:
                root = fixture(directory)
                self.assertEqual(finalize(root)["status"], "passed")
                output = (Path(directory) / "package").resolve()
                inventory = package_collection(root, output)
                part = output / inventory["archives"][0]["path"]
                if damage == "changed":
                    part.write_bytes(b"Invented damaged archive evidence")
                else:
                    part.unlink()
                    if damage == "symlink":
                        outside = Path(directory) / "outside"
                        outside.write_bytes(b"External bytes must remain untouched")
                        part.symlink_to(outside)
                report = self.report(inventory)
                issue = {"code": "invented_failure", "qid": None, "path": part.name, "message": "Invented archive failure"}
                report.update(status="failed", findings=[issue])
                report["checks"][1].update(status="failed", findings=[issue])
                report["checks"][2]["status"] = "not_checked"
                metadata = (output / "package-inventory.json").read_bytes()
                write_package_report(output, report, expected_inventory=inventory)
                self.assertEqual(json.loads((output / "package-verification.json").read_bytes()), report)
                self.assertEqual((output / "package-inventory.json").read_bytes(), metadata)
                if damage == "changed":
                    self.assertEqual(part.read_bytes(), b"Invented damaged archive evidence")
                elif damage == "missing":
                    self.assertFalse(part.exists())
                else:
                    self.assertTrue(part.is_symlink())
                    self.assertEqual(outside.read_bytes(), b"External bytes must remain untouched")

    def test_report_identity_inventory_changes_and_existing_report_hold_without_overwrite(self):
        from scripts.idea_json_backup.package import package_collection, write_package_report
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = (Path(directory) / "package").resolve()
            inventory = package_collection(root, output)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            report = self.report(inventory)
            with self.assertRaises(ValueError):
                write_package_report(output, dict(report, package_id="another-package"), expected_inventory=inventory)
            with self.assertRaises(ValueError):
                write_package_report(output, dict(report, extra="not in the approved schema"), expected_inventory=inventory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
            inventory_path = output / "package-inventory.json"
            inventory_path.write_bytes(before["package-inventory.json"] + b" ")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                write_package_report(output, report, expected_inventory=inventory)
            self.assertFalse((output / "package-verification.json").exists())
            inventory_path.write_bytes(before["package-inventory.json"])
            write_package_report(output, report, expected_inventory=inventory)
            with self.assertRaises(FileExistsError):
                write_package_report(output, report, expected_inventory=inventory)
            self.assertEqual(json.loads((output / "package-verification.json").read_bytes()), report)

    def test_report_input_change_during_staging_holds_before_passing_publication(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = (Path(directory) / "package").resolve()
            inventory = package.package_collection(root, output)
            part = output / inventory["archives"][0]["path"]
            original = package._write

            def damage_after_stage(destination, name, body):
                original(destination, name, body)
                if name == "package-verification.pending.json":
                    part.write_bytes(b"Invented later change")

            with patch.object(package, "_write", side_effect=damage_after_stage):
                with self.assertRaisesRegex(ValueError, "Archive changed"):
                    package.write_package_report(output, self.report(inventory), expected_inventory=inventory)
            self.assertFalse((output / "package-verification.json").exists())
            self.assertTrue((output / "package-verification.pending.json").exists())

    def test_report_directory_and_parent_swaps_never_redirect_writes(self):
        from scripts.idea_json_backup import package
        for timing in ("parent_before_attach", "directory_after_stage"):
            with self.subTest(timing=timing), TemporaryDirectory() as directory:
                root = fixture(directory)
                self.assertEqual(finalize(root)["status"], "passed")
                area = (Path(directory) / "packages").resolve()
                area.mkdir()
                output = area / "package"
                inventory = package.package_collection(root, output)
                outside = (Path(directory) / "outside").resolve()
                outside.mkdir()
                if timing == "parent_before_attach":
                    shutil.copytree(output, outside / "package")
                    before = {p.relative_to(outside).as_posix(): p.read_bytes()
                              for p in outside.rglob("*") if p.is_file()}
                    area.rename(Path(directory) / "owned-parent")
                    area.symlink_to(outside, target_is_directory=True)
                    with self.assertRaises((OSError, ValueError)):
                        package.write_package_report(output, self.report(inventory), expected_inventory=inventory)
                    self.assertEqual(before, {p.relative_to(outside).as_posix(): p.read_bytes()
                                              for p in outside.rglob("*") if p.is_file()})
                else:
                    original = package._write

                    def redirect_after_stage(destination, name, body):
                        original(destination, name, body)
                        if name == "package-verification.pending.json":
                            output.rename(area / "owned-package")
                            output.symlink_to(outside, target_is_directory=True)

                    with patch.object(package, "_write", side_effect=redirect_after_stage):
                        with self.assertRaises(ValueError):
                            package.write_package_report(output, self.report(inventory), expected_inventory=inventory)
                    self.assertEqual(list(outside.iterdir()), [])

    def test_report_publication_binds_exact_package_and_preserves_inputs(self):
        from scripts.idea_json_backup.package import package_collection, write_package_report
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = (Path(directory) / "package").resolve()
            inventory = package_collection(root, output)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            report = self.report(inventory)
            descriptor = write_package_report(output, report, expected_inventory=inventory)
            self.assertEqual(descriptor["path"], "package-verification.json")
            self.assertEqual(json.loads((output / descriptor["path"]).read_bytes()), report)
            after = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertEqual(before, {name: body for name, body in after.items()
                                      if name != "package-verification.json"})

    def test_inaccessible_public_subtree_cannot_be_silently_omitted(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = Path(directory) / "package"

            def unreadable_tree(*args, **kwargs):
                if "onerror" in kwargs:
                    kwargs["onerror"](PermissionError("Invented public subtree read failure"))
                return iter(())

            with patch.object(package.os, "walk", side_effect=unreadable_tree):
                with self.assertRaises(PermissionError):
                    package.package_collection(root, output)
            self.assertFalse(output.exists())

    def test_splits_at_either_bound_and_archives_have_stable_normalized_headers(self):
        from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_collection
        with TemporaryDirectory() as directory:
            root = self.retry_fixture(directory)
            original = self.public(root)
            largest = max(len(body) for body in original.values())
            for label, profile in (
                    ("members", dict(DEFAULT_PROFILE, max_members=2)),
                    ("bytes", dict(DEFAULT_PROFILE, max_payload_bytes_per_part=largest))):
                with self.subTest(bound=label):
                    first = package_collection(root, Path(directory) / (label + "-first"), profile=profile)
                    for path in root.rglob("*"):
                        if path.is_file() and ".state" not in path.relative_to(root).parts:
                            os.utime(path, (2000000000, 2000000000))
                    second = package_collection(root, Path(directory) / (label + "-second"), profile=profile)
                    self.assertGreater(len(first["archives"]), 1)
                    self.assertEqual([p["sha256"] for p in first["archives"]],
                                     [p["sha256"] for p in second["archives"]])
                    self.assertEqual([p["members"] for p in first["archives"]],
                                     [p["members"] for p in second["archives"]])
                    sizes = {row["path"]: row["size_bytes"] for row in first["payload"]}
                    for part in first["archives"]:
                        self.assertLessEqual(len(part["members"]), profile["max_members"])
                        self.assertLessEqual(sum(sizes[name] for name in part["members"]),
                                             profile["max_payload_bytes_per_part"])
                        archive = Path(directory) / (label + "-first") / part["path"]
                        header = archive.read_bytes()[:10]
                        self.assertEqual(header[:4], b"\x1f\x8b\x08\x00")
                        self.assertEqual(header[4:8], b"\0" * 4)
                        with tarfile.open(archive, "r:gz") as reader:
                            for member in reader:
                                self.assertEqual((member.uid, member.gid, member.uname, member.gname,
                                                  member.mode, member.mtime), (0, 0, "", "", 0o644, 0))
                    self.assertIn("responses/A000001.encoded", sizes)
                    self.assertIn("responses/A000001.decoded", sizes)
                    self.assertIn(b'"maxlag"', original["responses/A000001.decoded"])
            self.assertEqual(self.public(root), original)

    def test_oversized_member_existing_output_and_unfinalized_input_are_held(self):
        from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_collection
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            unfinalized = Path(directory) / "unfinalized"
            with self.assertRaises(ValueError):
                package_collection(root, unfinalized)
            self.assertFalse(unfinalized.exists())
            self.assertEqual(finalize(root)["status"], "passed")
            original = self.public(root)
            oversized = Path(directory) / "oversized"
            with self.assertRaisesRegex(ValueError, "single payload"):
                package_collection(root, oversized, profile=dict(DEFAULT_PROFILE, max_payload_bytes_per_part=1))
            self.assertFalse(oversized.exists())
            existing = Path(directory) / "existing"
            existing.mkdir()
            (existing / "sentinel").write_bytes(b"retain")
            with self.assertRaises(FileExistsError):
                package_collection(root, existing)
            self.assertEqual((existing / "sentinel").read_bytes(), b"retain")
            with self.assertRaises(ValueError):
                package_collection(root, root / "cannot-nest")
            self.assertEqual(self.public(root), original)

    def test_source_changed_after_audit_is_not_blessed_and_partial_evidence_stays(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = Path(directory) / "package"
            original = package._archive

            def archive_then_change_source(*args):
                result = original(*args)
                (root / "README.md").write_bytes(b"Invented mutation after archive copy")
                return result

            with patch.object(package, "_archive", side_effect=archive_then_change_source):
                with self.assertRaisesRegex(ValueError, "Collection changed"):
                    package.package_collection(root, output)
            self.assertFalse((output / "package-inventory.json").exists())
            self.assertTrue((output / "package-inventory.pending.json").exists())
            self.assertTrue(list(output.glob("part-*.tar.gz")))

    def test_payload_hashing_and_archive_copy_use_bounded_reads(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = self.retry_fixture(directory, payload_size=150000)
            requests = []
            original = package._open_regular

            class Reader:
                def __init__(self, stream):
                    self.stream = stream

                def read(self, size=-1):
                    if not 0 < size <= 65536:
                        raise AssertionError("Unbounded producer payload read")
                    requests.append(size)
                    return self.stream.read(size)

                def fileno(self):
                    return self.stream.fileno()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

            with patch.object(package, "_open_regular", side_effect=lambda path: Reader(original(path))):
                package.package_collection(root, Path(directory) / "package")
            self.assertTrue(requests)
            self.assertIn(65536, requests)

    def test_parent_replaced_after_audit_cannot_create_output_outside(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            area, outside = Path(directory) / "packages", Path(directory) / "outside"
            area.mkdir()
            outside.mkdir()
            original = package.verify_collection

            def replace_parent_after_audit(path):
                report = original(path)
                area.rename(Path(directory) / "original-area")
                area.symlink_to(outside, target_is_directory=True)
                return report

            with patch.object(package, "verify_collection", side_effect=replace_parent_after_audit):
                with self.assertRaises(ValueError):
                    package.package_collection(root, area / "new-package")
            self.assertEqual(list(outside.iterdir()), [])

    def test_candidate_profile_cannot_change_compression_or_assert_retention(self):
        from scripts.idea_json_backup.package import DEFAULT_PROFILE, package_collection
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            for index, changed in enumerate(({"gzip_level": 5}, {"gzip_mtime": 1},
                                             {"retention_evidence": {"claimed": "Yale"}},
                                             {"max_members": True}, {"max_payload_bytes_per_part": 0},
                                             {"max_members": 5001},
                                             {"max_payload_bytes_per_part": 268435457})):
                with self.subTest(changed=changed):
                    output = Path(directory) / f"package-{index}"
                    with self.assertRaises(ValueError):
                        package_collection(root, output, profile=dict(DEFAULT_PROFILE, **changed))
                    self.assertFalse(output.exists())

    def test_replaced_output_directory_cannot_redirect_archive_writes(self):
        from scripts.idea_json_backup import package
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            output = Path(directory) / "package"
            outside = Path(directory) / "outside"
            outside.mkdir()
            original = package._archive

            def replace_after_prepare(*args):
                output.rename(Path(directory) / "owned-package-evidence")
                output.symlink_to(outside, target_is_directory=True)
                return original(*args)

            try:
                with patch.object(package, "_archive", side_effect=replace_after_prepare):
                    with self.assertRaises((OSError, ValueError)):
                        package.package_collection(root, output)
            finally:
                self.assertEqual(list(outside.iterdir()), [])

    def test_nonmapping_profile_is_a_reportable_validation_error(self):
        from scripts.idea_json_backup.package import package_collection
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                package_collection(Path(directory) / "unused", Path(directory) / "output", profile=3)

    def test_packages_every_finalized_public_byte_once_without_mutation(self):
        from scripts.idea_json_backup.package import package_collection
        with TemporaryDirectory() as directory:
            root = fixture(directory)
            self.assertEqual(finalize(root)["status"], "passed")
            original = self.public(root)
            output = Path(directory) / "package"
            with patch("socket.socket.connect", side_effect=AssertionError("Offline archive test")):
                inventory = package_collection(root, output)
            self.assertEqual(self.public(root), original)
            self.assertEqual(set(inventory), {"format", "format_version", "package_id", "run_id", "run_kind",
                                              "created_at", "profile", "payload", "archives"})
            self.assertEqual(inventory["format"], "idea-json-backup")
            self.assertEqual(inventory["run_kind"], "synthetic")
            self.assertIsNone(inventory["profile"]["retention_evidence"])
            expected = set(original)
            self.assertEqual([row["path"] for row in inventory["payload"]], sorted(expected))
            extracted = {}
            for part in inventory["archives"]:
                archive = output / part["path"]
                body = archive.read_bytes()
                self.assertEqual(part["size_bytes"], len(body))
                self.assertEqual(part["sha256"], hashlib.sha256(body).hexdigest())
                with tarfile.open(archive, "r:gz") as reader:
                    members = reader.getmembers()
                    self.assertEqual([member.name for member in members], part["members"])
                    for member in members:
                        self.assertTrue(member.isfile())
                        self.assertNotIn(member.name, extracted)
                        extracted[member.name] = reader.extractfile(member).read()
            self.assertEqual(extracted, original)
            self.assertTrue((output / "package-inventory.json").is_file())
            self.assertEqual(set(p.name for p in output.iterdir()),
                             {"package-inventory.json"} | {p["path"] for p in inventory["archives"]})

    def public(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and ".state" not in p.relative_to(root).parts}

    def retry_fixture(self, directory, *, payload_size=0):
        from scripts.idea_json_backup.production import collect
        from scripts.idea_json_backup.selection import freeze_fixture_responses
        from test_idea_json_production import Clock, graph, item
        base = Path(directory)
        clock, attempts = Clock(), []
        freeze_fixture_responses(graph("Q1"), graph(), base / "selection")

        def fetcher(request, location, **options):
            attempts.append(True)
            if len(attempts) == 1:
                return clock.result(b'{"error":{"code":"maxlag","info":"Invented busy"}}',
                                    headers={"retry-after": ["5"]})
            return clock.result(json.dumps({"success": 1, "entities": {
                "Q1": dict(item("Q1"), invented_payload="x" * payload_size)}}).encode())

        root = base / "run"
        with patch("socket.socket.connect", side_effect=AssertionError("No external calls")):
            collect(base / "selection", root, fetcher=fetcher, sleep=clock.sleep,
                    now_fn=clock.utc, monotonic=clock.monotonic)
            self.assertEqual(finalize(root)["status"], "passed")
        return root

    def report(self, inventory):
        return {"format_version": "1.0.0", "package_id": inventory["package_id"],
                "checked_at": "2026-11-08T04:00:00.000000Z", "status": "passed",
                "checks": [{"check_id": name, "status": "passed", "findings": []}
                           for name in ("inventory", "archive_integrity", "payload_roundtrip")],
                "findings": []}


if __name__ == "__main__":
    unittest.main()

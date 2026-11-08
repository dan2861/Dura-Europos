"""Invented finalized collections packaged offline; no actual backup operations."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tarfile
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.finalize import finalize
from test_idea_json_finalize import fixture


class PackageTests(unittest.TestCase):
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
                                             {"max_members": True}, {"max_payload_bytes_per_part": 0})):
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


if __name__ == "__main__":
    unittest.main()

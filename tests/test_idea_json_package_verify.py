"""Independent invented archive packages, never built by the package producer."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.sample_backup.jsoncodec import dumps
from test_idea_json_collection_verify import fixture as collection_fixture

POLICY = "uid=0,gid=0,uname=,gname=,mode=0644,mtime=0"


def descriptor(path, body):
    return {"path": path, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def archive_bytes(members):
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode="wb", filename="", mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, body in members:
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(body), 0o644, 0
                archive.addfile(entry, io.BytesIO(body))
    return result.getvalue()


def write_inventory(root, inventory):
    (root / "package-inventory.json").write_text(dumps(inventory) + "\n")


def fill_package(package, inventory, files):
    for path in package.glob("part-*.tar.gz"):
        path.unlink()
    inventory["payload"], inventory["archives"] = [], []
    ordered = sorted(files.items())
    limit = inventory["profile"]["max_members"]
    for offset in range(0, len(ordered), limit):
        part = f"part-{offset // limit + 1:05d}.tar.gz"
        members = ordered[offset:offset + limit]
        body = archive_bytes(members)
        (package / part).write_bytes(body)
        inventory["archives"].append(dict(descriptor(part, body), members=[name for name, _ in members]))
        inventory["payload"].extend(dict(descriptor(name, body), archive_path=part) for name, body in members)
    write_inventory(package, inventory)


def part_members(package, record):
    with tarfile.open(package / record["path"], "r:gz") as archive:
        return [(member.name, archive.extractfile(member).read()) for member in archive]


def replace_part(package, inventory, record, body):
    record.update(descriptor(record["path"], body))
    (package / record["path"]).write_bytes(body)
    write_inventory(package, inventory)


def fixture(base):
    source, package = base / "public", base / "package"
    manifest, _, _ = collection_fixture(source)
    report = verify_collection(source)
    assert report["status"] == "passed"
    manifest.update(phase="finalized", collection_status="passed", verification_path="verification.json")
    (source / "verification.json").write_text(dumps(report) + "\n")
    (source / "manifest.json").write_text(dumps(manifest) + "\n")
    package.mkdir()
    inventory = {"format": "idea-json-backup", "format_version": "1.0.0",
                 "package_id": "20261107T120000.000000Z-invented-package", "run_id": manifest["run_id"],
                 "run_kind": "synthetic", "created_at": "2026-11-07T12:00:00.000000Z",
                 "profile": {"format": "tar.gz", "max_members": 8, "max_payload_bytes_per_part": 1048576,
                             "gzip_level": 6, "gzip_mtime": 0, "tar_header_policy": POLICY,
                             "retention_evidence": None}, "payload": [], "archives": []}
    fill_package(package, inventory, {path.relative_to(source).as_posix(): path.read_bytes()
                                     for path in source.rglob("*") if path.is_file()})
    return package, inventory


class PackageVerifierTests(unittest.TestCase):
    def test_linked_or_looped_package_root_returns_a_structured_failure(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for kind in ("link", "loop"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                base = Path(directory)
                package, _ = fixture(base)
                alias = base / "alias"
                alias.symlink_to(package if kind == "link" else alias, target_is_directory=True)
                report = verify_package(alias)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["checks"][0]["status"], "failed")
                self.assertTrue(report["findings"])

    def test_candidate_profile_cannot_raise_approved_test_ceilings(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for field, value in (("max_members", 5001), ("max_payload_bytes_per_part", 268435457)):
            with self.subTest(field=field), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                inventory["profile"][field] = value
                write_inventory(package, inventory)
                self.assertEqual(verify_package(package)["status"], "failed")

    def test_malformed_inventory_produces_a_typed_inventory_finding(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for bad in ("path_type", "json"):
            with self.subTest(bad=bad), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                if bad == "path_type":
                    inventory["payload"][0]["path"] = 123
                    write_inventory(package, inventory)
                else:
                    (package / "package-inventory.json").write_bytes(b"{bad json")
                report = verify_package(package)
                self.assertEqual(report["status"], "failed")
                self.assertIsNone(report["findings"][0]["path"])
                self.assertEqual(report["checks"][0]["status"], "failed")

    def test_oversized_or_unsupported_pax_extensions_are_held(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for kind in ("oversized", "unsupported"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                part = inventory["archives"][0]
                header = tarfile.TarInfo("././@PaxHeader")
                header.type, header.mode = tarfile.XHDTYPE, 0
                if kind == "oversized":
                    header.size, extension = 16385, b""
                else:
                    extension = b"11 size=99\n"
                    header.size = len(extension)
                raw = header.tobuf(format=tarfile.USTAR_FORMAT) + extension
                raw += b"\0" * ((-len(extension)) % 512) + b"\0" * 1024
                replace_part(package, inventory, part, gzip.compress(raw, mtime=0, compresslevel=6))
                report = verify_package(package)
                self.assertEqual(report["status"], "failed")
                self.assertIn("PAX", report["findings"][0]["message"])

    def test_owned_unicode_long_paths_stream_safely_and_pax_headers_are_normalized(self):
        from scripts.idea_json_backup.package_verify import verify_package
        with TemporaryDirectory() as directory:
            base = Path(directory)
            package, inventory = fixture(base)
            source = base / "public"
            relative = "diagnostics/A000001-" + "𒀭" * 40 + "-1930'619c~01.txt"
            body = b"1930'619c~01\n" * 10000
            (source / "diagnostics").mkdir()
            (source / relative).write_bytes(body)
            attempt = json.loads((source / "attempts.jsonl").read_bytes())
            attempt["diagnostics"].append({"role": "invented", "file": dict(descriptor(relative, body), complete=None),
                                            "explanation": "Invented Unicode owned diagnostic"})
            body = (json.dumps(attempt, ensure_ascii=False) + "\n").encode()
            (source / "attempts.jsonl").write_bytes(body)
            manifest = json.loads((source / "manifest.json").read_bytes())
            manifest["public_records"]["attempts"]["file"] = descriptor("attempts.jsonl", body)
            saved = json.loads((source / "verification.json").read_bytes())
            saved["inputs"]["attempts"] = manifest["public_records"]["attempts"]
            (source / "manifest.json").write_text(json.dumps(manifest) + "\n")
            (source / "verification.json").write_text(json.dumps(saved) + "\n")
            fill_package(package, inventory, {p.relative_to(source).as_posix(): p.read_bytes()
                                             for p in source.rglob("*") if p.is_file()})
            original_read, original_bytes = gzip.GzipFile.read, Path.read_bytes
            reads = []

            def bounded_read(stream, size=-1):
                self.assertTrue(0 <= size <= 65536, size)
                reads.append(size)
                return original_read(stream, size)

            def metadata_only(path):
                self.assertFalse(path.name.endswith(".tar.gz"), "whole archive read into memory")
                return original_bytes(path)

            with patch.object(gzip.GzipFile, "read", bounded_read), patch.object(Path, "read_bytes", metadata_only):
                report = verify_package(package)
            self.assertEqual(report["status"], "passed", report)
            self.assertIn(65536, reads)

            part = next(row for row in inventory["archives"] if relative in row["members"])
            raw = bytearray(gzip.decompress((package / part["path"]).read_bytes()))
            offset = 0
            while True:
                header = tarfile.TarInfo.frombuf(bytes(raw[offset:offset + 512]), encoding="utf-8", errors="strict")
                if header.type == tarfile.XHDTYPE:
                    break
                offset += 512 + ((header.size + 511) // 512) * 512
            header.uid = 1
            raw[offset:offset + 512] = header.tobuf(format=tarfile.USTAR_FORMAT)
            replace_part(package, inventory, part, gzip.compress(bytes(raw), mtime=0, compresslevel=6))
            self.assertEqual(verify_package(package)["status"], "failed")

    def test_gzip_profile_hint_cannot_disagree_with_recorded_level(self):
        from scripts.idea_json_backup.package_verify import verify_package
        with TemporaryDirectory() as directory:
            package, inventory = fixture(Path(directory))
            part = inventory["archives"][0]
            body = bytearray((package / part["path"]).read_bytes())
            body[8] = 2  # gzip XFL marker for maximum compression, not candidate level 6
            replace_part(package, inventory, part, bytes(body))
            self.assertEqual(verify_package(package)["status"], "failed")

    def test_package_changes_during_roundtrip_are_detected_before_success(self):
        from scripts.idea_json_backup import package_verify
        for changed in ("inventory", "extra_file", "earlier_archive"):
            with self.subTest(changed=changed), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                original = package_verify.Audit.archive

                def audit_then_change(audit, record, *args):
                    original(audit, record, *args)
                    if record["path"] == inventory["archives"][-1]["path"]:
                        if changed == "inventory":
                            (package / "package-inventory.json").write_bytes(b"{}")
                        elif changed == "extra_file":
                            (package / "unexpected.txt").write_bytes(b"added during audit")
                        else:
                            path = package / inventory["archives"][0]["path"]
                            body = bytearray(path.read_bytes())
                            body[-1] ^= 1
                            path.write_bytes(body)

                with patch.object(package_verify.Audit, "archive", audit_then_change):
                    self.assertEqual(package_verify.verify_package(package)["status"], "failed")

    def test_changed_payload_is_detected_after_archive_checksum_is_refreshed(self):
        from scripts.idea_json_backup.package_verify import verify_package
        with TemporaryDirectory() as directory:
            package, inventory = fixture(Path(directory))
            part = inventory["archives"][0]
            members = part_members(package, part)
            members[0] = (members[0][0], b"x" + members[0][1][1:])
            replace_part(package, inventory, part, archive_bytes(members))
            report = verify_package(package)
            self.assertEqual(report["status"], "failed")
            self.assertIn("checksum", report["findings"][0]["message"].lower())

    def test_coordinated_inventory_archive_omissions_cannot_drop_any_evidence(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for omitted in ("README.md", "verification.json", "responses/A000001.json", "selection/sources/main.json"):
            with self.subTest(omitted=omitted), TemporaryDirectory() as directory:
                base = Path(directory)
                package, inventory = fixture(base)
                files = {p.relative_to(base / "public").as_posix(): p.read_bytes()
                         for p in (base / "public").rglob("*") if p.is_file()}
                self.assertIn(omitted, files)
                del files[omitted]
                fill_package(package, inventory, files)
                self.assertEqual(verify_package(package)["status"], "failed")

    def test_unsafe_links_special_files_and_duplicate_members_never_extract(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for bad in ("parent", "absolute", "ambiguous", "private", "symlink", "hardlink", "device", "duplicate"):
            with self.subTest(bad=bad), TemporaryDirectory() as directory:
                base = Path(directory)
                package, inventory = fixture(base)
                part = inventory["archives"][0]
                members = part_members(package, part)
                name, data = members[0]
                if bad == "duplicate":
                    body = archive_bytes(members + [members[0]])
                elif bad in ("parent", "absolute", "ambiguous", "private"):
                    evil = {"parent": "../outside.json", "absolute": str(base / "outside.json"),
                            "ambiguous": "items//Q1.json", "private": ".state/private.json"}[bad]
                    body = archive_bytes([(evil, data)] + members[1:])
                else:
                    output = io.BytesIO()
                    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=6) as compressed:
                        with tarfile.open(fileobj=compressed, mode="w") as archive:
                            entry = tarfile.TarInfo(name)
                            entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                                          "device": tarfile.CHRTYPE}[bad]
                            entry.linkname = str(base / "outside.json") if bad != "device" else ""
                            archive.addfile(entry)
                    body = output.getvalue()
                replace_part(package, inventory, part, body)
                self.assertEqual(verify_package(package)["status"], "failed")
                self.assertFalse((base / "outside.json").exists())

    def test_damaged_trailers_truncated_tar_and_hidden_concatenated_tar_fail(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for bad in ("crc", "truncated_gzip", "truncated_tar", "hidden_tar", "hidden_gzip"):
            with self.subTest(bad=bad), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                part = inventory["archives"][0]
                body = (package / part["path"]).read_bytes()
                other = archive_bytes([("hidden.json", b"hidden")])
                if bad == "crc":
                    damaged = bytearray(body)
                    damaged[-8] ^= 1
                    body = bytes(damaged)
                elif bad == "truncated_gzip":
                    body = body[:-4]
                elif bad == "truncated_tar":
                    body = gzip.compress(gzip.decompress(body)[:1024], mtime=0, compresslevel=6)
                elif bad == "hidden_tar":
                    body = gzip.compress(gzip.decompress(body) + gzip.decompress(other), mtime=0, compresslevel=6)
                else:
                    body += other
                replace_part(package, inventory, part, body)
                self.assertEqual(verify_package(package)["status"], "failed")

    def test_exact_types_limits_inventory_links_and_package_files_are_enforced(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for bad in ("bool_limit", "fraction_size", "member_limit", "byte_limit", "extra_key", "extra_file", "missing_part",
                    "duplicate_assignment", "path_escape", "symlink_archive", "hardlink_archive"):
            with self.subTest(bad=bad), TemporaryDirectory() as directory:
                package, inventory = fixture(Path(directory))
                if bad == "bool_limit":
                    inventory["profile"]["max_members"] = True
                elif bad == "fraction_size":
                    inventory["payload"][0]["size_bytes"] = 1.5
                elif bad == "member_limit":
                    inventory["profile"]["max_members"] = 1
                elif bad == "byte_limit":
                    inventory["profile"]["max_payload_bytes_per_part"] = 1
                elif bad == "extra_key":
                    inventory["invented"] = True
                elif bad == "extra_file":
                    (package / "unexpected.txt").write_bytes(b"extra")
                elif bad == "missing_part":
                    (package / inventory["archives"][0]["path"]).unlink()
                elif bad == "duplicate_assignment":
                    inventory["archives"][1]["members"].append(inventory["archives"][0]["members"][0])
                elif bad == "path_escape":
                    inventory["payload"][0]["path"] = "../outside"
                else:
                    archive = package / inventory["archives"][0]["path"]
                    outside = package.parent / "outside.tar.gz"
                    outside.write_bytes(archive.read_bytes())
                    archive.unlink()
                    archive.symlink_to(outside) if bad == "symlink_archive" else archive.hardlink_to(outside)
                # The strict codec deliberately rejects Python floats; write this corrupt JSON with json only.
                (package / "package-inventory.json").write_text(json.dumps(inventory))
                self.assertEqual(verify_package(package)["status"], "failed")

    def test_saved_package_report_must_identify_this_package_and_have_typed_checks(self):
        from scripts.idea_json_backup.package_verify import verify_package
        for corruption in ("json", "identity", "checks"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as directory:
                package, _ = fixture(Path(directory))
                report = verify_package(package)
                if corruption == "json":
                    body = b"not a report"
                else:
                    report["package_id"] = "20261107T120000.000000Z-other" if corruption == "identity" else report["package_id"]
                    if corruption == "checks":
                        report["checks"] = []
                    body = (dumps(report) + "\n").encode()
                (package / "package-verification.json").write_bytes(body)
                self.assertEqual(verify_package(package)["status"], "failed")

    def test_complete_package_roundtrips_every_public_file_without_mutation(self):
        from scripts.idea_json_backup.package_verify import verify_package
        with TemporaryDirectory() as directory:
            package, inventory = fixture(Path(directory))
            before = {p.name: p.read_bytes() for p in package.iterdir()}
            report = verify_package(package)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual([row["check_id"] for row in report["checks"]],
                             ["inventory", "archive_integrity", "payload_roundtrip"])
            self.assertTrue(all(row["status"] == "passed" and not row["findings"] for row in report["checks"]))
            self.assertEqual(report["package_id"], inventory["package_id"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in package.iterdir()})
            (package / "package-verification.json").write_text(dumps(report) + "\n")
            self.assertEqual(verify_package(package)["status"], "passed")


if __name__ == "__main__":
    unittest.main()

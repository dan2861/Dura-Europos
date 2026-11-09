"""Handwritten invented redirect releases; never calls the release producer."""
import copy
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.sample_backup.jsoncodec import dumps, loads
from test_idea_json_collection_verify import fixture as collection_fixture, rewrite, store

STAMP = "2026-11-08T12:00:00.000000Z"
RELEASE_ID = "20261108T120000.000000Z-invented-release"
CHECKS = ("scope", "source_content", "provenance", "files")


def write(root, name, value):
    (root / name).write_text(dumps(value) + "\n")


def descriptor(root, name):
    body = (root / name).read_bytes()
    return {"path": name, "size_bytes": len(body), "sha256": sha256(body).hexdigest()}


def declared_report(root, marker, marker_name):
    return {"format_version": "1.0.0", "release_id": marker["release_id"], "run_id": marker["run_id"],
            "checked_at": STAMP,
            "inputs": {"release": dict(descriptor(root, marker_name), path="release.json"),
                       "resolutions": descriptor(root, "redirect-resolutions.json"),
                       "strict_verification": descriptor(root, "strict-verification.json")},
            "status": "passed", "checks": [{"check_id": name, "status": "passed", "findings": []}
                                                  for name in CHECKS],
            "counts": dict(marker["counts"]), "findings": []}


def fixture(root, *, pending=False, saved=True):
    root.mkdir()
    manifest, inventory, attempts = collection_fixture(root / "collection", unavailable=True)
    resolutions = {"format": "idea-json-backup-redirect-resolution", "format_version": "1.0.0",
                   "run_id": manifest["run_id"], "state_sequence": manifest["state_sequence"],
                   "inputs": {"qid_list": manifest["selection"]["qid_list"],
                              "inventory": manifest["public_records"]["inventory"]["file"],
                              "attempts": manifest["public_records"]["attempts"]["file"]},
                   "redirects": [{"requested_qid": "Q2", "target_qid": "Q1", "unavailable_attempt_id": "A000001",
                                  "source_response": dict(attempts[0]["decoded"]),
                                  "target_item": dict(inventory[0]["item"]),
                                  "evidence": {"evidence_kind": "operator_recorded",
                                               "page_url": "https://www.wikidata.org/wiki/Q2?redirect=no",
                                               "observed_at": None, "recorded_at": STAMP,
                                               "recorded_by": "Invented operator's review~01"}}]}
    write(root, "redirect-resolutions.json", resolutions)
    strict = verify_collection(root / "collection")
    assert strict["status"] == "failed" and strict["counts"]["unresolved"] == 1
    write(root, "strict-verification.json", strict)
    (root / "README.md").write_text(
        "# Invented redirect release\n\n"
        "Run ID: " + manifest["run_id"] + "\n"
        "Frozen QIDs: 2\nUsable item JSONs: 1\nReviewed redirects: 1\n\n"
        "operator_recorded redirect; collection period, not one historical instant.\n"
        "Redirect origins have no usable item JSON.\n")
    marker = {"format": "idea-json-backup-release", "format_version": "1.0.0", "release_id": RELEASE_ID,
              "run_id": manifest["run_id"], "run_kind": "synthetic", "created_at": STAMP,
              "completion_basis": "usable_items_and_reviewed_redirects",
              "inputs": {key: descriptor(root, "collection/" + name) for key, name in (
                  ("manifest", "manifest.json"), ("inventory", "inventory.jsonl"),
                  ("attempts", "attempts.jsonl"), ("qid_list", "selection/qids.txt"))},
              "resolutions": descriptor(root, "redirect-resolutions.json"),
              "strict_verification": descriptor(root, "strict-verification.json"),
              "readme": descriptor(root, "README.md"), "verification_path": "verification.json",
              "counts": {"selected": 2, "usable_items": 1, "redirected": 1, "pending": 0, "unresolved": 0},
              "limitations": ["Invented operator_recorded redirect; historical observation time unknown"]}
    marker_name = "release.pending.json" if pending else "release.json"
    write(root, marker_name, marker)
    if saved:
        write(root, "verification.pending.json" if pending else "verification.json", declared_report(root, marker, marker_name))
    return marker, resolutions, manifest, inventory, attempts


def refresh(root, marker, *, marker_name="release.json"):
    for field, name in (("resolutions", "redirect-resolutions.json"), ("strict_verification", "strict-verification.json"),
                        ("readme", "README.md")):
        marker[field] = descriptor(root, name)
    for key, current in marker["inputs"].items():
        marker["inputs"][key] = descriptor(root, current["path"])
    write(root, marker_name, marker)
    saved_name = "verification.json" if marker_name == "release.json" else "verification.pending.json"
    write(root, saved_name, declared_report(root, marker, marker_name))


class ReleaseVerifierTests(unittest.TestCase):
    def test_handwritten_release_reconciles_redirect_without_mutating_originals(self):
        from scripts.idea_json_backup.release_verify import verify_release
        with TemporaryDirectory() as directory, patch("socket.socket.connect", side_effect=AssertionError("Offline fixture")):
            root = Path(directory) / "release"
            fixture(root)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            report = verify_release(root)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["counts"], {"selected": 2, "usable_items": 1, "redirected": 1,
                                                "pending": 0, "unresolved": 0})
            self.assertTrue(all(check["status"] == "passed" for check in report["checks"]))
            self.assertEqual(before, {path.relative_to(root): path.read_bytes()
                                      for path in root.rglob("*") if path.is_file()})

    def test_pending_marker_supports_only_the_three_publication_states(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for state in ("absent", "pending", "published"):
            with self.subTest(state=state), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                fixture(root, pending=True, saved=state != "absent")
                if state == "published":
                    (root / "verification.pending.json").rename(root / "verification.json")
                self.assertEqual(verify_release(root, pending=True)["status"], "passed")
                self.assertEqual(verify_release(root)["status"], "failed")
        for conflict in ("reports", "markers"):
            with self.subTest(conflict=conflict), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                fixture(root, pending=True)
                if conflict == "reports":
                    (root / "verification.json").write_bytes((root / "verification.pending.json").read_bytes())
                else:
                    (root / "release.json").write_bytes((root / "release.pending.json").read_bytes())
                self.assertEqual(verify_release(root, pending=True)["status"], "failed")

    def test_accepted_corruption_is_rejected_even_with_refreshed_checksums(self):
        from scripts.idea_json_backup.release_verify import verify_release
        with TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            marker, resolutions, manifest, inventory, attempts = fixture(root)
            target = root / "collection/items/Q1.json"
            changed = target.read_bytes().replace(b'"identifier":"0007"', b'"identifier":"0008"')
            inventory[0]["item"] = store(root / "collection", "items/Q1.json", changed)
            rewrite(root / "collection", manifest, inventory, attempts)
            resolutions["inputs"]["inventory"] = manifest["public_records"]["inventory"]["file"]
            resolutions["redirects"][0]["target_item"] = inventory[0]["item"]
            write(root, "redirect-resolutions.json", resolutions)
            strict = verify_collection(root / "collection")
            self.assertEqual(next(check for check in strict["checks"] if check["check_id"] == "source_content")["status"], "failed")
            write(root, "strict-verification.json", strict)
            refresh(root, marker)
            self.assertEqual(verify_release(root)["status"], "failed")

    def test_stale_unknown_target_chain_and_wrong_source_are_rejected(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for case in ("sequence", "run", "target", "target_descriptor", "source", "attempt", "chain", "duplicate", "extra_mapping"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                marker, resolutions, _, _, _ = fixture(root)
                row = resolutions["redirects"][0]
                if case == "sequence": resolutions["state_sequence"] += 1
                elif case == "run": resolutions["run_id"] = "20261103T120000.000000Z-another"
                elif case == "target":
                    row["target_qid"] = "Q3"
                    row["target_item"]["path"] = "items/Q3.json"
                elif case == "target_descriptor": row["target_item"]["sha256"] = "f" * 64
                elif case == "source": row["source_response"] = dict(row["target_item"], complete=True)
                elif case == "attempt": row["unavailable_attempt_id"] = "A000002"
                elif case == "chain":
                    resolutions["redirects"].append(dict(copy.deepcopy(row), requested_qid="Q1", target_qid="Q3",
                        target_item=dict(row["target_item"], path="items/Q3.json"),
                        evidence=dict(row["evidence"], page_url="https://www.wikidata.org/wiki/Q1?redirect=no")))
                elif case == "duplicate": resolutions["redirects"].append(copy.deepcopy(row))
                else:
                    resolutions["redirects"].append(dict(copy.deepcopy(row), requested_qid="Q3",
                        evidence=dict(row["evidence"], page_url="https://www.wikidata.org/wiki/Q3?redirect=no")))
                write(root, "redirect-resolutions.json", resolutions)
                refresh(root, marker)
                self.assertEqual(verify_release(root)["status"], "failed")

    def test_unavailable_stub_identity_and_marker_must_match_saved_body(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for case in ("id", "missing"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                marker, resolutions, manifest, inventory, attempts = fixture(root)
                source = loads((root / "collection" / attempts[0]["decoded"]["path"]).read_bytes())
                if case == "id": source["entities"]["Q2"]["id"] = "Q3"
                else: del source["entities"]["Q2"]["missing"]
                body = dumps(source).encode()
                new_source = store(root / "collection", attempts[0]["decoded"]["path"], body, complete=True)
                attempts[0].update(encoded=new_source, decoded=dict(new_source))
                attempts[0]["http"]["headers"]["content-length"] = [str(len(body))]
                rewrite(root / "collection", manifest, inventory, attempts)
                resolutions["inputs"]["attempts"] = manifest["public_records"]["attempts"]["file"]
                resolutions["redirects"][0]["source_response"] = dict(new_source)
                write(root, "redirect-resolutions.json", resolutions)
                write(root, "strict-verification.json", verify_collection(root / "collection"))
                refresh(root, marker)
                report = verify_release(root)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(any("stub" in finding["message"] for finding in report["findings"]), report)

    def test_saved_reports_cannot_lie_or_add_unsupported_fields(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for case in ("strict_status", "release_counts", "release_extra", "release_time", "readme"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                marker, _, _, _, _ = fixture(root)
                if case == "readme":
                    (root / "README.md").write_text("Invented ordinary item export\n")
                    refresh(root, marker)
                else:
                    name = "strict-verification.json" if case == "strict_status" else "verification.json"
                    report = loads((root / name).read_bytes())
                    if case == "strict_status": report["status"] = "passed"
                    elif case == "release_counts": report["counts"]["usable_items"] = 2
                    elif case == "release_extra": report["claimed_independent_transfer"] = True
                    else: report["checked_at"] = "2026-02-30T12:00:00Z"
                    write(root, name, report)
                    if case == "strict_status": refresh(root, marker)
                self.assertEqual(verify_release(root)["status"], "failed")

    def test_readme_identity_counts_and_origin_limitation_cannot_be_refreshed_away(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for case in ("run", "selected", "usable", "redirected", "duplicate", "missing", "limitation"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                marker, _, _, _, _ = fixture(root)
                path = root / "README.md"
                body = path.read_text()
                if case == "run":
                    body = body.replace("Run ID: " + marker["run_id"], "Run ID: 20261103T120000.000000Z-other")
                elif case == "selected": body = body.replace("Frozen QIDs: 2", "Frozen QIDs: 3")
                elif case == "usable": body = body.replace("Usable item JSONs: 1", "Usable item JSONs: 2")
                elif case == "redirected": body = body.replace("Reviewed redirects: 1", "Reviewed redirects: 2")
                elif case == "duplicate": body += "  usable ITEM jsons: 1  \n"
                elif case == "missing": body = body.replace("Reviewed redirects: 1\n", "")
                else: body = body.replace("Redirect origins have no usable item JSON.\n", "")
                path.write_text(body)
                refresh(root, marker)
                report = verify_release(root)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(next(check for check in report["checks"] if check["check_id"] == "files")["status"], "failed")

    def test_extra_private_linked_nonregular_and_empty_paths_are_rejected(self):
        from scripts.idea_json_backup.release_verify import verify_release
        for case in ("extra", "nested_extra", "private", "empty", "symlink", "hardlink", "fifo"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                fixture(root)
                if case == "extra": (root / "extra.json").write_bytes(b"{}")
                elif case == "nested_extra": (root / "collection/extra.json").write_bytes(b"{}")
                elif case == "private":
                    (root / "collection/.state").mkdir()
                    (root / "collection/.state/private").write_bytes(b"Invented private bytes")
                elif case == "empty": (root / "unexpected").mkdir()
                else:
                    target = root / "README.md"
                    outside = Path(directory) / "outside"
                    outside.write_bytes(target.read_bytes())
                    target.unlink()
                    if case == "symlink": target.symlink_to(outside)
                    elif case == "hardlink": target.hardlink_to(outside)
                    else: os.mkfifo(target)
                if case == "fifo":
                    original = os.open
                    def opened(name, *args, **kwargs):
                        if str(name) == "README.md": self.fail("FIFO must be rejected before opening")
                        return original(name, *args, **kwargs)
                    with patch("scripts.idea_json_backup.release_verify.os.open", side_effect=opened):
                        report = verify_release(root)
                else:
                    report = verify_release(root)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report["findings"])

    def test_changes_during_audit_cannot_be_adopted_as_the_new_baseline(self):
        from scripts.idea_json_backup import release_verify
        for change in ("bytes", "extra", "root_link"):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory) / "release"
                fixture(root)
                original = release_verify.verify_collection
                def mutate(path):
                    result = original(path)
                    if change == "bytes": (root / "README.md").write_text("Changed operator_recorded redirect collection period\n")
                    elif change == "extra": (root / "later.json").write_bytes(b"{}")
                    else:
                        root.rename(Path(directory) / "owned-release")
                        outside = Path(directory) / "outside"
                        outside.mkdir()
                        root.symlink_to(outside, target_is_directory=True)
                    return result
                with patch.object(release_verify, "verify_collection", side_effect=mutate):
                    self.assertEqual(release_verify.verify_release(root)["status"], "failed")

    def test_tree_excludes_only_top_level_state_and_hashes_in_bounded_reads(self):
        from scripts.idea_json_backup.release_verify import Tree
        with TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            body = b"Invented public bytes" * 10000
            (root / "public").write_bytes(body)
            (root / ".state").mkdir()
            (root / ".state/private").write_bytes(b"Invented private bytes")
            with Tree(root, exclude_state=True) as tree:
                original = tree.open
                @contextmanager
                def bounded(name):
                    with original(name) as source:
                        class Reader:
                            def read(self, size):
                                self_test.assertTrue(0 < size <= 65536)
                                return source.read(size)
                        yield Reader()
                self_test = self
                with patch.object(tree, "open", side_effect=bounded):
                    self.assertEqual(tree.snapshot(), {"public": descriptor(root, "public")})
                    self.assertEqual(tree.body("public"), body)
                with self.assertRaises(ValueError): tree.body(".state/private")
            (root / "nested").mkdir()
            (root / "nested/.state").mkdir()
            with Tree(root, exclude_state=True) as tree, self.assertRaises(ValueError): tree.snapshot()


if __name__ == "__main__":
    unittest.main()

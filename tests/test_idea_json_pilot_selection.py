"""Offline pilot subsets of independently built production-parent fixtures."""
import hashlib
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.idea_json_backup.pilot_selection import create_pilot_selection
from scripts.idea_json_backup.selection_verify import verify_selection
from test_idea_json_selection_verify import fixture, production_fixture, store, write_metadata


def parent_fixture(root):
    metadata = production_fixture(root)
    # Keep invented receipt times in the past of the actual child-freeze time.
    metadata = json.loads(json.dumps(metadata).replace("2026-11-03", "2020-11-03"))
    write_metadata(root, metadata)
    return metadata


def descriptor(root, relative):
    body = (root / relative).read_bytes()
    return {"path": relative, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def handbuilt_pilot(root):
    root.mkdir()
    metadata = parent_fixture(root / "parent")
    shutil.copyfile(root / "parent/query.rq", root / "query.rq")
    shutil.copytree(root / "parent/sources", root / "sources")
    metadata.update(kind="pilot", frozen_at="2020-11-03T13:00:00.000000Z",
                    qid_list=store(root, "qids.txt", b"Q1\nQ10\n"), selected_count=2,
                    parent_selection={"metadata": descriptor(root, "parent/selection.json"),
                                      "qid_list": descriptor(root, "parent/qids.txt"), "selected_count": 3})
    write_metadata(root, metadata)
    return metadata


class PilotSelectionTests(unittest.TestCase):
    def test_verified_pilot_copies_parent_unchanged_and_freezes_exact_subset(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            parent = base / "production"
            parent_fixture(parent)
            (parent / ".state").mkdir()
            (parent / ".state/receipt.json").write_text("private bookkeeping")
            before = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            child = base / "pilot"
            create_pilot_selection(parent, ["Q10", "Q1"], child)
            self.assertEqual((child / "qids.txt").read_bytes(), b"Q1\nQ10\n")
            self.assertEqual((child / "parent/qids.txt").read_bytes(), b"Q1\nQ2\nQ10\n")
            self.assertEqual((child / "parent/selection.json").read_bytes(), before[Path("selection.json")])
            self.assertFalse((child / "parent/.state").exists())
            self.assertEqual(verify_selection(child), {"status": "passed", "findings": []})
            metadata = json.loads((child / "selection.json").read_bytes())
            self.assertEqual(metadata["kind"], "pilot")
            self.assertEqual(metadata["selected_count"], 2)
            self.assertEqual(metadata["parent_selection"]["selected_count"], 3)
            self.assertEqual(before, {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()})

    def test_rejects_invalid_or_outside_subset_before_creating_output(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            parent_fixture(base / "production")
            for number, qids in enumerate(([], ["Q1", "Q1"], ["Q01"], ["Q99"], ["../Q1"])):
                with self.subTest(qids=qids):
                    output = base / str(number)
                    with self.assertRaises(ValueError):
                        create_pilot_selection(base / "production", qids, output)
                    self.assertFalse(output.exists())

    def test_rejects_synthetic_or_corrupted_parent(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            fixture(base / "synthetic")
            with self.assertRaises(ValueError):
                create_pilot_selection(base / "synthetic", ["Q1"], base / "from-synthetic")
            parent_fixture(base / "damaged")
            (base / "damaged/qids.txt").write_text("Q99\n")
            with self.assertRaises(ValueError):
                create_pilot_selection(base / "damaged", ["Q1"], base / "from-damaged")
            self.assertFalse((base / "from-synthetic").exists())
            self.assertFalse((base / "from-damaged").exists())

    def test_no_overwrite_and_no_output_inside_immutable_parent(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            parent = base / "production"
            parent_fixture(parent)
            existing = base / "existing"
            existing.mkdir()
            (existing / "keep.txt").write_text("keep")
            with self.assertRaises(FileExistsError):
                create_pilot_selection(parent, ["Q1"], existing)
            self.assertEqual((existing / "keep.txt").read_text(), "keep")
            before = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            with self.assertRaises(ValueError):
                create_pilot_selection(parent, ["Q1"], parent / "child")
            self.assertEqual(before, {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()})

    def test_independent_handbuilt_pilot_passes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "pilot"
            handbuilt_pilot(root)
            self.assertEqual(verify_selection(root), {"status": "passed", "findings": []})

    def test_parent_linkage_and_subset_corruption_fail_after_rehash(self):
        for mode in ("outside", "production-label", "parent-count", "source-metadata", "parent-list"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                root = Path(directory) / "pilot"
                metadata = handbuilt_pilot(root)
                if mode == "outside":
                    metadata.update(qid_list=store(root, "qids.txt", b"Q99\n"), selected_count=1)
                elif mode == "production-label":
                    metadata.update(kind="production", parent_selection=None)
                elif mode == "parent-count":
                    metadata["parent_selection"]["selected_count"] = 2
                elif mode == "source-metadata":
                    metadata["sources"][0]["attempts"][0]["request"]["headers"]["User-Agent"] = "Changed/1 (https://example.org)"
                else:
                    parent_metadata = json.loads((root / "parent/selection.json").read_bytes())
                    parent_metadata.update(qid_list=store(root / "parent", "qids.txt", b"Q1\nQ10\n"), selected_count=2)
                    write_metadata(root / "parent", parent_metadata)
                    metadata["parent_selection"].update(metadata=descriptor(root, "parent/selection.json"),
                                                        qid_list=descriptor(root, "parent/qids.txt"), selected_count=2)
                write_metadata(root, metadata)
                self.assertEqual(verify_selection(root)["status"], "failed")

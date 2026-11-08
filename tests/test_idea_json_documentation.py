"""Scope documentation for invented runs; legacy repair never retrieves data."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.state import RunState
from test_idea_json_state import results


class DocumentationTests(unittest.TestCase):
    def test_new_run_documents_exact_scope_and_preservation_layers(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            freeze_fixture_responses(results("Q1"), results(), root / "selection")
            with RunState.create(root / "selection", root / "run") as store:
                metadata = store.manifest
            text = (root / "run/README.md").read_text()
            self.assertIn("Run ID: " + metadata["run_id"], text)
            self.assertIn("Run kind: synthetic", text)
            self.assertIn("Frozen QIDs: 1", text)
            self.assertIn(metadata["selection"]["qid_list"]["sha256"], text)
            for phrase in ("extracted item JSON", "response-body", "collection period", "media bytes",
                           "full revision history", "recursive", ".state/", "inventory.jsonl", "attempts.jsonl"):
                self.assertIn(phrase, text)
            self.assertEqual(metadata["counts"]["accepted"], 0)

    def test_explicit_legacy_documentation_preserves_all_existing_public_bytes(self):
        from scripts.idea_json_backup.documentation import write_readme
        from test_idea_json_finalize import fixture
        with TemporaryDirectory() as directory:
            run = fixture(directory)  # complete invented source and accepted item
            readme = run / "README.md"
            if readme.exists():
                readme.unlink()  # invented legacy version never created this file
            before = self.public(run)
            report = write_readme(run)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["created"])
            after = self.public(run)
            self.assertEqual(set(after) - set(before), {"README.md"})
            self.assertEqual(before, {name: body for name, body in after.items() if name != "README.md"})
            from scripts.idea_json_backup.collection_verify import verify_collection
            from scripts.idea_json_backup.finalize import finalize
            self.assertEqual(verify_collection(run)["status"], "passed")
            self.assertEqual(finalize(run)["status"], "passed")

    def test_identical_documentation_is_idempotent_but_changed_document_is_never_replaced(self):
        from scripts.idea_json_backup.documentation import write_readme
        from test_idea_json_finalize import fixture
        with TemporaryDirectory() as directory:
            run = fixture(directory)
            before = self.public(run)
            self.assertFalse(write_readme(run)["created"])
            self.assertEqual(before, self.public(run))
            (run / "README.md").write_bytes(b"changed scope")
            before = self.public(run)
            with self.assertRaises(ValueError):
                write_readme(run)
            self.assertEqual(before, self.public(run))

    def test_finalized_payload_cannot_be_documented_or_changed(self):
        from scripts.idea_json_backup.documentation import write_readme
        from scripts.idea_json_backup.finalize import finalize
        from test_idea_json_finalize import fixture
        with TemporaryDirectory() as directory:
            run = fixture(directory)
            self.assertEqual(finalize(run)["status"], "passed")
            before = self.public(run)
            with self.assertRaises(ValueError):
                write_readme(run)
            self.assertEqual(before, self.public(run))

    def test_failed_document_publication_retains_owned_bytes_and_holds_retry(self):
        from scripts.idea_json_backup.documentation import write_readme
        from test_idea_json_finalize import fixture
        with TemporaryDirectory() as directory:
            run = fixture(directory)
            (run / "README.md").unlink()
            before = self.public(run)
            with patch("scripts.idea_json_backup.state.os.link", side_effect=OSError("Invented publication failure")):
                with self.assertRaises(OSError):
                    write_readme(run)
            self.assertEqual(before, self.public(run))
            self.assertTrue(list((run / ".state/staging").glob("run-*.pending")))
            with self.assertRaisesRegex(ValueError, "Pending publication"):
                write_readme(run)
            self.assertEqual(before, self.public(run))

    def public(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and ".state" not in p.relative_to(root).parts}


if __name__ == "__main__":
    unittest.main()

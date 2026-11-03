"""Production discovery commands with invented results and mocked operations."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.export_idea_json import main
from scripts.idea_json_backup.selection import freeze_fixture_responses
from scripts.idea_json_backup.selection import new_selection


def result(*qids):
    return json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": [
        {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}} for q in qids]}}).encode()


class ProductionCommandTests(unittest.TestCase):
    def test_corrupt_pending_selection_is_failure_not_unfinished(self):
        for corruption in ("format", "criterion", "query"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as directory:
                root = Path(directory) / "selection"
                new_selection(root)
                path = root / "selection.json"
                metadata = json.loads(path.read_bytes())
                if corruption == "format":
                    metadata["format"] = "wrong-format"
                elif corruption == "criterion":
                    metadata["criterion"]["value_id"] = "Q1"
                else:
                    (root / "query.rq").write_text("SELECT * WHERE {}")
                path.write_text(json.dumps(metadata))
                code, report = self.invoke(["verify-selection", str(root)])
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")

    def test_unfinished_selection_has_unfinished_exit_code(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            new_selection(root)
            code, report = self.invoke(["verify-selection", str(root)])
            self.assertEqual(code, 2)
            self.assertEqual(report["status"], "not_checked")

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_verify_selection_is_read_only_and_reports_corruption(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"
            freeze_fixture_responses(result("Q2"), result("Q1"), root)
            before = (root / "selection.json").read_bytes()
            with patch("scripts.export_idea_json.discover", side_effect=AssertionError("no network")):
                code, report = self.invoke(["verify-selection", str(root)])
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "passed")
            self.assertEqual((root / "selection.json").read_bytes(), before)
            (root / "qids.txt").write_text("Q99\n")
            self.assertEqual(self.invoke(["verify-selection", str(root)])[0], 1)

    def test_discover_uses_explicit_handler_then_independent_audit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "selection"

            def invented(output, **options):
                return freeze_fixture_responses(result("Q10", "Q2"), result("Q1"), output)

            with patch("scripts.export_idea_json.discover", side_effect=invented) as operation:
                code, report = self.invoke(["discover", "--output", str(root)])
            operation.assert_called_once()
            self.assertEqual(code, 0)
            self.assertEqual(report["selected_count"], 3)
            self.assertEqual(report["status"], "passed")

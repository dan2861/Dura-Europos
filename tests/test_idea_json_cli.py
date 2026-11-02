"""MVP commands tested only on invented files or an injected collector."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.idea_json_backup.__main__ import main

BODY = (b'{"success":1,"entities":{"Q1":{"id":"Q1","type":"item",'
        b'"lastrevid":7,"modified":"2026-11-02T12:00:00Z","claims":{}}}}')


class CommandTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_preserve_and_verify_invented_response_with_no_overwrite(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "qids.txt").write_text("Q1\n")
            (base / "response.json").write_bytes(BODY)
            args = ["preserve", "--qids", str(base / "qids.txt"),
                    "--response", str(base / "response.json"), "--output", str(base / "run"),
                    "--kind", "synthetic", "--description", "Invented command test"]
            self.assertEqual(self.invoke(args)[0], 0)
            self.assertEqual(self.invoke(["verify", str(base / "run")]),
                             (0, {"status": "passed", "findings": []}))
            self.assertEqual(self.invoke(args)[0], 1)
            (base / "run/items/Q1.json").write_text("{}")
            self.assertEqual(self.invoke(["verify", str(base / "run")])[0], 1)

    def test_collect_command_is_wired_using_mock_only(self):
        with TemporaryDirectory() as directory:
            qids = Path(directory) / "qids.txt"
            qids.write_text("Q1\n")
            with patch("scripts.idea_json_backup.__main__.collect_batch") as collect, patch(
                    "scripts.idea_json_backup.__main__.verify_run", return_value={"status": "passed", "findings": []}):
                code, report = self.invoke(["collect", "--qids", str(qids), "--output", str(Path(directory) / "run"),
                                            "--description", "Future authorized pilot"])
            self.assertEqual(code, 0)
            collect.assert_called_once()
            self.assertEqual(collect.call_args.args[0], ["Q1"])

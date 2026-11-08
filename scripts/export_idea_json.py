"""Explicit operational commands; imports and read-only audits perform no network calls."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
from urllib.parse import quote

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.idea_json_backup.discovery import discover
from scripts.idea_json_backup.selection_verify import verify_selection
from scripts.idea_json_backup.transport import DEFAULT_USER_AGENT
from scripts.idea_json_backup.pilot_selection import create_pilot_selection
from scripts.idea_json_backup.production import collect, resume
from scripts.idea_json_backup.collection_verify import verify_collection
from scripts.idea_json_backup.finalize import finalize
from scripts.idea_json_backup.files import write_bytes
from scripts.idea_json_backup.documentation import write_readme
from scripts.sample_backup import jsoncodec as codec


def _qids(path):
    with path.open(encoding="utf-8", newline=None) as stream:
        return [line.removesuffix("\n") for line in stream]


def _status(root):
    path = root / ".state/state.sqlite"
    if root.is_symlink() or (root / ".state").is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("Missing or unsafe authoritative journal")
    with sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Journal integrity check failed")
        row = db.execute("SELECT record FROM run WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Missing run metadata")
        metadata = codec.loads(row[0])
    return {"status": "passed", "phase": metadata["phase"], "counts": metadata["counts"],
            "collection_status": metadata["collection_status"], "state_sequence": metadata["state_sequence"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="IDEA JSON backup: explicit selection, collection and verification")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("discover", help="LIVE: query both graphs and freeze the union")
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    command = commands.add_parser("verify-selection", help="Offline read-only selection audit")
    command.add_argument("directory", type=Path)
    command = commands.add_parser("pilot-selection", help="Offline parent-linked explicit subset")
    command.add_argument("--parent", required=True, type=Path)
    command.add_argument("--qids", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path)
    command = commands.add_parser("collect", help="LIVE: collect the explicitly selected scope")
    command.add_argument("--selection", required=True, type=Path)
    command.add_argument("--run", required=True, type=Path)
    command.add_argument("--kind", required=True, choices=("production", "pilot"))
    command.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    command.add_argument("--max-batches", type=int)
    command = commands.add_parser("resume", help="LIVE after recovery: unresolved eligible items only")
    command.add_argument("--run", required=True, type=Path)
    command.add_argument("--max-batches", type=int)
    command = commands.add_parser("status", help="Read-only authoritative journal status")
    command.add_argument("--run", required=True, type=Path)
    command = commands.add_parser("write-readme", help="Offline: add missing scope documentation to a stopped unfinalized run")
    command.add_argument("--run", required=True, type=Path)
    command = commands.add_parser("verify", help="Read-only public audit; --write finalizes a stopped run")
    command.add_argument("--run", required=True, type=Path)
    command.add_argument("--write", action="store_true")
    command.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify" and args.report is not None and args.report.resolve().is_relative_to(args.run.resolve()):
            raise ValueError("Read-only audit report must be external to the run payload")
        if args.command == "collect":
            collect(args.selection, args.run, expected_kind=args.kind, user_agent=args.user_agent, max_batches=args.max_batches)
            report = verify_collection(args.run)
        elif args.command == "resume":
            resume(args.run, max_batches=args.max_batches)
            report = verify_collection(args.run)
        elif args.command == "status":
            report = _status(args.run)
        elif args.command == "write-readme":
            report = write_readme(args.run)
        elif args.command == "verify":
            report = finalize(args.run) if args.write else verify_collection(args.run)
            if args.report is not None:
                write_bytes(args.report, (codec.dumps(report) + "\n").encode("utf-8"))
        elif args.command == "pilot-selection":
            metadata = create_pilot_selection(args.parent, _qids(args.qids), args.output)
            report = dict(verify_selection(args.output), selected_count=metadata["selected_count"], output=str(args.output))
        elif args.command == "discover":
            directory = args.output
            metadata = discover(directory, user_agent=args.user_agent)
            report = verify_selection(directory)
            if report["status"] == "passed":
                report = dict(report, selected_count=metadata["selected_count"], output=str(directory))
        else:
            report = verify_selection(args.directory)
        print(codec.dumps(report))
        return {"passed": 0, "failed": 1, "not_checked": 2}[report["status"]]
    except KeyboardInterrupt:
        print(json.dumps({"status": "not_checked", "findings": ["Interrupted; retain and review saved evidence"]}))
        return 2
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

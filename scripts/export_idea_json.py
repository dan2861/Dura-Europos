"""Production roadmap CLI: discovery only at this milestone; no item collection."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.idea_json_backup.discovery import discover
from scripts.idea_json_backup.selection_verify import verify_selection
from scripts.idea_json_backup.transport import DEFAULT_USER_AGENT


def main(argv=None):
    parser = argparse.ArgumentParser(description="IDEA JSON backup production discovery")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("discover", help="LIVE: query both graphs and freeze the union")
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    command = commands.add_parser("verify-selection", help="Offline read-only selection audit")
    command.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        directory = args.output if args.command == "discover" else args.directory
        if args.command == "discover":
            metadata = discover(directory, user_agent=args.user_agent)
        report = verify_selection(directory)
        if args.command == "discover" and report["status"] == "passed":
            report = dict(report, selected_count=metadata["selected_count"], output=str(directory))
        print(json.dumps(report))
        return 0 if report["status"] == "passed" else 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "not_checked", "findings": ["Interrupted; retain and review partial selection"]}))
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

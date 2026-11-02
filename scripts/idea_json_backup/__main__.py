"""Prototype commands. Only the explicitly invoked collect command uses a network."""
import argparse
import json
from pathlib import Path

from .collector import collect_batch
from .mvp import preserve_batch
from .transport import DEFAULT_USER_AGENT
from .verify import verify_run


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-batch IDEA JSON backup MVP")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Read-only offline verification")
    verify.add_argument("directory", type=Path)
    for name in ("preserve", "collect"):
        command = commands.add_parser(name, help=("Preserve a supplied offline response" if name == "preserve"
                                                  else "LIVE: requires an explicitly authorized pilot"))
        command.add_argument("--qids", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path)
        command.add_argument("--description", required=True)
        if name == "preserve":
            command.add_argument("--response", required=True, type=Path)
            command.add_argument("--kind", required=True, choices=("synthetic", "saved"))
        else:
            command.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
            command.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = verify_run(args.directory)
        else:
            with args.qids.open(encoding="utf-8", newline=None) as stream:
                qids = [line.removesuffix("\n") for line in stream]
            if args.command == "preserve":
                preserve_batch(args.response.read_bytes(), qids, args.output, provenance={
                    "kind": args.kind, "description": args.description, "retrieved_at": None})
            else:
                collect_batch(qids, args.output, description=args.description,
                              user_agent=args.user_agent, timeout_seconds=args.timeout_seconds)
            report = verify_run(args.output)
        print(json.dumps(report))
        return 0 if report["status"] == "passed" else 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "incomplete", "findings": ["Interrupted; inspect retained run evidence"]}))
        return 130
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

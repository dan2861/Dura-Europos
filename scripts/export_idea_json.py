"""Explicit operational commands; imports and read-only audits perform no network calls."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
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
from scripts.idea_json_backup.package import package_collection, package_release, write_package_report
from scripts.idea_json_backup.package_verify import verify_package
from scripts.idea_json_backup.deposit import Directory, verify_deposit
from scripts.idea_json_backup.external_report import ExternalReport
from scripts.sample_backup import jsoncodec as codec


def _qids(path):
    with path.open(encoding="utf-8", newline=None) as stream:
        return [line.removesuffix("\n") for line in stream]


def _profile(path):
    value = codec.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Candidate archive profile must be an object")
    converted = {}
    for key, field in value.items():
        if isinstance(field, codec.Number):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", field.token):
                raise ValueError("Candidate archive profile numbers must be JSON integers")
            field = int(field.token)
        converted[key] = field
    return converted


def _acquisition(path, *, protected_roots, stack):
    try:
        requested = path.absolute()
        target = requested.parent.resolve(strict=True) / requested.name
        roots = tuple(root.absolute() for root in protected_roots)
        anchors = tuple(root.resolve() for root in roots)

        def scope():
            if (requested.parent.resolve(strict=True) != target.parent
                    or any(requested.is_relative_to(root) for root in roots)
                    or any(target.is_relative_to(root) for root in anchors + tuple(root.resolve() for root in roots))):
                raise ValueError("Acquisition receipt must remain outside package and downloads")

        scope()
        directory = stack.enter_context(Directory(target.parent))
        body = directory.body(target.name)
        receipt = codec.loads(body)

        def unchanged():
            try:
                scope()
                if directory.body(target.name) != body:
                    raise ValueError("Acquisition receipt changed during verification")
            except (OSError, ValueError, RuntimeError) as exc:
                raise ValueError("Acquisition receipt changed or became unsafe") from exc

        return receipt, unchanged
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as exc:
        raise ValueError("Cannot safely read the external operator acquisition receipt") from exc


def _deposit_inputs(roots, stack):
    """Seal input bytes before an audit that will publish an external report."""
    try:
        directories = tuple(stack.enter_context(Directory(root)) for root in roots)
        before = tuple(directory.fingerprint() for directory in directories)
    except (OSError, ValueError, RuntimeError):
        directories, before = (), None

    def unchanged():
        if before is None or tuple(directory.fingerprint() for directory in directories) != before:
            raise ValueError("Package or downloaded evidence changed before report publication")

    return unchanged


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
    command = commands.add_parser("create-release", help="Offline: copy a stopped run with explicitly reviewed redirects")
    command.add_argument("--run", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--request", required=True, type=Path)
    command = commands.add_parser("verify-release", help="Read-only audit of a self-contained resolved release")
    command.add_argument("directory", type=Path)
    command = commands.add_parser("package-release", help="Offline bounded archives of a verified resolved release")
    command.add_argument("--release", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--profile", required=True, type=Path)
    command = commands.add_parser("package", help="Offline candidate archives and independent local roundtrip")
    command.add_argument("--run", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--profile", required=True, type=Path)
    command = commands.add_parser("verify-package", help="Read-only candidate archive audit in temporary storage")
    command.add_argument("directory", type=Path)
    command = commands.add_parser("verify-deposit", help="Offline supplied-download comparison; provenance is operator recorded")
    command.add_argument("--package", required=True, type=Path)
    command.add_argument("--downloads", required=True, type=Path)
    command.add_argument("--acquisition", type=Path, help="Operator receipt; without it deposit remains not_checked")
    command.add_argument("--report", type=Path, help="New report outside package and downloaded-file directories")
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
        elif args.command == "create-release":
            from scripts.idea_json_backup.release import create_release
            from scripts.idea_json_backup.release_verify import verify_release
            try:
                output = args.output.resolve()
            except RuntimeError:
                raise ValueError("Unsafe release output path") from None
            with ExitStack() as stack:
                request, unchanged = _acquisition(args.request, protected_roots=(args.run, output), stack=stack)
                create_release(args.run, output, request, validate_input=unchanged)
                report = verify_release(output)
                unchanged()
        elif args.command == "verify-release":
            from scripts.idea_json_backup.release_verify import verify_release
            report = verify_release(args.directory)
        elif args.command in ("package", "package-release"):
            try:
                output = args.output.resolve()
            except RuntimeError as exc:
                raise ValueError("Unsafe package output path: " + str(exc)) from exc
            inventory = (package_collection(args.run, output, profile=_profile(args.profile)) if args.command == "package"
                         else package_release(args.release, output, profile=_profile(args.profile)))
            report = verify_package(output)
            write_package_report(output, report, expected_inventory=inventory)
        elif args.command == "verify-package":
            report = verify_package(args.directory)
        elif args.command == "verify-deposit":
            with ExitStack() as stack:
                roots = (args.package, args.downloads)
                destination = stack.enter_context(ExternalReport(args.report, protected_roots=(
                    args.package, args.downloads))) if args.report is not None else None
                inputs_unchanged = _deposit_inputs(roots, stack) if destination is not None else None
                acquisition, receipt_unchanged = _acquisition(args.acquisition, protected_roots=roots,
                    stack=stack) if args.acquisition is not None else (None, lambda: None)
                report = verify_deposit(args.package, args.downloads, acquisition=acquisition)
                receipt_unchanged()
                if destination is not None:
                    def validate():
                        receipt_unchanged()
                        if report["byte_status"] == "passed":
                            inputs_unchanged()
                    destination.write(report, validate=validate)
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
        if args.command == "verify-deposit":
            if report["byte_status"] == "failed" or report["deposit_status"] == "failed":
                return 1
            return 0 if report["deposit_status"] == "passed" else 2
        return {"passed": 0, "failed": 1, "not_checked": 2}[report["status"]]
    except KeyboardInterrupt:
        print(json.dumps({"status": "not_checked", "findings": ["Interrupted; retain and review saved evidence"]}))
        return 2
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "findings": [f"{type(exc).__name__}: {exc}"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

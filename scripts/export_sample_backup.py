"""Explicit export and offline verify commands; importing never retrieves or creates artifacts."""
import argparse
from pathlib import Path
import sys

# Support both a direct script invocation and import through scripts.* in tests.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def read_requested_qids(path):
    with path.open(encoding="utf-8", newline=None) as source:
        qids = [line.removesuffix("\n") for line in source]

    seen = set()

    for line_number, qid in enumerate(qids, start=1):
        if qid == "":
            raise ValueError(f"Line {line_number}: blank QID line")

        # prefix check
        if not qid.startswith("Q"):
            raise ValueError(
                f"Line {line_number}: expected uppercase Q prefix, got {qid!r}"
            )

        # numeric part check
        numeric_part = qid[1:]
        if not (numeric_part.isascii() and numeric_part.isdigit()):
            raise ValueError(
                f"Line {line_number}: expected digits after Q, got {qid!r}"
            )

        if numeric_part.startswith("0"):
            raise ValueError(f"Line {line_number}: noncanonical QID {qid!r}")

        # duplicate qid check
        if qid in seen:
            raise ValueError(
                f"Line {line_number}: duplicate QID {qid!r}"
            )
        seen.add(qid)

    return qids


def collect_requests(store, *, fetch=None):
    """Collect one attempt sequentially. Only an explicit caller invokes retrieval."""
    from scripts.sample_backup.retrieval import Result, retrieve
    fetch = fetch or retrieve
    interrupted = False
    for entry in store.manifest["items"]:
        if entry["retrieval_status"] != "pending":
            raise ValueError("Collection cannot resume or retry an existing outcome")
    for entry in store.manifest["items"]:
        qid = entry["requested_qid"]
        try:
            result = fetch(qid)
        except KeyboardInterrupt:
            result = Result(b"", [], None, "interrupted before response", interrupted=True)
        except Exception as exc:
            result = Result(b"", [], None, f"{type(exc).__name__}: {exc}")
        entry["http_trace"] = result.trace
        entry["retrieved_at"] = result.retrieved_at
        if result.entity:
            entry.update(returned_qid=result.entity.get("id"),
                         lastrevid=result.entity.get("lastrevid"), modified=result.entity.get("modified"))
        error = result.error
        if not error and (not result.complete or not result.entity):
            error = "no complete usable entity response"
        stage = result.stage
        stop = result.interrupted or stage == "saving"
        interrupted = interrupted or result.interrupted
        if not error:
            try:
                path = store.save_original(qid, result.body)
                entry.update(source_json=path, retrieval_status="succeeded")
            except OSError as exc:
                error = f"original saving failed: {exc}"
                stage = "saving"
                stop = True
        if error:
            body_path = None
            try:
                body_path = store.save_failure(qid, result.body)
            except OSError as exc:
                error += f"; failure-body saving also failed: {exc}"
                stage = "saving"
                stop = True
            entry.update(retrieval_status="failed", error={
                "stage": stage, "message": error, "body_path": body_path,
                "body_complete": result.complete if body_path else None})
            store.manifest["validation_summary"]["status"] = "failed"
        store.checkpoint()  # inability to checkpoint stops collection via exception
        if stop:
            break
    return interrupted


def prepare_tables(store):
    """Project only identity-cleared saved responses; never perform retrieval."""
    from collections import Counter
    from scripts.sample_backup import jsoncodec as codec, transform
    entries = [e for e in store.manifest["items"] if e["retrieval_status"] == "succeeded"]
    counts = Counter(e["returned_qid"] for e in entries)
    sources = []
    for entry in entries:
        if entry["requested_qid"] != entry["returned_qid"] or counts[entry["returned_qid"]] > 1:
            continue  # explicit identity/collision review remains required
        envelope = codec.loads(store.path(entry["source_json"]).read_bytes())
        sources.append(next(iter(envelope["entities"].values())))
    projection = transform.project(sources)
    for table, rows in projection.tables.items():
        store.write_table(table, rows)
    for finding in projection.findings:
        check = next(c for c in store.manifest["validation_summary"]["checks"] if c["check_id"] == finding["check_id"])
        check["status"] = "failed"
        if check["details"] is None:
            check["details"] = []
        check["details"].append(finding)
    store.checkpoint()
    return projection


def _run_note(store, reason, *, failure=False):
    check = next(c for c in store.manifest["validation_summary"]["checks"] if c["check_id"] == "files")
    if check["details"] is None:
        check["details"] = []
    check["details"].append({"run_note": reason, "failure": failure})
    check["status"] = "failed" if failure else "not_checked"


def export_attempt(input_path, output_parent, *, fetch=None):
    """A new attempt only. Tests supply invented transport results explicitly."""
    from scripts.sample_backup import jsoncodec as codec, validation
    from scripts.sample_backup.storage import RunStore, utc_now
    qids = read_requested_qids(Path(input_path))  # before creating any run or calling fetch
    store = RunStore.create(output_parent, qids, str(input_path))
    try:
        if collect_requests(store, fetch=fetch):
            _run_note(store, "Collection interrupted; unattempted requests remain pending")
        prepare_tables(store)
    except KeyboardInterrupt:
        _run_note(store, "Interrupted; completed artifacts retained and remaining work unchecked")
    except (OSError, ValueError) as exc:
        _run_note(store, f"Storage/transformation stopped: {type(exc).__name__}: {exc}", failure=True)
    store.manifest["finished_at"] = utc_now()
    store.checkpoint()  # raises if even this cannot be saved; caller reports the limitation
    report = validation.verify(store.root, write=True)
    store.manifest = codec.loads((store.root / "manifest.json").read_bytes())
    return store, report


def build_parser():
    parser = argparse.ArgumentParser(description="IDEA convenience-sample structured-record backup")
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export", help="Explicit network export to a new run folder")
    export.add_argument("--input", type=Path, default=Path("config/sample-items.txt"))
    export.add_argument("--output", type=Path, default=Path("backup"))
    verify = actions.add_parser("verify", help="Audit saved artifacts offline; read-only by default")
    verify.add_argument("run", type=Path)
    verify.add_argument("--write", action="store_true", help="Atomically persist results without refreshing inventory")
    verify.add_argument("--manual-review", type=Path, help="Existing JSON manual-review evidence")
    return parser


def main(argv=None):
    from scripts.sample_backup import jsoncodec as codec, validation
    args = build_parser().parse_args(argv)
    try:
        if args.action == "verify":
            evidence = codec.loads(args.manual_review.read_bytes()) if args.manual_review else None
            report = validation.verify(args.run, write=args.write, manual_evidence=evidence)
        else:
            store, report = export_attempt(args.input, args.output)
            print(f"Run folder: {store.root}")
        print(codec.dumps(report))
        return {"passed": 0, "failed": 1, "not_checked": 2}[report["status"]]
    except (OSError, ValueError) as exc:
        print(f"Backup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; no completed validation is claimed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

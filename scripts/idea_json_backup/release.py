"""New self-contained redirect releases; original collection bytes stay intact."""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import uuid

from scripts.sample_backup import jsoncodec as codec
from .collection_verify import verify_collection
from .files import describe
from .package import _Parent, _Output, _write, _publish
from .release_contract import (VERSION, RESOLUTIONS_FORMAT, RELEASE_FORMAT, COMPLETION_BASIS,
                               INPUT_PATHS, integer, validate_request, validate_resolutions, validate_release)
from .release_verify import Tree, verify_release
from .state import RunState, utc_now


def _rows(body):
    return [codec.loads(line) for line in body.splitlines()]


def _strict_ready(report, origins):
    expected = {"code": "invalid_record", "path": None,
                "message": "Unresolved item prevents collection completion"}
    if (report["status"] != "failed" or report["counts"]["pending"] != 0
            or report["counts"]["accepted"] < 1 or report["counts"]["unresolved"] != len(origins)
            or len(report["findings"]) != len(origins)
            or {row["qid"] for row in report["findings"]} != origins
            or any({key: row[key] for key in expected} != expected for row in report["findings"])
            or any(check["status"] != ("failed" if check["check_id"] == "scope" else "passed")
                   for check in report["checks"])):
        raise ValueError("Source requires review beyond the declared redirect exceptions")


def _resolve(request, manifest, inventory, attempts, created):
    if (request["run_id"] != manifest["run_id"]
            or integer(request["state_sequence"]) != manifest["state_sequence"]
            or request["qid_list_sha256"] != manifest["selection"]["qid_list"]["sha256"]):
        raise ValueError("Redirect request differs from the stopped source generation")
    items = {row["requested_qid"]: row for row in inventory}
    sources = {row["attempt_id"]: row for row in attempts}
    origins = {row["requested_qid"] for row in request["redirects"]}
    if origins != {qid for qid, row in items.items() if row["status"] == "unresolved"}:
        raise ValueError("Redirect request must cover exactly the unresolved items")
    result = {"format": RESOLUTIONS_FORMAT, "format_version": VERSION, "run_id": manifest["run_id"],
              "state_sequence": manifest["state_sequence"],
              "inputs": {"qid_list": manifest["selection"]["qid_list"],
                         "inventory": manifest["public_records"]["inventory"]["file"],
                         "attempts": manifest["public_records"]["attempts"]["file"]}, "redirects": []}
    for row in request["redirects"]:
        origin, target = items[row["requested_qid"]], items.get(row["target_qid"])
        error = origin["error"] or {}
        if (target is None or target["status"] != "accepted" or not origin["attempt_ids"]
                or origin["attempt_ids"][-1] != row["unavailable_attempt_id"]
                or error.get("stage") != "identity" or error.get("code") != "missing_or_redirect"
                or error.get("retryable") is not False):
            raise ValueError("Redirect request lacks the held origin or accepted target")
        attempt = sources[row["unavailable_attempt_id"]]
        result["redirects"].append({
            "requested_qid": row["requested_qid"], "target_qid": row["target_qid"],
            "unavailable_attempt_id": row["unavailable_attempt_id"], "source_response": attempt["decoded"],
            "target_item": target["item"], "evidence": {
                "evidence_kind": "operator_recorded", "page_url": row["page_url"],
                "observed_at": row["observed_at"], "recorded_at": created, "recorded_by": request["recorded_by"]}})
    validate_resolutions(result)
    return result


def _json(output, name, value):
    body = (codec.dumps(value) + "\n").encode("utf-8")
    _write(output, name, body)
    return describe(name, body)


def _copy(source, expected, destination):
    digest, size = sha256(), 0
    with source.open(expected["path"]) as incoming, destination.open(PurePosixPath(expected["path"]).name, write=True) as outgoing:
        while block := incoming.read(65536):
            if outgoing.write(block) != len(block):
                raise OSError("Incomplete release copy")
            digest.update(block)
            size += len(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    destination.sync()
    if size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError("Source changed while copying the release")


def create_release(run_dir, output_dir, request, *, validate_input=None, now_fn=utc_now, hook=None):
    """Copy one reviewed source into an absent release; never retrieve or repair."""
    request = deepcopy(request)
    validate_request(request)
    validate_input = validate_input or (lambda: None)
    validate_input()
    output = Path(output_dir).absolute()
    with RunState.open(run_dir) as store, ExitStack() as stack:
        manifest = store.manifest
        if (manifest["phase"] != "collected" or store.get_internal("finalization") is not None
                or store.internal_items("payload:")):
            raise ValueError("Release requires a stopped source with no pending publications")
        if not codec.equal(codec.loads(store.path("manifest.json").read_bytes()), manifest):
            raise ValueError("Public source differs from its journal")
        target = output.parent.resolve(strict=True) / output.name
        if target.is_relative_to(store.root.resolve()) or store.root.resolve().is_relative_to(target):
            raise ValueError("Release output must be outside the source collection")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Release output directory already exists")
        parent = stack.enter_context(_Parent(target.parent))
        source = stack.enter_context(Tree(store.root, exclude_state=True))
        original = source.snapshot()
        strict = verify_collection(store.root)
        origins = {row["requested_qid"] for row in request["redirects"]}
        _strict_ready(strict, origins)
        created = now_fn()
        resolutions = _resolve(request, manifest, _rows(source.body("inventory.jsonl")),
                               _rows(source.body("attempts.jsonl")), created)
        if source.snapshot() != original:
            raise ValueError("Source changed during release preparation")
        validate_input()
        destination = stack.enter_context(_Output(output, target, parent))
        directories = {"": destination}

        def directory(name):
            current = ""
            for part in PurePosixPath(name).parts:
                current = (current + "/" + part).lstrip("/")
                if current not in directories:
                    destination.check()
                    path = target / current
                    guard = stack.enter_context(_Parent(path.parent))
                    directories[current] = stack.enter_context(_Output(path, path, guard))
            return directories[current]

        directory("collection")
        for name, descriptor in sorted(original.items()):
            folder = PurePosixPath("collection") / PurePosixPath(name).parent
            _copy(source, descriptor, directory(folder.as_posix()))
            destination.check()
        if hook:
            hook("after_copy")
        if source.snapshot() != original:
            raise ValueError("Source changed during release copy")
        resolution_file = _json(destination, "redirect-resolutions.json", resolutions)
        strict_file = _json(destination, "strict-verification.json", strict)
        counts = {"selected": strict["counts"]["selected"], "usable_items": strict["counts"]["accepted"],
                  "redirected": len(resolutions["redirects"]), "pending": 0, "unresolved": 0}
        readme = ("# IDEA Wikidata preservation release\n\nRun ID: " + manifest["run_id"] +
                  "\nCompletion basis: " + COMPLETION_BASIS + "\n\n" +
                  f"Frozen QIDs: {counts['selected']}\nUsable item JSONs: {counts['usable_items']}\n" +
                  f"Reviewed redirects: {counts['redirected']}\n\n" +
                  "The collection period is not one historical instant. Redirect mappings are operator_recorded;\n" +
                  "the missing stub does not prove the redirect target. Redirect origins have no usable item JSON.\n" +
                  "collection/ preserves the original public evidence unchanged.\n" +
                  "strict-verification.json retains the failed strict result.\n" +
                  "Media bytes, full history and recursive linked entities are excluded.\n").encode("utf-8")
        _write(destination, "README.md", readme)
        metadata = {"format": RELEASE_FORMAT, "format_version": VERSION,
                    "release_id": created.replace("-", "").replace(":", "") + "-" + uuid.uuid4().hex[:12],
                    "run_id": manifest["run_id"], "run_kind": manifest["run_kind"], "created_at": created,
                    "completion_basis": COMPLETION_BASIS,
                    "inputs": {key: dict(original[path.removeprefix("collection/")], path=path)
                               for key, path in INPUT_PATHS.items()},
                    "resolutions": resolution_file, "strict_verification": strict_file,
                    "readme": describe("README.md", readme), "verification_path": "verification.json", "counts": counts,
                    "limitations": ["Collection spans a documented period, not one historical instant",
                        "Redirect mappings are operator_recorded; the offline audit does not observe redirects",
                        "Redirect origins have no usable item JSON in this release",
                        "Media bytes, full revision history and recursive linked entities are excluded"]}
        validate_release(metadata)
        _json(destination, "release.pending.json", metadata)
        with Tree(output) as copied:
            sealed = copied.snapshot()
        report = verify_release(output, pending=True)
        if report["status"] != "passed":
            raise ValueError("Copied release failed independent verification")
        if hook:
            hook("after_audit")

        def unchanged(expected):
            destination.check()
            validate_input()
            if source.snapshot() != original:
                raise ValueError("Source changed before release publication")
            with Tree(output) as copied:
                if copied.snapshot() != expected:
                    raise ValueError("Copied release changed before publication")
            destination.check()

        unchanged(sealed)
        report_file = _json(destination, "verification.pending.json", report)
        sealed["verification.pending.json"] = report_file
        unchanged(sealed)
        _publish(destination, "verification.pending.json", "verification.json")
        sealed["verification.json"] = dict(sealed.pop("verification.pending.json"), path="verification.json")
        if hook:
            hook("after_report")
        unchanged(sealed)
        _publish(destination, "release.pending.json", "release.json")
        sealed["release.json"] = dict(sealed.pop("release.pending.json"), path="release.json")
        unchanged(sealed)
        return metadata

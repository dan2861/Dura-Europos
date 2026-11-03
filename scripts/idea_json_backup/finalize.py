"""Locked exact-byte verification finalization and resumable publication intent."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import uuid

from scripts.sample_backup import jsoncodec as codec

from .collection_verify import verify_collection
from .files import describe, write_bytes, _sync
from .state import RunState


def _hash(path, relative):
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Unsafe finalization input: {relative}")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            count += len(chunk)
            digest.update(chunk)
    if count != info.st_size:
        raise ValueError(f"Finalization input changed during hashing: {relative}")
    return {"path": relative, "size_bytes": count, "sha256": digest.hexdigest()}


def _inputs(store):
    store.internal_path(".state")
    root = store.root
    values = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == ".state":
            continue
        name = relative.as_posix()
        if path.is_symlink():
            raise ValueError(f"Symlink in finalization inputs: {name}")
        if path.is_dir() or name in ("manifest.json", "verification.json"):
            continue
        values.append(_hash(path, name))
    return sorted(values, key=lambda value: value["path"])


def _prepared(store, descriptor):
    name = descriptor["path"]
    if not isinstance(name, str):
        raise ValueError("Unsafe prepared finalization path")
    relative = PurePosixPath(name)
    if (relative.is_absolute() or ".." in relative.parts
            or "\\" in name or str(relative) != name or relative.parts[:2] != (".state", "finalization")):
        raise ValueError("Unsafe prepared finalization path")
    path = store.internal_path(name)
    if _hash(path, name) != descriptor:
        raise ValueError("Prepared finalization bytes changed")
    return path.read_bytes()


def _matches(path, expected):
    if expected is None:
        return not path.exists() and not path.is_symlink()
    if not path.exists() or path.is_symlink():
        return False
    return _hash(path, path.name) == dict(expected, path=path.name)


def _validate(store, intent):
    if not isinstance(intent, dict) or intent.get("run_id") != store.manifest["run_id"]:
        raise ValueError("Invalid finalization intent")
    report_body = _prepared(store, intent["report"])
    manifest_body = _prepared(store, intent["manifest"])
    report, target = codec.loads(report_body), codec.loads(manifest_body)
    if (report.get("run_id") != store.manifest["run_id"] or target.get("run_id") != store.manifest["run_id"]
            or report.get("status") not in ("passed", "failed", "not_checked")
            or target.get("phase") != ("finalized" if report["status"] == "passed" else "collected")
            or target.get("collection_status") != report["status"]
            or target.get("verification_path") != "verification.json"):
        raise ValueError("Prepared finalization status/identity disagrees")
    if _inputs(store) != intent["inputs"]:
        raise ValueError("Finalization inputs changed; prepared publication held")
    manifest_path, report_path = store.root / "manifest.json", store.root / "verification.json"
    target_manifest = describe("manifest.json", manifest_body)
    target_report = describe("verification.json", report_body)
    manifest_done = _matches(manifest_path, target_manifest)
    report_done = _matches(report_path, target_report)
    if manifest_done:
        if not report_done:
            raise ValueError("Published manifest lacks its exact prepared report")
    elif not _matches(manifest_path, intent["original_manifest"]):
        raise ValueError("Manifest changed since finalization preparation")
    if not report_done and not _matches(report_path, intent["original_report"]):
        raise ValueError("Verification report changed since finalization preparation")
    return report_body, manifest_body, report, target, report_done, manifest_done


def _publish_public(store, name, body, prepared):
    """Private owned staging keeps any interrupted copy out of public inputs."""
    relative = prepared["path"] + ".publish." + uuid.uuid4().hex
    staging = store.internal_path(relative)
    with staging.open("xb", buffering=0) as stream:
        if stream.write(body) != len(body):
            raise OSError("Incomplete finalization publication staging")
        stream.flush()
        os.fsync(stream.fileno())
    _sync(staging.parent)
    destination = store.path(name)
    os.replace(store.internal_path(relative), destination)
    _sync(store.root)


def resume_finalization(store, *, hook=None):
    """Finish only the exact prepared bytes; never rerun the independent audit."""
    intent = store.get_internal("finalization")
    if intent is None:
        return None
    report_body, manifest_body, report, target, report_done, manifest_done = _validate(store, intent)
    if not report_done:
        _publish_public(store, "verification.json", report_body, intent["report"])
    if hook:
        hook("afterreport")
    _validate(store, intent)
    if not manifest_done:
        _publish_public(store, "manifest.json", manifest_body, intent["manifest"])
    if hook:
        hook("aftermanifest")
        hook("beforejournal")
    _validate(store, intent)
    store.commit_finalization(target)
    return report


def finalize(run_dir, *, hook=None):
    """Audit a stopped collected run and finalize passing payload exactly once."""
    with RunState.open(run_dir) as store:
        if store.get_internal("finalization") is not None:
            return resume_finalization(store, hook=hook)
        current = store.manifest
        if current["phase"] != "collected":
            raise ValueError("Finalization requires a collected, non-finalized run")
        if store.internal_items("payload:"):
            raise ValueError("Unrecovered payload ownership intents prevent finalization")
        public_body = store.path("manifest.json").read_bytes()
        if not codec.equal(codec.loads(public_body), current):
            raise ValueError("Public snapshots are not current; explicit recovery is required")
        folder = store.internal_path(".state/finalization")
        folder.mkdir(exist_ok=True)
        folder = store.internal_path(".state/finalization")
        _sync(folder.parent)
        fingerprint = _inputs(store)
        report = verify_collection(store.root)
        if _inputs(store) != fingerprint:
            raise ValueError("Finalization inputs changed during independent audit")
        report_body = (codec.dumps(report) + "\n").encode("utf-8")
        target = dict(current, phase="finalized" if report["status"] == "passed" else "collected",
                      collection_status=report["status"], verification_path="verification.json")
        manifest_body = (codec.dumps(target) + "\n").encode("utf-8")
        identity = uuid.uuid4().hex
        report_name = f".state/finalization/{identity}.report.json"
        manifest_name = f".state/finalization/{identity}.manifest.json"
        write_bytes(store.internal_path(report_name), report_body)
        write_bytes(store.internal_path(manifest_name), manifest_body)
        original_report = store.path("verification.json")
        intent = {"run_id": current["run_id"], "inputs": fingerprint,
                  "original_manifest": describe("manifest.json", public_body),
                  "original_report": _hash(original_report, "verification.json") if original_report.exists() else None,
                  "report": describe(report_name, report_body), "manifest": describe(manifest_name, manifest_body)}
        store.set_internal("finalization", intent)
        if hook:
            hook("afterprepare")
        return resume_finalization(store, hook=hook)

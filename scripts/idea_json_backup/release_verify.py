"""Independent redirect-release audit and anchored read-only public trees."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import stat

from scripts.sample_backup.jsoncodec import Number, dumps, loads
from .collection_verify import verify_collection
from .release_contract import COUNT_KEYS, integer, stamp, validate_release, validate_resolutions

CHECKS = ("scope", "source_content", "provenance", "files")
REPORT_KEYS = {"format_version", "release_id", "run_id", "checked_at", "inputs", "status", "checks", "counts", "findings"}
STRICT_KEYS = REPORT_KEYS - {"release_id"}


class Invalid(ValueError):
    def __init__(self, message, category="scope", *, qid=None, path=None):
        super().__init__(message)
        self.category, self.qid, self.path = category, qid, path


def require(condition, message, category="scope", *, qid=None, path=None):
    if not condition:
        raise Invalid(message, category, qid=qid, path=path)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


class Tree:
    """Read only regular, single-linked public files beneath one pinned root."""
    def __init__(self, root, *, exclude_state=False):
        self.requested = Path(root).absolute()
        require(not self.requested.is_symlink(), "Linked tree root", "files")
        self.root = self.requested.resolve(strict=True)
        self.exclude_state = exclude_state
        self.fd = None
        self._seen = {}
        self.directories = set()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root.anchor, flags)
        try:
            for component in self.root.parts[1:]:
                before = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                require(stat.S_ISDIR(before.st_mode), "Unsafe tree ancestry", "files")
                child = os.open(component, flags, dir_fd=descriptor)
                try:
                    opened = os.fstat(child)
                    current = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                    require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
                            == (current.st_dev, current.st_ino), "Tree ancestry changed", "files")
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            self.fd = descriptor
            self.check()
        except BaseException:
            os.close(descriptor)
            self.fd = None
            raise

    def check(self):
        current = self.root.lstat()
        requested = self.requested.lstat()
        opened = os.fstat(self.fd)
        require(stat.S_ISDIR(current.st_mode) and stat.S_ISDIR(requested.st_mode)
                and self.requested.resolve(strict=True) == self.root
                and self.root.resolve(strict=True) == self.root
                and (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)
                == (requested.st_dev, requested.st_ino), "Tree root changed", "files")

    def _parts(self, relative):
        require(isinstance(relative, str) and relative and "\\" not in relative and "\x00" not in relative,
                "Unsafe tree path", "files")
        path = PurePosixPath(relative)
        require(not path.is_absolute() and ".." not in path.parts and str(path) == relative
                and relative != "." and ".state" not in path.parts, "Unsafe tree path", "files")
        return path.parts

    @contextmanager
    def _parent(self, parts):
        descriptor = os.dup(self.fd)
        ancestry = []
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            for component in parts[:-1]:
                before = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                require(stat.S_ISDIR(before.st_mode), "Unsafe tree directory", "files")
                child = os.open(component, flags, dir_fd=descriptor)
                try:
                    opened = os.fstat(child)
                    after = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                    require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
                            == (after.st_dev, after.st_ino), "Tree directory changed", "files")
                except BaseException:
                    os.close(child)
                    raise
                ancestry.append((opened.st_dev, opened.st_ino))
                os.close(descriptor)
                descriptor = child
            yield descriptor, ancestry
        finally:
            os.close(descriptor)

    @contextmanager
    def open(self, relative):
        self.check()
        parts = self._parts(relative)
        with self._parent(parts) as (parent, ancestry):
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    "Tree artifact must be a single regular file", "files")
            descriptor = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
            try:
                opened = os.fstat(descriptor)
                current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                        and _identity(before) == _identity(opened) == _identity(current),
                        "Tree artifact changed before reading", "files")
                signature = _identity(opened)
                require(relative not in self._seen or self._seen[relative] == signature,
                        "Tree artifact changed between reads", "files")
                self._seen[relative] = signature
                stream = os.fdopen(descriptor, "rb")
            except BaseException:
                os.close(descriptor)
                raise
            with stream:
                yield stream
                after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                require(signature == _identity(os.fstat(stream.fileno())) == _identity(after),
                        "Tree artifact changed while reading", "files")
            with self._parent(parts) as (current_parent, current_ancestry):
                require(ancestry == current_ancestry
                        and _identity(os.stat(parts[-1], dir_fd=current_parent, follow_symlinks=False)) == signature,
                        "Tree path changed while reading", "files")
        self.check()

    open_read = open

    def body(self, relative):
        with self.open(relative) as source:
            return b"".join(iter(lambda: source.read(65536), b""))

    def snapshot(self):
        self.check()
        result, directories = {}, set()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

        def visit(parent, prefix):
            for name in sorted(os.listdir(parent)):
                if not prefix and name == ".state" and self.exclude_state:
                    continue
                relative = prefix + name
                self._parts(relative)
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(before.st_mode):
                    child = os.open(name, flags, dir_fd=parent)
                    try:
                        opened = os.fstat(child)
                        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                                "Tree directory changed while enumerating", "files")
                        directories.add(relative)
                        visit(child, relative + "/")
                        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
                        require(stat.S_ISDIR(after.st_mode)
                                and (opened.st_dev, opened.st_ino) == (after.st_dev, after.st_ino),
                                "Tree directory changed while enumerating", "files")
                    finally:
                        os.close(child)
                else:
                    digest, size = sha256(), 0
                    with self.open(relative) as source:
                        while chunk := source.read(65536):
                            size += len(chunk)
                            digest.update(chunk)
                    result[relative] = {"path": relative, "size_bytes": size, "sha256": digest.hexdigest()}
        visit(self.fd, "")
        self.directories = directories
        self.check()
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, Number):
        return left.token == right.token
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def equivalent(left, right):
    return _same(loads(dumps(left)), loads(dumps(right)))


def _saved_report(saved, fresh, expected_keys):
    require(isinstance(saved, dict) and set(saved) == expected_keys, "Saved verification report has invalid schema", "provenance")
    stamp(saved["checked_at"])
    require(equivalent({key: value for key, value in saved.items() if key != "checked_at"},
                       {key: value for key, value in fresh.items() if key != "checked_at"}),
            "Saved verification report disagrees with independent audit", "provenance")


def _jsonl(tree, path):
    body = tree.body(path)
    require(body.endswith(b"\n"), "Release JSONL lacks final newline", "files")
    return [loads(line) for line in body.splitlines()]


def verify_release(directory, *, pending=False):
    """Audit an immutable release or the producer's explicitly pending output."""
    report = {"format_version": "1.0.0", "release_id": None, "run_id": None,
              "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "inputs": None,
              "status": "not_checked", "checks": [{"check_id": name, "status": "not_checked", "findings": []} for name in CHECKS],
              "counts": {name: None for name in COUNT_KEYS}, "findings": []}
    try:
        require(type(pending) is bool, "Pending-release mode must be explicit", "scope")
        with Tree(directory) as tree:
            before = tree.snapshot()
            marker_name = "release.pending.json" if pending else "release.json"
            root_names = {name for name in before if "/" not in name}
            saved_names = root_names.intersection({"verification.pending.json", "verification.json"})
            require(len(saved_names) <= 1 and (pending or saved_names == {"verification.json"}),
                    "Release lacks exactly one supported saved verification report", "files")
            required = {marker_name, "redirect-resolutions.json", "strict-verification.json", "README.md"} | saved_names
            require(root_names == required and all("/" not in name or name.startswith("collection/") for name in before),
                    "Unexpected release artifacts", "files")
            expected_dirs = {str(parent) for name in before for parent in PurePosixPath(name).parents if str(parent) != "."}
            require(tree.directories == expected_dirs, "Unexpected or empty release directories", "files")
            marker = loads(tree.body(marker_name))
            validate_release(marker)
            report.update(release_id=marker["release_id"], run_id=marker["run_id"], inputs={
                "release": dict(before[marker_name], path="release.json"),
                "resolutions": before["redirect-resolutions.json"],
                "strict_verification": before["strict-verification.json"]})
            for descriptor in list(marker["inputs"].values()) + [marker[field] for field in ("resolutions", "strict_verification", "readme")]:
                require(descriptor["path"] in before and equivalent(descriptor, before[descriptor["path"]]),
                        "Release metadata descriptor differs from saved bytes", "files")
            resolutions = loads(tree.body("redirect-resolutions.json"))
            validate_resolutions(resolutions)
            manifest = loads(tree.body("collection/manifest.json"))
            require(manifest["phase"] == "collected" and manifest["run_id"] == marker["run_id"]
                    and manifest["run_kind"] == marker["run_kind"] and resolutions["run_id"] == marker["run_id"]
                    and integer(resolutions["state_sequence"]) == integer(manifest["state_sequence"]),
                    "Release identifies a different or unfinished collection", "scope")
            bound = {"qid_list": manifest["selection"]["qid_list"],
                     "inventory": manifest["public_records"]["inventory"]["file"],
                     "attempts": manifest["public_records"]["attempts"]["file"]}
            require(equivalent(resolutions["inputs"], bound), "Redirect resolution is stale for this collection", "provenance")
            strict = verify_collection(tree.root / "collection")
            tree.check()
            _saved_report(loads(tree.body("strict-verification.json")), strict, STRICT_KEYS)
            rows = _jsonl(tree, "collection/inventory.jsonl")
            attempts = {row["attempt_id"]: row for row in _jsonl(tree, "collection/attempts.jsonl")}
            by_qid = {row["requested_qid"]: row for row in rows}
            unresolved = {qid for qid, row in by_qid.items() if row["status"] == "unresolved"}
            origins = {row["requested_qid"] for row in resolutions["redirects"]}
            require(strict["status"] == "failed" and strict["run_id"] == marker["run_id"]
                    and strict["counts"]["pending"] == 0 and unresolved == origins
                    and len(strict["findings"]) == len(origins), "Redirects do not exactly reconcile unresolved scope", "scope")
            expected_findings = [{"code": "invalid_record", "qid": qid, "path": None,
                                  "message": "Unresolved item prevents collection completion"} for qid in origins]
            require(all(finding in expected_findings for finding in strict["findings"])
                    and {finding["qid"] for finding in strict["findings"]} == origins,
                    "Strict failure includes an unreviewed condition", "scope")
            require(len(strict["checks"]) == len(CHECKS)
                    and all(check["check_id"] == name and check["status"] == ("failed" if name == "scope" else "passed")
                            and equivalent(check["findings"], strict["findings"] if name == "scope" else [])
                            for name, check in zip(CHECKS, strict["checks"])),
                    "Original item/source/provenance/file audits did not pass", "provenance")
            for resolution in resolutions["redirects"]:
                origin, target = resolution["requested_qid"], resolution["target_qid"]
                source_row, target_row = by_qid[origin], by_qid.get(target)
                error = source_row["error"]
                require(error["stage"] == "identity" and error["code"] == "missing_or_redirect"
                        and error["retryable"] is False and source_row["returned_qid"] == origin
                        and source_row["attempt_ids"] and source_row["attempt_ids"][-1] == resolution["unavailable_attempt_id"],
                        "Reviewed origin is not the preserved unavailable item", "provenance", qid=origin)
                attempt = attempts[resolution["unavailable_attempt_id"]]
                result = next(row for row in attempt["item_results"] if row["qid"] == origin)
                require(result["outcome"] == "review_required" and result["returned_qid"] == origin
                        and equivalent(result["error"], error) and attempt["receipt_complete"] is True
                        and attempt["http"] is not None and integer(attempt["http"]["status_code"]) == 200
                        and attempt["api_error"] is None and attempt["warnings"] is None
                        and attempt["decoded"] is not None and attempt["decoded"]["complete"] is True
                        and equivalent(resolution["source_response"], attempt["decoded"]),
                        "Redirect source differs from complete preserved response", "provenance", qid=origin)
                source = loads(tree.body("collection/" + resolution["source_response"]["path"]))
                require(isinstance(source, dict) and set(source) == {"success", "entities"}
                        and isinstance(source["success"], Number) and source["success"].token == "1"
                        and isinstance(source["entities"], dict), "Invalid unavailable-response wrapper", "source_content", qid=origin)
                stub = source["entities"].get(origin)
                require(isinstance(stub, dict) and stub.get("id") == origin and "missing" in stub,
                        "Preserved response lacks the matching unavailable stub", "source_content", qid=origin)
                require(target_row is not None and target_row["status"] == "accepted"
                        and target_row["returned_qid"] == target and equivalent(resolution["target_item"], target_row["item"]),
                        "Redirect target is not the already accepted frozen item", "scope", qid=origin)
            counts = {"selected": strict["counts"]["selected"], "usable_items": strict["counts"]["accepted"],
                      "redirected": len(origins), "pending": 0, "unresolved": 0}
            require(equivalent(marker["counts"], counts), "Release counts differ from independent reconciliation", "scope")
            report["counts"] = counts
            readme = tree.body("README.md").decode("utf-8")
            require(all(token in readme.casefold() for token in ("operator_recorded", "redirect", "collection period",
                        "redirect origins have no usable item json")),
                    "Release README does not explain its preservation basis", "files")
            fields = {"Run ID": marker["run_id"], "Frozen QIDs": str(counts["selected"]),
                      "Usable item JSONs": str(counts["usable_items"]), "Reviewed redirects": str(counts["redirected"])}
            for field, expected in fields.items():
                values = [value.strip() for line in readme.splitlines()
                          for key, separator, value in [line.partition(":")]
                          if separator and key.strip().casefold() == field.casefold()]
                require(values == [expected], "Release README identity/count differs or is duplicated", "files")
            report["status"] = "passed"
            for check in report["checks"]:
                check["status"] = "passed"
            if saved_names:
                _saved_report(loads(tree.body(next(iter(saved_names)))), report, REPORT_KEYS)
            require(tree.snapshot() == before, "Release inputs changed during independent audit", "files")
            tree.check()
        return report
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError, StopIteration, RuntimeError) as exc:
        category = exc.category if isinstance(exc, Invalid) else "files"
        finding = {"code": "invalid_release", "qid": exc.qid if isinstance(exc, Invalid) else None,
                   "path": exc.path if isinstance(exc, Invalid) else None,
                   "message": str(exc) if isinstance(exc, Invalid) else "Cannot safely audit redirect release"}
        report["status"] = "failed"
        report["findings"].append(finding)
        for check in report["checks"]:
            if check["check_id"] == category:
                check["status"] = "failed"
                check["findings"].append(finding)
        return report

"""Offline candidate archives from a locked, finalized JSON collection."""
import gzip
import hashlib
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import re
import stat
import tarfile
import uuid

from scripts.sample_backup import jsoncodec as codec

from .collection_verify import verify_collection
from .contract import valid_utc
from .state import RunState, utc_now
from .retention import validate_retention_evidence

TAR_HEADER_POLICY = "uid=0,gid=0,uname=,gname=,mode=0644,mtime=0"
DEFAULT_PROFILE = {"format": "tar.gz", "max_members": 5000,
                   "max_payload_bytes_per_part": 256 * 1024 * 1024,
                   "gzip_level": 6, "gzip_mtime": 0,
                   "tar_header_policy": TAR_HEADER_POLICY, "retention_evidence": None}


def _profile(value):
    if value is not None and not isinstance(value, dict):
        raise ValueError("Archive profile must be an object")
    profile = deepcopy(DEFAULT_PROFILE if value is None else value)
    if (set(profile) != set(DEFAULT_PROFILE) or profile["format"] != "tar.gz"
            or any(type(profile[key]) is not int or not 1 <= profile[key] <= DEFAULT_PROFILE[key]
                   for key in ("max_members", "max_payload_bytes_per_part"))
            or type(profile["gzip_level"]) is not int or profile["gzip_level"] != 6
            or type(profile["gzip_mtime"]) is not int or profile["gzip_mtime"] != 0
            or profile["tar_header_policy"] != TAR_HEADER_POLICY):
        raise ValueError("Invalid archive profile")
    validate_retention_evidence(profile["retention_evidence"])
    return profile


def _open_regular(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        current = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_ISLNK(current.st_mode)
                or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
            raise ValueError("Unsafe or changed package input: " + str(path))
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _hash(path, name):
    digest, count = hashlib.sha256(), 0
    with _open_regular(path) as stream:
        while chunk := stream.read(65536):
            count += len(chunk)
            digest.update(chunk)
        if count != os.fstat(stream.fileno()).st_size:
            raise ValueError("Input changed during package hashing: " + name)
    return {"path": name, "size_bytes": count, "sha256": digest.hexdigest()}


def _payload(store):
    if hasattr(store, "snapshot") and not isinstance(store, RunState):
        return sorted(store.snapshot().values(), key=lambda value: value["path"])
    def unreadable(error):
        raise error

    values = []
    for directory, folders, files in os.walk(store.root, onerror=unreadable):
        base = Path(directory)
        if base == store.root:
            folders[:] = [name for name in folders if name != ".state"]
        for name in folders:
            path = base / name
            if path.is_symlink():
                raise ValueError("Linked collection directory cannot be archived")
        for name in files:
            relative = (base / name).relative_to(store.root).as_posix()
            values.append(_hash(store.path(relative), relative))
    return sorted(values, key=lambda value: value["path"])


class _Parent:
    """Keep the chosen parent anchored across auditing and package creation."""
    def __init__(self, path):
        self.path = path
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.anchor, flags)
        try:
            for component in path.parts[1:]:
                child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            self.fd = descriptor
            self.check()
        except BaseException:
            os.close(descriptor)
            raise

    def check(self):
        info = self.path.lstat()
        opened = os.fstat(self.fd)
        if (not stat.S_ISDIR(info.st_mode) or self.path.resolve() != self.path
                or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError("Package output parent changed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)


class _Output:
    """Directory-relative writes cannot follow a replaced output ancestry."""
    def __init__(self, path, target, parent, *, create=True):
        self.path, self.target = path, target
        parent.check()
        if create:
            os.mkdir(path.name, dir_fd=parent.fd)
            os.fsync(parent.fd)
        self.fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                          | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent.fd)
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        info = self.path.lstat()
        opened = os.fstat(self.fd)
        if (not stat.S_ISDIR(info.st_mode) or self.path.resolve() != self.target
                or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError("Package output directory ancestry changed")

    def open(self, name, *, write=False):
        self.check()
        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("Unsafe package output name")
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL) if write else os.O_RDONLY
        descriptor = os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=self.fd)
        try:
            info = os.fstat(descriptor)
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
                raise ValueError("Unsafe package output file")
            return os.fdopen(descriptor, "wb" if write else "rb")
        except BaseException:
            os.close(descriptor)
            raise

    def sync(self):
        os.fsync(self.fd)
        self.check()

    def unlink(self, name):
        self.check()
        os.unlink(name, dir_fd=self.fd)
        self.sync()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)


def _write(output, name, body):
    with output.open(name, write=True) as stream:
        if stream.write(body) != len(body):
            raise OSError("Incomplete package metadata write")
        stream.flush()
        os.fsync(stream.fileno())
    output.sync()


def _publish(output, staging, destination):
    output.check()
    source = os.stat(staging, dir_fd=output.fd, follow_symlinks=False)
    if not stat.S_ISREG(source.st_mode) or source.st_nlink != 1:
        raise ValueError("Unsafe package publication staging")
    os.link(staging, destination, src_dir_fd=output.fd, dst_dir_fd=output.fd, follow_symlinks=False)
    output.sync()
    target = os.stat(destination, dir_fd=output.fd, follow_symlinks=False)
    linked = os.stat(staging, dir_fd=output.fd, follow_symlinks=False)
    if ((target.st_dev, target.st_ino) != (source.st_dev, source.st_ino)
            or (linked.st_dev, linked.st_ino) != (source.st_dev, source.st_ino) or linked.st_nlink != 2):
        raise ValueError("Package publication ownership changed")
    output.unlink(staging)


def _output_hash(output, name):
    digest, count = hashlib.sha256(), 0
    with output.open(name) as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
            count += len(chunk)
        opened = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=output.fd, follow_symlinks=False)
        if (count != opened.st_size or opened.st_nlink != 1 or not stat.S_ISREG(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise ValueError("Archive changed during hashing")
    output.check()
    return {"path": name, "size_bytes": count, "sha256": digest.hexdigest()}


class _HashReader:
    def __init__(self, stream, expected):
        self.stream, self.expected = stream, expected
        self.digest, self.count = hashlib.sha256(), 0

    def read(self, size):
        body = self.stream.read(size)
        self.digest.update(body)
        self.count += len(body)
        return body

    def finish(self):
        if (self.stream.read(1) or self.count != self.expected["size_bytes"]
                or self.count != os.fstat(self.stream.fileno()).st_size
                or self.digest.hexdigest() != self.expected["sha256"]):
            raise ValueError("Collection bytes changed during archive creation: " + self.expected["path"])


def _archive(store, output, name, members, profile):
    pending = name + ".partial"
    with output.open(pending, write=True) as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=profile["gzip_level"],
                           mtime=profile["gzip_mtime"]) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for member in members:
                    info = tarfile.TarInfo(member["path"])
                    info.size = member["size_bytes"]
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with (store.open_read(member["path"]) if hasattr(store, "open_read") else _open_regular(store.path(member["path"]))) as stream:
                        reader = _HashReader(stream, member)
                        archive.addfile(info, reader)
                        reader.finish()
        raw.flush()
        os.fsync(raw.fileno())
    output.sync()
    _publish(output, pending, name)
    return dict(_output_hash(output, name), members=[row["path"] for row in members])


def _build_package(store, output, profile, manifest, audit, *, payload_kind=None):
    with ExitStack() as stack:
        parent = output.parent.resolve(strict=True)
        target = parent / output.name
        if target.is_relative_to(store.root.resolve()) or store.root.resolve().is_relative_to(target):
            raise ValueError("Package output must be outside the collection payload")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Package output directory already exists")
        parent_guard = stack.enter_context(_Parent(parent))
        payload = _payload(store)
        if audit()["status"] != "passed":
            raise ValueError("Payload failed independent public verification")
        parts, members, count = [], [], 0
        for value in payload:
            if value["size_bytes"] > profile["max_payload_bytes_per_part"]:
                raise ValueError("A single payload exceeds the candidate archive part limit")
            if members and (len(members) >= profile["max_members"]
                            or count + value["size_bytes"] > profile["max_payload_bytes_per_part"]):
                parts.append(members)
                members, count = [], 0
            members.append(value)
            count += value["size_bytes"]
        if members:
            parts.append(members)
        created = utc_now()
        inventory = {"format": "idea-json-backup", "format_version": "1.1.0" if payload_kind else "1.0.0",
                     "package_id": created.replace("-", "").replace(":", "") + "-" + uuid.uuid4().hex[:12],
                     "run_id": manifest["run_id"], "run_kind": manifest["run_kind"], "created_at": created,
                     "profile": profile, "payload": [], "archives": []}
        if payload_kind:
            inventory["payload_kind"] = payload_kind
        for index, part in enumerate(parts, 1):
            name = f"part-{index:05d}.tar.gz"
            inventory["payload"].extend(dict(value, archive_path=name) for value in part)
        with _Output(output, target, parent_guard) as destination:
            prepared = "package-inventory.pending.json"
            _write(destination, prepared, (codec.dumps(inventory) + "\n").encode("utf-8"))
            for index, part in enumerate(parts, 1):
                inventory["archives"].append(_archive(store, destination, f"part-{index:05d}.tar.gz", part, profile))
            if _payload(store) != payload:
                raise ValueError("Collection changed during archive creation")
            complete = "package-inventory.complete.json"
            _write(destination, complete, (codec.dumps(inventory) + "\n").encode("utf-8"))
            _publish(destination, complete, "package-inventory.json")
            destination.unlink(prepared)
        return inventory


def package_collection(run_dir, output_dir, *, profile=None):
    """Package an ordinary finalized legacy collection."""
    profile = _profile(profile)
    with RunState.open(run_dir) as store:
        manifest = store.manifest
        if (manifest["phase"] != "finalized" or manifest["collection_status"] != "passed"
                or store.get_internal("finalization") is not None or store.internal_items("payload:")):
            raise ValueError("Packaging requires finalized verified collection with no pending publications")
        if not codec.equal(codec.loads(store.path("manifest.json").read_bytes()), manifest):
            raise ValueError("Public finalized manifest differs from its journal")
        return _build_package(store, Path(output_dir).absolute(), profile, manifest,
                              lambda: verify_collection(store.root))


def package_release(release_dir, output_dir, *, profile=None):
    """Package a separately verified resolved release; no source journal mutation."""
    from .release_verify import Tree, verify_release
    profile = _profile(profile)
    with Tree(release_dir) as store:
        metadata = codec.loads(store.body("release.json"))
        return _build_package(store, Path(output_dir).absolute(), profile, metadata,
                              lambda: verify_release(store.root), payload_kind="resolved_release")


def _report_contract(report, package_id):
    keys = {"format_version", "package_id", "checked_at", "status", "checks", "findings"}
    statuses = ("passed", "failed", "not_checked")
    if (not isinstance(report, dict) or set(report) != keys or report["format_version"] != "1.0.0"
            or report["package_id"] != package_id or not valid_utc(report["checked_at"])
            or report["status"] not in statuses or not isinstance(report["checks"], list)
            or len(report["checks"]) != 3 or not isinstance(report["findings"], list)):
        raise ValueError("Invalid package verification report identity/schema")
    findings = list(report["findings"])
    for label, check in zip(("inventory", "archive_integrity", "payload_roundtrip"), report["checks"]):
        if (not isinstance(check, dict) or set(check) != {"check_id", "status", "findings"}
                or check["check_id"] != label or check["status"] not in statuses
                or not isinstance(check["findings"], list)):
            raise ValueError("Invalid package verification check")
        findings.extend(check["findings"])
    for finding in findings:
        if (not isinstance(finding, dict) or set(finding) != {"code", "qid", "path", "message"}
                or not all(isinstance(finding[key], str) and finding[key] for key in ("code", "message"))
                or any(finding[key] is not None and not isinstance(finding[key], str) for key in ("qid", "path"))):
            raise ValueError("Invalid package verification finding")
    if report["status"] == "passed" and (findings or any(c["status"] != "passed" for c in report["checks"])):
        raise ValueError("Passed package report contains failed or unfinished evidence")


def _report_inputs(output, inventory, inventory_body, *, failed, ignored=()):
    actual = _output_hash(output, "package-inventory.json")
    expected = {"path": "package-inventory.json", "size_bytes": len(inventory_body),
                "sha256": hashlib.sha256(inventory_body).hexdigest()}
    if actual != expected:
        raise ValueError("Package inventory changed before verification publication")
    seen, archives = set(), []
    for part in inventory["archives"]:
        if (not isinstance(part, dict) or set(part) != {"path", "size_bytes", "sha256", "members"}
                or not isinstance(part["path"], str) or not re.fullmatch(r"part-[0-9]{5,}\.tar\.gz", part["path"])
                or part["path"] in seen or type(part["size_bytes"]) is not int or part["size_bytes"] < 0
                or not isinstance(part["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])):
            raise ValueError("Invalid expected archive descriptor")
        name = part["path"]
        seen.add(name)
        try:
            info = os.stat(name, dir_fd=output.fd, follow_symlinks=False)
        except FileNotFoundError:
            if not failed:
                raise ValueError("Expected archive is missing before passing report")
            archives.append({"path": name, "missing": True})
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            if not failed:
                raise ValueError("Unsafe archive cannot support a passing report")
            archives.append({"path": name, "unsafe": (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                                                        info.st_size, info.st_mtime_ns, info.st_ctime_ns)})
            continue  # retain failure evidence without following or reading unsafe objects
        current = _output_hash(output, name)
        if not failed and current != {key: part[key] for key in ("path", "size_bytes", "sha256")}:
            raise ValueError("Archive changed before passing verification publication")
        archives.append(current)
    files = set(os.listdir(output.fd)) - set(ignored)
    if not failed and files != {"package-inventory.json"} | seen:
        raise ValueError("Unexpected package artifacts prevent a passing report")
    output.check()
    return {"inventory": actual, "archives": archives, "files": sorted(files)}


def write_package_report(package_dir, report, *, expected_inventory):
    """Publish one report against the producer's exact inventory and stable inputs.

    The caller captures a canonical absolute output path before packaging/auditing.
    This function never resolves a newly linked ancestry to another destination.
    Failed reports retain genuine missing/unsafe/damaged archive facts; they confer
    no successful verification and never rewrite inventory or archive bytes.
    """
    inventory_keys = {"format", "format_version", "package_id", "run_id", "run_kind", "created_at",
                      "profile", "payload", "archives"}
    if (isinstance(expected_inventory, dict) and expected_inventory.get("format_version") == "1.1.0"
            and expected_inventory.get("payload_kind") == "resolved_release"):
        inventory_keys = inventory_keys | {"payload_kind"}
    if (not isinstance(expected_inventory, dict) or set(expected_inventory) != inventory_keys
            or expected_inventory.get("format_version") not in ("1.0.0", "1.1.0")
            or (expected_inventory.get("format_version") == "1.1.0"
                and expected_inventory.get("payload_kind") != "resolved_release")
            or not isinstance(expected_inventory["package_id"], str) or not expected_inventory["package_id"]
            or not isinstance(expected_inventory["archives"], list)):
        raise ValueError("Expected complete producer inventory is required")
    _report_contract(report, expected_inventory["package_id"])
    output = Path(package_dir).absolute()
    inventory_body = (codec.dumps(expected_inventory) + "\n").encode("utf-8")
    report_body = (codec.dumps(report) + "\n").encode("utf-8")
    report_file, pending = "package-verification.json", "package-verification.pending.json"
    with _Parent(output.parent) as parent, _Output(output, output, parent, create=False) as destination:
        if report_file in os.listdir(destination.fd) or pending in os.listdir(destination.fd):
            raise FileExistsError("Package report or publication evidence already exists")
        options = {"failed": report["status"] != "passed"}
        fingerprint = _report_inputs(destination, expected_inventory, inventory_body, **options)
        _write(destination, pending, report_body)
        if _report_inputs(destination, expected_inventory, inventory_body, ignored=(pending,), **options) != fingerprint:
            raise ValueError("Package inputs changed during report preparation")
        _publish(destination, pending, report_file)
        if _report_inputs(destination, expected_inventory, inventory_body, ignored=(report_file,), **options) != fingerprint:
            raise ValueError("Package inputs changed during report publication; retain evidence for review")
        descriptor = _output_hash(destination, report_file)
        if descriptor != {"path": report_file, "size_bytes": len(report_body),
                          "sha256": hashlib.sha256(report_body).hexdigest()}:
            raise ValueError("Published package report bytes changed")
        return descriptor

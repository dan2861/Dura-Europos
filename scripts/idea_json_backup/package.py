"""Offline candidate archives from a locked, finalized JSON collection."""
import gzip
import hashlib
from contextlib import ExitStack
import os
from pathlib import Path
import stat
import tarfile
import uuid

from scripts.sample_backup import jsoncodec as codec

from .collection_verify import verify_collection
from .state import RunState, utc_now

TAR_HEADER_POLICY = "uid=0,gid=0,uname=,gname=,mode=0644,mtime=0"
DEFAULT_PROFILE = {"format": "tar.gz", "max_members": 5000,
                   "max_payload_bytes_per_part": 256 * 1024 * 1024,
                   "gzip_level": 6, "gzip_mtime": 0,
                   "tar_header_policy": TAR_HEADER_POLICY, "retention_evidence": None}


def _profile(value):
    if value is not None and not isinstance(value, dict):
        raise ValueError("Archive profile must be an object")
    profile = dict(DEFAULT_PROFILE if value is None else value)
    if (set(profile) != set(DEFAULT_PROFILE) or profile["format"] != "tar.gz"
            or any(type(profile[key]) is not int or profile[key] < 1
                   for key in ("max_members", "max_payload_bytes_per_part"))
            or type(profile["gzip_level"]) is not int or profile["gzip_level"] != 6
            or type(profile["gzip_mtime"]) is not int or profile["gzip_mtime"] != 0
            or profile["tar_header_policy"] != TAR_HEADER_POLICY or profile["retention_evidence"] is not None):
        raise ValueError("Invalid provisional archive profile")
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
    values = []
    for directory, folders, files in os.walk(store.root):
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
                    with _open_regular(store.path(member["path"])) as stream:
                        reader = _HashReader(stream, member)
                        archive.addfile(info, reader)
                        reader.finish()
        raw.flush()
        os.fsync(raw.fileno())
    output.sync()
    _publish(output, pending, name)
    return dict(_output_hash(output, name), members=[row["path"] for row in members])


def package_collection(run_dir, output_dir, *, profile=None):
    """Create a new candidate package; no retrieval, payload mutation or deposit."""
    profile = _profile(profile)
    output = Path(output_dir).absolute()
    with RunState.open(run_dir) as store, ExitStack() as stack:
        manifest = store.manifest
        if (manifest["phase"] != "finalized" or manifest["collection_status"] != "passed"
                or store.get_internal("finalization") is not None or store.internal_items("payload:")):
            raise ValueError("Packaging requires finalized verified collection with no pending publications")
        if not codec.equal(codec.loads(store.path("manifest.json").read_bytes()), manifest):
            raise ValueError("Public finalized manifest differs from its journal")
        parent = output.parent.resolve(strict=True)
        target = parent / output.name
        if target.is_relative_to(store.root.resolve()) or store.root.resolve().is_relative_to(target):
            raise ValueError("Package output must be outside the collection payload")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Package output directory already exists")
        parent_guard = stack.enter_context(_Parent(parent))
        payload = _payload(store)
        if verify_collection(store.root)["status"] != "passed":
            raise ValueError("Finalized collection failed independent public verification")
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
        inventory = {"format": "idea-json-backup", "format_version": "1.0.0",
                     "package_id": created.replace("-", "").replace(":", "") + "-" + uuid.uuid4().hex[:12],
                     "run_id": manifest["run_id"], "run_kind": manifest["run_kind"], "created_at": created,
                     "profile": profile, "payload": [], "archives": []}
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

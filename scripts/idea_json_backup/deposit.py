"""Offline downloaded-byte comparison; provenance is separately operator recorded."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import stat

from scripts.sample_backup.jsoncodec import loads
from .package_verify import verify_package


class Invalid(ValueError):
    def __init__(self, code, message, path=None):
        super().__init__(message)
        self.code, self.path = code, path


def require(value, code, message, path=None):
    if not value:
        raise Invalid(code, message, path)


class Directory:
    """Read regular root-level artifacts through one anchored directory descriptor."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        require(not self.path.is_symlink() and self.path.is_dir(), "unsafe_input", "Expected a real input directory")
        self.anchor = self.path.resolve(strict=True)
        self.fd = os.open(self.anchor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        current, opened = self.path.lstat(), os.fstat(self.fd)
        require(stat.S_ISDIR(current.st_mode) and self.path.resolve(strict=True) == self.anchor
                and (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
                "input_changed", "Input directory changed during verification")

    def names(self):
        self.check()
        return set(os.listdir(self.fd))

    @contextmanager
    def open(self, name):
        self.check()
        require(isinstance(name, str) and name and Path(name).name == name and name not in (".", "..")
                and "\\" not in name, "unsafe_input", "Unsafe package artifact name")
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.fd)
        try:
            info = os.fstat(descriptor)
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
                    "unsafe_input", "Input artifact must be a single regular file", name)
            stream = os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            yield stream
            after = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink),
                    "input_changed", "Input artifact changed during verification", name)
        self.check()

    def body(self, name):
        with self.open(name) as source:
            return b"".join(iter(lambda: source.read(65536), b""))

    def digest(self, name):
        digest, size = sha256(), 0
        with self.open(name) as source:
            while block := source.read(65536):
                digest.update(block)
                size += len(block)
        return size, digest.hexdigest()

    def fingerprint(self):
        return {name: self.digest(name) for name in sorted(self.names())}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)


def _bytes(package_dir, downloads_dir, report):
    with ExitStack() as stack:
        package = stack.enter_context(Directory(package_dir))
        downloads = stack.enter_context(Directory(downloads_dir))
        require(not package.anchor.is_relative_to(downloads.anchor)
                and not downloads.anchor.is_relative_to(package.anchor),
                "overlapping_inputs", "Package and downloads must be distinct, nonnested directories")
        body = package.body("package-inventory.json")
        baseline = verify_package(package.path)
        require(baseline["status"] == "passed", "invalid_baseline", "Local baseline package failed independent audit")
        inventory = loads(body)
        report["package_id"] = inventory["package_id"]
        expected = {"package-inventory.json": (len(body), sha256(body).hexdigest())}
        expected.update({part["path"]: (int(part["size_bytes"].token), part["sha256"])
                         for part in inventory["archives"]})
        local = package.fingerprint()
        require(all(local.get(name) == value for name, value in expected.items()),
                "input_changed", "Local baseline changed after its audit")
        require(downloads.body("package-inventory.json") == body, "downloaded_inventory_mismatch",
                "Downloaded inventory differs from the preserved local bytes", "package-inventory.json")
        require(downloads.names() == set(expected), "downloaded_file_set_mismatch",
                "Downloaded files must contain exactly the baseline inventory and all archive parts")
        received = downloads.fingerprint()
        for name, value in expected.items():
            require(received[name] == value, "downloaded_archive_mismatch",
                    "Downloaded file differs from the preserved local descriptor", name)
        audit = verify_package(downloads.path)
        require(audit["status"] == "passed" and audit["package_id"] == report["package_id"],
                "invalid_downloaded_package", "Downloaded package failed independent roundtrip verification")
        require(package.fingerprint() == local and downloads.fingerprint() == received,
                "input_changed", "Package or downloaded files changed during verification")
        return set(expected)


def verify_deposit(package_dir, downloads_dir, acquisition=None):
    """Compare supplied local files; never download, repair, upload or publish."""
    report = {"format_version": "1.0.0", "package_id": None,
              "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
              "acquisition": None, "byte_status": "not_checked", "deposit_status": "not_checked",
              "findings": [], "publication": None}
    try:
        _bytes(package_dir, downloads_dir, report)
        report["byte_status"] = "passed"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ArithmeticError) as exc:
        report["byte_status"] = "failed"
        report["findings"].append({"code": exc.code if isinstance(exc, Invalid) else "unusable_input",
                                   "qid": None, "path": exc.path if isinstance(exc, Invalid) else None,
                                   "message": str(exc) if isinstance(exc, Invalid)
                                   else "Cannot safely read package or downloaded evidence"})
    report["findings"].append({"code": "acquisition_missing", "qid": None, "path": None,
                               "message": "No acquisition receipt; only local byte comparison can be established"})
    return report

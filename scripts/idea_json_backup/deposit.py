"""Offline downloaded-byte comparison; provenance is separately operator recorded."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from urllib.parse import parse_qsl, unquote, urlsplit

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
        before = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                "unsafe_input", "Input artifact must be a single regular file", name)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=self.fd)
        try:
            info = os.fstat(descriptor)
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino)
                    == (before.st_dev, before.st_ino),
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

    def matches(self, name, body):
        with self.open(name) as source:
            for offset in range(0, len(body), 65536):
                expected = body[offset:offset + 65536]
                if source.read(len(expected)) != expected:
                    return False
            return not source.read(1)

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


def _bytes(package_dir, downloads_dir, report, context):
    with ExitStack() as stack:
        package = stack.enter_context(Directory(package_dir))
        downloads = stack.enter_context(Directory(downloads_dir))
        require(not package.anchor.is_relative_to(downloads.anchor)
                and not downloads.anchor.is_relative_to(package.anchor),
                "overlapping_inputs", "Package and downloads must be distinct, nonnested directories")
        body = package.body("package-inventory.json")
        local = package.fingerprint()
        baseline = verify_package(package.path)
        require(baseline["status"] == "passed", "invalid_baseline", "Local baseline package failed independent audit")
        inventory = loads(body)
        report["package_id"] = inventory["package_id"]
        expected = {"package-inventory.json": (len(body), sha256(body).hexdigest())}
        expected.update({part["path"]: (int(part["size_bytes"].token), part["sha256"])
                         for part in inventory["archives"]})
        context["expected_files"] = set(expected)
        require(all(local.get(name) == value for name, value in expected.items()),
                "input_changed", "Local baseline changed after its audit")
        require(downloads.matches("package-inventory.json", body), "downloaded_inventory_mismatch",
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


def _text(value):
    if value is None:
        return False
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid acquisition text")
    return True


def _stamp(value):
    if not _text(value):
        return False
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", value):
        raise ValueError("Invalid acquisition UTC timestamp")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


def _credential_key(value):
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    key = re.sub(r"[^a-z0-9]", "", value.casefold())
    return key in {"auth", "authorization", "authtoken", "apikey", "apitoken", "xdataversekey",
                   "accesskey", "accesskeyid", "accesstoken", "token", "signature", "sig", "key",
                   "password", "passwd", "secret", "secretkey", "session", "sessionid", "sessionkey",
                   "securitytoken", "credential", "credentials", "awsaccesskeyid", "jwt", "code"} or key.endswith("token") or key.startswith(
                       ("xamz", "xgoog", "oauth", "oidc"))


def _url(value):
    if not _text(value):
        return False
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value) or "\\" in value:
        raise ValueError("Invalid acquisition URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.netloc or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Invalid acquisition URL")
    parsed.port  # validates malformed/out-of-range ports without echoing parser exceptions
    path = parsed.path
    for _ in range(3):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    segments = path.casefold().split("/")
    if any(segment in {"privateurldatasetversion", "previewurldatasetversion"}
           and any(segments[index + 1:]) for index, segment in enumerate(segments)):
        raise ValueError("Unsafe acquisition URL")
    if any(_credential_key(key) for query in (parsed.query, parsed.fragment)
           for key, _ in parse_qsl(query, keep_blank_values=True)):
        raise ValueError("Unsafe acquisition URL")
    return True


def _local_path(value, expected):
    if not _text(value):
        return False
    path = PurePosixPath(value)
    if ("\\" in value or "\x00" in value or path.is_absolute() or ".." in path.parts or str(path) != value
            or not re.fullmatch(r"package-inventory\.json|part-[0-9]{5,}\.tar\.gz", value)
            or expected is not None and value not in expected):
        raise ValueError("Invalid acquisition local path")
    return True


def _receipt(value, expected):
    required = {"dataset_url", "persistent_id", "dataset_version", "downloaded_at", "files", "recorded_by", "evidence_kind"}
    if not isinstance(value, dict) or set(value) != required or value["evidence_kind"] != "operator_recorded":
        raise ValueError("Invalid acquisition record")
    # Build the list before all(): every supplied URL is checked even when
    # some other field is unknown, rather than short-circuiting on incompleteness.
    known = [_url(value["dataset_url"]), _text(value["persistent_id"]), _text(value["dataset_version"]),
             _stamp(value["downloaded_at"]), _text(value["recorded_by"])]
    complete = all(known)
    files = value["files"]
    if files is None:
        return False
    if not isinstance(files, list):
        raise ValueError("Invalid acquisition files")
    paths, remote_ids = set(), set()
    for row in files:
        if not isinstance(row, dict) or set(row) != {"remote_file_id", "download_url", "local_path", "downloaded_at"}:
            raise ValueError("Invalid acquisition file record")
        fields = [_text(row["remote_file_id"]), _url(row["download_url"]),
                  _local_path(row["local_path"], expected), _stamp(row["downloaded_at"])]
        complete = all(fields) and complete
        for field, seen in (("local_path", paths), ("remote_file_id", remote_ids)):
            if row[field] is not None:
                if row[field] in seen:
                    raise ValueError("Ambiguous acquisition file records")
                seen.add(row[field])
    return bool(files) and complete and (expected is None or paths == expected)


def verify_deposit(package_dir, downloads_dir, acquisition=None):
    """Compare supplied local files; never download, repair, upload or publish."""
    report = {"format_version": "1.0.0", "package_id": None,
              "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
              "acquisition": None, "byte_status": "not_checked", "deposit_status": "not_checked",
              "findings": [], "publication": None}
    context, invalid_snapshot = {}, False
    try:
        receipt = deepcopy(acquisition)
    except (TypeError, ValueError, RuntimeError, ArithmeticError):
        receipt, invalid_snapshot = None, True
    try:
        _bytes(package_dir, downloads_dir, report, context)
        report["byte_status"] = "passed"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ArithmeticError) as exc:
        report["byte_status"] = "failed"
        report["findings"].append({"code": exc.code if isinstance(exc, Invalid) else "unusable_input",
                                   "qid": None, "path": exc.path if isinstance(exc, Invalid) else None,
                                   "message": str(exc) if isinstance(exc, Invalid)
                                   else "Cannot safely read package or downloaded evidence"})
    try:
        if invalid_snapshot:
            raise ValueError("Invalid acquisition snapshot")
        if receipt is None:
            report["findings"].append({"code": "acquisition_missing", "qid": None, "path": None,
                                       "message": "No acquisition receipt; only local byte comparison can be established"})
        else:
            complete = _receipt(receipt, context.get("expected_files"))
            report["acquisition"] = receipt
            if complete:
                report["deposit_status"] = "passed" if report["byte_status"] == "passed" else "failed"
            else:
                report["findings"].append({"code": "acquisition_incomplete", "qid": None, "path": None,
                                           "message": "Operator-recorded acquisition is incomplete; deposit remains unverified"})
    except (TypeError, ValueError, KeyError, RuntimeError, ArithmeticError):
        report["acquisition"] = None
        report["deposit_status"] = "failed"
        report["findings"].append({"code": "invalid_acquisition", "qid": None, "path": None,
                                   "message": "Acquisition record is malformed or contains unsafe evidence"})
    return report

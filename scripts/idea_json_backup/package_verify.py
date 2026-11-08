"""Independent bounded archive roundtrip audit; no producer or progress journal."""
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
from tempfile import TemporaryDirectory
import zlib

from scripts.sample_backup.jsoncodec import Number, loads
from .collection_verify import verify_collection

CHECKS = ("inventory", "archive_integrity", "payload_roundtrip")
POLICY = "uid=0,gid=0,uname=,gname=,mode=0644,mtime=0"
INVENTORY_KEYS = set("format format_version package_id run_id run_kind created_at profile payload archives".split())
PROFILE_KEYS = set("format max_members max_payload_bytes_per_part gzip_level gzip_mtime tar_header_policy retention_evidence".split())
CORE = {"README.md", "manifest.json", "inventory.jsonl", "attempts.jsonl", "verification.json",
        "selection/selection.json", "selection/qids.txt", "selection/query.rq"}


class Invalid(ValueError):
    def __init__(self, check, message, path=None):
        super().__init__(message)
        self.check, self.path = check, path if isinstance(path, str) else None


def require(value, message, check="inventory", path=None):
    if not value:
        raise Invalid(check, message, path)


def keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == expected, f"Invalid {label} keys")


def integer(value, *, positive=False):
    require(isinstance(value, Number) and re.fullmatch(r"[1-9][0-9]*" if positive else r"(?:0|[1-9][0-9]*)", value.token),
            "Expected a JSON integer")
    return int(value.token)


def utc(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[A-Za-z0-9-]+", value),
            "Invalid generated identifier")


def name(value):
    require(isinstance(value, str) and value and "\\" not in value and "\x00" not in value, "Unsafe relative path", path=value)
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and ".." not in relative.parts and str(relative) == value
            and relative.parts and ".state" not in relative.parts and relative != PurePosixPath("."),
            "Unsafe relative path", path=value)
    require(len(value.encode("utf-8")) <= 4096, "Payload path exceeds safe archive-name limit", path=value)
    return relative


def descriptor(value, extra):
    keys(value, {"path", "size_bytes", "sha256"} | extra, "file descriptor")
    name(value["path"])
    integer(value["size_bytes"])
    require(isinstance(value["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]), "Invalid SHA-256")


def digest_file(path):
    digest, size = sha256(), 0
    with path.open("rb") as source:
        while block := source.read(65536):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def exact(stream, size):
    value = stream.read(size)
    require(len(value) == size, "Truncated tar stream", "archive_integrity")
    return value


def pax_path(body):
    """The candidate producer needs only bounded UTF-8 long/unicode paths."""
    cursor, values = 0, {}
    while cursor < len(body):
        space = body.find(b" ", cursor)
        require(space > cursor and re.fullmatch(rb"[1-9][0-9]*", body[cursor:space]), "Malformed PAX record", "archive_integrity")
        end = cursor + int(body[cursor:space])
        require(space + 1 < end <= len(body) and body[end - 1:end] == b"\n", "Truncated PAX record", "archive_integrity")
        pair = body[space + 1:end - 1].decode("utf-8").split("=", 1)
        require(len(pair) == 2 and pair[0] == "path" and pair[0] not in values,
                "Unsupported or duplicate PAX field", "archive_integrity")
        values[pair[0]] = pair[1]
        cursor = end
    require(set(values) == {"path"}, "PAX header lacks a single path", "archive_integrity")
    return values["path"]


class Audit:
    def __init__(self, directory):
        self.root = Path(directory)
        self.anchor = None
        self.current_check = "inventory"
        self.report = {"format_version": "1.0.0", "package_id": None,
                       "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                       "status": "not_checked", "checks": [{"check_id": key, "status": "not_checked", "findings": []}
                                                                  for key in CHECKS], "findings": []}

    def path(self, relative):
        value = name(relative)
        require(self.root.is_dir() and not self.root.is_symlink() and self.root.resolve() == self.anchor,
                "Unsafe package directory")
        path = self.root
        for part in value.parts:
            path /= part
            require(not path.is_symlink(), "Linked package artifact", path=relative)
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Package artifact is not a single regular file", path=relative)
        return path

    def archive(self, record, payload, profile, destination, seen):
        path = self.path(record["path"])
        before = path.stat()
        expected = (integer(record["size_bytes"]), record["sha256"])
        require(digest_file(path) == expected, "Archive size/checksum mismatch", "archive_integrity", record["path"])
        names, total, pending = [], 0, None
        with path.open("rb") as raw:
            header = raw.read(10)
            require(len(header) == 10 and header[:4] == b"\x1f\x8b\x08\x00" and header[4:8] == b"\0" * 4 and header[8] == 0,
                    "Archive gzip header differs from candidate profile", "archive_integrity", record["path"])
            raw.seek(0)
            with gzip.GzipFile(fileobj=raw, mode="rb") as source:
                while True:
                    block = exact(source, 512)
                    if block == b"\0" * 512:
                        require(pending is None and exact(source, 512) == b"\0" * 512,
                                "Invalid tar end marker", "archive_integrity", record["path"])
                        padding = 1024
                        while tail := source.read(65536):
                            padding += len(tail)
                            require(padding <= 10240 and not any(tail), "Hidden/trailing tar data", "archive_integrity", record["path"])
                        break  # gzip read to EOF validates its trailer, even after tar stops
                    entry = tarfile.TarInfo.frombuf(block, encoding="utf-8", errors="strict")
                    if entry.type == tarfile.XHDTYPE:
                        require(pending is None and 0 < entry.size <= 16384,
                                "Oversized or repeated PAX extension", "archive_integrity", record["path"])
                        require(entry.uid == entry.gid == entry.mtime == entry.mode == 0
                                and entry.uname == entry.gname == entry.linkname == "",
                                "PAX metadata header differs from normalized profile", "archive_integrity", record["path"])
                        pending = pax_path(exact(source, entry.size))
                        require(not any(exact(source, (-entry.size) % 512)), "Nonzero PAX padding", "archive_integrity")
                        continue
                    require(entry.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not entry.linkname,
                            "Archive member is not a regular file", "archive_integrity", entry.name)
                    member = pending if pending is not None else entry.name
                    pending = None
                    relative = name(member)
                    require(member in payload and payload[member]["archive_path"] == record["path"]
                            and member not in seen, "Unexpected or duplicate archive member", "payload_roundtrip", member)
                    declared = payload[member]
                    require(entry.size == integer(declared["size_bytes"]), "Tar member size differs", "payload_roundtrip", member)
                    require(entry.uid == entry.gid == entry.mtime == 0 and entry.mode == 0o644
                            and entry.uname == entry.gname == "", "Tar header differs from candidate profile", "archive_integrity", member)
                    total += entry.size
                    names.append(member)
                    require(len(names) <= profile["members"] and total <= profile["bytes"],
                            "Archive exceeds declared part limits", "archive_integrity", record["path"])
                    output = destination.joinpath(*relative.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    digest, left = sha256(), entry.size
                    with output.open("xb") as stream:
                        while left:
                            chunk = exact(source, min(65536, left))
                            require(stream.write(chunk) == len(chunk), "Incomplete roundtrip write", "payload_roundtrip", member)
                            digest.update(chunk)
                            left -= len(chunk)
                    require(digest.hexdigest() == declared["sha256"], "Extracted payload checksum differs", "payload_roundtrip", member)
                    require(not any(exact(source, (-entry.size) % 512)), "Nonzero tar member padding", "archive_integrity", member)
                    seen.add(member)
        require(names == record["members"], "Actual archive membership/order differs", "payload_roundtrip", record["path"])
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "Archive changed during audit", "archive_integrity", record["path"])

    def saved_report(self, package_id):
        body = self.path("package-verification.json").read_bytes()
        report = loads(body)
        keys(report, {"format_version", "package_id", "checked_at", "status", "checks", "findings"}, "package report")
        require(report["format_version"] == "1.0.0" and report["package_id"] == package_id,
                "Saved package report identifies another package")
        stamp = report["checked_at"]
        require(isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp),
                "Invalid saved report timestamp")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        require(report["status"] in ("passed", "failed", "not_checked") and isinstance(report["findings"], list)
                and isinstance(report["checks"], list) and len(report["checks"]) == len(CHECKS), "Invalid saved report outcome")
        all_findings = list(report["findings"])
        for label, check in zip(CHECKS, report["checks"]):
            keys(check, {"check_id", "status", "findings"}, "package check")
            require(check["check_id"] == label and check["status"] in ("passed", "failed", "not_checked")
                    and isinstance(check["findings"], list), "Invalid saved package check")
            all_findings.extend(check["findings"])
        for finding in all_findings:
            keys(finding, {"code", "qid", "path", "message"}, "package finding")
            require(all(isinstance(finding[field], str) and finding[field] for field in ("code", "message"))
                    and (finding["qid"] is None or isinstance(finding["qid"], str))
                    and (finding["path"] is None or isinstance(finding["path"], str)), "Invalid saved package finding")
        if report["status"] == "passed":
            require(not all_findings and all(check["status"] == "passed" for check in report["checks"]),
                    "Saved passed report has failed or incomplete checks")
        return len(body), sha256(body).hexdigest()

    def files(self):
        result = set()
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root).as_posix()
            self.path(relative)  # packages contain only regular root-level artifacts
            result.add(relative)
        return result

    def verify(self):
        require(self.root.is_dir() and not self.root.is_symlink(), "Unsafe package directory")
        self.anchor = self.root.resolve()
        body = self.path("package-inventory.json").read_bytes()
        expected_files = {"package-inventory.json": (len(body), sha256(body).hexdigest())}
        inventory = loads(body)
        del body
        keys(inventory, INVENTORY_KEYS, "package inventory")
        require(inventory["format"] == "idea-json-backup" and inventory["format_version"] == "1.0.0", "Wrong package format")
        utc(inventory["package_id"])
        utc(inventory["run_id"])
        self.report["package_id"] = inventory["package_id"]
        require(inventory["run_kind"] in ("production", "pilot", "synthetic"), "Invalid package run kind")
        stamp = inventory["created_at"]
        require(isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp), "Invalid creation time")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        profile = inventory["profile"]
        keys(profile, PROFILE_KEYS, "package profile")
        require(profile["format"] == "tar.gz" and integer(profile["gzip_level"]) == 6
                and integer(profile["gzip_mtime"]) == 0 and profile["tar_header_policy"] == POLICY
                and profile["retention_evidence"] is None, "Unsupported candidate archive profile")
        limits = {"members": integer(profile["max_members"], positive=True),
                  "bytes": integer(profile["max_payload_bytes_per_part"], positive=True)}
        require(limits["members"] <= 5000 and limits["bytes"] <= 268435456,
                "Candidate profile exceeds approved test ceilings")
        require(isinstance(inventory["payload"], list) and inventory["payload"]
                and isinstance(inventory["archives"], list) and inventory["archives"], "Empty or invalid package inventory")
        payload, archives = {}, {}
        for value in inventory["payload"]:
            descriptor(value, {"archive_path"})
            require(value["path"] not in payload, "Duplicate payload path", path=value["path"])
            require(value["path"] not in ("package-inventory.json", "package-verification.json"), "External package record listed as payload")
            payload[value["path"]] = value
        require(CORE <= set(payload), "Required collection documentation/records are absent")
        require(list(payload) == sorted(payload), "Payload inventory is not in stable path order")
        membership = []
        for index, value in enumerate(inventory["archives"], 1):
            descriptor(value, {"members"})
            require(value["path"] == f"part-{index:05d}.tar.gz" and value["path"] not in archives,
                    "Archive naming/order differs from candidate profile")
            members = value["members"]
            require(isinstance(members, list) and members and len(members) <= limits["members"]
                    and all(isinstance(member, str) and member in payload for member in members), "Invalid archive members")
            require(sum(integer(payload[member]["size_bytes"]) for member in members) <= limits["bytes"],
                    "Archive declared payload exceeds byte limit")
            require(all(payload[member]["archive_path"] == value["path"] for member in members), "Payload archive assignment differs")
            membership.extend(members)
            archives[value["path"]] = value
            expected_files[value["path"]] = (integer(value["size_bytes"]), value["sha256"])
        require(membership == list(payload) and len(membership) == len(set(membership)), "Payload is not assigned exactly once in stable order")
        actual = self.files()
        require(actual in ({"package-inventory.json"} | set(archives),
                           {"package-inventory.json", "package-verification.json"} | set(archives)),
                "Unexpected or missing package artifacts")
        if "package-verification.json" in actual:
            expected_files["package-verification.json"] = self.saved_report(inventory["package_id"])
        seen = set()
        with TemporaryDirectory(prefix="idea-package-roundtrip-") as directory:
            destination = Path(directory)
            for record in inventory["archives"]:
                self.current_check = "archive_integrity"
                self.archive(record, payload, limits, destination, seen)
            self.current_check = "payload_roundtrip"
            require(seen == set(payload), "Roundtrip payload path set differs", "payload_roundtrip")
            manifest = loads((destination / "manifest.json").read_bytes())
            require(manifest.get("run_id") == inventory["run_id"] and manifest.get("run_kind") == inventory["run_kind"]
                    and manifest.get("phase") == "finalized" and manifest.get("collection_status") == "passed",
                    "Packaged run is not the declared finalized collection", "payload_roundtrip")
            report = verify_collection(destination)
            require(report["status"] == "passed", "Roundtripped collection audit failed: " +
                    "; ".join(finding["message"] for finding in report["findings"]), "payload_roundtrip")
        require(self.files() == set(expected_files), "Package file set changed during audit")
        self.current_check = "archive_integrity"
        for relative, expected in expected_files.items():
            require(digest_file(self.path(relative)) == expected, "Package bytes changed during audit",
                    "archive_integrity", relative)
        self.report["status"] = "passed"
        for check in self.report["checks"]:
            check["status"] = "passed"
        return self.report


def verify_package(directory):
    """Read package bytes and roundtrip in temporary storage; never repair or fetch."""
    audit = Audit(directory)
    try:
        return audit.verify()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ArithmeticError, tarfile.TarError, EOFError, zlib.error) as exc:
        category = exc.check if isinstance(exc, Invalid) else audit.current_check
        finding = {"code": "invalid_package", "qid": None, "path": exc.path if isinstance(exc, Invalid) else None,
                   "message": str(exc)}
        audit.report["status"] = "failed"
        audit.report["findings"].append(finding)
        for check in audit.report["checks"]:
            check["status"] = "failed" if check["check_id"] == category else "not_checked"
            if check["check_id"] == category:
                check["findings"].append(finding)
        return audit.report

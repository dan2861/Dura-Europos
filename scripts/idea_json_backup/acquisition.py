"""Pure operator-acquisition schema checks; no file or network access."""
from datetime import datetime
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qsl, unquote, urlsplit


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



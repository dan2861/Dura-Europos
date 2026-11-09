"""Independent public-file audit of a production JSON collection.

This module neither opens the progress journal nor calls extraction, transport
or collection code. Object comparisons retain JSON types and numeric tokens.
"""
import gzip
import re
import stat
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

from scripts.sample_backup.jsoncodec import Number, dumps, loads
from .selection_verify import verify_selection

MANIFEST_KEYS = set("format format_version run_id run_kind exporter_version runtime selection created_at started_at finished_at request_settings next_dispatch_at phase state_sequence public_records counts collection_status verification_path limitations".split())
ITEM_KEYS = set("requested_qid returned_qid status lastrevid modified retrieved_at item source_response_id source_entity_key attempt_ids membership_at_retrieval next_eligible_at error".split())
ATTEMPT_KEYS = set("attempt_id requested_qids reserved_at dispatch_started_at headers_received_at headers_observed response_received_at response_elapsed_ms receipt_complete finished_at recovered_at request http encoded decoded diagnostics api_error warnings outcome item_results next_eligible_at error".split())
ERROR_KEYS = {"stage", "code", "message", "retryable"}
STAGES = {"selection", "transport", "api", "decoding", "identity", "extraction", "saving", "recovery"}
HEADERS = {"content-type", "content-encoding", "content-length", "retry-after", "date", "etag", "last-modified", "location", "x-database-lag"}
PARAMETERS = {"action": "wbgetentities", "format": "json", "formatversion": "2", "redirects": "no", "maxlag": "5"}
CHECKS = ("scope", "source_content", "provenance", "files")
QID = re.compile(r"Q[1-9][0-9]*\Z")


class Invalid(ValueError):
    def __init__(self, check, code, message, qid=None, path=None):
        super().__init__(message)
        self.check, self.code, self.qid, self.path = check, code, qid, path


def _require(condition, message, check="scope", code="invalid_record", qid=None, path=None):
    if not condition:
        raise Invalid(check, code, message, qid, path)


def _keys(value, expected, label, check="scope"):
    _require(isinstance(value, dict) and set(value) == expected, f"Invalid {label} keys", check)


def _integer(value, *, positive=False):
    return isinstance(value, Number) and bool(re.fullmatch(
        r"[1-9][0-9]*" if positive else r"(?:0|[1-9][0-9]*)", value.token))


def _int(value, *, positive=False, label="integer", check="scope"):
    _require(_integer(value, positive=positive), f"Expected JSON {label}", check)
    return int(value.token)


def _time(value, *, generated=True, nullable=False, check="provenance"):
    if nullable and value is None:
        return None
    pattern = (r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.\d{6}Z" if generated else
               r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.\d+)?Z")
    _require(isinstance(value, str) and re.fullmatch(pattern, value), "Invalid UTC timestamp", check)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Invalid(check, "invalid_time", str(exc)) from exc


def _same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, Number):
        return left.token == right.token
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(v, right[k]) for k, v in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _error(value, *, nullable=True):
    if nullable and value is None:
        return
    _keys(value, ERROR_KEYS, "error", "provenance")
    _require(value["stage"] in STAGES and type(value["retryable"]) is bool
             and all(isinstance(value[k], str) and value[k] for k in ("code", "message")),
             "Invalid typed error", "provenance")


def _membership(entity):
    claims = entity.get("claims", {})
    _require(isinstance(claims, dict), "Malformed claims object", "source_content")
    rows = claims.get("P5008", [])
    _require(isinstance(rows, list), "Malformed P5008 group", "source_content")
    matches = False
    for row in rows:
        _require(isinstance(row, dict) and row.get("rank") in ("normal", "preferred", "deprecated")
                 and isinstance(row.get("mainsnak"), dict), "Malformed IDEA statement", "source_content")
        snak = row["mainsnak"]
        _require(snak.get("snaktype") in ("value", "novalue", "somevalue"), "Unknown IDEA snak", "source_content")
        if snak["snaktype"] != "value":
            _require("datavalue" not in snak, "Non-value IDEA snak carries a value", "source_content")
            continue
        data = snak.get("datavalue")
        _require(isinstance(data, dict) and data.get("type") == "wikibase-entityid"
                 and isinstance(data.get("value"), dict), "Malformed IDEA value", "source_content")
        value = data["value"]
        _require(isinstance(value.get("id"), str) and QID.fullmatch(value["id"])
                 and value.get("entity-type", "item") == "item"
                 and snak.get("datatype", "wikibase-item") == "wikibase-item", "Malformed IDEA item ID", "source_content")
        if "numeric-id" in value:
            _require(_integer(value["numeric-id"], positive=True) and value["numeric-id"].token == value["id"][1:],
                     "IDEA numeric ID disagrees", "source_content")
        matches |= value["id"] == "Q114241199" and row["rank"] in ("normal", "preferred")
    return "matches" if matches else "changed"


class Audit:
    def __init__(self, directory):
        self.root = Path(directory)
        self.accounted = {"manifest.json": "manifest"}
        self.report = {"format_version": "1.0.0", "run_id": None,
                       "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                       "inputs": None, "status": "not_checked",
                       "checks": [{"check_id": name, "status": "not_checked", "findings": []} for name in CHECKS],
                       "counts": {name: None for name in ("selected", "pending", "accepted", "unresolved")},
                       "findings": []}
        self.unfinished = False

    def failure(self, category, code, message, *, qid=None, path=None):
        finding = {"code": code, "qid": qid, "path": path, "message": message}
        self.report["status"] = "failed"
        self.report["findings"].append(finding)
        for check in self.report["checks"]:
            if check["check_id"] == category:
                check["status"] = "failed"
                check["findings"].append(finding)

    def path(self, name):
        _require(isinstance(name, str) and name and "\\" not in name, "Unsafe artifact path", "files", path=name)
        relative = PurePosixPath(name)
        _require(not relative.is_absolute() and ".." not in relative.parts and str(relative) == name
                 and name != "." and relative.parts[0] != ".state", "Unsafe artifact path", "files", path=name)
        path = self.root
        for part in relative.parts:
            path = path / part
            _require(not path.is_symlink(), "Symlink in artifact path", "files", path=name)
        info = path.stat()
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Artifact is not an unlinked regular file", "files", path=name)
        return path

    def read(self, descriptor, owner, *, body=False, expected=None):
        _keys(descriptor, {"path", "size_bytes", "sha256", "complete"} if body else
              {"path", "size_bytes", "sha256"}, "file descriptor", "files")
        name = descriptor["path"]
        _require(expected is None or name == expected, "Unexpected artifact path", "files", path=name)
        value = self.path(name).read_bytes()
        _require(name not in self.accounted or self.accounted[name] == owner,
                 "Artifact has multiple owners", "files", path=name)
        self.accounted[name] = owner
        _require(_integer(descriptor["size_bytes"]) and int(descriptor["size_bytes"].token) == len(value),
                 "Artifact size mismatch", "files", path=name)
        _require(isinstance(descriptor["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"])
                 and sha256(value).hexdigest() == descriptor["sha256"], "Artifact checksum mismatch", "files", path=name)
        if body:
            _require(descriptor["complete"] is None or type(descriptor["complete"]) is bool,
                     "Invalid body completeness", "provenance", path=name)
            _require(value, "Empty body must not invent an artifact", "provenance", path=name)
        return value

    def records(self, descriptor, owner, expected):
        body = self.read(descriptor, owner, expected=expected)
        _require(not body or body.endswith(b"\n"), "JSONL lacks final newline")
        return [loads(line) for line in body.splitlines()]

    def documentation(self, manifest):
        name = "README.md"
        candidate = self.root / name
        if not candidate.exists() and not candidate.is_symlink():
            _require(not self.terminal, "Required run README.md is missing", "files",
                     code="missing_readme", path=name)
            self.unfinished = True
            return
        try:
            text = self.path(name).read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Invalid("files", "invalid_readme", "README.md is not UTF-8 text", path=name) from exc
        _require(text.strip(), "README.md is empty", "files", code="invalid_readme", path=name)
        fields = {"Run ID": manifest["run_id"], "Run kind": manifest["run_kind"],
                  "Frozen QIDs": manifest["selection"]["selected_count"].token,
                  "Frozen QID list SHA-256": manifest["selection"]["qid_list"]["sha256"]}
        lines = text.splitlines()
        for field, expected in fields.items():
            declared = [line for line in lines if line.startswith(field + ":")]
            _require(declared == [field + ": " + expected], "README.md identity differs from the frozen run",
                     "files", code="invalid_readme", path=name)
        self.accounted[name] = "documentation"

    def settings(self, value):
        expected = {"endpoint": "https://www.wikidata.org/w/api.php", "action_parameters": PARAMETERS,
                    "headers": value.get("headers") if isinstance(value, dict) else None,
                    "batch_size": 50, "concurrency": 1, "minimum_gap_seconds": 1, "response_deadline_seconds": 60,
                    "max_attempts_per_item": 3, "retry_backoff_seconds": [5, 10],
                    "supported_content_encodings": ["identity", "gzip"], "http_redirect_policy": "reject"}
        _require(_same(value, loads(dumps(expected))), "Changed collection request settings", "provenance")
        headers = value["headers"]
        _keys(headers, {"Accept", "Accept-Encoding", "User-Agent"}, "request headers", "provenance")
        _require(headers["Accept"] == "application/json" and headers["Accept-Encoding"] == "gzip, identity"
                 and isinstance(headers["User-Agent"], str) and headers["User-Agent"].strip()
                 and not any(c in headers["User-Agent"] for c in "\r\n"), "Invalid request identification", "provenance")

    def attempt(self, value, settings, positions, owner):
        _keys(value, ATTEMPT_KEYS, "attempt", "provenance")
        qids = value["requested_qids"]
        _require(isinstance(qids, list) and 1 <= len(qids) <= 50 and all(q in positions for q in qids)
                 and len(set(qids)) == len(qids) and qids == sorted(qids, key=positions.get), "Invalid attempt scope", "scope")
        reserved = _time(value["reserved_at"])
        dispatch = _time(value["dispatch_started_at"], nullable=True)
        headers_at = _time(value["headers_received_at"], nullable=True)
        received = _time(value["response_received_at"], nullable=True)
        finished = _time(value["finished_at"], nullable=True)
        _time(value["recovered_at"], nullable=True)
        _time(value["next_eligible_at"], nullable=True)
        _require(dispatch is None or reserved <= dispatch, "Dispatch precedes reservation", "provenance")
        _require(finished is None or reserved <= finished, "Attempt finish precedes reservation", "provenance")
        request = value["request"]
        _keys(request, {"method", "url", "parameters", "headers"}, "request", "provenance")
        expected = {"method": "GET", "url": settings["endpoint"], "parameters": dict(PARAMETERS, ids="|".join(qids)), "headers": settings["headers"]}
        _require(_same(request, expected), "Request differs from frozen settings/scope", "provenance")
        observed, complete = value["headers_observed"], value["receipt_complete"]
        _require(observed is None or type(observed) is bool, "Invalid header observation", "provenance")
        _require(complete is None or type(complete) is bool, "Invalid receipt completeness", "provenance")
        headers = {}
        if value["http"] is not None:
            _keys(value["http"], {"status_code", "headers"}, "HTTP receipt", "provenance")
            code = _int(value["http"]["status_code"], check="provenance")
            headers = value["http"]["headers"]
            _require(100 <= code <= 599 and observed is True and isinstance(headers, dict)
                     and set(headers) <= HEADERS and all(isinstance(v, list) and v and all(isinstance(x, str) for x in v)
                                                       for v in headers.values()), "Invalid HTTP receipt", "provenance")
        else:
            code = None
            _require(observed is not True and headers_at is None, "Observed headers lack HTTP receipt", "provenance")
        if observed is True:
            _require(dispatch is not None and headers_at is not None and dispatch <= headers_at
                     and (finished is None or headers_at <= finished), "Invalid header timing", "provenance")
        else:
            _require(headers_at is None, "Unobserved headers claim a timestamp", "provenance")
        if complete is True:
            _require(headers_at is not None and received is not None and headers_at <= received
                     and (finished is None or received <= finished), "Invalid completed response timing", "provenance")
            _require(_integer(value["response_elapsed_ms"]) and int(value["response_elapsed_ms"].token) <= 60000,
                     "Invalid/excessive response deadline evidence", "provenance")
        else:
            _require(received is None and value["response_elapsed_ms"] is None,
                     "Incomplete receipt claims completion", "provenance")
        encoded = self.read(value["encoded"], owner, body=True) if value["encoded"] is not None else b""
        decoded = self.read(value["decoded"], owner, body=True) if value["decoded"] is not None else None
        if value["encoded"] is not None:
            _require(value["encoded"]["complete"] is complete, "Encoded completeness differs from receipt", "provenance")
        if complete is True:
            lengths = headers.get("content-length", [])
            _require(not lengths or (len(lengths) == 1 and re.fullmatch(r"[0-9]+", lengths[0])
                                    and int(lengths[0]) == len(encoded)), "Encoded framing mismatch", "provenance")
        if decoded is not None and value["decoded"]["complete"] is True:
            _require(complete is True, "Complete decoded body lacks receipt proof", "provenance")
            encoding = headers.get("content-encoding", ["identity"])
            _require(len(encoding) == 1 and encoding[0].strip().lower() in ("identity", "gzip"), "Invalid content encoding", "provenance")
            try:
                original = gzip.decompress(encoded) if encoding[0].strip().lower() == "gzip" else encoded
            except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
                raise Invalid("provenance", "decode_failed", str(exc)) from exc
            _require(original == decoded, "Encoded bytes do not decode to the saved response", "provenance")
        _require(isinstance(value["diagnostics"], list), "Invalid diagnostics", "provenance")
        for diagnostic in value["diagnostics"]:
            _keys(diagnostic, {"role", "file", "explanation"}, "diagnostic", "provenance")
            _require(all(isinstance(diagnostic[k], str) and diagnostic[k] for k in ("role", "explanation")), "Unexplained diagnostic", "provenance")
            self.read(diagnostic["file"], owner, body=True)
        _error(value["error"])
        if value["api_error"] is not None or value["warnings"] is not None:
            _require(decoded is not None and value["decoded"]["complete"] is True,
                     "API summary lacks a complete preserved body", "provenance")
            envelope = loads(decoded)
            _require(isinstance(envelope, dict), "API summary body is not an object", "provenance")
            if value["api_error"] is not None:
                _keys(value["api_error"], {"code", "message"}, "API error", "provenance")
                raw = envelope.get("error")
                _require(isinstance(raw, dict) and isinstance(raw.get("code"), str)
                         and value["api_error"]["code"] == raw["code"]
                         and value["api_error"]["message"] == raw.get("info", raw.get("message")),
                         "API summary differs from preserved body", "provenance")
            _require(_same(value["warnings"], envelope.get("warnings")),
                     "Warnings differ from preserved body", "provenance")
        _require(value["outcome"] in ("reserved", "succeeded", "mixed", "transient_failure", "review_required", "interrupted", "saving_failure"),
                 "Unknown attempt outcome", "provenance")
        results = value["item_results"]
        _require(isinstance(results, list) and len(results) == len(qids), "Attempt item results differ from scope", "scope")
        for qid, row in zip(qids, results):
            _keys(row, {"qid", "outcome", "returned_qid", "error"}, "item result", "provenance")
            _require(row["qid"] == qid and row["outcome"] in ("accepted", "transient_failure", "review_required", "unknown"), "Invalid item result", "provenance")
            _error(row["error"])
            _require(row["returned_qid"] is None or (isinstance(row["returned_qid"], str)
                     and QID.fullmatch(row["returned_qid"])), "Invalid returned item ID", "provenance")
            if row["outcome"] == "accepted":
                _require(row["error"] is None and row["returned_qid"] == qid,
                         "Accepted result claims an error or different ID", "provenance")
            elif row["outcome"] in ("transient_failure", "review_required"):
                _require(row["error"] is not None and row["error"]["retryable"] is
                         (row["outcome"] == "transient_failure"),
                         "Item outcome lacks its typed failure", "provenance")
        if value["outcome"] == "succeeded":
            _require(value["error"] is None and (finished is None or all(row["outcome"] == "accepted" for row in results)),
                     "Successful attempt claims failure or unfinished items", "provenance")
        usable = value["outcome"] in ("succeeded", "mixed")
        if usable:
            _require(code == 200 and complete is True and decoded is not None and value["decoded"]["complete"] is True
                     and value["api_error"] is None and value["warnings"] is None,
                     "Successful source lacks complete usable receipt", "provenance")
            if finished is None:
                _require(not self.terminal, "Terminal collection has unfinished local extraction", "provenance")
                self.unfinished = True
            source = loads(decoded)
            _require(isinstance(source, dict) and set(source) == {"success", "entities"}
                     and _same(source["success"], Number("1")) and isinstance(source["entities"], dict)
                     and set(source["entities"]) <= set(qids), "Unusable source wrapper", "source_content")
            return source["entities"]
        _require(not any(row["outcome"] == "accepted" for row in results), "Failed attempt claims accepted items", "provenance")
        return None

    def retry_history(self, attempts):
        """Derive dispatch lower bounds from public receipts and consumed quota."""
        used, eligible = {}, {}
        global_gate = None
        unfinished_attempt = False
        held = set()
        for attempt in attempts:
            dispatch = _time(attempt["dispatch_started_at"], nullable=True)
            if dispatch is not None:
                _require(not unfinished_attempt, "Dispatch occurred before local source processing finished", "provenance")
                _require(not held.intersection(attempt["requested_qids"]),
                         "Attempt repeats an accepted or nonretryable held item", "provenance")
                _require(global_gate is None or dispatch >= global_gate,
                         "Dispatch evades global cooldown", "provenance")
                for qid in attempt["requested_qids"]:
                    _require(qid not in eligible or dispatch >= eligible[qid],
                             "Dispatch evades item retry backoff", "provenance", qid=qid)
            for qid in attempt["requested_qids"]:
                used[qid] = used.get(qid, 0) + 1
            finished = _time(attempt["finished_at"], nullable=True)
            recovered_at = _time(attempt["recovered_at"], nullable=True)
            recovered = finished is None and attempt["outcome"] == "interrupted" and recovered_at is not None
            anchor = recovered_at if recovered else finished
            if anchor is None:
                _require(attempt["outcome"] == "reserved" or (not self.terminal and attempt["outcome"] in ("succeeded", "mixed")),
                         "Completed attempt lacks finish time", "provenance")
                unfinished_attempt = self.unfinished = True
                continue
            _require(anchor >= _time(attempt["reserved_at"])
                     and (dispatch is None or anchor >= dispatch), "Recovery precedes reservation/dispatch", "provenance")
            global_gate = anchor + timedelta(seconds=1)
            headers = attempt["http"]["headers"] if attempt["http"] is not None else {}
            malformed = False
            for value in headers.get("retry-after", []):
                try:
                    if re.fullmatch(r"[0-9]+", value):
                        receipt = _time(attempt["headers_received_at"])
                        bound = receipt + timedelta(seconds=int(value))
                    else:
                        bound = parsedate_to_datetime(value)
                        if bound.tzinfo is None:
                            raise ValueError("Retry-After needs timezone")
                    global_gate = max(global_gate, bound)
                except (TypeError, ValueError, OverflowError):
                    malformed = True
            if malformed:
                error = attempt["error"]
                _require(isinstance(error, dict) and "retry_after" in error["code"],
                         "Malformed Retry-After lacks an explicit finding", "provenance")
            status = attempt["http"]["status_code"] if attempt["http"] is not None else None
            status = int(status.token) if isinstance(status, Number) else None
            for result in attempt["item_results"]:
                if result["outcome"] == "accepted" or (result["error"] is not None
                                                       and result["error"]["retryable"] is False):
                    held.add(result["qid"])
                if result["error"] is None or result["error"]["retryable"] is not True:
                    continue
                _require(attempt["warnings"] is None, "Warning-bearing response cannot be retried automatically", "provenance")
                error = result["error"]
                known_receipt = type(attempt["headers_observed"]) is bool
                transient = (error["stage"] in ("transport", "decoding", "api") and known_receipt
                             and (status in (429, 500, 502, 503, 504)
                                  or (error["stage"] == "transport" and attempt["receipt_complete"] is not True)
                                  or (status == 200 and error["stage"] == "api"
                                      and attempt["api_error"] is not None
                                      and attempt["api_error"]["code"] == "maxlag")))
                known_recovery = (error["stage"] == "recovery" and (known_receipt or dispatch is None)
                                  and attempt["outcome"] == "interrupted" and recovered_at is not None)
                _require(transient or known_recovery, "History retries a held or unknown failure", "provenance", qid=result["qid"])
                qid = result["qid"]
                eligible[qid] = max(global_gate, anchor + timedelta(seconds=5 if used[qid] == 1 else 10))
            if attempt["next_eligible_at"] is not None:
                bound = _time(attempt["next_eligible_at"])
                _require(bound >= global_gate and all(bound >= eligible[qid]
                         for qid in attempt["requested_qids"] if qid in eligible),
                         "Attempt retry eligibility shortens recorded waits", "provenance")

    def verify(self):
        _require(self.root.is_dir() and not self.root.is_symlink(), "Invalid run directory", "files")
        internal = self.root / ".state"
        if internal.exists() or internal.is_symlink():
            _require(internal.is_dir() and not internal.is_symlink(), "Internal state must be a real directory", "files")
        manifest = loads(self.path("manifest.json").read_bytes())
        _keys(manifest, MANIFEST_KEYS, "manifest")
        self.report["run_id"] = manifest["run_id"]
        _require(manifest["format"] == "idea-json-backup" and manifest["format_version"] == "1.0.0", "Wrong collection format")
        _require(isinstance(manifest["run_id"], str) and re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z-[A-Za-z0-9-]+", manifest["run_id"]), "Invalid run ID")
        _require(manifest["run_kind"] in ("production", "pilot", "synthetic"), "Invalid run kind")
        _require(isinstance(manifest["exporter_version"], str) and manifest["exporter_version"], "Missing exporter version")
        _keys(manifest["runtime"], {"python", "sqlite", "platform"}, "runtime")
        _require(all(isinstance(v, str) and v for v in manifest["runtime"].values()), "Invalid runtime record")
        created = _time(manifest["created_at"])
        started = _time(manifest["started_at"], nullable=True)
        finished = _time(manifest["finished_at"], nullable=True)
        _time(manifest["next_dispatch_at"], nullable=True)
        _require((started is None or created <= started) and (finished is None or started is not None and started <= finished), "Invalid collection interval")
        _require(manifest["phase"] in ("initialized", "collecting", "paused", "collected", "finalized"), "Invalid phase")
        self.terminal = manifest["phase"] in ("collected", "finalized")
        if manifest["phase"] in ("collected", "finalized"):
            _require(finished is not None, "Terminal collection lacks finish time")
        else:
            _require(finished is None, "Resumable phase claims terminal finish")
            self.unfinished = True
        _require(manifest["collection_status"] in ("not_checked", "failed", "passed"), "Invalid collection status")
        _require(isinstance(manifest["limitations"], list) and manifest["limitations"]
                 and all(isinstance(v, str) and v for v in manifest["limitations"]), "Missing limitations")
        self.settings(manifest["request_settings"])
        sequence = _int(manifest["state_sequence"], label="state sequence")
        selection = manifest["selection"]
        _keys(selection, {"metadata", "qid_list", "selected_count"}, "selection reference")
        saved_selection = loads(self.read(selection["metadata"], "selection", expected="selection/selection.json"))
        qid_bytes = self.read(selection["qid_list"], "selection", expected="selection/qids.txt")
        _require(verify_selection(self.root / "selection")["status"] == "passed", "Copied selection failed independent audit")
        _require(saved_selection["kind"] == manifest["run_kind"], "Run and selection kinds differ")
        for path in (self.root / "selection").rglob("*"):
            if path.is_file() and ".state" not in path.relative_to(self.root / "selection").parts:
                relative = path.relative_to(self.root).as_posix()
                self.path(relative)
                self.accounted[relative] = "selection"
        qids = qid_bytes.decode("utf-8").splitlines()
        _require(_integer(selection["selected_count"], positive=True)
                 and int(selection["selected_count"].token) == len(qids), "Selection count differs")
        records = manifest["public_records"]
        _keys(records, {"inventory", "attempts"}, "public records")
        for name, descriptor in records.items():
            _keys(descriptor, {"file", "state_sequence"}, "public record descriptor")
            value = _int(descriptor["state_sequence"], label="projection sequence")
            _require(value <= sequence, "Public projection is ahead of journal sequence")
            self.unfinished |= value < sequence
        inventory = self.records(records["inventory"]["file"], "inventory", "inventory.jsonl")
        attempts = self.records(records["attempts"]["file"], "attempts", "attempts.jsonl")
        self.report["inputs"] = {"selection": selection, "inventory": records["inventory"], "attempts": records["attempts"]}
        _require(len(inventory) == len(qids), "Inventory scope differs from selection")
        positions = {qid: index for index, qid in enumerate(qids)}
        links = {qid: [] for qid in qids}
        ids = []
        for value in attempts:
            _keys(value, ATTEMPT_KEYS, "attempt", "provenance")
            identifier = value["attempt_id"]
            _require(isinstance(identifier, str) and re.fullmatch(r"A[0-9]+", identifier)
                     and int(identifier[1:]) > 0 and identifier not in ids
                     and (not ids or int(identifier[1:]) > int(ids[-1][1:])), "Invalid attempt order/ID", "scope")
            ids.append(identifier)
            _require(isinstance(value["requested_qids"], list) and all(q in links for q in value["requested_qids"]), "Attempt requests outside selection")
            for qid in value["requested_qids"]:
                links[qid].append(identifier)
        grouped = {}
        counts = {"selected": len(qids), "pending": 0, "accepted": 0, "unresolved": 0}
        for qid, row in zip(qids, inventory):
            _keys(row, ITEM_KEYS, "inventory item")
            _require(row["requested_qid"] == qid and row["status"] in ("pending", "accepted", "unresolved"), "Inventory QID/order/status mismatch")
            _require(row["attempt_ids"] == links[qid] and len(links[qid]) <= 3, "Item attempt history differs or exceeds quota")
            _error(row["error"])
            _time(row["next_eligible_at"], nullable=True)
            counts[row["status"]] += 1
            if row["status"] == "accepted":
                _require(row["error"] is None and row["returned_qid"] == qid and row["source_entity_key"] == qid
                         and row["attempt_ids"] and row["source_response_id"] == row["attempt_ids"][-1]
                         and row["next_eligible_at"] is None, "Accepted item lacks consistent provenance", "provenance", qid=qid)
                grouped.setdefault(row["source_response_id"], []).append(row)
            else:
                _require(all(row[key] is None for key in ("lastrevid", "modified", "retrieved_at", "item", "source_response_id", "source_entity_key"))
                         and row["membership_at_retrieval"] == "not_checked", "Unaccepted item claims accepted data", "provenance", qid=qid)
                if row["status"] == "pending":
                    _require(row["error"] is None, "Pending item claims failure")
                    self.unfinished = True
                else:
                    _error(row["error"], nullable=False)
                    if not (row["error"]["retryable"] and len(links[qid]) < 3
                            and manifest["phase"] not in ("collected", "finalized")):
                        self.failure("scope", "invalid_record", "Unresolved item prevents collection completion", qid=qid)
                    self.unfinished = True
        self.report["counts"] = counts
        _keys(manifest["counts"], set(counts), "counts")
        _require(all(_integer(manifest["counts"][k]) and int(manifest["counts"][k].token) == v for k, v in counts.items()), "Run counts differ from inventory")
        for value in attempts:
            source = self.attempt(value, manifest["request_settings"], positions, value["attempt_id"])
            for row in grouped.get(value["attempt_id"], []):
                qid = row["requested_qid"]
                _require(source is not None and qid in source, "Accepted item lacks source object", "source_content", qid=qid)
                entity = source[qid]
                _require(isinstance(entity, dict) and entity.get("id") == qid and entity.get("type") == "item"
                         and not any(k in entity for k in ("missing", "redirect", "redirects", "error")), "Invalid source entity identity", "source_content", qid=qid)
                _require(_integer(entity.get("lastrevid"), positive=True), "Invalid source revision", "source_content", qid=qid)
                _time(entity.get("modified"), generated=False, check="source_content")
                _require(_same(row["lastrevid"], entity["lastrevid"]) and row["modified"] == entity["modified"]
                         and row["retrieved_at"] == value["response_received_at"], "Accepted metadata differs from source receipt", "provenance", qid=qid)
                result = next(result for result in value["item_results"] if result["qid"] == qid)
                _require(result["outcome"] == "accepted" and result["returned_qid"] == qid and result["error"] is None, "Attempt did not accept the saved item", "provenance", qid=qid)
                _require(row["membership_at_retrieval"] == _membership(entity), "Membership differs from preserved evidence", "source_content", qid=qid)
                saved = loads(self.read(row["item"], qid, expected=f"items/{qid}.json"))
                _require(_same(saved, entity), "Extracted content differs from preserved source", "source_content", qid=qid)
        self.retry_history(attempts)
        _require(set(grouped) <= set(ids), "Unknown accepted source ID", "provenance")
        if attempts:
            dispatches = [a["dispatch_started_at"] for a in attempts if a["dispatch_started_at"] is not None]
            _require(not dispatches or manifest["started_at"] == dispatches[0], "Run start differs from first dispatch", "provenance")
        self.documentation(manifest)
        if manifest["verification_path"] is not None:
            _require(manifest["verification_path"] == "verification.json", "Unexpected verification path")
            self.path("verification.json")
            self.accounted["verification.json"] = "verification"
        if manifest["phase"] == "finalized":
            _require(manifest["verification_path"] == "verification.json" and manifest["collection_status"] == "passed", "Finalized run lacks passing report")
            report = loads(self.path("verification.json").read_bytes())
            _keys(report, {"format_version", "run_id", "checked_at", "inputs", "status", "checks", "counts", "findings"},
                  "verification report")
            _time(report["checked_at"])
            _require(not self.unfinished and report["format_version"] == "1.0.0"
                     and report["run_id"] == manifest["run_id"] and report["status"] == "passed"
                     and report["findings"] == []
                     and _same(report["inputs"], self.report["inputs"])
                     and _same(report["counts"], loads(dumps(counts))), "Finalized verification report disagrees")
            _require(isinstance(report["checks"], list) and len(report["checks"]) == len(CHECKS), "Incomplete verification checks")
            for name, check in zip(CHECKS, report["checks"]):
                _keys(check, {"check_id", "status", "findings"}, "verification check")
                _require(check == {"check_id": name, "status": "passed", "findings": []}, "Finalized check did not pass")
        actual = set()
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if relative.parts[0] == ".state":
                continue
            _require(not path.is_symlink(), "Symlink in collection payload", "files", path=str(relative))
            if path.is_dir():
                continue
            self.path(relative.as_posix())
            actual.add(relative.as_posix())
        _require(actual == set(self.accounted), "Unexpected or unaccounted public artifacts", "files")
        self.report["status"] = "failed" if self.report["findings"] else "not_checked" if self.unfinished else "passed"
        for check in self.report["checks"]:
            if not check["findings"]:
                check["status"] = "not_checked" if self.unfinished and check["check_id"] == "scope" else "passed"
        return self.report


def verify_collection(directory):
    """Return an audit report without reading SQLite, retrieving or changing data."""
    audit = Audit(directory)
    try:
        return audit.verify()
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ArithmeticError, StopIteration) as exc:
        category = exc.check if isinstance(exc, Invalid) else "files"
        audit.failure(category, exc.code if isinstance(exc, Invalid) else "unusable_evidence", str(exc),
                      qid=exc.qid if isinstance(exc, Invalid) else None,
                      path=exc.path if isinstance(exc, Invalid) else None)
        return audit.report

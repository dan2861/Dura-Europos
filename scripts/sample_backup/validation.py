"""Independent audit of saved originals, CSV files, and manifest; never imports projection."""
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import io
from pathlib import Path
import re
from urllib.parse import quote, urljoin

from . import jsoncodec as codec
from .schema import CHECK_IDS, ENDPOINT, HEADERS, ITEM_FIELDS, RUN_FIELDS, SCHEMA_VERSION, request_options

KEYS = {"items": ("qid",), "statements": ("statement_id",),
        "qualifiers": ("statement_id", "property_id", "snak_order"),
        "references": ("reference_id", "property_id", "snak_order"),
        "statement_references": ("statement_id", "reference_order")}
CATEGORIES = {"items": "item_data", "statements": "statements_qualifiers",
              "qualifiers": "statements_qualifiers", "references": "references",
              "statement_references": "references"}


def _text(value):
    return "" if value is None else str(value)


def _unsigned_integer(value):
    return (type(value) is int and value >= 0) or (
        isinstance(value, codec.Number) and re.fullmatch(r"0|[1-9][0-9]*", value.token) is not None)


def _display(snak):
    kind = snak.get("snaktype")
    if kind in ("somevalue", "novalue"):
        return "[unknown value]" if kind == "somevalue" else "[no value]"
    dv = snak.get("datavalue")
    if not isinstance(dv, dict) or "value" not in dv:
        return ""
    value, typ = dv["value"], dv.get("type")
    if typ == "string" and isinstance(value, str):
        return value
    if typ == "wikibase-entityid" and isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"]
    if (typ == "monolingualtext" and isinstance(value, dict) and set(value) == {"text", "language"}
            and isinstance(value["text"], str) and isinstance(value["language"], str)):
        return f'{value["text"]} [{value["language"]}]'
    if (typ == "time" and set(dv) == {"type", "value"} and isinstance(value, dict)
            and set(value) == {"time", "precision", "calendarmodel", "timezone", "before", "after"}
            and _text(value["precision"]) == "11"
            and all(_text(value[n]) == "0" for n in ("timezone", "before", "after"))
            and value["calendarmodel"] == "http://www.wikidata.org/entity/Q1985727"
            and isinstance(value["time"], str)
            and re.fullmatch(r"\+[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00Z", value["time"])):
        day = value["time"][1:11]
        try:
            date.fromisoformat(day)
            return f"{day} (day precision)"
        except ValueError:
            pass
    return codec.dumps(dv)


def _compact(text):
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in " \r\n\t":
            return False
    return True


def _crlf(body):
    state = "start"
    i = 0
    while i < len(body):
        b = body[i]
        if state == "quoted":
            if b == 34 and i + 1 < len(body) and body[i + 1] == 34:
                i += 2
                continue
            if b == 34:
                state = "closed"
            i += 1
            continue
        if state == "closed" and b not in (44, 13):
            return False
        if b == 34:
            if state != "start":
                return False
            state = "quoted"
        elif b == 44:
            state = "start"
        elif b in (10, 13):
            if body[i:i + 2] != b"\r\n":
                return False
            state = "start"
            i += 2
            continue
        else:
            state = "unquoted"
        i += 1
    return state == "start" and body.endswith(b"\r\n")


class Audit:
    def __init__(self, root, manifest, manual_evidence=None, *, write=False):
        self.root = Path(root)
        self.manifest = manifest
        self.checks = {c: {"check_id": c, "status": "passed", "details": []} for c in CHECK_IDS}
        self.checks["manual_review"]["status"] = "not_checked"
        self.tables = {t: [] for t in HEADERS}
        self.index = {t: defaultdict(list) for t in HEADERS}
        self.used = {t: set() for t in HEADERS}
        self.sources = {}
        self.group_ids = {}
        self.id_groups = {}
        self.coverage = Counter()
        self.manual_evidence = manual_evidence
        self.write = write
        previous = manifest.get("validation_summary")
        previous_checks = previous.get("checks", []) if isinstance(previous, dict) else []
        for old in previous_checks if isinstance(previous_checks, list) else []:
            if isinstance(old, dict) and old.get("check_id") in self.checks and isinstance(old.get("details"), list):
                for detail in old["details"]:
                    if (old["check_id"] == "manual_review" and self.manual_evidence is None
                            and isinstance(detail, dict) and "manual_evidence" in detail):
                        self.manual_evidence = detail["manual_evidence"]
                    if isinstance(detail, dict) and "run_note" in detail:
                        self.checks[old["check_id"]]["details"].append(detail)
                        if detail.get("failure"):
                            self.issue(old["check_id"], f"recorded run failure: {detail['run_note']}")

    def issue(self, check, reason, *, qid=None, path=None, pending=False):
        entry = self.checks[check]
        if not pending or entry["status"] != "failed":
            entry["status"] = "not_checked" if pending else "failed"
        entry["details"].append({"qid": qid, "path": path, "reason": reason})

    def path(self, relative):
        if not isinstance(relative, str):
            raise ValueError("artifact path is not a string")
        p = Path(relative)
        if p.is_absolute() or not p.parts or ".." in p.parts:
            raise ValueError("non-relative artifact path")
        candidate = self.root / p
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("artifact path escapes run")
        cursor = self.root
        for part in p.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError("artifact symlink")
        return candidate

    def fields(self, obj, required, allowed, check, qid, path):
        if not isinstance(obj, dict):
            self.issue(check, "expected source object", qid=qid, path=path)
            return False
        for key in set(obj) - set(allowed):
            self.issue(check, f"unrepresented field {key!r}", qid=qid, path=path + "/" + key)
        for key in required:
            if key not in obj or obj[key] is None:
                self.issue(check, f"missing/null required field {key}", qid=qid, path=path)
        return True

    def manifest_contract(self):
        m = self.manifest
        if set(m) != set(RUN_FIELDS) or m.get("schema_version") != SCHEMA_VERSION:
            self.issue("files", "manifest keys or schema version differ from contract")
        scope = m.get("scope", {})
        if (set(scope) != {"selection_method", "input_path", "requested_qids", "requested_count", "idea_criterion"}
                or scope.get("selection_method") != "explicit convenience sample"
                or not isinstance(scope.get("input_path"), str)
                or not _unsigned_integer(scope.get("requested_count"))
                or scope.get("idea_criterion") != "P5008 = Q114241199"):
            self.issue("files", "scope keys/selection/criterion differ from contract")
        method = m.get("retrieval_method", {})
        options = request_options()
        options["headers"]["User-Agent"] = "IDEA-sample-backup/" + str(method.get("exporter_version"))
        if (set(method) != {"endpoint_template", "http_method", "request_options", "exporter_version"}
                or method.get("endpoint_template") != ENDPOINT or method.get("http_method") != "GET"
                or not codec.equal(method.get("request_options"), options)):
            self.issue("files", "retrieval settings differ from recorded contract")
        for field in ("started_at", "finished_at"):
            value = m.get(field)
            if field == "finished_at" and value is None:
                continue
            try:
                timestamp = datetime.fromisoformat(value)
                if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
                    raise ValueError("not UTC")
            except (TypeError, ValueError, AttributeError):
                self.issue("files", f"invalid UTC {field}")
        try:
            started = datetime.fromisoformat(m["started_at"])
            if m.get("finished_at") is not None and datetime.fromisoformat(m["finished_at"]) < started:
                self.issue("files", "finish precedes start")
            if m.get("run_id") != self.root.name or not self.root.name.startswith(started.strftime("%Y%m%dT%H%M%S.%fZ-")):
                self.issue("files", "run-folder identity does not match UTC start/run_id")
        except (ValueError, TypeError, KeyError):
            self.issue("files", "unreadable run timing/identity")
        checks = m.get("validation_summary", {}).get("checks", [])
        if (not isinstance(checks, list) or len(checks) != 6
                or {c.get("check_id") for c in checks if isinstance(c, dict)} != set(CHECK_IDS)):
            self.issue("files", "exactly six validation entries required")
        elif any(set(c) != {"check_id", "status", "details"} or c["status"] not in
                 ("not_checked", "passed", "failed") for c in checks):
            self.issue("files", "invalid validation check fields/status")

    def files(self):
        for table, headers in HEADERS.items():
            relative = table + ".csv"
            try:
                body = self.path(relative).read_bytes()
                if body.startswith(b"\xef\xbb\xbf") or not _crlf(body):
                    self.issue("files", "BOM or invalid CSV record separators", path=relative)
                records = list(csv.reader(io.StringIO(body.decode("utf-8"), newline=""), strict=True))
                if not records or records[0] != list(headers):
                    raise ValueError("wrong ordered header")
                for record in records[1:]:
                    if len(record) != len(headers):
                        raise ValueError("wrong CSV field count")
                    row = dict(zip(headers, record))
                    self.tables[table].append(row)
                    key = tuple(row[k] for k in KEYS[table])
                    self.index[table][key].append(row)
                    for field, value in row.items():
                        if field.endswith("_json"):
                            codec.loads(value)
                            if not _compact(value):
                                raise ValueError("noncompact JSON cell")
                for key, rows in self.index[table].items():
                    if len(rows) != 1:
                        self.issue(CATEGORIES[table], f"duplicate table key {key!r}", path=relative)
            except (OSError, ValueError, UnicodeError, csv.Error) as exc:
                self.issue("files", f"unreadable/invalid required CSV: {exc}", path=relative)
        inventory = self.manifest.get("outputs", [])
        paths = []
        if not isinstance(inventory, list):
            self.issue("files", "outputs is not a list")
            inventory = []
        for output in inventory:
            try:
                if set(output) != {"path", "size_bytes", "sha256", "row_count"}:
                    raise ValueError("wrong inventory fields")
                relative = output["path"]
                if relative == "manifest.json":
                    raise ValueError("manifest must not inventory itself")
                if relative in paths:
                    raise ValueError("duplicate inventory path")
                paths.append(relative)
                body = self.path(relative).read_bytes()
                if (not _unsigned_integer(output["size_bytes"]) or str(output["size_bytes"]) != str(len(body))
                        or output["sha256"] != hashlib.sha256(body).hexdigest()):
                    raise ValueError("size/checksum mismatch")
                if relative in {t + ".csv" for t in HEADERS}:
                    count = len(list(csv.reader(io.StringIO(body.decode("utf-8"), newline="")))) - 1
                    if not _unsigned_integer(output["row_count"]) or str(output["row_count"]) != str(count):
                        raise ValueError("CSV record count mismatch")
                elif output["row_count"] is not None:
                    raise ValueError("non-CSV row_count must be null")
            except (OSError, TypeError, ValueError, UnicodeError, csv.Error) as exc:
                self.issue("files", f"invalid output inventory: {exc}", path=output.get("path") if isinstance(output, dict) else None)
        required = {t + ".csv" for t in HEADERS}
        disk = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file() or p.is_symlink()}
        disk.discard("manifest.json")
        for missing in required - set(paths):
            self.issue("files", "required file absent from inventory", path=missing)
        for path in disk ^ set(paths):
            self.issue("files", "disk/inventory disagreement (including staging/orphan files)", path=path)

    def requests(self):
        scope = self.manifest.get("scope", {})
        qids = scope.get("requested_qids", [])
        entries = self.manifest.get("items", [])
        if (not isinstance(qids, list) or any(not isinstance(q, str) or not re.fullmatch(r"Q[1-9][0-9]*", q) for q in qids)
                or len(qids) != len(set(qids)) or str(scope.get("requested_count")) != str(len(qids))):
            self.issue("request_coverage", "invalid ordered scope/count")
        if not isinstance(entries, list) or [e.get("requested_qid") for e in entries] != qids:
            self.issue("request_coverage", "one exact ordered entry required for each request")
        returned = Counter()
        for entry in entries:
            qid = entry.get("requested_qid")
            if set(entry) != set(ITEM_FIELDS):
                self.issue("files", "wrong per-request keys", qid=qid)
            status = entry.get("retrieval_status")
            if status not in ("pending", "succeeded", "failed") or entry.get("validation_status") not in ("not_checked", "passed", "failed"):
                self.issue("files", "invalid per-request status", qid=qid)
            if status == "succeeded" and entry.get("retrieved_at") is None:
                self.issue("request_coverage", "success lacks actual retrieval time", qid=qid)
            if entry.get("retrieved_at") is not None:
                try:
                    timestamp = datetime.fromisoformat(entry["retrieved_at"])
                    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
                        raise ValueError("not UTC")
                except (ValueError, TypeError, AttributeError):
                    self.issue("request_coverage", "retrieval time is not UTC", qid=qid)
            if entry.get("source_url") != ENDPOINT.format(qid=qid):
                self.issue("request_coverage", "original request URL differs", qid=qid)
            trace = entry.get("http_trace")
            if not isinstance(trace, list):
                self.issue("request_coverage", "http_trace is not a list", qid=qid)
                trace = []
            for i, step in enumerate(trace):
                if (not isinstance(step, dict) or set(step) != {"url", "status_code", "location"}
                        or not isinstance(step.get("url"), str)
                        or not _unsigned_integer(step.get("status_code"))
                        or not re.fullmatch(r"[1-5][0-9]{2}", str(step.get("status_code")))
                        or (step.get("location") is not None and not isinstance(step["location"], str))):
                    self.issue("request_coverage", "malformed received HTTP trace", qid=qid)
                    continue
                if i == 0 and step["url"] != entry.get("source_url"):
                    self.issue("request_coverage", "trace does not start at requested URL", qid=qid)
                if i and (str(trace[i - 1].get("status_code")) not in ("301", "302", "303", "307", "308")
                          or urljoin(trace[i - 1]["url"], trace[i - 1].get("location") or "") != step["url"]):
                    self.issue("request_coverage", "trace forwarding chain differs", qid=qid)
            if len(trace) > 6:
                self.issue("request_coverage", "trace exceeds redirect limit", qid=qid)
            error = entry.get("error")
            if error is not None:
                if (not isinstance(error, dict) or set(error) != {"stage", "message", "body_path", "body_complete"}
                        or error.get("stage") not in ("retrieval", "saving", "validation")
                        or not isinstance(error.get("message"), str)):
                    self.issue("files", "malformed failure details", qid=qid)
                elif error.get("body_path") is not None:
                    try:
                        if error["body_path"] != f"failures/{qid}.body":
                            raise ValueError("failure path not requested filename")
                        body = self.path(error["body_path"]).read_bytes()
                        if not body or error["body_complete"] not in (True, False, None):
                            raise ValueError("invalid saved failure body/completeness")
                    except (OSError, ValueError) as exc:
                        self.issue("files", str(exc), qid=qid)
                elif error.get("body_complete") is not None:
                    self.issue("files", "body completeness claimed without saved body", qid=qid)
            if status == "failed" and error is None:
                self.issue("request_coverage", "retrieval failure lacks error", qid=qid)
            if status == "pending":
                self.issue("request_coverage", "request is pending", qid=qid, pending=True)
            source_path = entry.get("source_json")
            if source_path is None:
                if status == "succeeded":
                    self.issue("request_coverage", "successful retrieval lacks original", qid=qid)
                continue
            try:
                if source_path != f"original/{qid}.json":
                    raise ValueError("original path not exact requested QID")
                envelope = codec.loads(self.path(source_path).read_bytes())
                entities = envelope.get("entities") if isinstance(envelope, dict) else None
                if not isinstance(entities, dict) or len(entities) != 1:
                    raise ValueError("original lacks single entity")
                source = next(iter(entities.values()))
                if (not isinstance(source, dict) or source.get("type") != "item" or "missing" in source
                        or not isinstance(source.get("id"), str) or not re.fullmatch(r"Q[1-9][0-9]*", source["id"])):
                    raise ValueError("original is not a usable item")
                for field, key in (("returned_qid", "id"), ("lastrevid", "lastrevid"), ("modified", "modified")):
                    if not codec.equal(entry.get(field), source.get(key)):
                        self.issue("request_coverage", f"original {key} differs from manifest", qid=qid, path=source_path)
                if status != "succeeded":
                    self.issue("request_coverage", "saved entity without successful outcome", qid=qid)
                if status == "succeeded" and (not trace or not str(trace[-1].get("status_code", "")).startswith("2")):
                    self.issue("request_coverage", "success lacks final successful HTTP response", qid=qid)
                self.sources[qid] = source
                returned[source.get("id")] += 1
                tags = source.get("claims", {}).get("P5008", []) if isinstance(source.get("claims"), dict) else []
                tag_ranks = []
                for s in tags if isinstance(tags, list) else []:
                    main = s.get("mainsnak") if isinstance(s, dict) else None
                    dv = main.get("datavalue") if isinstance(main, dict) else None
                    value = dv.get("value") if isinstance(dv, dict) else None
                    if isinstance(value, dict) and value.get("id") == "Q114241199":
                        tag_ranks.append(s.get("rank"))
                if not any(rank in ("normal", "preferred") for rank in tag_ranks):
                    self.issue("request_coverage", f"IDEA membership absent/ambiguous; matching ranks={tag_ranks}", qid=qid, pending=True)
            except (OSError, ValueError, UnicodeError, TypeError, AttributeError) as exc:
                self.issue("request_coverage", f"unusable original: {exc}", qid=qid, path=source_path)
                self.issue("files", f"unusable original: {exc}", qid=qid, path=source_path)
        associated = {e.get("source_json") for e in entries if e.get("source_json")}
        associated.update(e["error"]["body_path"] for e in entries
                          if isinstance(e.get("error"), dict) and e["error"].get("body_path"))
        for path in list((self.root / "original").glob("*.json")) + list((self.root / "failures").glob("*.body")):
            relative = path.relative_to(self.root).as_posix()
            if relative not in associated:
                self.issue("request_coverage", "saved evidence has no request association", path=relative)
        for qid, source in self.sources.items():
            if qid != source.get("id") or returned[source.get("id")] > 1:
                for check in ("request_coverage", "item_data", "statements_qualifiers", "references"):
                    self.issue(check, "identity/collision review required; rows withheld", qid=qid, pending=True)
                continue
            try:
                self.entity(qid, source)
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                self.issue("statements_qualifiers", f"malformed source structure: {exc}", qid=qid,
                           path=f"/entities/{qid}")

    def take(self, table, key, qid, path):
        rows = self.index[table].get(tuple(str(k) for k in key), [])
        if len(rows) != 1:
            self.issue(CATEGORIES[table], f"expected exactly one row for {key!r}, found {len(rows)}", qid=qid, path=path)
            return None
        self.used[table].add(tuple(str(k) for k in key))
        return rows[0]

    def compare(self, row, values, check, qid, path):
        if row is None:
            return
        for key, expected in values.items():
            if row.get(key) != _text(expected):
                self.issue(check, f"{key}: expected {_text(expected)!r}, got {row.get(key)!r}", qid=qid, path=path)

    def snak(self, original, row, pid, check, qid, path):
        if not self.fields(original, ("property", "snaktype"),
                           ("property", "snaktype", "datatype", "hash", "datavalue"), check, qid, path):
            return
        if original.get("property") != pid:
            self.issue(check, "snak property differs from containing property", qid=qid, path=path)
        for name in ("datatype", "hash"):
            if name in original and (not isinstance(original[name], str) or not original[name]):
                self.issue(check, f"unexpected optional {name} presence/type", qid=qid, path=path)
        kind = original.get("snaktype")
        if kind not in ("value", "somevalue", "novalue"):
            self.issue(check, "unknown snaktype", qid=qid, path=path)
        dv = original.get("datavalue")
        if kind == "value":
            if not isinstance(dv, dict) or "value" not in dv or "type" not in dv:
                self.issue(check, "missing/malformed datavalue", qid=qid, path=path)
            elif ((dv["type"] == "string" and not isinstance(dv["value"], str))
                    or (dv["type"] in ("time", "quantity", "globecoordinate", "wikibase-entityid", "monolingualtext")
                        and not isinstance(dv["value"], dict))):
                self.issue(check, "malformed typed datavalue", qid=qid, path=path)
        elif "datavalue" in original:
            self.issue(check, "unexpected special datavalue presence", qid=qid, path=path)
        if row is not None:
            try:
                if not codec.equal(codec.loads(row["datavalue_json"]), dv):
                    self.issue(check, "complete typed datavalue differs", qid=qid, path=path)
            except ValueError as exc:
                self.issue(check, str(exc), qid=qid, path=path)
            self.compare(row, {"snak_hash": original.get("hash"), "snaktype": kind,
                               "datatype": original.get("datatype"), "value_text": _display(original)}, check, qid, path)
        self.coverage["json_fallback" if dv is not None and _display(original) == codec.dumps(dv) else str(kind)] += 1

    def ordered(self, group, order, check, qid, path):
        if not isinstance(group, dict) or not group:
            self.issue(check, "empty/malformed source group", qid=qid, path=path)
            return
        if (not isinstance(order, list) or any(not isinstance(p, str) for p in order)
                or len(set(order)) != len(order) or set(order) != set(group)):
            self.issue(check, "missing/inconsistent recorded property order", qid=qid, path=path)
            return
        for po, pid in enumerate(order, 1):
            if not isinstance(group[pid], list) or not group[pid]:
                self.issue(check, "empty/malformed property list", qid=qid, path=path + "/" + pid)
                continue
            for so, snak in enumerate(group[pid], 1):
                yield po, pid, so, snak, path + f"/{pid}/{so - 1}"

    def entity(self, qid, source):
        path = f"/entities/{qid}"
        self.fields(source, ("id", "lastrevid", "modified", "claims"),
                    ("id", "lastrevid", "modified", "claims", "labels", "descriptions", "aliases", "sitelinks",
                     "type", "pageid", "ns", "title"), "item_data", qid, path)
        row = self.take("items", (qid,), qid, path)
        self.compare(row, {"qid": qid, "lastrevid": source.get("lastrevid"), "modified": source.get("modified")}, "item_data", qid, path)
        for name in ("labels", "descriptions", "aliases", "sitelinks"):
            value = source.get(name)
            if name in source and not isinstance(value, dict):
                self.issue("item_data", f"malformed {name} map", qid=qid, path=path + "/" + name)
            if row is not None:
                try:
                    if not codec.equal(codec.loads(row[name + "_json"]), value):
                        self.issue("item_data", f"complete {name} map differs", qid=qid, path=path + "/" + name)
                except ValueError as exc:
                    self.issue("item_data", str(exc), qid=qid, path=path)
            if name in ("labels", "descriptions"):
                en = value.get("en", {}) if isinstance(value, dict) else {}
                text = en.get("value", "") if isinstance(en, dict) else ""
                self.compare(row, {"label_en" if name == "labels" else "description_en": text}, "item_data", qid, path)
        claims = source.get("claims")
        if not isinstance(claims, dict):
            self.issue("statements_qualifiers", "malformed claims", qid=qid, path=path + "/claims")
            return
        for pid, statements in claims.items():
            if not isinstance(statements, list) or not statements:
                self.issue("statements_qualifiers", "empty/malformed statement list", qid=qid, path=path + "/claims/" + pid)
                continue
            for pos, statement in enumerate(statements, 1):
                p = path + f"/claims/{pid}/{pos - 1}"
                self.statement(qid, pid, pos, statement, p)

    def statement(self, qid, pid, pos, s, path):
        check = "statements_qualifiers"
        if not self.fields(s, ("id", "type", "rank", "mainsnak"),
                           ("id", "type", "rank", "mainsnak", "qualifiers", "qualifiers-order", "references"), check, qid, path):
            return
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            self.issue(check, "missing statement identity", qid=qid, path=path)
            return
        row = self.take("statements", (sid,), qid, path)
        self.compare(row, {"qid": qid, "statement_id": sid, "property_id": pid,
                           "statement_order": pos, "rank": s.get("rank"), "statement_type": s.get("type")}, check, qid, path)
        if s.get("rank") not in ("normal", "preferred", "deprecated"):
            self.issue(check, "invalid source rank", qid=qid, path=path)
        self.snak(s.get("mainsnak"), row, pid, check, qid, path + "/mainsnak")
        main = s.get("mainsnak", {})
        media = ""
        if isinstance(main, dict) and main.get("datatype") == "commonsMedia" and main.get("snaktype") == "value":
            value = main.get("datavalue", {}).get("value")
            if isinstance(value, str):
                media = "https://commons.wikimedia.org/wiki/File:" + quote(value.replace(" ", "_"), safe=":,_-~.")
        self.compare(row, {"commons_file_url": media}, check, qid, path)
        if "qualifiers" in s or "qualifiers-order" in s:
            for po, qp, so, qualifier, qp_path in self.ordered(s.get("qualifiers"), s.get("qualifiers-order"), check, qid, path + "/qualifiers"):
                qr = self.take("qualifiers", (sid, qp, so), qid, qp_path)
                self.compare(qr, {"qid": qid, "statement_id": sid, "property_id": qp,
                                  "property_order": po, "snak_order": so}, check, qid, qp_path)
                self.snak(qualifier, qr, qp, check, qid, qp_path)
        if "references" not in s:
            return
        if not isinstance(s["references"], list):
            self.issue("references", "malformed reference list", qid=qid, path=path + "/references")
            return
        for ro, group in enumerate(s["references"], 1):
            p = path + f"/references/{ro - 1}"
            if not self.fields(group, ("snaks", "snaks-order"), ("hash", "snaks", "snaks-order"), "references", qid, p):
                continue
            if "hash" in group and (not isinstance(group["hash"], str) or not group["hash"]):
                self.issue("references", "unexpected source reference-hash presence/type", qid=qid, path=p + "/hash")
            link = self.take("statement_references", (sid, ro), qid, p)
            self.compare(link, {"qid": qid, "statement_id": sid, "reference_order": ro,
                                "source_reference_hash": group.get("hash")}, "references", qid, p)
            if link is None:
                continue
            rid = link["reference_id"]
            complete = codec.dumps(group, sort_keys=True)
            if complete in self.group_ids and self.group_ids[complete] != rid:
                self.issue("references", "identical complete groups redundantly split", qid=qid, path=p)
            if rid in self.id_groups and self.id_groups[rid] != complete:
                self.issue("references", "distinct complete groups merged", qid=qid, path=p)
            self.group_ids[complete] = rid
            self.id_groups[rid] = complete
            for po, rp, so, ref, rp_path in self.ordered(group.get("snaks"), group.get("snaks-order"), "references", qid, p + "/snaks"):
                rr = self.take("references", (rid, rp, so), qid, rp_path)
                self.compare(rr, {"reference_id": rid, "property_id": rp, "property_order": po,
                                  "snak_order": so}, "references", qid, rp_path)
                self.snak(ref, rr, rp, "references", qid, rp_path)

    def run(self):
        self.manifest_contract()
        self.files()
        self.requests()
        for table in HEADERS:
            for key in set(self.index[table]) - self.used[table]:
                self.issue(CATEGORIES[table], f"extra/orphan row key {key!r}", path=table + ".csv")
        if self.manifest.get("finished_at") is None:
            self.issue("files", "attempt has no recorded finish; interrupted/in progress", pending=True)
        self.checks["statements_qualifiers"]["details"].append({"renderer_coverage": dict(self.coverage)})
        completed = set()
        for check in CHECK_IDS:
            if check != "manual_review":
                completed.add(check)
                self.persist_progress(completed)
        self.manual()
        failed = any(c["status"] == "failed" for c in self.checks.values()) or any(
            e.get("retrieval_status") == "failed" for e in self.manifest.get("items", []))
        passed = all(c["status"] == "passed" for c in self.checks.values()) and all(
            e.get("retrieval_status") == "succeeded" for e in self.manifest.get("items", []))
        status = "failed" if failed else "passed" if passed else "not_checked"
        report = {"status": status, "checks": list(self.checks.values())}
        for entry in self.manifest.get("items", []):
            self.item_status(entry)
        self.manifest["validation_summary"] = report
        return report

    def persist_progress(self, completed):
        if not self.write:
            return
        from .storage import RunStore
        progress = dict(self.manifest)
        checks = []
        for check_id, result in self.checks.items():
            check = dict(result)
            if check_id not in completed:
                check["status"] = "not_checked"
            if check_id == "manual_review" and self.manual_evidence is not None:
                check["details"] = [{"manual_evidence": self.manual_evidence}]
            checks.append(check)
        failed = any(c["status"] == "failed" for c in self.checks.values()) or any(
            e.get("retrieval_status") == "failed" for e in self.manifest.get("items", []))
        progress["validation_summary"] = {"status": "failed" if failed else "not_checked", "checks": checks}
        RunStore(self.root, progress)._write("manifest.json", (codec.dumps(progress) + "\n").encode(), replace=True)

    def item_status(self, entry):
        qid = entry.get("requested_qid")
        def applies(check):
            return any(isinstance(d, dict) and "reason" in d and d.get("qid") in (None, qid)
                       for d in check["details"])
        failed = entry.get("retrieval_status") == "failed" or any(
            c["status"] == "failed" and applies(c) for c in self.checks.values())
        pending = entry.get("retrieval_status") != "succeeded" or any(
            c["status"] == "not_checked" and (c["check_id"] == "manual_review" or applies(c))
            for c in self.checks.values())
        entry["validation_status"] = "failed" if failed else "not_checked" if pending else "passed"
        if failed and entry.get("error") is None:
            reasons = [d for c in self.checks.values() if c["status"] == "failed"
                       for d in c["details"] if isinstance(d, dict) and "reason" in d and d.get("qid") in (None, qid)]
            entry["error"] = {"stage": "validation", "message": str(reasons[:3]),
                              "body_path": None, "body_complete": None}
        elif not failed and isinstance(entry.get("error"), dict) and entry["error"].get("stage") == "validation":
            entry["error"] = None

    def signature(self, source):
        """Structural contrast excludes entity IDs, text contents, and ordinary values."""
        claims = {}
        for prop, statements in source.get("claims", {}).items():
            claims[prop] = [{"rank": s.get("rank"), "snaktype": s.get("mainsnak", {}).get("snaktype"),
                             "datatype": s.get("mainsnak", {}).get("datatype"),
                             "qualifiers": {p: len(v) for p, v in s.get("qualifiers", {}).items()},
                             "references": [{p: len(v) for p, v in r.get("snaks", {}).items()}
                                            for r in s.get("references", [])]} for s in statements]
        texts = {name: {lang: len(v) if isinstance(v, list) else 1 for lang, v in source.get(name, {}).items()}
                 for name in ("labels", "descriptions", "aliases", "sitelinks")}
        return codec.dumps({"claims": claims, "texts": texts}, sort_keys=True)

    def manual(self):
        evidence = self.manual_evidence
        if evidence is None:
            for old in self.manifest.get("validation_summary", {}).get("checks", []):
                if old.get("check_id") == "manual_review" and isinstance(old.get("details"), list):
                    evidence = next((d["manual_evidence"] for d in old["details"]
                                     if isinstance(d, dict) and "manual_evidence" in d), None)
        if not isinstance(evidence, dict):
            self.issue("manual_review", "two-item manual review has not been recorded", pending=True)
            return
        self.checks["manual_review"]["details"].append({"manual_evidence": evidence})
        if evidence.get("status") == "failed" or evidence.get("findings"):
            self.issue("manual_review", "recorded manual review has unresolved findings")
            return
        try:
            reviews = evidence.get("items", [])
            if (evidence.get("status") != "passed" or evidence.get("findings") != []
                    or not evidence.get("reviewer") or not evidence.get("contrast")
                    or not isinstance(evidence.get("reviewed_at"), str)
                    or len(reviews) != 2 or len({r["qid"] for r in reviews}) != 2):
                raise ValueError("incomplete reviewer/date/contrast or two-item selections")
            date.fromisoformat(evidence["reviewed_at"][:10])
            signatures = []
            for review in reviews:
                qid = review["qid"]
                source = self.sources[qid]
                if source.get("id") != qid:
                    raise ValueError("identity review unresolved")
                if not codec.equal(source.get("lastrevid"), review.get("lastrevid")):
                    raise ValueError("reviewed revision differs")
                body = self.path(f"original/{qid}.json").read_bytes()
                if hashlib.sha256(body).hexdigest() != review.get("source_sha256"):
                    raise ValueError("review does not identify the saved source bytes")
                comparisons = review.get("comparisons", {})
                if any(not isinstance(comparisons.get(table), str) or not comparisons[table].strip() for table in HEADERS):
                    raise ValueError("comparison evidence required for all five table roles")
                signatures.append(self.signature(source))
            if signatures[0] == signatures[1]:
                raise ValueError("selected saved items show no structural contrast")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.issue("manual_review", f"review unfinished: {exc}", pending=True)
            return
        self.checks["manual_review"]["status"] = "passed"


def verify(root, *, write=False, manual_evidence=None):
    root = Path(root)
    try:
        if (root / "manifest.json").is_symlink():
            raise ValueError("manifest must be a regular artifact, not a symlink")
        manifest = codec.loads((root / "manifest.json").read_bytes())
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not an object")
    except (OSError, ValueError, UnicodeError) as exc:
        return {"status": "failed", "checks": [
            {"check_id": c, "status": "failed" if c == "files" else "not_checked",
             "details": str(exc) if c == "files" else None} for c in CHECK_IDS]}
    audit = Audit(root, manifest, manual_evidence, write=write)
    try:
        report = audit.run()
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        audit.issue("files", f"malformed manifest/source structure: {type(exc).__name__}: {exc}")
        for check in audit.checks.values():
            if check["status"] != "failed":
                check["status"] = "not_checked"
        # Do not rewrite a malformed manifest into a superficially repaired one.
        return {"status": "failed", "checks": list(audit.checks.values())}
    if write:
        from .storage import RunStore
        # Preserve original inventory for future comparisons; never refresh hashes here.
        RunStore(root, manifest)._write("manifest.json", (codec.dumps(manifest) + "\n").encode(), replace=True)
    return report

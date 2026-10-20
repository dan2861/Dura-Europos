"""Offline source-to-table mapping."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
import hashlib
import re
from urllib.parse import quote

from . import jsoncodec as codec
from .schema import HEADERS


def cell(value):
    return "" if value is None else str(value)


def pointer(*parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def commons_url(filename):
    return "https://commons.wikimedia.org/wiki/File:" + quote(filename.replace(" ", "_"), safe=":,_-~.")


def group_digest(group):
    return hashlib.sha256(codec.dumps(group, sort_keys=True).encode("utf-8")).hexdigest()


def render(dv):
    value = dv["value"]
    if dv.get("type") == "string" and isinstance(value, str):
        return value, "string"
    if dv.get("type") == "wikibase-entityid" and isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"], "linked_id"
    if (dv.get("type") == "monolingualtext" and isinstance(value, dict)
            and set(value) == {"text", "language"}
            and all(isinstance(value[k], str) for k in ("text", "language"))):
        return value["text"] + " [" + value["language"] + "]", "monolingualtext"
    if (set(dv) == {"value", "type"} and dv["type"] == "time" and isinstance(value, dict)
            and set(value) == {"time", "timezone", "before", "after", "precision", "calendarmodel"}
            and str(value["precision"]) == "11"
            and all(str(value[k]) == "0" for k in ("timezone", "before", "after"))
            and value["calendarmodel"] == "http://www.wikidata.org/entity/Q1985727"
            and isinstance(value["time"], str)
            and re.fullmatch(r"\+[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00Z", value["time"])):
        day = value["time"][1:11]
        try:
            date.fromisoformat(day)
            return day + " (day precision)", "day_precision"
        except ValueError:
            pass
    return codec.dumps(dv), "json_fallback"


@dataclass
class Projection:
    tables: dict = field(default_factory=lambda: {t: [] for t in HEADERS})
    findings: list = field(default_factory=list)
    coverage: Counter = field(default_factory=Counter)
    groups: list = field(default_factory=list)


class Projector:
    def __init__(self):
        self.result = Projection()
        self.qid = None
        self.reference_index = {}
        self.statement_ids = {}
        self.item_ids = set()

    def finding(self, check, path, reason):
        self.result.findings.append({"check_id": check, "qid": self.qid,
                                     "path": path, "reason": reason})

    def fields(self, obj, required, allowed, check, path):
        if not isinstance(obj, dict):
            self.finding(check, path, "expected object")
            return False
        for key in sorted(set(obj) - set(allowed)):
            self.finding(check, path + pointer(key), "unrepresented field")
        for key in required:
            if key not in obj or obj[key] is None:
                self.finding(check, path + pointer(key), "missing/null required field")
        return True

    def row(self, table, **values):
        return {key: cell(values.get(key)) for key in HEADERS[table]}

    def snak(self, source, prop, check, path):
        if not self.fields(source, ("property", "snaktype"),
                           ("property", "snaktype", "datatype", "datavalue", "hash"), check, path):
            return None
        if source.get("property") != prop:
            self.finding(check, path + "/property", "property differs from containing key")
        for name in ("datatype", "hash"):
            if name in source and (not isinstance(source[name], str) or not source[name]):
                self.finding(check, path + pointer(name), "unexpected optional-field type/empty value")
        kind = source.get("snaktype")
        dv = source.get("datavalue")
        if kind == "value" and (not isinstance(dv, dict) or "value" not in dv or "type" not in dv):
            self.finding(check, path + "/datavalue", "missing/malformed value datavalue")
            return None
        if kind != "value":
            if kind not in ("somevalue", "novalue"):
                self.finding(check, path + "/snaktype", "unsupported snaktype")
                return None
            if "datavalue" in source:
                self.finding(check, path + "/datavalue", "unexpected datavalue on special snak")
            self.result.coverage[kind] += 1
            return {"snak_hash": source.get("hash", ""), "snaktype": kind,
                    "datatype": source.get("datatype", ""),
                    "value_text": "[unknown value]" if kind == "somevalue" else "[no value]",
                    "datavalue_json": "null"}
        value = dv["value"]
        if ((dv.get("type") == "string" and not isinstance(value, str))
                or (dv.get("type") in ("time", "monolingualtext", "wikibase-entityid", "quantity", "globecoordinate")
                    and not isinstance(value, dict))):
            self.finding(check, path + "/datavalue/value", "invalid value type for datavalue")
        try:
            text, renderer = render(dv)
            serialized = codec.dumps(dv)
        except ValueError as exc:
            self.finding(check, path + "/datavalue", f"cannot serialize complete value: {exc}")
            return None
        self.result.coverage[renderer] += 1
        return {"snak_hash": source.get("hash", ""), "snaktype": kind,
                "datatype": source.get("datatype", ""), "value_text": text,
                "datavalue_json": serialized}

    def entity(self, source):
        self.qid = source.get("id")
        path = pointer("entities", self.qid)
        if self.qid in self.item_ids:
            self.finding("item_data", path, "duplicate item identity")
        self.item_ids.add(self.qid)
        self.fields(source, ("id", "lastrevid", "modified", "claims"),
                    ("id", "type", "pageid", "ns", "title", "lastrevid", "modified",
                     "labels", "descriptions", "aliases", "sitelinks", "claims"), "item_data", path)
        values = {"qid": self.qid, "lastrevid": source.get("lastrevid"), "modified": source.get("modified")}
        for name in ("labels", "descriptions", "aliases", "sitelinks"):
            obj = source.get(name)
            if name in source and not isinstance(obj, dict):
                self.finding("item_data", path + pointer(name), "expected map, including when empty")
            values[name + "_json"] = codec.dumps(obj)
        for name, target in (("labels", "label_en"), ("descriptions", "description_en")):
            text_map = source.get(name)
            english = text_map.get("en", {}) if isinstance(text_map, dict) else {}
            values[target] = english.get("value", "") if isinstance(english, dict) else ""
            if not isinstance(values[target], str):
                self.finding("item_data", path + pointer(name, "en"), "invalid English convenience text")
                values[target] = ""
        self.result.tables["items"].append(self.row("items", **values))
        claims = source.get("claims")
        if not isinstance(claims, dict):
            self.finding("statements_qualifiers", path + "/claims", "expected claims object")
            return
        for prop, statements in claims.items():
            if not isinstance(statements, list) or not statements:
                self.finding("statements_qualifiers", path + pointer("claims", prop), "empty/malformed statement list")
                continue
            for order, statement in enumerate(statements, 1):
                self.statement(statement, prop, order, path + pointer("claims", prop, order - 1))

    def statement(self, source, prop, order, path):
        check = "statements_qualifiers"
        if not self.fields(source, ("id", "type", "rank", "mainsnak"),
                           ("id", "type", "rank", "mainsnak", "qualifiers", "qualifiers-order", "references"),
                           check, path):
            return
        sid = source.get("id")
        if not isinstance(sid, str) or not sid:
            self.finding(check, path + "/id", "required statement identity unavailable")
            return
        if sid in self.statement_ids:
            self.finding(check, path + "/id", "duplicate statement identity")
        self.statement_ids[sid] = path
        if source.get("rank") not in ("normal", "preferred", "deprecated"):
            self.finding(check, path + "/rank", "invalid rank")
        main = self.snak(source.get("mainsnak"), prop, check, path + "/mainsnak")
        if main:
            media = ""
            if (source["mainsnak"].get("datatype") == "commonsMedia"
                    and main["snaktype"] == "value"
                    and isinstance(source["mainsnak"]["datavalue"].get("value"), str)):
                media = commons_url(source["mainsnak"]["datavalue"]["value"])
            self.result.tables["statements"].append(self.row(
                "statements", qid=self.qid, statement_id=sid, property_id=prop,
                statement_order=order, statement_type=source.get("type"), rank=source.get("rank"),
                commons_file_url=media, **main))
        if "qualifiers" in source or "qualifiers-order" in source:
            for pid, po, so, snak, snak_path in self.ordered_snaks(
                source.get("qualifiers"), source.get("qualifiers-order"), check, path + "/qualifiers"
            ):
                values = self.snak(snak, pid, check, snak_path)
                if values:
                    self.result.tables["qualifiers"].append(self.row(
                        "qualifiers", qid=self.qid, statement_id=sid, property_id=pid,
                        property_order=po, snak_order=so, **values))
        if "references" in source:
            references = source["references"]
            if not isinstance(references, list):
                self.finding("references", path + "/references", "expected reference list")
            else:
                for ro, group in enumerate(references, 1):
                    self.reference(group, sid, ro, path + pointer("references", ro - 1))

    def reference(self, group, sid, ro, path):
        check = "references"
        if not isinstance(group, dict):
            self.finding(check, path, "expected complete reference object")
            return
        try:
            digest = group_digest(group)
        except ValueError as exc:
            self.finding(check, path, f"cannot compare complete reference group: {exc}")
            return
        match = next((i for i in self.reference_index.get(digest, [])
                      if codec.equal(self.result.groups[i], group)), None)
        if match is None:
            match = len(self.result.groups)
            self.result.groups.append(group)
            self.reference_index.setdefault(digest, []).append(match)
            self.fields(group, ("snaks", "snaks-order"), ("hash", "snaks", "snaks-order"), check, path)
            for pid, po, so, snak, snak_path in self.ordered_snaks(
                group.get("snaks"), group.get("snaks-order"), check, path + "/snaks"
            ):
                values = self.snak(snak, pid, check, snak_path)
                if values:
                    self.result.tables["references"].append(self.row(
                        "references", reference_id=f"R{match + 1:06d}", property_id=pid,
                        property_order=po, snak_order=so, **values))
        if "hash" in group and (not isinstance(group["hash"], str) or not group["hash"]):
            self.finding(check, path + "/hash", "unexpected reference hash presence/type")
        # Report extra fields on every attachment, even when a shared group was seen earlier.
        if set(group) - {"hash", "snaks", "snaks-order"}:
            self.finding(check, path, "reference contains unrepresented extra fields")
        self.result.tables["statement_references"].append(self.row(
            "statement_references", qid=self.qid, statement_id=sid, reference_id=f"R{match + 1:06d}",
            reference_order=ro, source_reference_hash=group.get("hash", "")))

    def ordered_snaks(self, group, order, check, path):
        if not isinstance(group, dict) or not group:
            self.finding(check, path, "empty/malformed snak group")
            return
        if (not isinstance(order, list) or any(not isinstance(p, str) for p in order)
                or len(order) != len(set(order)) or set(order) != set(group)):
            self.finding(check, path, "missing/inconsistent property-order list; no order invented")
            return
        for po, pid in enumerate(order, 1):
            snaks = group[pid]
            if not isinstance(snaks, list) or not snaks:
                self.finding(check, path + pointer(pid), "empty/malformed snak list")
                continue
            for so, snak in enumerate(snaks, 1):
                yield pid, po, so, snak, path + pointer(pid, so - 1)


def project(entities):
    projector = Projector()
    for source in entities:
        projector.entity(source)
    return projector.result

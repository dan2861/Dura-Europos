"""Synthetic inputs unless explicitly named saved-real-response regression."""
import copy
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import csv
import io

from scripts.sample_backup import jsoncodec as codec, transform


def snak(prop="P217", value="1930'619c~01", datatype="string"):
    return {"property": prop, "snaktype": "value", "datatype": datatype,
            "datavalue": {"value": value, "type": "string"}}


def statement(sid="Q42$Mixed-Case", main=None, **extra):
    return {"id": sid, "type": "statement", "rank": "normal",
            "mainsnak": main or snak(), **extra}


def entity(qid="Q42", claims=None):
    return {"id": qid, "type": "item", "lastrevid": 123, "modified": "2026-01-01T00:00:00Z",
            "labels": {"en": {"language": "en", "value": "Photo"},
                       "ar": {"language": "ar", "value": "صورة"}},
            "descriptions": {"fr": {"language": "fr", "value": "document"}},
            "aliases": {"en": [{"language": "en", "value": "alias"},
                               {"language": "en", "value": "alias"}]},
            "sitelinks": {}, "claims": claims if claims is not None else {"P217": [statement()]}}


class TransformTests(unittest.TestCase):
    def test_projects_independent_maps_and_statement_identity(self):
        original = entity()
        result = transform.project([original])
        self.assertEqual(result.findings, [])
        item = result.tables["items"][0]
        self.assertEqual(item["description_en"], "")
        for name in ("labels", "descriptions", "aliases", "sitelinks"):
            self.assertTrue(codec.equal(codec.loads(item[name + "_json"]), original[name]))
        row = result.tables["statements"][0]
        self.assertEqual(row["statement_id"], "Q42$Mixed-Case")
        self.assertEqual(row["value_text"], "1930'619c~01")
        self.assertEqual(row["statement_order"], "1")
        self.assertTrue(codec.equal(codec.loads(row["datavalue_json"]),
                                    original["claims"]["P217"][0]["mainsnak"]["datavalue"]))

    def test_special_snaks_qualifier_order_and_ranks(self):
        unknown = {"property": "P217", "snaktype": "somevalue"}
        no_value = {"property": "P195", "snaktype": "novalue", "datatype": "wikibase-item"}
        first = statement(main=unknown, qualifiers={"P195": [no_value, no_value]},
                          **{"qualifiers-order": ["P195"]})
        second = statement("Q42$Other", main=snak(value="[unknown value]"))
        second["rank"] = "deprecated"
        result = transform.project([entity(claims={"P217": [first, second]})])
        self.assertEqual(result.findings, [])
        rows = result.tables["statements"]
        self.assertEqual([r["rank"] for r in rows], ["normal", "deprecated"])
        self.assertEqual([r["value_text"] for r in rows], ["[unknown value]"] * 2)
        self.assertEqual(rows[0]["datavalue_json"], "null")
        self.assertNotEqual(rows[1]["datavalue_json"], "null")
        qualifiers = result.tables["qualifiers"]
        self.assertEqual([r["snak_order"] for r in qualifiers], ["1", "2"])
        self.assertTrue(all(r["statement_id"] == "Q42$Mixed-Case" and
                            r["value_text"] == "[no value]" and
                            r["property_order"] == "1" for r in qualifiers))

    def test_renderers_and_complete_json_fallback(self):
        day = {"value": {"time": "+2026-06-29T00:00:00Z", "timezone": 0,
                         "before": 0, "after": 0, "precision": 11,
                         "calendarmodel": "http://www.wikidata.org/entity/Q1985727"}, "type": "time"}
        mono = {"value": {"text": "عنوان", "language": "ar"}, "type": "monolingualtext"}
        item = {"value": {"entity-type": "item", "numeric-id": 5, "id": "Q5"}, "type": "wikibase-entityid"}
        broad = copy.deepcopy(day)
        broad["value"]["precision"] = 8
        broad["value"]["time"] = "+1930-00-00T00:00:00Z"
        claims = {}
        for index, (datatype, dv) in enumerate((("time", day), ("monolingualtext", mono),
                                                ("wikibase-item", item), ("time", broad))):
            s = statement(f"Q42${index}", main=snak())
            s["mainsnak"].update(datatype=datatype, datavalue=dv)
            claims.setdefault("P217", []).append(s)
        result = transform.project([entity(claims=claims)])
        self.assertEqual(result.findings, [])
        rows = result.tables["statements"]
        self.assertEqual([r["value_text"] for r in rows[:3]],
                         ["2026-06-29 (day precision)", "عنوان [ar]", "Q5"])
        self.assertEqual(rows[3]["value_text"], codec.dumps(broad))
        self.assertEqual(rows[3]["datavalue_json"], codec.dumps(broad))

    def test_complete_reference_sharing_retains_every_attachment(self):
        group = {"hash": "same-source-hash", "snaks": {"P304": [snak("P304", "001")]},
                 "snaks-order": ["P304"]}
        changed = copy.deepcopy(group)
        changed["snaks"]["P304"][0]["datavalue"]["value"] = "002"
        s = statement(references=[group, copy.deepcopy(group), changed])
        other = entity("Q1", {"P217": [statement("Q1$Case", references=[group])]})
        result = transform.project([entity(claims={"P217": [s]}), other])
        self.assertEqual(result.findings, [])
        rows = result.tables["references"]
        self.assertEqual([r["value_text"] for r in rows], ["001", "002"])
        links = result.tables["statement_references"]
        self.assertEqual([r["reference_id"] for r in links], ["R000001", "R000001", "R000002", "R000001"])
        self.assertEqual([r["reference_order"] for r in links], ["1", "2", "3", "1"])
        self.assertTrue(all(r["source_reference_hash"] == "same-source-hash" for r in links))

    def test_saved_real_response_counts_and_csv_roundtrip(self):
        path = Path(__file__).resolve().parents[1] / "review/q124840826-revision-2533342425-20261015T002253Z.json"
        body = path.read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         "4824029e1fd0cf03a5e92bdbff07b2902b9efde11e580d219873290cc136bb3d")
        source = codec.loads(body)["entities"]["Q124840826"]
        result = transform.project([source])
        self.assertEqual(result.findings, [])
        self.assertEqual({k: len(v) for k, v in result.tables.items()},
                         {"items": 1, "statements": 41, "qualifiers": 28,
                          "references": 20, "statement_references": 29})
        self.assertEqual(len(result.groups), 11)
        from scripts.sample_backup.storage import RunStore
        with TemporaryDirectory() as directory:
            store = RunStore.create(Path(directory), ["Q124840826"], "synthetic-offline-regression")
            for table, rows in result.tables.items():
                store.write_table(table, rows)
                with (store.root / (table + ".csv")).open(encoding="utf-8", newline="") as stream:
                    self.assertEqual(list(csv.DictReader(stream)), rows)
            refs = result.tables["references"]
            expanded = sum(sum(r["reference_id"] == link["reference_id"] for r in refs)
                           for link in result.tables["statement_references"])
            self.assertEqual(expanded, 70)
        self.assertEqual(path.read_bytes(), body)
        # Independent source traversal: expected values never come from project().
        statements = {r["statement_id"]: r for r in result.tables["statements"]}
        for pid, source_statements in source["claims"].items():
            for position, original in enumerate(source_statements, 1):
                sid = original["id"]
                row = statements[sid]
                self.assertEqual((row["property_id"], row["statement_order"], row["rank"], row["statement_type"]),
                                 (pid, str(position), original["rank"], original["type"]))
                self.assert_snak_matches(original["mainsnak"], row)
                for po, qp in enumerate(original.get("qualifiers-order", []), 1):
                    actual = [r for r in result.tables["qualifiers"]
                              if r["statement_id"] == sid and r["property_id"] == qp]
                    self.assertEqual(len(actual), len(original["qualifiers"][qp]))
                    for so, (q, qr) in enumerate(zip(original["qualifiers"][qp], actual), 1):
                        self.assertEqual((qr["property_order"], qr["snak_order"]), (str(po), str(so)))
                        self.assert_snak_matches(q, qr)
                links = [r for r in result.tables["statement_references"] if r["statement_id"] == sid]
                self.assertEqual(len(links), len(original.get("references", [])))
                for ro, (group, link) in enumerate(zip(original.get("references", []), links), 1):
                    self.assertEqual(link["reference_order"], str(ro))
                    self.assertEqual(link["source_reference_hash"], group.get("hash", ""))
                    for po, rp in enumerate(group["snaks-order"], 1):
                        rows = [r for r in result.tables["references"]
                                if r["reference_id"] == link["reference_id"] and r["property_id"] == rp]
                        self.assertEqual(len(rows), len(group["snaks"][rp]))
                        for so, (ref, rr) in enumerate(zip(group["snaks"][rp], rows), 1):
                            self.assertEqual((rr["property_order"], rr["snak_order"]), (str(po), str(so)))
                            self.assert_snak_matches(ref, rr)

    def assert_snak_matches(self, original, row):
        self.assertEqual(row["snaktype"], original["snaktype"])
        self.assertEqual(row["datatype"], original.get("datatype", ""))
        self.assertEqual(row["snak_hash"], original.get("hash", ""))
        self.assertTrue(codec.equal(codec.loads(row["datavalue_json"]), original.get("datavalue")))

    def test_reference_digest_collision_still_compares_complete_objects(self):
        a = {"hash": "h", "snaks": {"P304": [snak("P304", "1")]}, "snaks-order": ["P304"]}
        b = copy.deepcopy(a)
        b["snaks"]["P304"][0]["datavalue"]["value"] = "2"
        with patch.object(transform, "group_digest", return_value="forced-collision"):
            result = transform.project([entity(claims={"P217": [statement(references=[a, b, a])]})])
        self.assertEqual([r["reference_id"] for r in result.tables["statement_references"]],
                         ["R000001", "R000002", "R000001"])

    def test_media_encoding_and_compound_precision_roundtrips(self):
        name = "A é%#?&'/B.jpg"
        media = statement(main=snak("P18", name, "commonsMedia"))
        second_media = copy.deepcopy(media)
        second_media["id"] = "Q42$SecondImage"
        result = transform.project([entity(claims={"P18": [media, second_media]})])
        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.tables["statements"]), 2)
        self.assertEqual(result.tables["statements"][0]["value_text"], name)
        self.assertEqual(result.tables["statements"][0]["commons_file_url"],
                         "https://commons.wikimedia.org/wiki/File:A_%C3%A9%25%23%3F%26%27%2FB.jpg")
        compound = codec.loads('{"value":{"latitude":12.1234567890123456789,"longitude":-1e-90,"precision":0.000000000000001},"type":"globecoordinate"}')
        source = entity()
        source["claims"]["P217"][0]["mainsnak"]["datavalue"] = compound
        result = transform.project([source])
        row = result.tables["statements"][0]
        self.assertTrue(codec.equal(codec.loads(row["datavalue_json"]), compound))
        self.assertEqual(row["value_text"], row["datavalue_json"])

    def test_unrepresentable_structures_fail_visibly_without_crashing(self):
        cases = []
        a = entity(); a["labels"] = ["malformed"]; cases.append(a)
        a = entity(); a["claims"]["P217"][0]["extra"] = "unrepresented"; cases.append(a)
        a = entity(); a["claims"]["P217"][0]["references"] = [{}]; cases.append(a)
        a = entity(); a["claims"]["P217"][0]["qualifiers"] = {"P195": [snak("P195")]}; cases.append(a)
        a = entity(); a["claims"]["P217"].append(copy.deepcopy(a["claims"]["P217"][0])); cases.append(a)
        a = entity(); a["claims"]["P217"][0]["mainsnak"]["datavalue"]["value"] = None; cases.append(a)
        for index, source in enumerate(cases):
            with self.subTest(case=index):
                result = transform.project([source])
                self.assertTrue(result.findings)
                self.assertTrue(all(f["qid"] == "Q42" and f["path"].startswith("/entities/Q42")
                                    for f in result.findings))

    def test_csv_unicode_quotes_linebreaks_empty_and_json_null(self):
        from scripts.sample_backup.storage import RunStore
        value = '001, "صورة"\r\nnext\nline\r1930\'619c~01'
        source = entity(claims={"P217": [statement(main=snak(value=value)),
                                         statement("Q42$empty", main=snak(value=""))]})
        result = transform.project([source])
        with TemporaryDirectory() as directory:
            store = RunStore.create(Path(directory), ["Q42"], "synthetic")
            store.write_table("statements", result.tables["statements"])
            body = (store.root / "statements.csv").read_bytes()
            self.assertFalse(body.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b'""', body)
            self.assertTrue(body.endswith(b"\r\n"))
            rows = list(csv.DictReader(io.StringIO(body.decode(), newline="")))
            self.assertEqual(rows[0]["value_text"], value)
            self.assertEqual(rows[1]["value_text"], "")
            self.assertEqual(codec.loads(rows[1]["datavalue_json"])["value"], "")
            self.assertEqual(next(o["row_count"] for o in store.inventory()
                                  if o["path"] == "statements.csv"), 2)

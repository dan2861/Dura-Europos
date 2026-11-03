"""Invented batch content; no retrieval or operational verification."""
import json
import unittest

from scripts.idea_json_backup.production_response import classify_response


def tag(qid="Q114241199", rank="normal"):
    return {"rank": rank, "mainsnak": {"snaktype": "value", "datatype": "wikibase-item",
            "datavalue": {"type": "wikibase-entityid", "value": {"id": qid, "entity-type": "item"}}}}


def item(qid, claims=None):
    return {"id": qid, "type": "item", "lastrevid": 7, "modified": "2026-11-03T12:00:00Z",
            "claims": {} if claims is None else claims}


class ResponseTests(unittest.TestCase):
    def test_rank_rule_and_changed_membership_keep_every_requested_item(self):
        entities = {"Q1": item("Q1", {"P5008": [tag(), tag("Q2", "preferred")]}),
                    "Q2": item("Q2", {"P5008": [tag(rank="deprecated")]}),
                    "Q3": item("Q3")}
        result = classify_response(json.dumps({"success": 1, "entities": entities}).encode(), ["Q1", "Q2", "Q3"])
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["memberships"], {"Q1": "matches", "Q2": "changed", "Q3": "changed"})
        self.assertEqual([row["outcome"] for row in result["item_results"]], ["accepted"] * 3)

    def test_clean_mixed_response_accepts_valid_neighbor_but_holds_missing(self):
        body = json.dumps({"success": 1, "entities": {"Q1": item("Q1"), "Q2": {"id": "Q2", "missing": True}}}).encode()
        result = classify_response(body, ["Q1", "Q2", "Q3"])
        self.assertEqual(result["outcome"], "mixed")
        self.assertEqual([row["outcome"] for row in result["item_results"]], ["accepted", "review_required", "review_required"])
        self.assertEqual(result["item_results"][1]["error"]["code"], "missing_or_redirect")
        self.assertEqual(result["item_results"][2]["error"]["code"], "omitted")

    def test_maxlag_is_retryable_but_warning_or_malformed_membership_is_held(self):
        result = classify_response(b'{"error":{"code":"maxlag","info":"lagged"}}', ["Q1"])
        self.assertEqual(result["outcome"], "transient_failure")
        self.assertTrue(result["error"]["retryable"])
        for value in ({"success": 1, "entities": {"Q1": item("Q1")}, "warnings": {"unknown": "notice"}},
                      {"success": 1, "entities": {"Q1": item("Q1", {"P5008": [{}]})}}):
            result = classify_response(json.dumps(value).encode(), ["Q1"])
            self.assertEqual(result["outcome"], "review_required")
            self.assertFalse(result["item_results"][0]["error"]["retryable"])

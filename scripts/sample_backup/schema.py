"""The approved 1.0.0 contract. Keep ordering explicit."""

SCHEMA_VERSION = "1.0.0"
HEADERS = {
    "items": ("qid", "lastrevid", "modified", "label_en", "description_en",
              "labels_json", "descriptions_json", "aliases_json", "sitelinks_json"),
    "statements": ("qid", "statement_id", "property_id", "statement_order",
                   "statement_type", "rank", "snak_hash", "snaktype", "datatype",
                   "value_text", "datavalue_json", "commons_file_url"),
    "qualifiers": ("qid", "statement_id", "property_id", "property_order",
                   "snak_order", "snak_hash", "snaktype", "datatype", "value_text",
                   "datavalue_json"),
    "references": ("reference_id", "property_id", "property_order", "snak_order",
                   "snak_hash", "snaktype", "datatype", "value_text", "datavalue_json"),
    "statement_references": ("qid", "statement_id", "reference_id",
                             "reference_order", "source_reference_hash"),
}
CHECK_IDS = ("request_coverage", "item_data", "statements_qualifiers",
             "references", "files", "manual_review")
ITEM_FIELDS = ("requested_qid", "returned_qid", "retrieval_status", "validation_status",
               "retrieved_at", "source_url", "source_json", "lastrevid", "modified",
               "error", "http_trace")
RUN_FIELDS = ("run_id", "schema_version", "started_at", "finished_at", "scope",
              "retrieval_method", "limitations", "items", "outputs", "validation_summary")
ENDPOINT = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def request_options():
    from . import EXPORTER_VERSION
    return {"timeout_seconds": 60, "follow_redirects": True, "max_redirects": 5,
            "automatic_retries": 0, "query_parameters": {}, "concurrency": 1,
            "headers": {"Accept": "application/json",
                        "User-Agent": f"IDEA-sample-backup/{EXPORTER_VERSION}"}}

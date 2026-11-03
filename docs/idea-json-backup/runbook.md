# IDEA JSON backup: production roadmap runbook

Updated 2026-11-03. The three-item MVP pilot and local review are complete. The first production milestone implements **selection discovery and independent selection verification only**. Separate milestone/final reviews are clear and all 153 offline tests pass; Danu reports guided discovery and persisted verification passed; saved-evidence review confirms the frozen union of 33,709 QIDs (33,239 main plus 470 scholarly, no overlap). Production storage/collection/recovery is now the active offline implementation stage. Production item collection/resume, the SQLite journal, archive packaging and deposit checks are later increments. The [MVP runbook](mvp-runbook.md) remains applicable to the prototype.

Danu runs operational commands with guidance. The assistant runs invented offline TDD tests and makes small commits. Do not infer a live discovery or full backup from passing unit tests. No phase starts another phase automatically.

## First guided discovery

From `/Users/danu/Documents/ChatGPT/Dura-Europos`, Danu runs:

```bash
python3 -B -m scripts.export_idea_json discover \
  --output backup/idea-selection-001
```

The output directory must not exist. The command queries the main and scholarly graphs sequentially using the approved explicit normal/preferred `P5008 = Q114241199` query, preserves request/response evidence, deduplicates the union and sorts QIDs numerically. It automatically runs the independent selection audit. It retrieves identifiers, not full entity JSON, and performs no Wikidata edit or Dataverse upload.

There is at least one second between completed attempts and later dispatches, a 60-second supervised response deadline, and at most three attempts per graph. Known transient failures wait at least 5/10 seconds or the longer observed Retry-After. Saving failures, uncertain header receipt, complete malformed responses and non-transient outcomes stop for review. A real Retry-After can make the command take longer than the per-response deadline. Do not interrupt a legitimate cooldown merely because the command has not printed a final report.

Success prints JSON with `status: passed`, no findings, the actual `selected_count`, and the output path, and exits 0. Approximately 33,000 is an expectation, not a required count or a completion threshold. Stop after this command and return its exact output for review.

If it fails, retain the directory and report the output. Failed/incomplete graph evidence never creates a consumable frozen list. This milestone has no discovery-resume command; do not reuse the directory or automatically start a fresh attempt before reviewing the previous server-wait/error evidence.

## Separate persisted selection check

After reviewing the discovery command's result, Danu performs the separate read-only audit:

```bash
python3 -B -m scripts.export_idea_json verify-selection backup/idea-selection-001
```

Expected success is `{"status": "passed", "findings": []}`. The check reads public files only, does not query Wikidata, repair data or rewrite checksums. Exit 1 means a known failure; exit 2 means an unfinished pending selection or a handled interruption. No item collection is started by discovery or verification.

## Saved evidence and limitations

- `query.rq`: exact approved explicit-rank query, with no label service or LIMIT.
- `sources/`: immutable encoded/decoded response bodies, including failed/partial attempts where bytes were received. Original duplicate bindings remain in the saved results.
- `qids.txt`: nonempty, distinct canonical QIDs, one per UTF-8/LF line in numeric order. It is published only after both graphs succeed.
- `selection.json`: production format `idea-json-backup` version `1.0.0`, criterion, both graph sources, exact requests, timing/elapsed/header/completeness evidence, all attempts, body/list/query descriptors, frozen count and time. An incomplete selection keeps unavailable fields null.
- `.state/`: internal durable dispatch/worker receipts and spool files, explicitly outside the public payload. Retain them on failure for diagnosis; the public verifier does not use them as expected evidence.

An empty scholarly graph is valid if the combined union is nonempty. A failed graph, ambiguous receipt or empty union prevents a complete selection. WDQS graphs update asynchronously; the frozen list is the observed two-graph result, not a claim that all records describe one historical instant.

Before accepting the selection, review the actual count, endpoints, graph outcomes, attempts and query. Its checksum fixes the population for later collection. Any subsequent membership change will be recorded without silently changing that list.

## Next implementation gate

After Danu's discovery and persisted audit pass and their saved evidence is reviewed, continue offline TDD for production item storage, retry/resume and independent finalization. The MVP one-batch collector is not the full-population collector. Actual production collection and later Yale upload/download remain guided operations. Yale dataset destination, depositor access, metadata and archive retention are still unresolved and must be established before deposit. Publication remains a separate request.

Implementation/review evidence: [production-log.md](production-log.md); full approved roadmap: [plan.md](plan.md) and [record-layouts.md](record-layouts.md).

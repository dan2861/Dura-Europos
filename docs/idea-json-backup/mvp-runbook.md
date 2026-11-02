# One-batch JSON backup MVP

This prototype preserves and verifies one supplied list of **1–50 distinct canonical QIDs**, in supplied order, using one response and a new output directory. It does not establish an all-IDEA backup or Dataverse deposit. The current work authorizes offline implementation and tests; a live pilot requires a separate explicit request.

## Offline preservation

Run from the repository root. Prepare a UTF-8 QID file with one QID per line and no blank lines, duplicates, surrounding whitespace or prefixes beyond uppercase `Q` and its canonical positive integer. Provide an invented or previously saved complete Action API batch response: `success` must be JSON integer `1`, with an `entities` object keyed by the requested QIDs. Each accepted entity needs matching `id`, `type: "item"`, a positive integer `lastrevid`, and a valid UTC `modified` string. Missing, redirected, omitted or malformed items fail visibly.

Example using **invented files**; replace the input paths and choose an output directory that does not exist:

```bash
python3 -B -m scripts.idea_json_backup preserve \
  --qids review/mvp-fixtures/qids.txt \
  --response review/mvp-fixtures/response.json \
  --kind synthetic \
  --description "Invented fixture; no retrieval performed" \
  --output backup/mvp-offline-001
```

Use `--kind saved` for a previously saved response and describe its known origin accurately. Synthetic/saved inputs retain `retrieved_at: null`; the command does not invent a historical retrieval time. The source response is preserved byte for byte. Extracted item JSON retains the whole entity, including unknown fields, numeric tokens, arrays and exact strings; its formatting may differ from the source.

The command automatically runs the independent verifier after preservation. It prints a JSON report and exits `0` only when verification passes; failures exit `1`, and a handled keyboard interruption exits `130`.

## Files and completion states

| File | Meaning |
| --- | --- |
| `manifest.json` | Prototype format `idea-json-backup-mvp`, version `1`; frozen input QIDs, provenance, every item outcome/revision, source/item descriptors and evidence inventory |
| `source.json` | Unchanged supplied response, or decoded response bytes from the adapter when available |
| `items/QID.json` | Complete extracted entity for each successfully saved item |
| `request.json`, `transport.json`, `encoded.body` | Adapter request settings, receipt/completeness/timing/error metadata, and original encoded response bytes |
| `capture/` | Adapter worker evidence retained when present, including partial receipt/body or staging evidence after failure |

Descriptors record relative path, byte size and SHA-256. Manifest status `collected` means all requested items were saved; **verification report `passed` is a separate outcome**. Manifest status `incomplete`, unresolved items, errors, missing artifacts or extra artifacts prevent a passing verification. A partially saved result is not complete.

An existing output directory is rejected. The MVP never resumes, retries automatically, repairs or overwrites a prior run. After failure or interruption, retain the directory and inspect its manifest/evidence; any authorized new attempt uses a fresh directory. Saving failures may leave partial evidence, so never infer completion from the mere presence of JSON files.

## Independent read-only verification

```bash
python3 -B -m scripts.idea_json_backup verify backup/mvp-offline-001
```

Verification compares every saved entity with its original source object, checks scope, revisions, numeric tokens/types, paths, sizes and checksums, and validates adapter receipts when present. It detects changed item content even if its checksum was recomputed. Verification does not retrieve data, refresh checksums, repair files or change the manifest.

## Adapter and offline checks

The `collect` subcommand exists for a **separately authorized future pilot**. It uses the fixed Wikidata Action API batch settings, a descriptive User-Agent, one request, no redirects/retries, and a supervised total deadline of at most 60 seconds. Live provenance records the actual receipt time. HTTP/API failures, incomplete framing, unsupported/invalid compression and interruption retain evidence and leave the run incomplete. No live command is part of this runbook's current execution scope.

Run the MVP's offline tests with invented responses and injected transports/workers:

```bash
python3 -B -m unittest discover -s tests -p 'test_idea_json_*.py' -v
```

Full-population discovery, many-batch scheduling, resume/retry policy, SQLite, 33,000-item scale checks, archives, Dataverse upload and publication remain later work under the approved production roadmap.

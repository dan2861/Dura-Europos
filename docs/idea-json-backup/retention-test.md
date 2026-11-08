# Small Dataverse upload/download test

Prepared 2026-11-08. Destination and account access are not established yet. This is preparation for a guided unpublished test; it is not evidence of a deposit.

## What we are trying to prove

A backup is useful when we can recover the same data later. We are testing this path with three real items before collecting and depositing all 33,709 selected items:

1. Save complete item JSON and the original response evidence. Complete locally.
2. Put all public files into an archive, with an inventory of file fingerprints (SHA-256 checksums). Complete locally.
3. Unpack the local archive and compare every file. Passed, including a separate saved-package check.
4. Put the small archive and inventory into an unpublished Yale draft, download both and compare the returned bytes with the preserved local originals. This is the next operational test.

The offline checker establishes whether the supplied downloaded files match. A separate operator receipt records where/when Danu downloaded them. The checker does not observe the transfer or contact Dataverse itself, and it never publishes a dataset.

## Concrete local test package

Local directory: `/Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-pilot-package-001`.

Package ID: `20261108T184113.708915Z-a1cb9dfcab5e`.

| File to retain and test | Bytes | SHA-256 of the local baseline |
| --- | ---: | --- |
| part-00001.tar.gz | 503,551 | acac30ba3056381165e23fc0ee7ebefd0f7bfcb609be16d84dd94580b0a68dd9 |
| package-inventory.json | 6,083 | 60cae9d13ef98bc24119f8411defe907941bebf9e0c50e91acf0d9df3493d89f |

The archive contains all 28 public pilot files, including three item JSONs and their supporting evidence. Keep the original local files unchanged. The local package-verification.json stays as local audit evidence; it is not a required acquired file. Local .state/ recovery files are not part of the archive.

## Establish access and destination first

Use the official [Yale Dataverse quick start](https://researchdata.yale.edu/yale-dataverse-quick-start-guide) to check login/access. It describes Yale NetID sign-in and the account-request route for external collaborators. The operator needs permission to create or upload to a draft in the chosen collection.

Before a concrete creation/upload step, establish the target collection or existing draft URL and any required title, author, contact and subject fields. A possible title is **IDEA Wikidata JSON archive retention pilot (three items)**. This is proposed text, not an already-created dataset. Author/contact/terms are not inferred by the assistant.

Yale's current guide says compressed uploads can be unpacked and offers alternative upload handling. The generic [Dataverse file-management guide](https://guides.dataverse.org/en/latest/user/dataset-management.html#compressed-files) describes configurable ZIP handling; it does not establish how Yale will retain this tar.gz. Therefore we need the actual two-file roundtrip before accepting the archive profile. Saving a draft is distinct from publication.

## Later guided steps, once the destination is known

The operator will create/use the chosen unpublished draft, upload the two listed files, check how they appear, save the draft, and return the actual dataset/version/file details. Then download the original archive and inventory into a new dedicated directory containing only those two files. Preserve their declared filenames; record dataset/file identifiers, stable download URLs and observed UTC download times in a copy of [acquisition-template.json](acquisition-template.json). The template's null values are deliberately incomplete and cannot establish deposit verification.

The acquisition receipt and any deposit report stay outside the package and downloaded-file directories. Stable URLs belong in the receipt; credentials, private/preview access links and signed access tokens do not. The implemented offline verify-deposit command compares the downloaded inventory to the local baseline byte for byte, checks the archive and all extracted contents, then separately validates the operator-recorded receipt. Publication remains null.

Offline implementation/review is complete: 302 tests pass, including synthetic changed downloads, incomplete/unsafe receipts and report-publication changes. This proves checker behavior, not an actual upload. Destination/access remains unknown, so no concrete upload action is supplied yet. Danu performs each operational step with guidance.

## Recorded command for the later guided download check

Do not run this before an actual guided upload/download and receipt review. The paths below are proposed new locations; no acquired files or receipt are claimed to exist there:

```bash
python3 -B -m scripts.export_idea_json verify-deposit \
  --package backup/idea-pilot-package-001 \
  --downloads backup/idea-pilot-downloads-001 \
  --acquisition review/idea-json-backup-pilot-acquisition-001.json \
  --report review/idea-json-backup-pilot-deposit-001.json
```

The report destination must be new; it is never overwritten. Receipt/report paths must be outside both input directories. Expected completed-test outcome: byte_status and deposit_status passed, exact operator_recorded acquisition, publication null, exit0. Omitting the receipt or retaining safe unknowns can pass byte comparison but leaves deposit_status not_checked/exit2. A byte or receipt failure exits1. Preserve all failed/pending evidence for review; do not repair downloads or rewrite baseline checksums. A later fresh download uses a new directory/report.

A failed retention test prompts a concrete format/upload-method review; it does not justify silently changing the verified package or expanding the full collection. After success, record actual retention evidence separately; the immutable pilot package's provisional profile stays unchanged. Review the evidence before selecting a profile for later full-population packaging. Full collection still requires its separate service-feasibility/operational gate.

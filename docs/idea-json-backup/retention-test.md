# Small Dataverse upload/download test

Updated 2026-11-08. Danu confirms both downloaded files are already located in backup/idea-pilot-downloads-001 and their SHA-256 values match the originals. The [actual acquisition receipt](../../review/idea-json-backup-pilot-acquisition-001.json) already records doi:10.60600/YU/KPHJOF, DRAFT, inventoryID221111 and archiveID221110. Danu completed verify-deposit001 at2026-11-09T00:42:08.482124Z: byte_status passed, deposit_status not_checked, sole acquisition_incomplete finding, publication null. The saved report was read directly and agrees. Download times were explicitly not recorded and remain null. No further path collection, checksum check, verification rerun or fresh download is needed to establish this pair. Preserve receipt/report/downloads001 unchanged. Next review the archive profile and full-collection readiness with the acquisition limitation explicit; this does not waive the approved deposit-verification requirements.

## What we are trying to prove

A backup is useful when we can recover the same data later. We are testing this path with three real items before collecting and depositing all 33,709 selected items:

1. Save complete item JSON and the original response evidence. Complete locally.
2. Put all public files into an archive, with an inventory of file fingerprints (SHA-256 checksums). Complete locally.
3. Unpack the local archive and compare every file. Passed, including a separate saved-package check.
4. Put the small archive and inventory into an unpublished Yale draft, download both and compare the returned bytes with the preserved local originals. The guided001 offline check passes byte/all-payload verification. Actual download times remain null, so deposit verification is incomplete under the approved record contract. Keep that limitation explicit without repeating completed file-location or byte checks.

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

Offline implementation/review is complete: 302 tests pass, including synthetic changed downloads, incomplete/unsafe receipts and report-publication changes. Dataset identity/version and both file URLs are recorded from Danu's replies. The first guided local check is complete with bytes passed and deposit_status not_checked because times are null. Danu confirms these are the same downloads001 files; no new acquisition or check is established. The assistant has not run an operational checker on the downloads. Danu performs operational steps with guidance.

## Recorded command: completed diagnostic check001

Danu ran the following command and created the report. It returned byte_status passed, deposit_status not_checked and acquisition_incomplete. This is incomplete acquisition evidence, not corruption. This command is recorded history; do not rerun into the existing report path:

```bash
python3 -B -m scripts.export_idea_json verify-deposit \
  --package backup/idea-pilot-package-001 \
  --downloads backup/idea-pilot-downloads-001 \
  --acquisition review/idea-json-backup-pilot-acquisition-001.json \
  --report review/idea-json-backup-pilot-deposit-001.json
```

The report destination must be new; it is never overwritten. Receipt/report paths must be outside both input directories. Expected completed-test outcome: byte_status and deposit_status passed, exact operator_recorded acquisition, publication null, exit0. Omitting the receipt or retaining safe unknowns can pass byte comparison but leaves deposit_status not_checked/exit2. A byte or receipt failure exits1. Preserve all failed/pending evidence for review; do not repair downloads or rewrite baseline checksums. A later fresh download uses a new directory/report.

A failed retention test prompts a concrete format/upload-method review; it does not justify silently changing the verified package or expanding the full collection. After success, record actual retention evidence separately; the immutable pilot package's provisional profile stays unchanged. Review the evidence before selecting a profile for later full-population packaging. Full collection still requires its separate service-feasibility/operational gate.

## Current checkpoint: file clarification closed

Danu confirms the inventory is backup/idea-pilot-downloads-001/package-inventory.json and the archive is beside it. The existing saved audit covers this pair, and the receipt already includes the known dataset/version/file identifiers. Download times were not recorded. Do not ask for paths, known IDs or historical times again, rerun verification merely to repeat the result, or request another download as part of this clarification.

Earlier instructions to prepare a fresh002 pair or copy a Finder pathname are superseded. Partial receipt002 is unused preparation with unknown times, not a new acquisition; report002 has not been created. Preserve the001 evidence and its limitation. The canonical dataset link redirected the assistant browser to Yale Log In, so remote draft metadata remains operator-recorded.

The observed result supports unchanged tar.gz retention for this 503,551-byte pilot. It does not establish the proposed 256MiB/5,000-member limits, complete deposit verification or publication. The next review concerns the production archive profile and service-feasibility gate, carrying the incomplete acquisition evidence explicitly. No criteria are silently relaxed and no operational command starts from this status correction.

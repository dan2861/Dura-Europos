# Guided redirect-release operations

Prepared2026-11-08; updated2026-11-09 after Danu created the package. Offline implementation is complete:342 tests passed29.744s, separate contract/producer/verifier/package reviews and a final independent invented CLI composition are clear. The actual source audit, release creation, separate release verification and package creation passed their respective requirements. The separate saved-package verification in Stop5 also passed. Danu reports the production draft deposit complete and has deferred the download/acquisition step in Stop7. Danu accepts provisional reliance on the pilot result while production verification is deferred; this does not establish a production verification pass. A General Preview URL can share the draft for review. Publication has not been reported; resume operational work when requested. The assistant has not run operational commands.

The [reviewed request](../../review/idea-json-backup-production-redirect-request-001.json) explicitly binds run20261109T012636.715412Z-746d5d786f2f, generation36409, frozen-list hash and Q134471369→Q122677115/A000623. observed_at is null; the mapping is operator_recorded. All future generated record times describe creation, not the unknown earlier observation. No historical JSON retrieval is requested.

## Stop1: audit all original saved data and retain its strict result

Completed by Danu: checked_at2026-11-09T04:53:03.520742Z (November8 New York). Saved report matches the supplied output: selected33,709/accepted33,708/pending0/unresolved1; scope failed only for Q134471369, and source_content/provenance/files passed with no other findings. Input generation36409 and frozen-list/inventory/attempt descriptors remain unchanged. This command is completed history; preserve its report and do not rerun into the same output path. Next is Stop2.

From /Users/danu/Documents/ChatGPT/Dura-Europos, Danu runs:

```bash
python3 -B -m scripts.export_idea_json verify \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --report /Users/danu/Documents/ChatGPT/Dura-Europos/review/idea-json-backup-production-strict-001.json
```

Return the entire JSON report. This reads/hashes every accepted source/item and writes a new external diagnostic report. It does not change the original run or request new data. Read-only preflight found the report path absent. Never overwrite it or add --write to this step.

Expected result: original strict status/scope **failed** only for Q134471369, accurate counts33,709selected/33,708accepted/0pending/1unresolved, and source_content/provenance/files **passed**. The failure remains intentional under the original rule; the new release will separately reconcile the reviewed redirect. If another finding/check fails, stop and review it before making the release.

## Stop2: capacity before a separate public-payload copy

Completed by Danu: full run1.2G, responses391M, diagnostics0B, .state428M, selection4.3M, items426M. df reports228Gi size/162Gi used/34Gi available/83% capacity on /dev/disk3s5. These are rounded operator observations, with no invented timestamp or inference about the cause of increased free space. The separate public copy excludes .state/ and is roughly0.8GiB at the observed footprint;34Gi available provides room for this copy and subsequent archive/download/extraction work. Proceed to Stop3; no cleanup is requested.

After reviewing Stop1, Danu obtains the current allocated breakdown and free space:

```bash
du -h -d 1 /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001
df -h /Users/danu/Documents/ChatGPT/Dura-Europos
```

Return both outputs. The old289M/12Gi measurements were before the remainder was collected. Plan for one additional public-payload copy excluding .state/, then later archives/downloads/temporary extraction. No cleanup, drive purchase or fixed free-space threshold is assumed.

## Stop3: create the separate resolved release

Completed by Danu2026-11-09: release20261109T050238.412534Z-872c198368aa, created_at05:02:38.412534Z. The supplied post-creation audit at05:07:55.807074Z passed all four checks with33,709selected/33,708usable_items/1redirected/0pending/0unresolved and no findings. Read-only saved metadata agrees; saved verification.json is the earlier producer audit at05:04:20.502768Z with the same inputs/counts/status. Preserve both observations. The creation command is completed history; do not rerun it into the existing output. Proceed to Stop4.

Source/capacity review is clear. The request was read directly and retains the approved mapping/run/generation/frozen-list hash with observed_at null. A renewed read-only preflight finds backup/idea-production-release-001 absent and not a symlink. This is now the next guided command; the assistant has not executed it.

Only after source/capacity review, Danu runs:

```bash
python3 -B -m scripts.export_idea_json create-release \
  --run /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-run-001 \
  --request /Users/danu/Documents/ChatGPT/Dura-Europos/review/idea-json-backup-production-redirect-request-001.json \
  --output /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001
```

The output must be absent; do not create it beforehand. Initial read-only preflight found it absent/no symlink. Return the report. Expect status passed, all four release checks passed, selected33,709/usable_items33,708/redirected1/pending0/unresolved0. The nested original collection/ remains unchanged and strictly failed for that one unavailable QID. On interruption/failure retain the original and partial release; do not delete, overwrite or reuse output to retry without review.

## Stop4: separate saved-release verification

Completed by Danu: checked_at2026-11-09T05:11:11.225908Z, same release/run IDs and all three input descriptors, all four checks passed,33,709selected/33,708usable_items/1redirected/0pending/0unresolved and no findings. The supplied fresh audit is read-only; retain the original saved producer report at05:04:20.502768Z unchanged. Proceed to Stop5.

After reviewing creation, Danu runs:

```bash
python3 -B -m scripts.export_idea_json verify-release \
  /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001
```

Return the entire report. This independently checks all saved release/source/resolution/report bytes and does not repair anything. A passing reconciliation is distinct from ordinary acceptance of the old QID and from deposit/publication.

## Stop5: archive the verified release

Completed by Danu2026-11-09: package20261109T051551.962194Z-e1d1bb30c783, checked_at05:16:40.486908Z, inventory/archive_integrity/payload_roundtrip all passed, no findings. Saved report agrees exactly. Inventory records35,074 public payload files /809,133,230bytes, including33,708 item JSONs;8 tar.gz parts total95,542,899bytes. This creation command is completed history; preserve the existing package. Next is the separate saved-package check below.

Saved-release review is clear. Direct read-only inspection confirms the prepared profile remains tar.gz/gzip6, maximum5,000 members or268,435,456uncompressed payload bytes per part, with unchanged historical pilot byte-pass/deposit-not_checked evidence. Renewed preflight finds backup/idea-production-package-001 absent/not symlinked. Prior34Gi free-space review provides headroom for this archive/extraction step; no repeated capacity command is requested now. This is the next guided operation, not an already-created package or deposit.

After saved-release and profile/capacity review, Danu runs:

```bash
python3 -B -m scripts.export_idea_json package-release \
  --release /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-release-001 \
  --output /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-package-001 \
  --profile /Users/danu/Documents/ChatGPT/Dura-Europos/changes/idea-json-backup/production-archive-profile.json
```

Output must be absent; initial preflight found it absent/no symlink. Return the JSON. The external package inventory uses1.1.0/payload_kind resolved_release, bounded tar.gz parts, and full independent extraction/audit. The proposed profile's local caps are not measured Yale maximum limits; its embedded pilot byte evidence still says deposit not_checked for unknown times. Do not change the immutable pilot.

After reviewing packaging, Danu separately runs:

```bash
python3 -B -m scripts.export_idea_json verify-package \
  /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-package-001
```

Return the complete report. Expect all three checks passed for the same package ID; this rechecks the saved archives without rewriting package-verification.json. Full production deposit metadata/destination/upload/download/acquisition verification and publication remain later guided operations. The pilot's DOI/file IDs do not automatically identify a production deposit.

## Stop6: establish the production draft destination

Danu completed the separate verify-package check at 2026-11-09T05:29:16.562154Z for package20261109T051551.962194Z-e1d1bb30c783. All three checks passed with no findings. The supplied output is retained separately in review/idea-json-backup-production-package-recheck-001.json; the original package report remains unchanged. Stop5's commands are completed history.

Danu clarified that the Dataverse collection itself is being created. Use [dataverse-collection-metadata.md](../../changes/idea-json-backup/dataverse-collection-metadata.md) for its name, alias, category and description, then return its URL. Inside that collection, create a new production draft dataset via its Add Data → New Dataset action. Copy the proposed title/description from [production-dataset-metadata.md](../../changes/idea-json-backup/production-dataset-metadata.md), supply appropriate author/contact/required metadata, save the draft and return its URL. Saving is distinct from publication, per [Yale's official guidance](https://researchdata.yale.edu/yale-dataverse-quick-start-guide), rechecked 2026-11-09. The assistant does not operate the external application.

After the destination is recorded, guide upload of the inventory plus all eight tar.gz parts, then download and verify those nine files with new acquisition evidence. Do not reuse the pilot DOI/file IDs as production provenance. Production deposit and publication remain unverified/unperformed.

## Stop7: download the production draft files and record acquisition

Danu reports completing the production draft deposit at https://dataverse.yale.edu/dataset.xhtml?persistentId=doi%3A10.60600%2FYU%2F2S1INK&version=DRAFT (doi:10.60600/YU/2S1INK, DRAFT). This supersedes the earlier destination/upload instructions. The assistant web tool could not inspect the draft; upload contents are operator-reported and deposit verification is pending.

Danu creates the absent directory:

```bash
mkdir /Users/danu/Documents/ChatGPT/Dura-Europos/backup/idea-production-downloads-001
```

Download the nine original files individually into it: package-inventory.json and part-00001.tar.gz through part-00008.tar.gz. Preserve exact filenames and the compressed archive bytes. Keep the directory limited to those nine files. For each file, copy its Metadata → Download URL and record the actual download completion time with its time zone. Return filename, URL and time; the assistant can then populate review/idea-json-backup-production-acquisition-001.json. That partial receipt already records the known dataset/version but has null remote IDs/URLs/times. Do not substitute upload/Deposit Date or infer download times from file metadata. Official file-page URL guidance: https://guides.dataverse.org/en/latest/user/find-use-data.html#downloading-via-url .

After receipt review, guide the user through verify-deposit against the production package and downloads001, writing a new external review/idea-json-backup-production-deposit-001.json. Do not run it automatically or replace earlier reports. Expected successful outcome is byte_status passed, deposit_status passed, publication null. Download or verification completion has not yet been reported.

## Deferred verification checkpoint

On 2026-11-09 Danu asked to table Stop7 for later and asked whether publication should proceed now. Recommended retaining the saved draft until the production download/deposit check and final metadata/terms review are complete. This is a recommendation, not an instruction from Yale that checksum verification is mandatory for publication. Yale's quick-start guide confirms private preview URLs are available for review and published datasets retain a record even after deaccession. No publication or new operational command was executed. Stop7 remains the resumption point.

On 2026-11-09 Danu subsequently explicitly chose provisional reliance on the pilot retention result while production download verification remains deferred. Do not represent this as a production verification pass or impose the deferred check as a permission gate. Danu asked whether publication is reversible and whether the draft can be shared. Official guidance confirms publication cannot be reversed to draft; deaccession leaves a public citation record. For review, use Edit Dataset → Preview URL → Create General Preview URL (wording may vary by installation), which permits viewing/downloading without login and can later be disabled. No preview was created or shared, and no publication was executed or observed by the assistant. Sources: https://guides.dataverse.org/en/latest/user/dataset-management.html#publish-dataset and https://guides.dataverse.org/en/latest/user/dataset-management.html#preview-url-to-review-unpublished-dataset .

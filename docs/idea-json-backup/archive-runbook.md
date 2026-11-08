# Candidate archives: guided pilot packaging

Prepared 2026-11-07; reviewed 2026-11-08. **Implementation, separate component reviews and final integrated review are clear for guided candidate packaging of the finalized pilot.** The full offline suite passed 273 tests; the separate real-files/SQLite 33,000-item scale exercise also passed. Danu executes operational commands one guided step at a time. The assistant implements/tests offline with invented fixtures. The finalized three-item pilot remains immutable throughout packaging.

The candidate profile is [candidate-archive-profile.json](candidate-archive-profile.json): tar.gz, gzip level 6, deterministic gzip/tar metadata, at most 5,000 regular payload files or 256 MiB summed uncompressed payload per part. A single oversized file causes a hold. These are provisional test settings, not established Yale limits; retention_evidence stays null until an actual draft roundtrip test. Archive header/part overhead can make an archive's physical size differ from its summed payload limit.

## First guided stop: package the finalized pilot

Completed 2026-11-08: Danu created package `20261108T184113.708915Z-a1cb9dfcab5e`; all three checks passed with no findings. Read-only saved review is clear: one 503,551-byte part, exactly28 public payload files /8,850,019 bytes, all matching finalized source. The output directory now exists; do not rerun creation into it. **Separate saved-package verification subsequently passed; local pilot packaging is complete. The next gate is preparing the Yale draft retention test.**

Read-only preflight confirms the finalized pilot has 28 public files totaling 8,850,019 bytes and `backup/idea-pilot-package-001` is absent. These fit one part under the candidate limits. From `/Users/danu/Documents/ChatGPT/Dura-Europos`, Danu runs:

```bash
python3 -B -m scripts.export_idea_json package \
  --run backup/idea-pilot-run-001 \
  --output backup/idea-pilot-package-001 \
  --profile docs/idea-json-backup/candidate-archive-profile.json
```

The new output directory must be absent; do not create it first or reuse a failed attempt. The collector is not called. Packaging requires the locked finalized/passed collection and independent audit. It inventories every public payload file, including README, manifest, verification, selection/parent evidence, item JSON and earlier failed-response bodies. `.state/` stays local and is excluded from the payload.

Each payload file goes into exactly one bounded `part-00001.tar.gz`-style part. `package-inventory.json` is external to the archive payload and records exact payload/archive paths, sizes, hashes and membership. The independent checker manually extracts only safe regular members into empty temporary storage, checks exact byte/path sets and audits the extracted finalized collection. `package-verification.json` records the local result outside the archived payload, avoiding a checksum cycle.

Stop and return the complete report. Expected: status passed, checks inventory/archive_integrity/payload_roundtrip passed, no findings. Local packaging success is not a Yale upload, retention or publication result.

## Separate guided check of saved package

Completed2026-11-08: Danu reported the separate check passed at `2026-11-08T19:41:00.081646Z`, all three checks passed with no findings. Original local inventory/archive bytes and saved report remain unchanged. The following command is recorded history for this run.

After the first report and saved evidence are reviewed, Danu runs:

```bash
python3 -B -m scripts.export_idea_json verify-package backup/idea-pilot-package-001
```

Stop and return the complete report. This reads existing package bytes and extracts only into empty temporary storage; it does not rewrite the package or finalized collection. A corrupt inventory, archive, saved report, path set or extracted payload must be reported rather than refreshed.

On failure retain all output, including pending inventory/partial archives, and return the report. Do not replace the finalized collection or silently delete partial package evidence to retry. Review the concrete failure before a new output directory is chosen.

## Later operational gate

Local review is complete. Follow [retention-test.md](retention-test.md) to establish the actual Yale dataset/draft destination, depositor access, required metadata and upload method. The offline supplied-download checker is implemented, with 302 full-suite tests passing. A separately guided draft retention test must upload the candidate archive(s) plus external inventory, download all deposited files, compare the downloaded inventory with the local baseline and verify archive/all-payload roundtrip. Record actual dataset/version/file identifiers and acquisition evidence. No upload, colleague contact or publication is implied by local packaging.

Full 33,709-item collection still needs its own reviewed service-feasibility and operational gate. Synthetic scale checks establish bounded implementation behavior, not live population sizes, runtime, service endorsement or upload handling. Full package/deposit verification and publication remain separate outcomes.

Implementation evidence: [increment log](production-log.md), [scale review](../../review/idea-json-backup-scale-review-2026-11-07.md) and [archive-stage review](../../review/idea-json-backup-archives-review-2026-11-08.md). These are offline implementation/review results; Danu has now created the actual pilot package and reported passed; its separate saved-package check has also passed. The next operational gate is a guided Yale draft retention test after destination/access and offline deposit checking are ready.

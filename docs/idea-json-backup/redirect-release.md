# Reviewed redirect release

Approved outcome2026-11-08:33,708 usable item JSONs plus an explicit Q134471369→Q122677115 redirect record, retaining all33,709 frozen IDs. Danu chose redirect-record-only; historical JSON retrieval is excluded. This addendum implements that choice without changing the existing collection's records or legacy strict result.

## Preservation boundary

The original run remains format idea-json-backup1.0.0 with33,708 accepted/1 unresolved. Its strict verification remains failed for the unavailable QID. Improve diagnostics so this known scope failure does not prevent counts and full accepted-content/provenance/file checks. It must continue to detect corruption and never make an incomplete legacy run pass.

Create a separate, self-contained resolved release in an absent output directory. Copy every public collection byte unchanged under collection/, excluding private .state/. Do not use hardlinks. Hold the original run lock, reject pending payload/finalization intents, audit and fingerprint source files, stream-copy, then independently audit the copy and recheck the source fingerprint. Retain failed/pending output; never overwrite or reuse a directory. This costs one additional public-payload copy and needs a guided capacity review before operation.

The release adds release.json, redirect-resolutions.json, strict-verification.json, verification.json and README.md. The receipt binds the exact run/generation/frozen-list/public-record descriptors, preserved unavailable response and already-accepted target descriptor. The stub proves unavailability under redirects=no; the target mapping remains explicitly operator_recorded. Unknown observed_at stays null; actual record-creation time is separate.

The independent release audit must require all original non-scope checks passed, only the expected unavailable-QID scope findings, no pending items, and exact redirect coverage of the unresolved set. Require a matching missing stub in a complete successful response, a distinct ordinary accepted target in the same frozen selection, and exact descriptors. Reject stale/extra/self/chained/duplicate mappings, unsafe paths, changed bytes or unsupported claims. No old-QID file may be fabricated from the target's JSON.

## Versioned completion basis

The release uses distinct format idea-json-backup-release, version1.0.0, and completion_basis usable_items_and_reviewed_redirects. Its counts explicitly distinguish selected/usable_items/redirected/pending/unresolved. For this case:33,709/33,708/1/0/0. The original counts and failed strict report remain in the nested collection/evidence. A passing release report means reconciled release verification, not33,709 ordinary entity JSONs or a verified deposit/publication.

Metadata binds source manifest/inventory/attempt/QID-list descriptors, resolution record, strict report and README. The release marker does not hash its own verification report. Its verification report binds the exact release-marker bytes and is published before the final marker, avoiding a checksum cycle. Use owned pending files, recheck inputs before publication and publish release.json last. Partial output is not a finalized release and is retained for review; this small release producer does not resume a failed copy.

## Packaging and guided workflow

Add explicit create-release, verify-release and package-release commands. Existing collection/finalization/package commands keep their original meaning. A package-inventory1.1.0 branch identifies payload_kind resolved_release; the bounded tar.gz format/caps and all-payload comparison remain unchanged. Its independent extractor dispatches to verify_release for the new payload. Legacy inventory1.0.0 packages continue to dispatch to strict finalized-collection verification. Deposit comparison continues to validate every downloaded byte and independently audit the payload; its acquisition/publication rules are unchanged.

Use small offline RED→GREEN/local commits: diagnostic audit; pure record contract; independent release audit; safe release creation; release packaging/CLI. Perform separate producer/verifier reviews and a final invented integrated workflow. Danu then runs the original strict diagnostic audit to a new external report, reviews actual full-run capacity, creates the separate release, checks it independently and packages it. The assistant does not run operational commands, retrieve entities, upload or publish.

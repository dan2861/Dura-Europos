# Proposed treatment of one redirect in the frozen selection

Status: **Danu approved the redirect-record-only outcome on2026-11-08.** Preserve33,708 usable JSONs plus explicit Q134471369→Q122677115 redirect accounting; do not retrieve historical pre-redirect JSON. The implementation addendum is [redirect-release.md](../../docs/idea-json-backup/redirect-release.md). Operational commands remain guided; approval does not claim a completed release or deposit.

## Evidence

- Frozen scope:33,709 QIDs. Saved run records33,708 accepted,0 pending,1 unresolved.
- A000623 preserved the complete HTTP200 response containing `{"id":"Q134471369","missing":""}`. The other49 requested items were accepted. The request used redirects=no.
- Danu inspected the page and reports Q134471369 redirects to Q122677115. This mapping is operator-reported; the assistant did not retrieve the page or entity.
- Q122677115 is already accepted in the same frozen selection: items/Q122677115.json,9,593bytes, revision2506727154, retrieved2026-11-09T02:05:51.352649Z from A000372. Its saved membership check matches. The target's recorded SHA-256 is4874cd8e602fc2961d15976bd8fc4189c250a04e91ca7843b60882d1abd24d53; no new assistant rehash was run.

## Recommended outcome: explicit redirect exception

Preserve33,708 usable item JSONs and a separate explicit Q134471369→Q122677115 redirect-resolution record. Keep every original frozen QID, source response, attempt and accepted revision. The target remains stored under its own QID; do not duplicate or rename its content as the old entity.

The resolution record must identify both QIDs, the saved unavailable response/attempt, operator-supplied page evidence and the already-saved target descriptor. Unknown observation time stays unknown; record/report creation time must not be substituted for the earlier observation. Final verification must independently audit every usable item and source/file provenance, require the target to be accepted, and reconcile33,709 requested IDs as33,708 usable entities plus1 explicitly resolved redirect. No other unavailable item is automatically covered by this decision.

Keep the existing strict failed report/evidence intact. Any new release/report must identify its reviewed completion basis and versioned record contract, with distinct JSON and redirect counts. Do not label all33,709 IDs as ordinary accepted item JSONs or silently turn the original failure into a pass. Final packaging must preserve the frozen scope, original diagnostic stub and the resolution evidence.

This requires a limited reviewed addendum to design.md sections4/7 and a versioned record-layout/verification plan before implementation. The current Spec requires a usable matching item for every frozen QID; it has no approved redirect-completion exception. Offline implementation would follow the existing incremental TDD, milestone and integrated-review workflow. Operational checks/package/deposit remain guided, and publication remains separate.

## Alternative: add historical pre-redirect JSON

If Danu also needs the old entity's content, identify and preserve a historical pre-redirect revision in addition to the redirect record. Its revision/time and historical nature must be explicit; it cannot be presented as current JSON retrieved during this collection. This adds guided historical retrieval and a separately reviewed preservation contract. No historical revision or source is assumed available, and no retrieval is authorized or performed by this proposal.

# IDEA JSON backup: first MVP

Delivery direction requested by Danu on 2026-10-28: start with an MVP. The full [Plan](plan.md) is approved as the roadmap; this short document defines the first deliverable. Danu selected guided execution: Danu writes code/tests and runs commands, with the assistant explaining one TDD increment at a time. On 2026-11-02 Danu explicitly requested applying and committing the proposed first RED increment. The assistant added the stub and test and observed the expected failure: “Original response must be saved”. At Danu’s subsequent explicit request on the same date, the assistant applied the minimal preservation implementation and observed one passing focused offline test. Entity identity validation is the next guided TDD increment; this is not a completed MVP.

## Small working slice

For one supplied, frozen list of at most 50 QIDs and one batch response:

1. Preserve the unchanged response bytes.
2. Save each complete, identity-matched entity as its own QID.json, including unknown fields and exact numeric tokens.
3. Write a compact prototype manifest containing the input list, source provenance, per-item outcomes/revisions, file paths, sizes and checksums. Mark synthetic/saved/live provenance honestly; do not invent retrieval times for saved fixtures.
4. Independently compare every saved item with its original response object and verify the files' checksums. Fail visibly for missing, substituted or damaged data.

Start with saved/invented responses and temporary directories. Then add a one-batch retrieval adapter, tested offline. The adapter must still identify itself, enforce the request deadline, detect API errors and incomplete/undecodable bodies, and preserve partial/error evidence. No live run is part of implementing or testing it; an actual pilot needs its own request.

Use one attempt and a new output directory. No automatic retries, resume or overwriting of an earlier result. Failure/interruption retains whatever evidence was durably saved and leaves the result visibly incomplete; it cannot pass merely because some items were saved.

The output is explicitly a **prototype**, using a separate `idea-json-backup-mvp` format identity rather than claiming the complete production 1.0.0 schema. Its compact manifest is not a replacement for the approved final record layouts. MVP completion means verified preservation behavior and an offline-tested adapter, not a completed live IDEA backup or deposit.

## First test and review

First behavior: given an invented one-item batch, preserve its source bytes and the entire entity object, including an unfamiliar nested field with the string identifier `0007`. The first test checks those outputs; further tests add identity failures, precision, checksums and independent corruption detection in small increments. Explain each new behavior/test before execution and follow red–green–refactor. Existing codec coverage that already passes is regression evidence, not a manufactured failing test.

Deliver and review this MVP before expanding it. Its source/extraction/verification logic should remain separate from the later network scheduler and storage journal. A small separate assistant review checks data preservation and the adapter before presenting the result.

## Later deliverables

Add full-population discovery, batching across many requests, durable SQLite progress, resume/retry policy, 33,000-item checks, archive packaging and Dataverse verification in later reviewed increments. These remain requirements for the final system; they are not all part of the first MVP. The production [Spec](design.md) remains unchanged.

Danu selected guided execution on 2026-10-28. The assistant may inspect results and maintain planning/continuity documents; Danu performs application/test edits and command execution unless explicitly requesting otherwise. Each increment starts with the behavior and test explanation, followed by Danu's failing test result before implementation guidance.

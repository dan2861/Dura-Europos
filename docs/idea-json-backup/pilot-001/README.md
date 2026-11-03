# MVP pilot 001: prepared for a guided run

Prepared 2026-11-03 (America/Chicago). Status: **not run**. Danu authorized automatic offline TDD/local commits, with operational commands performed by Danu in guided runs. This packet prepares one live batch using the already tested MVP; it introduces no new collection behavior and no fabricated RED test.

## Frozen pilot scope and evidence

The exact supplied order is in [qids.txt](qids.txt). These are three convenience examples from existing local evidence, not a production selection bundle or a census. No current Wikidata entity was retrieved while preparing this list.

Baseline files are under `backup/20261020T050635.725535Z-609db4bfca20/original/`. Read-only inspection on 2026-11-03 found a normal-rank `P5008 = Q114241199` statement in each entity. Each file's size and SHA-256 matched its descriptor in the historical run manifest. This establishes local baseline consistency, not current membership or an unchanged live revision.

| QID | Saved revision | Saved modified | Baseline bytes | Selection purpose |
| --- | --- | --- | --- | --- |
| Q124840826 | 2557685621 | 2026-10-16T15:16:09Z | 42,993 | More statements; 41 observed |
| Q134471203 | 2429503129 | 2025-11-14T13:18:27Z | 28,937 | Intermediate record; 32 statements observed |
| Q122814653 | 2212079737 | 2024-07-24T19:07:42Z | 5,810 | Smaller record; 7 statements observed |

Statement counts describe the saved fixtures only. Different live revisions or contents are expected possibilities and do not by themselves indicate a preservation error. Selection does not resolve any LUX matching uncertainty.

## Access guidance checked before preparation

Official documentation was read on 2026-11-03; no item request was made:

- [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access#MediaWiki_Action_API) documents complete entity JSON in small groups, up to 50 per request, and cautions against large result sets. This three-item technical pilot does not establish suitability or endorsement for the eventual approximately 33,000-item workload.
- [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) supports serial grouped requests, compression and meaningful identification.
- [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) requires descriptive identification with a real contact route. The configured project URL matches this repository's Git remote: `IDEA-JSON-Backup/0.1.0 (https://github.com/dan2861/Dura-Europos)`.
- [Maxlag guidance](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter) recommends `maxlag=5`; HTTP 200 can still contain an API error. The MVP rejects such a response and does not retry.

## Guided command: Danu executes

From `/Users/danu/Documents/ChatGPT/Dura-Europos`:

```bash
python3 -B -m scripts.idea_json_backup collect \
  --qids docs/idea-json-backup/pilot-001/qids.txt \
  --output backup/mvp-live-001 \
  --description "MVP pilot 001: three QIDs selected from local 2026-10-20 evidence" \
  --timeout-seconds 60
```

`backup/mvp-live-001` did not exist when prepared. The command refuses any existing output directory. It sends one read-only batch, saves encoded and decoded evidence, extracts the complete items and invokes independent verification automatically. The maximum response deadline is 60 seconds; process startup is included. There is no automatic retry, resume or upload.

Expected success report: `{"status": "passed", "findings": []}` with exit code 0. A failure or interruption must be returned for review; retain its directory and do not rerun automatically or reuse that path.

Pause after this command and share the exact output. The next guided step is read-only verification of the persisted result:

```bash
python3 -B -m scripts.idea_json_backup verify backup/mvp-live-001
```

## Review before expansion

Record actual outcomes in `review/idea-json-backup-pilot-001.md` after Danu's run. Do not fill observations in advance.

1. Both the command's verification and the later persisted-file check pass with no findings; all three QIDs remain accounted for in supplied order.
2. Inspect saved request/receipt, HTTP status, times, encoding, decoded/encoded sizes and actual per-item revisions. Record errors explicitly; do not extrapolate one batch's duration into a full-run guarantee.
3. Inspect the complete saved `P5008` statements and ranks for all three QIDs. The MVP verifier checks preservation, not IDEA membership. A tag changed since the local baseline is a recorded membership difference, not permission to discard the QID.
4. Manually inspect at least one complete extracted entity and its matching source object, including a qualifier/reference or unfamiliar field, and confirm the receipt/revision linkage.
5. Hold for review on warnings, HTTP/API failures, missing/redirected items, framing/decode trouble, identity disagreement or verification findings. Keep every saved byte; no retry or expansion is automatic.

After the pilot review, resume the approved production roadmap with the first offline discovery-union TDD increment. Actual discovery, production collection and Dataverse upload/download remain guided operational steps. Yale destination, access and archive-retention details are later clarifications. Publication and Wikidata edits are outside this packet.

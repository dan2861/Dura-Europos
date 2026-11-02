# IDEA JSON backup: initial research

Date: 2026-10-28. QRSPI stage: Research, preliminary findings. This is not an approved specification, implementation plan or completed full backup.

## Requirements carried forward

Danu requests one export before LUX edits, approximately 33,000 items, complete JSON and archive downloads in Yale Dataverse. A documented collection period is acceptable. Select items with at least one normal/preferred P5008 = Q114241199 statement; deprecated-only matching tags do not qualify. Freeze the selected QID list at the start, with later membership changes reported separately (confirmed on 2026-10-28). Preserve all ranks and other content within every selected item. Archive format/limits still need an instance-specific check. See [brief.md](brief.md).

## Population selection

Wikidata's direct/truthy predicates return best-rank values. The confirmed rule therefore needs explicit statement/rank filtering: a normal IDEA tag must still qualify when another P5008 value is preferred. [Official RDF rank semantics](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format#Truthy_statements).

Candidate selection query, **not executed**:

```sparql
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT DISTINCT ?item WHERE {
  ?item p:P5008 ?statement .
  ?statement ps:P5008 wd:Q114241199 ;
             wikibase:rank ?rank .
  VALUES ?rank { wikibase:NormalRank wikibase:PreferredRank }
}
ORDER BY ?item
```

The public query graph is split: query.wikidata.org contains the main graph and query-scholarly.wikidata.org the scholarly graph. An all-item census must cover both and deduplicate their union, or document an explicitly narrower scope. We have not established whether any IDEA items occur in the scholarly graph. [Official graph-split documentation](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_graph_split).

WDQS updates are asynchronous, so a query result and later entity response can differ. Query text, endpoints, raw results, timestamps and the exact QID list should be preserved. A query result is not proof of a perfectly synchronized Wikidata state. [WDQS implementation](https://www.mediawiki.org/wiki/Wikidata_Query_Service/Implementation#Usage_constraints).

**Confirmed scope policy (2026-10-28):** freeze the selected QID list before collection, and report later membership changes separately. Define completeness against this recorded selection. Proposed exception handling remains to be specified: report deleted items and identity differences without silently dropping requests or changing the target. Whether to run an end-of-collection membership comparison is a separate specification detail.

## Collection options

The official access guide distinguishes individual complete-entity retrieval, small batched API retrieval, and full dumps. It discourages EntityData and Action API use for large quantities and does not state that a 33,000-item job is automatically an approved bulk workload. [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access).

| Route | Documented behavior | Implication for this backup |
| --- | --- | --- |
| One EntityData response per item | Intended for known individual complete entities; not large-volume collection | Closest to the sample's byte-preserving route, but not selected for the full job merely because it already exists |
| Batched wbgetentities | Ordinary limit is 50 IDs; defaults cover all available attributes and languages; redirects default to yes | Practical candidate, subject to access guidance and measured feasibility; batching reduces request count |
| Dated full JSON dump | Weekly JSON dumps contain complete entity objects and require substantial download/processing resources | Alternative if targeted collection is unsuitable; select and extract from the same dump rather than mixing current membership with an older dump |

[Generated wbgetentities documentation](https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities); [official dump documentation](https://www.wikidata.org/wiki/Wikidata:Database_download).

33,000 / 50 = 660 batches before discovery, retries or errors: arithmetic, not a runtime estimate or service guarantee. Batch extraction also changes provenance: a per-item file serialized from a batch is a derived representation, not the original HTTP response. Retaining exact batch responses plus per-item extraction provenance is a candidate design; its storage/layout and numeric preservation must be specified if this route is chosen. Do not silently label reconstructed files original response bytes.

Unattended Action API guidance supports serial requests, compression, a descriptive User-Agent with genuine operator contact, maxlag handling and backoff. Inspect JSON error bodies even after HTTP 200; maxlag may be reported there. Honor Retry-After and published 429/503 handling rather than running at a nominal ceiling. Rates must be checked again when execution is scheduled. [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter), [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy), [rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).

**Research recommendation, not a route decision:** evaluate a controlled, checkpointed batch collector first, with a dump as the alternative. A later explicitly requested pilot should establish endpoint behavior, response completeness, timing and storage requirements. No pilot was run. Define bounded retries, interruption recovery, no-overwrite rules and unresolved-failure reporting in the new specification; they are preservation design recommendations, not assertions that the old sample supports them.

## Existing local evidence and reusable code

Read-only inspection of `backup/20261020T050635.725535Z-609db4bfca20/original/` found 15 JSON files totaling 292,206 bytes. Minimum: 5,810; maximum: 88,246; mean: 19,480.4; median: 11,418 bytes. If 33,000 files had this same mean, originals would total 642,853,200 bytes (about 643 MB uncompressed). This convenience sample is not representative: the calculation is a planning scenario, not a capacity forecast or upper bound. It excludes inventory, logs, batch/failure responses, temporary files, archives and extra copies. Compression and live runtime are unmeasured.

| Existing code | Potential reuse | Constraint |
| --- | --- | --- |
| [Input/collection](../../scripts/export_sample_backup.py) | Exact QIDs, explicit outcomes, save before success | Existing outcomes cannot be resumed/retried; orchestration also projects five CSV tables |
| [Retrieval](../../scripts/sample_backup/retrieval.py) | Deadline supervision, redirect trace, partial-body capture | Sample-specific endpoint/settings and a spawned worker per retrieval; batching is not implemented |
| [JSON codec](../../scripts/sample_backup/jsoncodec.py) | Strict parsing, duplicate-key rejection, preserved number tokens | Extraction/serialization provenance still needs a new contract |
| [Storage](../../scripts/sample_backup/storage.py) | Atomic/no-clobber writes, safe paths, byte checksums | Creates sample tables and refreshes the whole inventory on every checkpoint |
| [Validation](../../scripts/sample_backup/validation.py) | Independent identity/integrity checks; normal/preferred IDEA membership recognition | Hard-codes sample manifest, five CSVs and six categories; not the JSON-only validator |

The collection loop checkpoints after every item (`export_sample_backup.py`, collect_requests). RunStore.checkpoint calls inventory, which rereads/hashes already produced files (`storage.py`, inventory/checkpoint, lines 145–165). Repeating this across a growing run creates quadratic cumulative original-file I/O. This follows from code inspection; no full-scale performance test was run. Incremental inventory updates plus a separate final verification pass are a design candidate, not an implemented fix. Preserve the historical sample code while designing the new versioned JSON-only contract.

## Yale Dataverse packaging

Yale's guide allows individual files/folders or compressed packages, normally extracting ZIPs; saving a draft is separate from publication. Alternative upload handling is available when normal extraction/size behavior is unsuitable. [Yale quick start](https://researchdata.yale.edu/yale-dataverse-quick-start-guide).

Yale's FAQ currently documents up to 8,000 files inside a ZIP, cautions about ZIPs above 2.5 GB, and states up to 1,000 files uploaded at once. Thus file count matters independently of byte size; 33,000 item files should not be assumed to fit one normal ZIP upload. These are published settings, not a tested account/dataset limit. [Yale FAQ](https://researchdata.yale.edu/yale-dataverse-faqs).

Generic Dataverse documentation describes configurable ZIP extraction (a generic default is not Yale's actual configuration), file-path handling, and DVUploader for many files with restart/fixity options. Installation-specific upload choices must be checked. [Dataset/file management](https://guides.dataverse.org/en/latest/user/dataset-management.html).

**Confirmed delivery choice:** Danu selected archive downloads containing the separate per-item JSONs. Multiple bounded archive parts are the proposed implementation. Do not choose part sizes or claim archive retention until an explicitly requested draft test confirms Yale's handling. Retain a local copy, inventory and README; verify downloaded original bytes and extracted per-item checksums against the pre-upload inventory before claiming successful deposit. No draft dataset/upload was created and no administrator was contacted.

## Focused API contract check

The documented default props are info, sitelinks, aliases, labels, descriptions, claims and datatype; `props=all` is not a documented option. Omitting language/site filters retains the available language/site data; language fallback is off by default. Pin JSON format version and test the expected ID-keyed entity mapping rather than assuming response order. With redirects=no, redirects are treated like missing/deleted entities, so a missing stub must not be labeled definitely deleted. Batch success can coexist with missing items. These details inform the now-approved specification; no entity request was made. [Generated module help](https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities), [Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API#Response), [JSON version 2](https://www.mediawiki.org/wiki/API:JSON_version_2), [official GetEntities source](https://raw.githubusercontent.com/wikimedia/mediawiki-extensions-Wikibase/master/repo/includes/Api/GetEntities.php).

## Research status and next decisions

- Confirmed membership and collection-period requirements are in the brief.
- Frozen selection and archive downloads are confirmed. Archive format/retention is still an instance-specific check.
- The approved Spec adopts the pilot-gated API route, source/extracted-file contract and bounded retry/recovery requirements. The draft Plan makes their implementation and record layouts concrete; no live performance claim is established.
- Exact Yale collection/dataset destination, depositor access, chosen upload mode and post-upload byte verification remain to be established.
- The approved Spec explicitly excludes media/history/recursive linked-entity retrieval from the current structured-record export.
- Danu approved [design.md](design.md) and subsequently [plan.md](plan.md) on 2026-10-28, requesting [MVP-first delivery](mvp.md) rather than implementing the entire roadmap at once. Danu subsequently selected guided execution: Danu writes code/tests and runs commands with step-by-step guidance. No new code, tests, selection run, entity retrieval, external edit, deposit or Git operation occurred during this Research/Plan work.

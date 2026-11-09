# Proposed production dataset metadata

Prepared 2026-11-09. Danu enters this in a new draft dataset within the intended IDEA Dataverse collection. For creation of the collection itself, use [dataverse-collection-metadata.md](dataverse-collection-metadata.md). The existing three-item pilot dataset remains separate. This file is a proposal, not evidence that a dataset has been created or uploaded.

## Title

IDEA-tagged Wikidata items — JSON preservation export, November 2026

## Author and contact

Use Daniel Metaferia and the appropriate affiliation/contact details already used for the pilot. No affiliation or email address is inferred here. Add other authors only when appropriate and confirmed by the operator.

## Description

This dataset preserves a frozen selection of 33,709 Wikidata item identifiers carrying a normal- or preferred-rank P5008 (on focus list of Wikimedia project) statement for Q114241199 (IDEA). It contains 33,708 complete usable item JSON files and one documented redirect resolution, Q134471369 → Q122677115, accounting for every selected identifier. The redirect mapping is operator-recorded; its original observation time was not recorded. The unavailable item's saved API response is retained; no historical pre-redirect item JSON is supplied.

The export records a collection period rather than a single historical instant. Each usable item retains its complete retrieved JSON content, including statements, ranks and unknown fields. Supporting materials preserve the frozen selection, source responses, revision/retrieval provenance, checksums, audit reports, method and limitations. Media files and complete revision histories are outside the scope.

Delivery consists of package-inventory.json and eight tar.gz archive parts, which together preserve the release payload. All eight parts are needed to recover the entire release. The package passed independent local inventory, archive-integrity and payload-roundtrip verification before deposit.

## Suggested subject and keywords

Subject: Arts and Humanities, if offered by the collection.

Add five separate keyword entries using the form's add-another-keyword control. These are proposed free-text keywords; no controlled vocabulary has been selected.

| Term | Term URI | Controlled Vocabulary Name | Controlled Vocabulary URL |
|---|---|---|---|
| IDEA | Leave blank | Leave blank | Leave blank |
| Wikidata | Leave blank | Leave blank | Leave blank |
| Dura-Europos | Leave blank | Leave blank | Leave blank |
| JSON | Leave blank | Leave blank | Leave blank |
| digital preservation | Leave blank | Leave blank | Leave blank |

“Leave blank” is an instruction, not text to enter. Do not put all five terms in one semicolon-separated entry.

Term is the keyword label. Term URI identifies that particular concept. Controlled Vocabulary Name identifies the vocabulary from which a term was selected, and Controlled Vocabulary URL points to information about that vocabulary. A keyword being “Wikidata” does not by itself make Wikidata the controlled vocabulary for the keyword list. The three supporting fields can remain empty for this free-text proposal; if the local form explicitly requires them, review that requirement before supplying values.

Field meanings checked against the official [Dataverse Citation metadata definition](https://github.com/IQSS/dataverse/blob/master/scripts/api/data/metadatablocks/citation.tsv), linked from its [metadata appendix](https://guides.dataverse.org/en/latest/user/appendix.html). The local form's field names are operator-reported; no external metadata was edited by the assistant.

## Related publication

Leave this section blank for now. No article or report using this export has been identified in the discussion; this is not a claim that no relevant publication exists. Do not enter “N/A” or invent a citation.

Dataverse defines this field for an article or report that uses the dataset. If an applicable publication is identified, enter its full bibliographic citation, identifier type (for example DOI), the actual identifier, and its corresponding URL. If a Relation Type field appears, choose the relationship supported by that publication. Confirm the publication before entering values.

The pilot dataset DOI belongs under Related Dataset if included; the Wikidata source and the export code repository should be documented in the appropriate source/software or related-material fields. They do not supply a publication citation by themselves. Field meanings are from the official Citation metadata definition linked above.

## Operational sequence

1. After creating or selecting the intended IDEA collection, create and save a new draft dataset using that collection's Add Data → New Dataset action. Keep the pilot dataset separate.
2. Return the new draft dataset URL before uploading, so the production destination is recorded explicitly.
3. Later upload exactly package-inventory.json and part-00001.tar.gz through part-00008.tar.gz from backup/idea-production-package-001. Keep package-verification.json as local audit evidence.
4. Check that Dataverse retains the archive parts as files, then download all nine deposited files, recording actual dataset/version/file IDs, URLs and download completion times. Verify those downloads locally with the guided deposit command.
5. Publication is a separate step after deposit verification and an explicit request.

Official UI guidance checked read-only: [Yale Dataverse Quick Start Guide](https://researchdata.yale.edu/yale-dataverse-quick-start-guide). Saving a dataset leaves it unpublished. The pilot demonstrated byte preservation for its own archive; the production files still need their own upload/download verification.

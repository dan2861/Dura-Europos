# IDEA JSON backup fixture provenance

Discovery-stage fixtures are invented inline in the test modules, then written only to temporary directories. They describe SPARQL result shapes, HTTP receipts, compressed bodies, retry timing and deliberately damaged artifacts. None is an observed census or evidence of live service behavior.

Selection verifier fixtures are built independently of the selection producer. Worker integration tests inject invented HTTP responses and deny external socket connections. The discovery CLI tests mock the operational handler; the assistant does not run live discovery during TDD.

The older sample regression tests may read existing saved local evidence. They do not retrieve new entities. Actual guided pilot results remain separately under backup/mvp-live-001 and are not silently relabeled as invented fixtures or full-population evidence.

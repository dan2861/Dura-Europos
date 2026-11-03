# IDEA JSON backup fixture provenance

Discovery-stage fixtures are invented inline in the test modules, then written only to temporary directories. They describe SPARQL result shapes, HTTP receipts, compressed bodies, retry timing and deliberately damaged artifacts. None is an observed census or evidence of live service behavior.

Selection verifier fixtures are built independently of the selection producer. Worker integration tests inject invented HTTP responses and deny external socket connections. The discovery CLI tests mock the operational handler; the assistant does not run live discovery during TDD.

The older sample regression tests may read existing saved local evidence. They do not retrieve new entities. Actual guided pilot results remain separately under backup/mvp-live-001 and are not silently relabeled as invented fixtures or full-population evidence.

Production storage, recovery, parent-linked pilot and finalization fixtures are also invented in temporary directories. Independent public-verifier fixtures do not call extraction or use SQLite to supply expected values. Controller integration exercises the actual spawned capture and journal with an invented streamed gzip response and sockets denied. Corruption/crash tests deliberately change only temporary evidence, including failed responses, diagnostics, publication stages and finalization inputs. These tests establish implementation behavior, not live service or 33,709-item scale performance.

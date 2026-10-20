# Fixture provenance

All fixture builders and transport doubles in `tests/test_sample_backup_*.py` are invented test data unless a test explicitly names the saved Q124840826 response. They are kept inline beside independently stated assertions; no downloaded sample response is relabeled as synthetic.

- `test_sample_backup_transform.py`: invented entity/snak/statement builders; text maps, special snaks, ranks, ordered children, reference groups, media encoding, compound precision, malformed structures. The separately named real regression reads the unchanged saved review response at its documented SHA-256.
- `test_sample_backup_retrieval.py`: invented Response/Transport objects and spawned slow/deep-body workers. example.invalid URLs are inert labels passed to doubles; no public endpoint is contacted. The production opener is mocked in the client-configuration test.
- `test_sample_backup_validation.py`: temporary invented attempts and intentional semantic/inventory corruption. Invented manual evidence is only for status/gating tests.
- `test_sample_backup_integration.py`: temporary input lists and explicit fake fetch functions. No live export command is invoked.

All generated run-like artifacts use TemporaryDirectory. Raw project evidence, sources/, config/sample-items.txt and production backup/ are not modified by the suites. Tests for invalid cases may expect failed/not_checked statuses; that is correct failure handling, not a validated backup of malformed data.

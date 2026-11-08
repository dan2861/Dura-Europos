"""Immutable run-scope documentation; explicit offline completion for older runs."""
import stat

from scripts.sample_backup import jsoncodec as codec

from .files import describe


def readme_bytes(manifest):
    """Use immutable identity/settings only; actual progress stays in public records."""
    selection = manifest["selection"]
    return (f"""# IDEA JSON backup run

Run ID: {manifest['run_id']}
Run kind: {manifest['run_kind']}
Frozen QIDs: {codec.dumps(selection['selected_count'])}
Frozen QID list SHA-256: {selection['qid_list']['sha256']}

Scope and method

The frozen selection is selection/qids.txt; selection/ retains the query,
discovery evidence and any complete production parent for a pilot subset.
A pilot or synthetic run covers only its declared selection.
Items are retrieved in serial batches of up to 50 using wbgetentities.
The exact endpoint, parameters, identifying User-Agent and runtime are in
manifest.json and each attempts.jsonl record.

responses/ preserves received response-body bytes at the recorded encoded and
decoded layers, including earlier errors and any partial diagnostic evidence.
items/ contains extracted item JSON: complete returned entity objects with
strings, number tokens, types, arrays and unknown fields preserved.
The extracted serialization may differ in formatting and object-key order.

Collection takes place over a documented collection period, not one historical
instant. Consult manifest.json for the actual start/finish interval and
inventory.jsonl for each accepted revision and retrieval time. The scope excludes
media bytes, full revision history and recursive retrieval of linked entities.

Progress, verification and recovery

manifest.json records phase/counts, method and public snapshot descriptors.
inventory.jsonl accounts for every frozen QID; attempts.jsonl retains request,
receipt, retry and source provenance, including attempts before later success.
verification.json is created only by explicit finalization after independent
verification. A populated directory or collected phase alone does not establish
a complete verified backup, a Dataverse deposit or publication.

.state/ contains local lock, SQLite journal and recovery artifacts. Retain it
locally for recovery and exclude it from deposited collection payload.
Resume the same unfinalized run with unchanged selection/settings, retaining
accepted revisions, cooldowns and the maximum three attempts per QID.
Do not overwrite accepted evidence, reset quota or infer complete responses
from parseable partial bytes. Corruption or uncertain receipt requires review.
Finalized payload is immutable. Archive packaging and Dataverse deposit/download
verification are separate later operations; keep the local verified copy.
""").encode("utf-8")


def check_readme(store, *, missing_ok=False):
    path = store.path("README.md")
    if not path.exists():
        if missing_ok:
            return False
        raise ValueError("Run README is missing; use explicit write-readme before continuing")
    if not stat.S_ISREG(path.stat().st_mode) or path.read_bytes() != readme_bytes(store.manifest):
        raise ValueError("Run README differs from its immutable scope; review required")
    return True


def write_readme(run_dir):
    """Publish only missing scope documentation, under the existing writer lock."""
    from .state import RunState
    with RunState.open(run_dir) as store:
        if store.manifest["phase"] not in ("initialized", "paused", "collected"):
            raise ValueError("write-readme requires a stopped, unfinalized run")
        if store.get_internal("finalization") is not None or store.internal_items("payload:"):
            raise ValueError("Pending publication requires review before documentation")
        body = readme_bytes(store.manifest)
        created = not check_readme(store, missing_ok=True)
        if created:
            store.publish("README.md", body)
        return {"status": "passed", "findings": [], "created": created,
                "file": describe("README.md", body)}

# G0 evidence contract

`gate.py` writes `schema_version: 1` JSON atomically. The file records the
content-addressed parser image, exact fixture-manifest hash, three or more
cold and post-cold **short-lived** execution hashes, source-snapshot hashes,
OCR scores, typed malicious and oversized-input rejections, recovery runs,
container/network orphan scans, strict sandbox probes, a controlled
same-image network positive control, Compose secret positive control, cgroup
runtime/resource observations, and the final `evaluate_g0` decision.

The browser runner supplies a separate artifact to `--browser-evidence`:

```json
{
  "schema_version": 2,
  "attestation": {
    "nonce": "<fresh non-empty token>",
    "manifest_sha256": "<lowercase sha256>",
    "policy_sha256": "<lowercase sha256>",
    "extraction_image_id": "sha256:<64 lowercase hex>",
    "provenance_sha256": "<lowercase sha256>"
  },
  "fixtures": {
    "pdf/text-korean.pdf": {
      "selected_count": 1,
      "target_anchor_set_hash": "<lowercase sha256>",
      "deep_link_match": true,
      "geometry_match": true,
      "external_requests": 0
    }
  }
}
```

The gate deletes the requested output before launching `npm test`, supplies the
attestation through environment variables, and rejects stale, missing, extra,
duplicate-key, malformed, or hash-mismatched output. Every golden manifest
path must be present exactly once. Each proof must have exactly those five
fields and must be produced from the host-validated extraction payload; the
schematic viewer fixture is not gate evidence.

Example (after the image, canonical manifest, and real browser artifact exist):

```powershell
.\.venv\Scripts\python.exe spikes/document-ingestion/gate.py `
  --image axit-ingestion-g0:local `
  --fixture-root tests/fixtures/document-ingestion `
  --manifest tests/fixtures/document-ingestion/manifest.v1.json `
  --browser-evidence .omx/state/g0/browser-evidence.v2.json `
  --output .omx/state/g0/g0-evidence.v1.json
```

Exit status is `0` only for `GO`, `1` for evaluated `NO_GO`, and `2` when a
structural harness error prevents trustworthy evaluation. Runtime evidence and
the output file contain no original document text or secret values.

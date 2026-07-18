# G0 citation anchor browser proof

This intentionally dependency-light static viewer proves that host-validated G0 extraction anchors resolve to the same browser target without contacting an external origin. The committed payloads are real successful `sandbox_runner.execute_sandbox` envelopes, not hand-authored or schematic extraction data.

## Run

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm --filter @axit/g0-document-viewer-proof test
```

If the pinned bundled Chromium is not installed on a Windows workstation, use the installed Edge Chromium channel without changing the test contract:

```powershell
$env:AXIT_PLAYWRIGHT_CHANNEL = "msedge"
npm test --prefix spikes/document-ingestion/viewer
```

`npm test` first removes the configured evidence target, verifies every committed envelope against the canonical fixture manifest, source bytes, approved parser identity, canonical anchor hashes, ordered anchor-set hash, and content-addressed capture provenance. It then starts a loopback-only static server and drives a real Chromium browser through Playwright 1.61.0. A passing serial suite writes `evidence/browser-evidence.v2.json` by default; the output is not recreated if an earlier proof fails.

The G0 gate must instead supply a fresh **absolute** output path and a source-bound attestation:

```powershell
$env:AXIT_G0_BROWSER_EVIDENCE_PATH = "C:\absolute\fresh-browser-evidence.v2.json"
$env:AXIT_G0_BROWSER_ATTESTATION_JSON = '{"nonce":"gate-generated-nonce","manifest_sha256":"<current manifest hash>","policy_sha256":"<current policy hash>","extraction_image_id":"sha256:<current image id>","provenance_sha256":"<current viewer provenance hash>"}'
npm test --prefix spikes/document-ingestion/viewer
```

The viewer recomputes the manifest, policy, and provenance digests from the current working tree, reads the extraction image ID from `fixtures/provenance.v1.json`, and rejects any supplied mismatch. The resulting v2 JSON has exactly `schema_version`, `fixtures`, and `attestation`; `attestation` has exactly the five fields above. A normal standalone run remains useful but is explicitly local: it writes the same source-bound hashes with `nonce: null`. The gate must reject a null or absent nonce.

To intentionally refresh payloads after rebuilding the parser image:

```powershell
uv run python spikes/document-ingestion/viewer/fixtures/capture_real_payloads.py `
  --image axit-ingestion-g0:local
node spikes/document-ingestion/viewer/fixtures/build-fixtures.mjs --check
```

The capture command runs all nine golden manifest inputs through separate sandbox containers. `hwp/table-footnote.hwp` is run twice independently, so ten exact envelopes are retained. `fixtures/provenance.v1.json` binds each payload to its manifest path, source SHA-256, media type, sandbox execution result, policy SHA-256, and resolved extraction image ID.

The E2E checks cover:

- PDF and image top-left normalized bounding boxes within one CSS pixel;
- complete HWP and HWPX base paragraph paths plus table index/block/row/cell/paragraph and footnote index/paragraph paths;
- exactly one highlighted source target after citation selection;
- deep-link reload restoration;
- all anchors in every golden document mapping to a source target;
- two independent real extraction runs resolving the same anchor hash to the same DOM id; and
- no request outside the loopback viewer origin.

The viewer accepts only same-origin `/fixtures/<slug>.json` payload paths. The server binds only to `127.0.0.1` and sends a deny-by-default content security policy.

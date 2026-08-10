# Phase 1 G0 document-ingestion spike

This directory is the disposable, blocking proof for the approved Phase 1
parser/OCR/sandbox gate.  It is deliberately separate from the production
domain and persistence contracts that are not allowed to start until G0 is a
GO.

## Proof order

1. Generate project-owned fixtures and pin their bytes, provenance, expected
   text, expected locator class, and typed failure in
   `tests/fixtures/document-ingestion/manifest.v1.json`.
2. Freeze the spike-only extraction envelope, anchor canonicalization, and
   hash rules before format adapters.
3. Execute the parser image through the host sandbox runner with a read-only
   staged input, bounded output, no credentials, no network, and explicit
   CPU/RAM/PID/wall limits.
4. Exercise real PDF, OCR, HWP, HWPX, PPTX, and XLSX implementations and the adversarial
   fixture/probe matrix.
5. Repeat cold and post-cold extraction in separate short-lived containers,
   then prove each locator class with a fresh nonce-bound browser
   click-to-highlight test.
6. Record versions, licenses, runtime measurements, limitations, and the
   GO/NO-GO decision in `docs/adr/0002-document-ingestion.md`.

Phase 2 stays blocked if any required locator, clean Korean OCR threshold,
sandbox boundary, license check, repeated anchor hash, or browser highlight
check fails.  This spike never calls xAI/Grok and its evidence says nothing
about production model quality.

## Reproduce a fresh G0 run

The browser payload/provenance must be recaptured whenever the image,
manifest, policy, or extraction implementation changes. The gate launches the
fresh browser proof itself; do not point it at a previously generated proof.

```powershell
$tmp = Join-Path $PWD '.omx/state/g0-local'
New-Item -ItemType Directory -Force $tmp | Out-Null
$env:TEMP = $tmp; $env:TMP = $tmp
$env:AXIT_PLAYWRIGHT_CHANNEL = 'msedge' # only when bundled Chromium is absent

.\.venv\Scripts\python.exe -m pytest spikes/document-ingestion -q --basetemp $tmp
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
.\.venv\Scripts\python.exe spikes/document-ingestion/viewer/fixtures/capture_real_payloads.py --image axit-ingestion-g0:local
.\.venv\Scripts\python.exe spikes/document-ingestion/gate.py `
  --image axit-ingestion-g0:local `
  --fixture-root tests/fixtures/document-ingestion `
  --manifest tests/fixtures/document-ingestion/manifest.v1.json `
  --browser-evidence "$tmp/browser-evidence.v2.json" `
  --output "$tmp/g0-evidence.v1.json"
```

The gate command writes deterministic, machine-readable evidence under a
gitignored runtime directory. Reviewed aggregate results are copied into the
ADR; raw documents and secrets are never written to logs.

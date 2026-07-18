# ADR 0002: Keep document extraction in a pinned, secretless parser sandbox

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

Meeting-source documents are untrusted inputs, but later phases need stable
extracted spans and anchors for citations and source highlighting. The first
milestone must support Korean text and scanned PDFs, HWP/HWPX paragraphs and
tables, and PNG/JPEG OCR without exposing host credentials, the Docker socket,
or the network to a parser process.

This is a document-ingestion decision only. It is independent from ADR 0001:
the deterministic `MockProvider` fixtures remain development-time provider
substitutes and are not an extraction provider, Grok experiment, or production
model-quality claim.

## Decision

Run each document extraction in a short-lived Docker container. The host
orchestrator stages a bounded, content-addressed copy of the input and validates
the typed JSON envelope before accepting anchors. The parser container is
non-root, read-only, has no network or secrets, no Docker socket, no retained
input mount, `no-new-privileges`, dropped capabilities, and a bounded tmpfs.
The approved policy is versioned at
`spikes/document-ingestion/policy.v1.json`:

- input: 20 MiB, at most 100 PDF pages, and 25,000,000 image pixels;
- archive: 256 entries, 20 MiB per entry, 64 MiB total, 100:1 expansion, and
  8 MiB XML;
- runtime: 20 seconds wall time, 768 MiB RAM/swap, one CPU, 64 PIDs, and a
  128 MiB tmpfs;
- result: 1 MiB stdout, 64 KiB stderr, 10,000 blocks, and 1,000,000 total
  extracted characters.

The image is content-pinned in
`spikes/document-ingestion/Dockerfile`. It uses Python 3.12.11 and uv 0.11.29,
Pillow 12.3.0, pypdfium2 5.12.1, Debian Tesseract 5.3.0 and Leptonica 1.82.0,
the SHA-256 verified `tessdata_best` Korean model at commit
`e12c65a915945e4c28e237a9b52bc4a8f39a0cec`, hwplib 1.1.10, hwpxlib 1.0.9,
and OpenJDK 17. Component licensing and notices are recorded in
`spikes/document-ingestion/licenses.lock.json`.

Anchors use the approved canonical coordinate contract and hash their
canonical JSON. HWP/HWPX parsing is an explicit Java sidecar protocol rather
than a fallback to opaque line numbers. The viewer receives only
host-validated envelopes and proves a real browser can resolve the canonical
anchor to one same-origin highlight target.

## G0 evidence

The original pre-remediation result is superseded and must not be treated as
G0 evidence: its repeated “warm” samples reused a long-lived container rather
than the approved short-lived staging boundary.

The clean local rerun on 2026-07-18 returned **GO** with no blockers using
image `sha256:a5a293b071adc6629a7dec5764657ea6e4a073fe0c82c545519bda1c9f36bc04`
and manifest `287b3fee1bd68fda28bf3547c38d16b419ed7a28ea1584c4311c4a9d1771d856`.
It passed all 88 **gate checks**: three cold and three post-cold, independently
staged short-lived executions for each of nine golden fixtures; nine typed
malicious rejections and recovery runs; generated oversized-input rejection;
five boundary probes and their recoveries; and 16 containment checks. The
fresh nonce-bound browser proof, controlled same-image network positive
control, Compose secret positive control, image/manifest/policy/provenance
integrity checks, and bounded evidence leak scan all passed.

On the recorded Docker Desktop host (x86_64, 16 logical CPUs, 16,437,665,792
bytes memory, Docker 29.2.1), the run measured 1,062 ms cold start, 176,189,440
peak cgroup bytes, and 17 peak PIDs. The fixture set covers text and scanned
PDFs, HWP/HWPX including table-cell/footnote paths, clean and rotated JPEG/PNG,
Korean OCR at or above 90%, deterministic anchors and browser highlights, plus
corrupt, encrypted, oversized, traversal, polyglot, XXE, and zip-bomb inputs.

The generated evidence JSON SHA-256 was
`6803e7808722dbe5fbcbc56d78c1f6bf57fa7b1aa052d464d31823a006da7f40`.
The raw evidence JSON, browser evidence, and screenshots remain local,
gitignored verification artifacts; they are never committed. Their schema and
reproduction command are documented in
`spikes/document-ingestion/evidence/README.md` and the viewer README.

## Consequences

Phase 2 may freeze durable contracts only while this policy, parser identity,
normalization profile, anchor schema, and IPC validation remain explicit.
Changes to a parser/runtime, resource limit, anchor canonicalization, HWP
sidecar, or allowed format require a new G0 evidence run and an ADR amendment
before promotion. A Java 17 fixture-generation constraint and known parser
semantic limitations remain visible rather than being disguised as stable
extraction behavior.

No original document bytes are uploaded to third parties, and no credentials
are introduced. Future production storage, retention, or external-model work
requires its own decision record and must not treat this G0 proof as evidence
of Grok compatibility or factual-model quality.

## Reproduction

```powershell
$tmp = Join-Path $PWD '.omx/state/g0-local'
New-Item -ItemType Directory -Force $tmp | Out-Null
$env:TEMP = $tmp; $env:TMP = $tmp
$env:AXIT_PLAYWRIGHT_CHANNEL = 'msedge' # only when bundled Chromium is absent
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
.\.venv\Scripts\python.exe spikes/document-ingestion/viewer/fixtures/capture_real_payloads.py `
  --image axit-ingestion-g0:local
.\.venv\Scripts\python.exe spikes/document-ingestion/gate.py `
  --image axit-ingestion-g0:local `
  --fixture-root tests/fixtures/document-ingestion `
  --manifest tests/fixtures/document-ingestion/manifest.v1.json `
  --browser-evidence "$tmp/browser-evidence.v2.json" `
  --output "$tmp/g0-evidence.v1.json"
```

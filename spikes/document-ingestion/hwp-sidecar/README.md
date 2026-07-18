# HWP/HWPX G0 sidecar

This isolated Java 17 spike proves deterministic HWP 5 and HWPX extraction for the
Phase 1 G0 gate. It is a parser process, not a network service. The outer ingestion
runner is responsible for starting it inside the approved no-network/read-only/resource-
limited sandbox.

## Runtime contract

Build the jar and its runtime classpath:

```text
mvn --file spikes/document-ingestion/hwp-sidecar/pom.xml package
```

Invoke one document per process:

```text
java -cp "target/axit-hwp-sidecar-0.1.0.jar:target/dependency/*" \
  com.axit.ingestion.hwp.Main \
  --input /input/document \
  --media HWP \
  --profile-hash <lowercase-64-hex>
```

`--media` accepts only `HWP` or `HWPX`. Success exits `0`; every safe typed failure
exits `2`. Stdout contains exactly one bounded JSON value and the sidecar intentionally
writes nothing to stderr. Success uses `hwp-sidecar.v1`:

```json
{
  "extraction_profile_hash": "…",
  "ok": true,
  "parser": {"name": "hwplib", "version": "1.1.10"},
  "records": [
    {
      "kind": "paragraph",
      "locator": {"paragraph": 0, "section": 0},
      "text": "…",
      "text_fingerprint": "…"
    }
  ],
  "schema_version": "hwp-sidecar.v1",
  "source_sha256": "…",
  "warnings": []
}
```

All indexes are zero-based. A table record adds `table`, `table_block`,
`table_row`, `cell`, and `cell_paragraph`; a footnote record adds `footnote` and
`footnote_paragraph`. Text is normalized to NFC with LF line endings while preserving
meaningful whitespace. Its fingerprint is SHA-256 over the emitted UTF-8 text.

Failure JSON is stable and excludes input paths and third-party exception text:

```json
{"error":{"code":"CORRUPT_DOCUMENT","message":"…","retryable":false},"ok":false}
```

## Bounds and preflight

- one regular non-symlink input, non-empty and at most 20 MiB;
- at most 10,000 records, 100,000 code points per record, and 1,000,000 code points total;
- at most 1 MiB of stdout JSON;
- HWPX: at most 256 entries, 20 MiB per expanded entry, 8 MiB per XML entry,
  64 MiB expanded total, and a
  100:1 compression-ratio ceiling for every non-empty entry;
- HWPX paths, duplicates, non-UTF-8 XML, NULs, DTDs, and entity declarations are
  rejected before the third-party SAX parser runs;
- every HWPX entry is streamed once during preflight, so declared and observed sizes
  must agree.

The process sandbox remains mandatory because HWP is a complex binary parser and
resource bounds are defense in depth, not a proof that malformed inputs are harmless.

## Dependencies and scope

- [`kr.dogfoot:hwplib:1.1.10`](https://github.com/neolord0/hwplib), Apache-2.0,
  reads/writes genuine OLE2 CFB HWP 5 documents.
- [`kr.dogfoot:hwpxlib:1.0.9`](https://github.com/neolord0/hwpxlib), Apache-2.0,
  reads/writes HWPX packages.

These maintained permissive libraries were selected instead of the obsolete AGPL
`pyhwp` path. Encrypted documents are rejected. Endnotes produce
`UNSUPPORTED_ENDNOTE`; structured controls nested inside table-cell paragraphs produce
`NESTED_CONTROL_SKIPPED`. Paragraphs, top-level table cells, and footnotes are fully
located for the G0 fixtures.

## Synthetic fixtures

Run `spikes/document-ingestion/fixture_sources/hwp/generate.ps1` (or `generate.sh`).
The generator writes genuine `simple.hwp`, `table-footnote.hwp`, `simple.hwpx`, and
`table-footnote.hwpx`, plus
a deliberately truncated magic-bearing `malicious/corrupt.hwp`. Byte regeneration is
deterministic under the pinned Java 17 generator used by the `hwp-build` Docker stage;
the scripts reject other Java feature versions because ZIP timestamp metadata differs
between JDK implementations. Lane metadata, hashes, exact expected NFC text, provenance, and parser
versions are stored in
`spikes/document-ingestion/fixture_sources/hwp/generated-fixtures.json`.

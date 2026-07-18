# Deterministic G0 PDF/image fixtures

This directory owns the repository-authored PDF, image, and adversarial HWPX
fixture bytes listed in `metadata.v1.json`. The fixture prose is original test
text released under `CC0-1.0`; the committed Korean font subset is derived from
Noto Sans KR 2.004 under `OFL-1.1`, with the immutable upstream URL and both
source/subset SHA-256 values recorded in metadata.

`font-build.Dockerfile` pins the independent fonttools build environment. Feed
it the upstream font named by metadata; `prepare_font.py` refuses any source
whose SHA-256 differs and produces the recorded subset hash.

```powershell
pwsh -NoProfile -File spikes/document-ingestion/fixture_sources/common/verify-font-rebuild.ps1
```

Canonical regeneration uses the digest-pinned Python 3.12.11 container and the
hash-pinned Pillow wheel. It regenerates into the repository and immediately
performs an independent empty-directory byte comparison:

```powershell
pwsh -NoProfile -File spikes/document-ingestion/fixture_sources/common/regenerate.ps1
```

```sh
sh spikes/document-ingestion/fixture_sources/common/regenerate.sh
```

The G0 fixture validator checks hashes, NFC fingerprints, PDF text-layer
behavior, EXIF orientation, adversarial container shape, and Korean OCR in a
networkless resource-bounded Tesseract 5.3.0 container:

```powershell
.venv/Scripts/python.exe spikes/document-ingestion/fixture_sources/common/verify.py
```

`polyglot-image.jpg` is deliberately valid as both a JPEG prefix and appended
ZIP. A decoder that accepts arbitrary bytes after JPEG EOI does **not** satisfy
its expected `CORRUPT_DOCUMENT` contract; the parser must reject the trailing
payload rather than weakening this fixture.

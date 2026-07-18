"""Create the small, committed OFL Korean font used by G0 fixtures.

The input is the official Noto Sans KR variable TTF from the immutable
``Sans2.004`` tag.  The large upstream file is deliberately not committed;
its URL and SHA-256 are pinned here and in ``metadata.v1.json``.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from fixture_text import FONT_TEXT


SOURCE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/"
    "Sans/Variable/TTF/Subset/NotoSansKR-VF.ttf"
)
SOURCE_SHA256 = "9e1d729e7e2b36f9ef439da102f8c134c10aabe46f1c843bf0aca5c043b86f76"
FIXED_TTF_TIMESTAMP = 3_748_944_000  # 2022-10-18T00:00:00Z in the 1904 epoch.


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path, output: Path) -> None:
    actual_hash = sha256(source)
    if actual_hash != SOURCE_SHA256:
        raise SystemExit(
            f"source hash mismatch: expected {SOURCE_SHA256}, got {actual_hash}"
        )

    font = TTFont(source, recalcTimestamp=False)
    instantiateVariableFont(font, {"wght": 600.0}, inplace=True)

    options = subset.Options()
    options.hinting = False
    options.recalc_timestamp = False
    options.canonical_order = True
    options.layout_features = ["*"]
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.glyph_names = True
    options.symbol_cmap = True
    options.legacy_cmap = True
    options.notdef_glyph = True
    options.notdef_outline = True
    options.recommended_glyphs = True

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=FONT_TEXT)
    subsetter.subset(font)

    font["head"].created = FIXED_TTF_TIMESTAMP
    font["head"].modified = FIXED_TTF_TIMESTAMP
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output, reorderTables=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
    print(f"{sha256(args.output)}  {args.output.as_posix()}")


if __name__ == "__main__":
    main()

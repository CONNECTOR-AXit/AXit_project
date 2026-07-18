from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MERGER_PATH = (
    REPOSITORY_ROOT
    / "spikes"
    / "document-ingestion"
    / "fixture_sources"
    / "merge_manifest.py"
)


def _load_merger() -> ModuleType:
    specification = importlib.util.spec_from_file_location("merge_manifest", MERGER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_committed_manifest_is_exact_reproducible_lane_merge() -> None:
    merger = _load_merger()
    manifest = merger.build_manifest(
        common_metadata=merger.DEFAULT_COMMON,
        hwp_metadata=merger.DEFAULT_HWP,
        fixture_root=merger.DEFAULT_FIXTURE_ROOT,
    )
    committed = json.loads(merger.DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert committed == manifest
    assert [fixture["path"] for fixture in committed["fixtures"]] == sorted(
        (fixture["path"] for fixture in committed["fixtures"]),
        key=lambda path: (
            next(
                fixture["classification"]
                for fixture in committed["fixtures"]
                if fixture["path"] == path
            )
            != "golden",
            path,
        ),
    )

from __future__ import annotations

import json
from pathlib import Path


SPIKE_ROOT = Path(__file__).resolve().parents[2]


def test_policy_matches_the_approved_demo_bounds_and_has_finite_sandbox_caps() -> None:
    policy = json.loads((SPIKE_ROOT / "policy.v1.json").read_text(encoding="utf-8"))

    assert policy["schema_version"] == 1
    assert policy["input"]["max_bytes"] == 20 * 1024 * 1024
    assert policy["input"]["pdf_max_pages"] == 100
    assert policy["input"]["image_max_pixels"] == 25_000_000

    archive = policy["archive"]
    assert archive["max_entries"] > 0
    assert archive["max_entry_uncompressed_bytes"] <= archive["max_total_uncompressed_bytes"]
    assert archive["max_compression_ratio"] > 1
    assert archive["max_xml_bytes"] > 0

    result = policy["result"]
    assert result["max_blocks"] > 0
    assert result["max_block_chars"] > 0
    assert result["max_total_chars"] >= result["max_block_chars"]
    assert result["max_stdout_bytes"] > 0
    assert result["max_stderr_bytes"] > 0

    sandbox = policy["sandbox"]
    assert 0 < sandbox["wall_timeout_seconds"] <= 30
    assert sandbox["memory_bytes"] == sandbox["memory_swap_bytes"]
    assert 0 < sandbox["pids"] <= 128
    assert 0 < sandbox["cpus"] <= 2
    assert sandbox["uid"] != 0
    assert sandbox["gid"] != 0

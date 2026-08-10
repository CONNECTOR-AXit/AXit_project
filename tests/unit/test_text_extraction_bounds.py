from app.file_extraction_worker import _extract_utf8_text


def test_builtin_text_bounds_more_than_g0_block_limit_with_a_warning() -> None:
    execution = _extract_utf8_text(("x\n" * 10_001).encode())
    assert execution.ok is True
    assert execution.payload is not None
    result = execution.payload["result"]
    assert len(result["blocks"]) == 10_000
    assert result["warnings"] == ["TRUNCATED_TO_EXTRACTION_LIMIT"]


def test_builtin_text_bounds_total_character_limit_with_a_warning() -> None:
    execution = _extract_utf8_text((("x" * 100_000 + "\n") * 11).encode())
    assert execution.ok is True
    assert execution.payload is not None
    result = execution.payload["result"]
    assert sum(len(block["text"]) for block in result["blocks"]) == 1_000_000
    assert result["warnings"] == ["TRUNCATED_TO_EXTRACTION_LIMIT"]

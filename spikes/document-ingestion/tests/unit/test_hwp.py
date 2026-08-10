from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pytest

from axit_ingestion_spike.hwp import (
    HwpSidecarResult,
    JavaHwpExtractor,
    hwp_config_profile_hash,
)
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractionException,
    ExtractionPolicy,
    MediaType,
)
from axit_ingestion_spike.normalization import text_fingerprint
from axit_ingestion_spike.pipeline import extract_document


SOURCE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture"
SOURCE_SHA256 = hashlib.sha256(SOURCE).hexdigest()


@dataclass
class FakeRunner:
    result: HwpSidecarResult
    calls: list[tuple[bytes, MediaType, str, int, float]]

    def invoke(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        profile_hash: str,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> HwpSidecarResult:
        self.calls.append(
            (data, media_type, profile_hash, max_output_bytes, timeout_seconds)
        )
        return self.result


def sidecar_success(
    *,
    profile_hash: str,
    records: list[dict[str, object]] | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    payload = {
        "extraction_profile_hash": profile_hash,
        "ok": True,
        "parser": {"name": "hwplib", "version": "1.1.10"},
        "records": records
        or [
            {
                "kind": "paragraph",
                "locator": {"paragraph": 0, "section": 0},
                "text": "회의 본문",
                "text_fingerprint": text_fingerprint("회의 본문"),
            },
            {
                "kind": "table_cell",
                "locator": {
                    "paragraph": 1,
                    "section": 0,
                    "cell": 0,
                    "cell_paragraph": 0,
                    "table": 0,
                    "table_block": 0,
                    "table_row": 0,
                },
                "text": "표 셀",
                "text_fingerprint": text_fingerprint("표 셀"),
            },
            {
                "kind": "footnote",
                "locator": {
                    "paragraph": 2,
                    "section": 0,
                    "footnote": 0,
                    "footnote_paragraph": 0,
                },
                "text": "각주",
                "text_fingerprint": text_fingerprint("각주"),
            },
        ],
        "schema_version": "hwp-sidecar.v1",
        "source_sha256": SOURCE_SHA256,
        "warnings": warnings or [],
    }
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def make_extractor(result: HwpSidecarResult) -> tuple[JavaHwpExtractor, FakeRunner]:
    runner = FakeRunner(result, [])
    policy = ExtractionPolicy()
    return JavaHwpExtractor(policy=policy, runner=runner), runner


def test_hwp_adapter_validates_and_maps_structural_records() -> None:
    policy = ExtractionPolicy()
    extractor, runner = make_extractor(
        HwpSidecarResult(
            sidecar_success(
                profile_hash=hwp_config_profile_hash(policy, MediaType.HWP)
            ),
            b"",
            0,
        )
    )

    result = extractor.extract(
        SOURCE,
        media_type=MediaType.HWP,
        source_sha256=SOURCE_SHA256,
    )

    assert [block.block_type for block in result.blocks] == [
        "hwp_paragraph",
        "hwp_table_cell",
        "hwp_footnote",
    ]
    assert result.parser_name == "hwplib"
    assert result.parser_version == "1.1.10"
    assert result.blocks[1].anchor.to_dict()["locator"]["table"] == {
        "index": 0,
        "block": 0,
        "row": 0,
        "cell": 0,
        "paragraph": 0,
    }
    assert result.blocks[2].anchor.to_dict()["locator"]["footnote"] == {
        "index": 0,
        "paragraph": 0,
    }
    assert runner.calls == [
        (
            SOURCE,
            MediaType.HWP,
            hwp_config_profile_hash(policy, MediaType.HWP),
            policy.max_output_bytes,
            policy.ocr_timeout_seconds,
        )
    ]


@pytest.mark.parametrize(
    ("sidecar_warning", "expected_warning"),
    [
        ("UNSUPPORTED_ENDNOTE", "PARTIAL_EXTRACTION"),
        ("NESTED_CONTROL_SKIPPED", "PARTIAL_EXTRACTION"),
    ],
)
def test_hwp_adapter_maps_reviewable_partial_extraction_warnings(
    sidecar_warning: str,
    expected_warning: str,
) -> None:
    policy = ExtractionPolicy()
    extractor, _ = make_extractor(
        HwpSidecarResult(
            sidecar_success(
                profile_hash=hwp_config_profile_hash(policy, MediaType.HWP),
                warnings=[sidecar_warning],
            ),
            b"",
            0,
        )
    )

    result = extractor.extract(
        SOURCE,
        media_type=MediaType.HWP,
        source_sha256=SOURCE_SHA256,
    )

    assert [warning.code.value for warning in result.warnings] == [expected_warning]


@pytest.mark.parametrize(
    ("sidecar_code", "common_code"),
    [
        ("ARCHIVE_LIMIT_EXCEEDED", ErrorCode.ZIP_EXPANSION_LIMIT),
        ("ARCHIVE_RATIO_REJECTED", ErrorCode.ZIP_EXPANSION_LIMIT),
        ("XML_DTD_FORBIDDEN", ErrorCode.XML_DTD_FORBIDDEN),
        ("XML_ENCODING_REJECTED", ErrorCode.CORRUPT_DOCUMENT),
        ("ENCRYPTED_DOCUMENT", ErrorCode.ENCRYPTED_DOCUMENT),
        ("CORRUPT_ARCHIVE", ErrorCode.CORRUPT_DOCUMENT),
        ("ARCHIVE_PATH_REJECTED", ErrorCode.CORRUPT_DOCUMENT),
        ("OUTPUT_LIMIT_EXCEEDED", ErrorCode.OUTPUT_TOO_LARGE),
        ("TYPE_MISMATCH", ErrorCode.TYPE_MISMATCH),
    ],
)
def test_hwp_adapter_maps_sidecar_failures_without_exposing_raw_messages(
    sidecar_code: str,
    common_code: ErrorCode,
) -> None:
    raw_secret = "raw fixture path C:/secret/input.hwpx"
    output = json.dumps(
        {
            "error": {
                "code": sidecar_code,
                "message": raw_secret,
                "retryable": False,
            },
            "ok": False,
        },
        separators=(",", ":"),
    ).encode()
    extractor, _ = make_extractor(HwpSidecarResult(output, b"", 2))

    with pytest.raises(ExtractionException) as caught:
        extractor.extract(
            SOURCE,
            media_type=MediaType.HWP,
            source_sha256=SOURCE_SHA256,
        )

    assert caught.value.error.code is common_code
    assert raw_secret not in caught.value.error.message


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(source_sha256="0" * 64),
        lambda payload: payload.update(extraction_profile_hash="0" * 64),
        lambda payload: payload["parser"].update(version="9.9.9"),
        lambda payload: payload["records"][0].update(text_fingerprint="0" * 64),
        lambda payload: payload["records"][0]["locator"].update(extra=0),
        lambda payload: payload.update(unknown=True),
    ],
)
def test_hwp_adapter_fails_closed_on_sidecar_protocol_drift(mutate: object) -> None:
    policy = ExtractionPolicy()
    payload = json.loads(
        sidecar_success(profile_hash=hwp_config_profile_hash(policy, MediaType.HWP))
    )
    mutate(payload)  # type: ignore[operator]
    extractor, _ = make_extractor(
        HwpSidecarResult(json.dumps(payload, ensure_ascii=False).encode(), b"", 0)
    )

    with pytest.raises(ExtractionException) as caught:
        extractor.extract(
            SOURCE,
            media_type=MediaType.HWP,
            source_sha256=SOURCE_SHA256,
        )

    assert caught.value.error.code is ErrorCode.INTERNAL_ERROR


def test_hwp_adapter_rejects_output_boundary_and_stderr_violations() -> None:
    extractor, _ = make_extractor(
        HwpSidecarResult(b"{}", b"unexpected parser log", 0, "stderr_limit")
    )

    with pytest.raises(ExtractionException) as caught:
        extractor.extract(
            SOURCE,
            media_type=MediaType.HWP,
            source_sha256=SOURCE_SHA256,
        )

    assert caught.value.error.code is ErrorCode.INTERNAL_ERROR


def test_pipeline_uses_injected_hwp_adapter_and_preserves_anchor_identity() -> None:
    policy = ExtractionPolicy()
    extractor, _ = make_extractor(
        HwpSidecarResult(
            sidecar_success(
                profile_hash=hwp_config_profile_hash(policy, MediaType.HWP)
            ),
            b"",
            0,
        )
    )

    envelope = extract_document(
        SOURCE,
        filename="meeting.hwp",
        policy=policy,
        hwp_extractor=extractor,
    )

    assert envelope.ok
    assert envelope.result is not None
    assert envelope.result.source_sha256 == SOURCE_SHA256
    assert envelope.result.config_profile_hash == hwp_config_profile_hash(
        policy, MediaType.HWP
    )
    assert envelope.result.anchor_set_hash == (
        "b20f6aa9b6a28d5b3011e6d050ea4487b00c9371c7e08412506071cee36963bc"
    )

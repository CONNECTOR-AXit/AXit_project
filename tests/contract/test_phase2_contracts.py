"""Phase 2 wire-contract freeze and generated-artifact freshness tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.contracts import (
    AnchorKind,
    CitationTarget,
    SourceAnchor,
    SummaryItem,
    SummarySupport,
    WebEvidence,
    contract_app,
)
from app.main import app as runtime_app


ROOT = Path(__file__).resolve().parents[2]
G0_VIEWER_FIXTURES = ROOT / "spikes" / "document-ingestion" / "viewer" / "fixtures"


def test_durable_openapi_freezes_every_prd_route_and_hides_phase0_paths() -> None:
    paths = contract_app.openapi()["paths"]
    expected = {
        "/api/csrf",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/me",
        "/api/friend-requests",
        "/api/friend-requests/{friend_request_id}/accept",
        "/api/friend-requests/{friend_request_id}/reject",
        "/api/friends",
        "/api/rooms",
        "/api/rooms/{room_id}/invitations",
        "/api/rooms/{room_id}/sessions",
        "/api/sessions/{session_id}",
        "/api/sessions/{session_id}/close",
        "/api/sessions/{session_id}/retry",
        "/api/sessions/{session_id}/submissions/text",
        "/api/sessions/{session_id}/submissions/files",
        "/api/submissions/{submission_id}",
        "/api/source-revisions/{revision_id}/original",
        "/api/source-revisions/{revision_id}/viewer",
        "/api/sessions/{session_id}/summary",
        "/api/sessions/{session_id}/research",
        "/api/citations/{citation_id}/resolve",
    }
    assert set(paths) == expected
    assert not any("__phase0" in path for path in paths)

    runtime_paths = runtime_app.openapi()["paths"]
    assert set(runtime_paths) == expected | {"/health"}


def test_contract_only_routes_return_the_advertised_error_response_shape() -> None:
    expected = {
        "code": "contract_only",
        "detail": "phase 2 contract only; implementation is scheduled for a later phase",
    }
    for application in (contract_app, runtime_app):
        response = TestClient(application).get("/api/csrf")
        assert response.status_code == 501
        assert response.json() == expected



def test_summary_supports_are_exactly_declared_and_anchor_locators_are_typed() -> None:
    supported_anchor = uuid4()
    other_anchor = uuid4()
    support = SummarySupport(
        citation_id=uuid4(),
        source_anchor_id=supported_anchor,
        exact_quote="exact participant support",
        start=0,
        end=25,
    )
    accepted = SummaryItem(
        text="The participant supplied the support.",
        source_anchor_ids=[supported_anchor],
        supports=[support],
    )
    assert accepted.source_anchor_ids == [supported_anchor]
    with pytest.raises(ValidationError, match="must match support"):
        SummaryItem(
            text="unsupported declaration",
            source_anchor_ids=[other_anchor],
            supports=[support],
        )

    anchor = SourceAnchor(
        id=uuid4(),
        revision_id=uuid4(),
        schema_version=1,
        kind=AnchorKind.TEXT_LINE,
        locator={
            "line": 1,
            "start": 0,
            "end": 25,
        },
        source_sha256="a" * 64,
        extraction_profile_hash="b" * 64,
        text_fingerprint="c" * 64,
        exact_quote="exact participant support",
    )
    assert anchor.locator.line == 1
    with pytest.raises(ValidationError, match="must match typed locator"):
        SourceAnchor(
            id=uuid4(),
            revision_id=uuid4(),
            schema_version=1,
            kind=AnchorKind.PDF_BLOCK,
            locator={
                "line": 1,
                "start": 0,
                "end": 25,
            },
            source_sha256="a" * 64,
            extraction_profile_hash="b" * 64,
            text_fingerprint="c" * 64,
            exact_quote="exact participant support",
        )


def test_g0_canonical_anchor_payloads_round_trip_without_loss() -> None:
    anchor_count = 0
    seen_categories: set[str] = set()
    for fixture_path in sorted(G0_VIEWER_FIXTURES.glob("*.json")):
        if fixture_path.name == "provenance.v1.json":
            continue
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for block in fixture["result"]["blocks"]:
            anchor = SourceAnchor(
                id=uuid4(),
                revision_id=uuid4(),
                exact_quote=block["text"],
                **block["anchor"],
            )
            canonical_projection = anchor.canonical_payload()
            assert canonical_projection == block["anchor"], fixture_path.name
            locator = block["anchor"]["locator"]
            if fixture_path.name == "pdf-text-korean.json":
                seen_categories.add("pdf-text")
            if fixture_path.name == "pdf-scanned-korean.json":
                seen_categories.add("pdf-scanned")
            if fixture_path.name == "image-korean-clean-png.json":
                seen_categories.add("image-png")
            if fixture_path.name == "image-korean-clean-jpeg.json":
                seen_categories.add("image-jpeg")
            if "table" in locator:
                seen_categories.add("hwp-table")
            if "footnote" in locator:
                seen_categories.add("hwp-footnote")
            anchor_count += 1
    assert anchor_count == 52
    assert {
        "pdf-text",
        "pdf-scanned",
        "image-png",
        "image-jpeg",
        "hwp-table",
        "hwp-footnote",
    } <= seen_categories

    text_line_fixture = json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "contracts"
            / "canonical-text-line-anchor.v1.json"
        ).read_text(encoding="utf-8")
    )
    text_line_anchor = SourceAnchor(
        id=uuid4(),
        revision_id=uuid4(),
        exact_quote=text_line_fixture["exact_quote"],
        **text_line_fixture["anchor"],
    )
    assert text_line_anchor.canonical_payload() == text_line_fixture["anchor"]

    malformed_hash = dict(text_line_fixture["anchor"])
    malformed_hash["source_sha256"] = " " + malformed_hash["source_sha256"]
    with pytest.raises(ValidationError):
        SourceAnchor(
            id=uuid4(),
            revision_id=uuid4(),
            exact_quote=text_line_fixture["exact_quote"],
            **malformed_hash,
        )

    boolean_schema_version = dict(text_line_fixture["anchor"])
    boolean_schema_version["schema_version"] = True
    with pytest.raises(ValidationError, match="integer 1"):
        SourceAnchor(
            id=uuid4(),
            revision_id=uuid4(),
            exact_quote=text_line_fixture["exact_quote"],
            **boolean_schema_version,
        )

    malformed_hwp_path = {
        "schema_version": 1,
        "kind": "hwp_paragraph",
        "source_sha256": "a" * 64,
        "extraction_profile_hash": "b" * 64,
        "locator": {
            "parser": "hwplib",
            "parser_version": "1.1.10",
            "section": 0,
            "paragraph": 0,
            "table": None,
        },
        "text_fingerprint": "c" * 64,
    }
    with pytest.raises(ValidationError, match="absent or complete"):
        SourceAnchor(
            id=uuid4(),
            revision_id=uuid4(),
            exact_quote="HWP source",
            **malformed_hwp_path,
        )


def test_summary_citations_expose_the_resolver_and_source_viewer_identifiers() -> None:
    citation_id = uuid4()
    anchor_id = uuid4()
    revision_id = uuid4()
    support = SummarySupport(
        citation_id=citation_id,
        source_anchor_id=anchor_id,
        exact_quote="exact participant support",
        start=0,
        end=25,
    )
    assert support.citation_id == citation_id
    source_target = CitationTarget(
        citation_id=citation_id,
        target_type="source_anchor",
        source_anchor_id=anchor_id,
        source_revision_id=revision_id,
    )
    assert source_target.source_revision_id == revision_id
    with pytest.raises(ValidationError, match="does not match target_type"):
        CitationTarget(
            citation_id=citation_id,
            target_type="source_anchor",
            source_anchor_id=anchor_id,
        )


def test_contract_excludes_fixture_aliases_storage_and_lease_secrets() -> None:
    serialized = json.dumps(contract_app.openapi(), sort_keys=True)
    for forbidden in ("storage_key", "lease_token", "fixture_id", "anchor-agenda-001"):
        assert forbidden not in serialized
    with pytest.raises(ValidationError):
        WebEvidence(
            id=uuid4(),
            url="https://fixtures.invalid/evidence",
            title="Evidence",
            domain="fixtures.invalid",
            accessed_at=datetime(2026, 7, 18, 0, 0),
            snippet_hash="sha256:" + "a" * 64,
        )


@pytest.mark.parametrize(
    ("url", "domain"),
    (
        ("https://", ""),
        ("https://evil.example@trusted.example/path", "trusted.example"),
        ("https://trusted.example/\r\nnext", "trusted.example"),
        ("https://trusted.example/path", "other.example"),
    ),
)
def test_web_evidence_requires_a_safe_matching_origin(url: str, domain: str) -> None:
    with pytest.raises(ValidationError):
        WebEvidence(
            id=uuid4(),
            url=url,
            title="Evidence",
            domain=domain,
            accessed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            snippet_hash="sha256:" + "a" * 64,
        )

    accepted = WebEvidence(
        id=uuid4(),
        url="https://evidence.example/path?q=1",
        title="Evidence",
        domain="evidence.example",
        accessed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        snippet_hash="sha256:" + "a" * 64,
    )
    assert accepted.domain == "evidence.example"


def test_checked_contract_artifacts_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/generate_contracts.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

#!/usr/bin/env python3
"""Validate the deterministic MockProvider fixture corpus.

The validator intentionally uses only Python's standard library.  Validation is
performed in two passes: every canonical document is loaded and indexed first,
then cross-document hashes and citations are resolved against that index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "provider_fixtures"
SCHEMA_VERSION = "provider-fixture.v1"
PROMPT_VERSION = "mock-provider.prompt.v1"
REVIEWER_ROLE = "coding-agent-cross-review"
JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
COMMON_SCHEMA_ID = "https://schemas.fixtures.invalid/provider-fixture.v1.schema.json"
SOURCE_SCHEMA_ID = "https://schemas.fixtures.invalid/source-pack.v1.schema.json"
COMMON_ALLOF_DIGEST = (
    "sha256:3a62292125e680f41029cf90443853262063488c49bb029483685b83809efbf7"
)
COMMON_SCHEMA_DIGEST = (
    "sha256:a376de63242e7c8cad5c8d9cb31b8fbb137a658c41f0c89d85f3fdc6de77b526"
)
SOURCE_SCHEMA_DIGEST = (
    "sha256:2fbe5cb4edf2e804a074b3251ff7e01a273fd17434f866e7f647ad85cf155337"
)

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
URL = re.compile(r"https?://", re.IGNORECASE)
UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
VERDICT_WORD = re.compile(
    r"\b(?:supported|refuted|mixed|unverifiable|verdict)\b", re.IGNORECASE
)

ANCHOR_TYPES = {"factual_claim", "instruction_like_content", "opinion"}
FOUR_VERDICTS = {"supported", "refuted", "mixed", "unverifiable"}
REVISION_IDS = {
    "revision-agenda-001",
    "revision-alice-001",
    "revision-bob-001",
}
ANCHOR_IDS = {
    "anchor-agenda-001",
    "anchor-alice-001",
    "anchor-alice-002",
    "anchor-bob-001",
    "anchor-bob-opinion-001",
}

SUMMARY_GROUNDED = "summary-grounded-001"
SUMMARY_UNSUPPORTED = "summary-ungrounded-assertion-rejection-001"
SUMMARY_FOREIGN = "summary-foreign-anchor-rejection-001"
SUMMARY_INJECTION = "summary-source-prompt-injection-rejection-001"
SUMMARY_TIMEOUT = "summary-provider-timeout-001"
SUMMARY_MALFORMED = "summary-malformed-schema-001"
SUMMARY_RETRY = "summary-deterministic-retry-001"
SUMMARY_IDS = {
    SUMMARY_GROUNDED,
    SUMMARY_UNSUPPORTED,
    SUMMARY_FOREIGN,
    SUMMARY_INJECTION,
    SUMMARY_TIMEOUT,
    SUMMARY_MALFORMED,
    SUMMARY_RETRY,
}

REQUIRED_FIXTURES = {
    "source": {"meeting-pack-001"},
    "summary": SUMMARY_IDS,
    "web_evidence": {f"web-evidence-{index:03d}" for index in range(1, 7)},
    "research": {f"research-{verdict}-001" for verdict in FOUR_VERDICTS},
    "factcheck": {
        *(f"factcheck-{verdict}-001" for verdict in FOUR_VERDICTS),
        "factcheck-opinion-excluded-001",
    },
}
EXPECTED_PATHS = {
    Path(category) / f"{fixture_id}.json": fixture_id
    for category, fixture_ids in REQUIRED_FIXTURES.items()
    for fixture_id in fixture_ids
}
REQUIRED_SCHEMA_PATHS = {
    Path("schema/provider-fixture.v1.schema.json"),
    Path("schema/source-pack.v1.schema.json"),
}
COMMON_SCHEMA_DEFS = {
    "factcheckResult",
    "metadata",
    "opinionExclusion",
    "researchResult",
    "summaryForeignAnchor",
    "summaryGrounded",
    "summaryItem",
    "summaryMalformed",
    "summaryPromptInjection",
    "summaryRetry",
    "summaryTimeout",
    "summaryUnsupported",
    "webEvidence",
}
METADATA_REQUIRED_KEYS = {
    "author_role",
    "reviewer_role",
    "created_at",
    "prompt_version",
    "source_hash",
}
METADATA_ALLOWED_KEYS = METADATA_REQUIRED_KEYS | {"evidence_hash"}


def contains_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, dict):
        return any(contains_surrogate(key) for key in value) or any(
            contains_surrogate(child) for child in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_surrogate(child) for child in value)
    return False


def canonical_bytes(value: object) -> bytes:
    """Return the sole accepted JSON byte representation."""

    if contains_surrogate(value):
        raise ValueError("JSON contains a UTF-16 surrogate code point")
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def digest(value: object) -> str:
    """Hash a value's canonical JSON bytes."""

    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def fail(path: Path, message: str) -> str:
    try:
        display = path.relative_to(ROOT)
    except ValueError:
        display = path
    return f"{display}: {message}"


def payload_without_metadata(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "metadata"}


def is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(None)


def reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant {value}")


def parse_json_bytes(raw: bytes) -> object:
    text = raw.decode("utf-8")
    document = json.loads(text, parse_constant=reject_nonfinite_json_constant)
    if contains_surrogate(document):
        raise ValueError("JSON contains a UTF-16 surrogate code point")
    return document


def recursive_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [
            key for child in value.values() for key in recursive_keys(child)
        ]
    if isinstance(value, list):
        return [key for child in value for key in recursive_keys(child)]
    return []


def recursive_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            item for child in value.values() for item in recursive_strings(child)
        ]
    if isinstance(value, list):
        return [item for child in value for item in recursive_strings(child)]
    return []


def validate_document(path: Path, document: object) -> list[str]:
    """Validate the envelope shared by every non-schema fixture."""

    if not isinstance(document, dict):
        return [fail(path, "top-level JSON must be an object")]

    errors: list[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(fail(path, "invalid schema_version"))
    if not is_nonempty_string(document.get("fixture_id")):
        errors.append(fail(path, "fixture_id must be a non-empty string"))
    if "expected_rejection" in document and not isinstance(
        document["expected_rejection"], bool
    ):
        errors.append(fail(path, "expected_rejection must be a boolean"))

    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        return errors + [fail(path, "missing metadata object")]

    for field in sorted(METADATA_REQUIRED_KEYS):
        if not is_nonempty_string(metadata.get(field)):
            errors.append(fail(path, f"metadata.{field} is required"))
    unexpected_metadata = sorted(set(metadata) - METADATA_ALLOWED_KEYS)
    if unexpected_metadata:
        errors.append(
            fail(
                path,
                "metadata has unexpected keys: " + ", ".join(unexpected_metadata),
            )
        )

    if metadata.get("author_role") != "coding-agent":
        errors.append(fail(path, "metadata.author_role must be coding-agent"))
    if metadata.get("reviewer_role") != REVIEWER_ROLE:
        errors.append(
            fail(
                path,
                f"metadata.reviewer_role must be {REVIEWER_ROLE}",
            )
        )
    if metadata.get("prompt_version") != PROMPT_VERSION:
        errors.append(fail(path, "invalid metadata.prompt_version"))
    if not is_utc_timestamp(metadata.get("created_at")):
        errors.append(fail(path, "metadata.created_at must be a UTC timestamp"))

    for field in ("source_hash", "evidence_hash"):
        if field in metadata and (
            not isinstance(metadata[field], str)
            or SHA256.fullmatch(metadata[field]) is None
        ):
            errors.append(fail(path, f"invalid metadata.{field}"))
    return errors


def _source_graph(
    path: Path, document: dict[str, Any]
) -> tuple[list[str], str, dict[str, str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    allowed_keys = {
        "anchors",
        "fixture_id",
        "metadata",
        "revisions",
        "schema_version",
    }
    if set(document) != allowed_keys:
        errors.append(fail(path, "source fixture has unexpected or missing fields"))
    source_hash = digest(payload_without_metadata(document))
    metadata = document.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("source_hash") != source_hash:
        errors.append(
            fail(
                path,
                "metadata.source_hash must hash canonical source payload excluding metadata",
            )
        )
    if isinstance(metadata, dict) and "evidence_hash" in metadata:
        errors.append(fail(path, "source metadata must not contain evidence_hash"))

    revisions_value = document.get("revisions")
    revisions: dict[str, str] = {}
    if not isinstance(revisions_value, list) or not revisions_value:
        errors.append(fail(path, "source revisions must be a non-empty list"))
    else:
        for index, revision in enumerate(revisions_value):
            if not isinstance(revision, dict):
                errors.append(fail(path, f"revisions[{index}] must be an object"))
                continue
            if set(revision) != {"revision_id", "text"}:
                errors.append(
                    fail(
                        path,
                        f"revisions[{index}] has unexpected or missing fields",
                    )
                )
            revision_id = revision.get("revision_id")
            text = revision.get("text")
            if not is_nonempty_string(revision_id) or not is_nonempty_string(text):
                errors.append(
                    fail(
                        path,
                        f"revisions[{index}] requires revision_id and text",
                    )
                )
                continue
            if revision_id in revisions:
                errors.append(fail(path, f"duplicate revision_id {revision_id}"))
            revisions[revision_id] = text
        if set(revisions) != REVISION_IDS:
            errors.append(
                fail(
                    path,
                    "source revisions must use exactly the fixed revision ID set",
                )
            )

    anchors_value = document.get("anchors")
    anchors: dict[str, dict[str, Any]] = {}
    if not isinstance(anchors_value, list) or not anchors_value:
        errors.append(fail(path, "source anchors must be a non-empty list"))
    else:
        for index, anchor in enumerate(anchors_value):
            if not isinstance(anchor, dict):
                errors.append(fail(path, f"anchors[{index}] must be an object"))
                continue
            allowed_anchor_keys = {
                "anchor_id",
                "anchor_type",
                "atomic_quotes",
                "exact_quote",
                "participant",
                "revision_id",
            }
            if set(anchor) != allowed_anchor_keys:
                errors.append(
                    fail(
                        path,
                        f"anchors[{index}] has unexpected or missing fields",
                    )
                )
            anchor_id = anchor.get("anchor_id")
            revision_id = anchor.get("revision_id")
            exact_quote = anchor.get("exact_quote")
            participant = anchor.get("participant")
            anchor_type = anchor.get("anchor_type")
            atomic_quotes = anchor.get("atomic_quotes")
            if not all(
                is_nonempty_string(value)
                for value in (anchor_id, revision_id, exact_quote, participant)
            ):
                errors.append(
                    fail(
                        path,
                        f"anchors[{index}] requires anchor_id, revision_id, participant, and exact_quote",
                    )
                )
                continue
            if (
                not isinstance(atomic_quotes, list)
                or not atomic_quotes
                or not all(is_nonempty_string(quote) for quote in atomic_quotes)
            ):
                errors.append(
                    fail(
                        path,
                        f"anchor {anchor_id} atomic_quotes must be a non-empty string list",
                    )
                )
            else:
                if len(atomic_quotes) != len(set(atomic_quotes)):
                    errors.append(
                        fail(path, f"anchor {anchor_id} atomic_quotes must be unique")
                    )
                for atomic_quote in atomic_quotes:
                    if atomic_quote not in exact_quote:
                        errors.append(
                            fail(
                                path,
                                f"anchor {anchor_id} atomic quote is not contained in exact_quote",
                            )
                        )
                combined_atomic_quotes = normalize_whitespace(
                    " ".join(atomic_quotes)
                )
                if combined_atomic_quotes != normalize_whitespace(exact_quote):
                    errors.append(
                        fail(
                            path,
                            f"anchor {anchor_id} atomic_quotes must completely segment exact_quote in order",
                        )
                    )
            if anchor_id in anchors:
                errors.append(fail(path, f"duplicate anchor_id {anchor_id}"))
            anchors[anchor_id] = anchor
            if anchor_type not in ANCHOR_TYPES:
                errors.append(
                    fail(
                        path,
                        f"anchor {anchor_id} has invalid anchor_type {anchor_type!r}",
                    )
                )
            revision_text = revisions.get(revision_id)
            if revision_text is None:
                errors.append(
                    fail(
                        path,
                        f"anchor {anchor_id} references unknown revision {revision_id}",
                    )
                )
            elif exact_quote not in revision_text:
                errors.append(
                    fail(
                        path,
                        f"anchor {anchor_id} exact_quote is not contained in revision {revision_id}",
                    )
                )
        if set(anchors) != ANCHOR_IDS:
            errors.append(
                fail(path, "source anchors must use exactly the fixed anchor ID set")
            )
    return errors, source_hash, revisions, anchors


def validate_source_pack(path: Path, document: object) -> list[str]:
    """Validate a source pack in isolation.

    Cross-document source-hash checks happen in :func:`validate`.
    """

    errors = validate_document(path, document)
    if not isinstance(document, dict):
        return errors
    if document.get("fixture_id") != "meeting-pack-001":
        errors.append(fail(path, "source fixture_id must be meeting-pack-001"))
    graph_errors, _, _, _ = _source_graph(path, document)
    return errors + graph_errors


def _list_of_unique_strings(
    path: Path, value: object, label: str, *, nonempty: bool = True
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if not isinstance(value, list) or (nonempty and not value):
        return [], [fail(path, f"{label} must be a non-empty list")]
    if not all(is_nonempty_string(item) for item in value):
        return [], [fail(path, f"{label} must contain only non-empty strings")]
    strings = list(value)
    if len(strings) != len(set(strings)):
        errors.append(fail(path, f"{label} must not contain duplicates"))
    return strings, errors


def _validate_web_evidence(
    path: Path, document: dict[str, Any]
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    allowed_keys = {
        "accessed_at",
        "domain",
        "evidence_kind",
        "fixture_id",
        "metadata",
        "schema_version",
        "snippet_hash",
        "statement",
        "synthetic",
        "title",
        "url",
        "web_evidence_id",
    }
    if set(document) != allowed_keys:
        errors.append(
            fail(path, "web evidence fixture has unexpected or missing fields")
        )
    fixture_id = document.get("fixture_id")
    if document.get("web_evidence_id") != fixture_id:
        errors.append(fail(path, "web_evidence_id must equal fixture_id"))
    if document.get("synthetic") is not True:
        errors.append(fail(path, "web evidence must set synthetic=true"))

    statement = document.get("statement")
    if not is_nonempty_string(statement):
        errors.append(fail(path, "web evidence statement is required"))
    for field in ("title", "evidence_kind"):
        if not is_nonempty_string(document.get(field)):
            errors.append(fail(path, f"web evidence {field} is required"))

    raw_url = document.get("url")
    expected_url = f"https://fixtures.invalid/evidence/{fixture_id}"
    try:
        parsed = urlparse(raw_url) if isinstance(raw_url, str) else None
        parsed_hostname = parsed.hostname if parsed is not None else None
    except ValueError:
        parsed = None
        parsed_hostname = None
    if raw_url != expected_url or parsed is None or parsed_hostname != "fixtures.invalid":
        errors.append(
            fail(path, f"web evidence URL must equal {expected_url}")
        )
    if document.get("domain") != "fixtures.invalid":
        errors.append(fail(path, "web evidence domain must be fixtures.invalid"))
    if not is_utc_timestamp(document.get("accessed_at")):
        errors.append(fail(path, "web evidence accessed_at must be a UTC timestamp"))

    if is_nonempty_string(statement) and document.get("snippet_hash") != digest(
        statement
    ):
        errors.append(
            fail(path, "snippet_hash must hash the canonical statement string")
        )

    expected_evidence_hash = digest(payload_without_metadata(document))
    metadata = document.get("metadata", {})
    actual_evidence_hash = (
        metadata.get("evidence_hash") if isinstance(metadata, dict) else None
    )
    if actual_evidence_hash != expected_evidence_hash:
        errors.append(
            fail(
                path,
                "metadata.evidence_hash must hash canonical web-evidence payload excluding metadata",
            )
        )
        return errors, None
    return errors, expected_evidence_hash


def _validate_source_claim(
    path: Path,
    document: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
    *,
    required_type: str,
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    anchor_id = document.get("source_anchor_id")
    if not is_nonempty_string(anchor_id):
        return [fail(path, "source_anchor_id is required")], None
    anchor = anchors.get(anchor_id)
    if anchor is None:
        return [fail(path, f"source_anchor_id {anchor_id} does not resolve")], None
    if anchor.get("anchor_type") != required_type:
        errors.append(
            fail(
                path,
                f"source anchor {anchor_id} must have anchor_type {required_type}",
            )
        )
    if not is_nonempty_string(anchor.get("participant")):
        errors.append(fail(path, f"source anchor {anchor_id} lacks a participant"))

    source_claim_quote = document.get("source_claim_quote")
    if not is_nonempty_string(source_claim_quote):
        errors.append(fail(path, "source_claim_quote is required"))
    elif source_claim_quote not in anchor.get("atomic_quotes", []):
        errors.append(
            fail(
                path,
                f"source_claim_quote must select a declared atomic quote from anchor {anchor_id}",
            )
        )
    claim = document.get("claim")
    if not is_nonempty_string(claim):
        errors.append(fail(path, "claim is required"))
    elif claim != source_claim_quote:
        errors.append(fail(path, "claim must exactly equal source_claim_quote"))
    return errors, anchor


def _evidence_manifest_hash(
    evidence_ids: list[str], evidence_hashes: dict[str, str]
) -> str | None:
    if any(evidence_id not in evidence_hashes for evidence_id in evidence_ids):
        return None
    manifest = [
        {
            "web_evidence_id": evidence_id,
            "evidence_hash": evidence_hashes[evidence_id],
        }
        for evidence_id in sorted(evidence_ids)
    ]
    return digest(manifest)


def _validate_evidence_citations(
    path: Path,
    document: dict[str, Any],
    evidence_hashes: dict[str, str],
) -> list[str]:
    evidence_ids, errors = _list_of_unique_strings(
        path, document.get("web_evidence_ids"), "web_evidence_ids"
    )
    if evidence_ids != sorted(evidence_ids):
        errors.append(fail(path, "web_evidence_ids must be sorted"))
    for evidence_id in evidence_ids:
        if evidence_id not in evidence_hashes:
            errors.append(
                fail(path, f"web_evidence_id {evidence_id} does not resolve")
            )

    expected_hash = _evidence_manifest_hash(evidence_ids, evidence_hashes)
    metadata = document.get("metadata", {})
    actual_hash = metadata.get("evidence_hash") if isinstance(metadata, dict) else None
    if not isinstance(actual_hash, str) or SHA256.fullmatch(actual_hash) is None:
        errors.append(fail(path, "metadata.evidence_hash is required"))
    elif expected_hash is not None and actual_hash != expected_hash:
        errors.append(
            fail(
                path,
                "metadata.evidence_hash must hash the sorted resolved evidence manifest",
            )
        )
    return errors


def _validate_research(
    path: Path,
    document: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
    evidence_hashes: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    allowed_keys = {
        "claim",
        "finding",
        "fixture_id",
        "metadata",
        "outcome",
        "schema_version",
        "source_anchor_id",
        "source_claim_quote",
        "synthetic_evidence_only",
        "web_evidence_ids",
    }
    if set(document) != allowed_keys:
        errors.append(fail(path, "research fixture has unexpected or missing fields"))
    if document.get("expected_rejection") is True:
        errors.append(fail(path, "research fixtures must not be rejection fixtures"))
    if document.get("outcome") not in FOUR_VERDICTS:
        errors.append(fail(path, "research outcome must be a four-verdict value"))
    expected_outcome = str(document.get("fixture_id", "")).removeprefix(
        "research-"
    ).removesuffix("-001")
    if document.get("outcome") != expected_outcome:
        errors.append(
            fail(path, "research outcome must match the value encoded in fixture_id")
        )
    if not is_nonempty_string(document.get("finding")):
        errors.append(fail(path, "research finding is required"))
    if document.get("synthetic_evidence_only") is not True:
        errors.append(fail(path, "research must set synthetic_evidence_only=true"))
    claim_errors, _ = _validate_source_claim(
        path, document, anchors, required_type="factual_claim"
    )
    errors.extend(claim_errors)
    errors.extend(_validate_evidence_citations(path, document, evidence_hashes))
    return errors


def _validate_factcheck(
    path: Path,
    document: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
    evidence_hashes: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    fixture_id = document.get("fixture_id")
    if fixture_id == "factcheck-opinion-excluded-001":
        allowed_keys = {
            "claim",
            "exclusion_reason",
            "expected_rejection",
            "fixture_id",
            "metadata",
            "schema_version",
            "selection_status",
            "source_anchor_id",
            "source_claim_quote",
        }
        if set(document) != allowed_keys:
            errors.append(
                fail(path, "opinion exclusion fixture has unexpected or missing fields")
            )
        if document.get("expected_rejection") is not True:
            errors.append(
                fail(path, "excluded opinion must set expected_rejection=true")
            )
        if document.get("selection_status") != "excluded":
            errors.append(
                fail(path, "excluded opinion must set selection_status=excluded")
            )
        claim_errors, _ = _validate_source_claim(
            path, document, anchors, required_type="opinion"
        )
        errors.extend(claim_errors)
        keys = set(recursive_keys(document))
        if "web_evidence_id" in keys or "web_evidence_ids" in keys:
            errors.append(fail(path, "excluded opinion must not reference web evidence"))
        metadata = document.get("metadata", {})
        if isinstance(metadata, dict) and "evidence_hash" in metadata:
            errors.append(fail(path, "excluded opinion must not have evidence_hash"))
        if "verdict" in keys:
            errors.append(fail(path, "excluded opinion must not have a verdict"))
        if not is_nonempty_string(document.get("exclusion_reason")):
            errors.append(fail(path, "excluded opinion requires exclusion_reason"))
        return errors

    allowed_keys = {
        "claim",
        "fixture_id",
        "metadata",
        "rationale",
        "schema_version",
        "source_anchor_id",
        "source_claim_quote",
        "synthetic_evidence_only",
        "verdict",
        "web_evidence_ids",
    }
    if set(document) != allowed_keys:
        errors.append(fail(path, "fact-check fixture has unexpected or missing fields"))
    if document.get("expected_rejection") is True:
        errors.append(
            fail(path, "non-opinion fact-check must not be a rejection fixture")
        )
    if document.get("verdict") not in FOUR_VERDICTS:
        errors.append(fail(path, "fact-check verdict must be a four-verdict value"))
    expected_verdict = str(document.get("fixture_id", "")).removeprefix(
        "factcheck-"
    ).removesuffix("-001")
    if document.get("verdict") != expected_verdict:
        errors.append(
            fail(path, "fact-check verdict must match the value encoded in fixture_id")
        )
    for field in ("claim", "rationale"):
        if not is_nonempty_string(document.get(field)):
            errors.append(fail(path, f"fact-check {field} is required"))
    if document.get("synthetic_evidence_only") is not True:
        errors.append(fail(path, "fact-check must set synthetic_evidence_only=true"))
    claim_errors, _ = _validate_source_claim(
        path, document, anchors, required_type="factual_claim"
    )
    errors.extend(claim_errors)
    errors.extend(_validate_evidence_citations(path, document, evidence_hashes))
    return errors


SUMMARY_CONTAMINATION_KEYS = {
    "accessed_at",
    "claim",
    "domain",
    "evidence_hash",
    "finding",
    "outcome",
    "rationale",
    "research",
    "research_results",
    "snippet_hash",
    "source_claim_quote",
    "synthetic_evidence_only",
    "url",
    "verdict",
    "web_evidence_id",
    "web_evidence_ids",
}


def _validate_summary_isolation(path: Path, value: object) -> list[str]:
    errors: list[str] = []
    keys = {key.lower() for key in recursive_keys(value)}
    contaminated = sorted(keys & SUMMARY_CONTAMINATION_KEYS)
    if contaminated:
        errors.append(
            fail(
                path,
                "accepted summary contains research/web/verdict fields: "
                + ", ".join(contaminated),
            )
        )
    strings = recursive_strings(value)
    if any(URL.search(text) for text in strings):
        errors.append(fail(path, "accepted summary must not contain URLs"))
    if any(VERDICT_WORD.search(text) for text in strings):
        errors.append(fail(path, "accepted summary must not contain verdict language"))
    return errors


def _validate_summary_item(
    path: Path,
    item: object,
    anchors: dict[str, dict[str, Any]],
    label: str,
    *,
    expected_keys: set[str] | None = None,
) -> list[str]:
    if not isinstance(item, dict):
        return [fail(path, f"{label} must be an object")]
    errors: list[str] = []
    expected_item_keys = expected_keys or {
        "text",
        "source_anchor_ids",
        "supporting_quotes",
    }
    if set(item) != expected_item_keys:
        errors.append(
            fail(path, f"{label} must contain exactly the accepted summary item fields")
        )
    if not is_nonempty_string(item.get("text")):
        errors.append(fail(path, f"{label}.text is required"))

    anchor_ids, anchor_errors = _list_of_unique_strings(
        path, item.get("source_anchor_ids"), f"{label}.source_anchor_ids"
    )
    errors.extend(anchor_errors)
    quote_value = item.get("supporting_quotes")
    quotes: dict[str, str] = {}
    if not isinstance(quote_value, list) or not quote_value:
        errors.append(
            fail(path, f"{label}.supporting_quotes must be a non-empty list")
        )
    else:
        for index, quote in enumerate(quote_value):
            if not isinstance(quote, dict):
                errors.append(
                    fail(path, f"{label}.supporting_quotes[{index}] must be an object")
                )
                continue
            expected_quote_keys = {"source_anchor_id", "exact_quote"}
            if set(quote) != expected_quote_keys:
                errors.append(
                    fail(
                        path,
                        f"{label}.supporting_quotes[{index}] must contain exactly source_anchor_id and exact_quote",
                    )
                )
            anchor_id = quote.get("source_anchor_id")
            exact_quote = quote.get("exact_quote")
            if not is_nonempty_string(anchor_id) or not is_nonempty_string(exact_quote):
                errors.append(
                    fail(
                        path,
                        f"{label}.supporting_quotes[{index}] requires source_anchor_id and exact_quote",
                    )
                )
                continue
            if anchor_id in quotes:
                errors.append(
                    fail(path, f"{label}.supporting_quotes duplicates {anchor_id}")
                )
            quotes[anchor_id] = exact_quote

    if set(anchor_ids) != set(quotes):
        errors.append(
            fail(
                path,
                f"{label}.supporting_quotes must cover exactly source_anchor_ids",
            )
        )
    for anchor_id in anchor_ids:
        anchor = anchors.get(anchor_id)
        if anchor is None:
            errors.append(fail(path, f"summary anchor {anchor_id} does not resolve"))
            continue
        if anchor.get("anchor_type") != "factual_claim":
            errors.append(
                fail(
                    path,
                    f"accepted summary anchor {anchor_id} must be factual_claim, not {anchor.get('anchor_type')}",
                )
            )
        if anchor_id in quotes and quotes[anchor_id] not in anchor.get(
            "atomic_quotes", []
        ):
            errors.append(
                fail(
                    path,
                    f"supporting quote for {anchor_id} must select a declared atomic quote",
                )
            )
    errors.extend(_validate_summary_isolation(path, item))
    return errors


def _require_response_shape(
    path: Path,
    document: dict[str, Any],
    *,
    status: str,
    error_code: str,
    expected_keys: set[str] | None = None,
) -> list[str]:
    response = document.get("response")
    if not isinstance(response, dict):
        return [fail(path, "response must be an object")]
    errors: list[str] = []
    required_keys = expected_keys or {"error_code", "status"}
    if set(response) != required_keys:
        errors.append(fail(path, "response has unexpected or missing fields"))
    if response.get("status") != status:
        errors.append(fail(path, f"response.status must be {status}"))
    if response.get("error_code") != error_code:
        errors.append(fail(path, f"response.error_code must be {error_code}"))
    return errors


def _validate_summary(
    path: Path,
    document: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
) -> list[str]:
    fixture_id = document.get("fixture_id")
    errors: list[str] = []
    metadata = document.get("metadata")
    if isinstance(metadata, dict) and "evidence_hash" in metadata:
        errors.append(fail(path, "summary metadata must not contain evidence_hash"))
    base_keys = {"fixture_id", "metadata", "response", "schema_version"}
    if fixture_id in {SUMMARY_GROUNDED, SUMMARY_RETRY}:
        allowed_keys = base_keys
    elif fixture_id in {
        SUMMARY_UNSUPPORTED,
        SUMMARY_FOREIGN,
        SUMMARY_INJECTION,
    }:
        allowed_keys = base_keys | {"expected_rejection", "request"}
    else:
        allowed_keys = base_keys | {"expected_rejection"}
    if set(document) != allowed_keys:
        errors.append(fail(path, "summary fixture has unexpected or missing fields"))

    if fixture_id == SUMMARY_GROUNDED:
        if document.get("expected_rejection") is True:
            errors.append(fail(path, "grounded summary must not be rejected"))
        response = document.get("response")
        sections = response.get("sections") if isinstance(response, dict) else None
        if isinstance(response, dict) and set(response) != {"sections"}:
            errors.append(
                fail(path, "grounded summary response has unexpected or missing fields")
            )
        if not isinstance(sections, list) or not sections:
            return errors + [fail(path, "grounded summary requires response.sections")]
        for section_index, section in enumerate(sections):
            if isinstance(section, dict) and set(section) != {"items"}:
                errors.append(
                    fail(
                        path,
                        f"response.sections[{section_index}] has unexpected or missing fields",
                    )
                )
            items = section.get("items") if isinstance(section, dict) else None
            if not isinstance(items, list) or not items:
                errors.append(
                    fail(
                        path,
                        f"response.sections[{section_index}].items must be non-empty",
                    )
                )
                continue
            for item_index, item in enumerate(items):
                errors.extend(
                    _validate_summary_item(
                        path,
                        item,
                        anchors,
                        f"response.sections[{section_index}].items[{item_index}]",
                    )
                )
        errors.extend(_validate_summary_isolation(path, response))
        return errors

    if document.get("expected_rejection") is not True and fixture_id != SUMMARY_RETRY:
        errors.append(fail(path, "summary rejection fixture must set expected_rejection=true"))

    if fixture_id == SUMMARY_UNSUPPORTED:
        errors.extend(
            _require_response_shape(
                path,
                document,
                status="rejected",
                error_code="assertion_not_grounded",
            )
        )
        request = document.get("request")
        if not isinstance(request, dict) or not is_nonempty_string(
            request.get("assertion") if isinstance(request, dict) else None
        ):
            errors.append(fail(path, "unsupported assertion request is required"))
            return errors
        if set(request) != {"assertion", "source_anchor_ids"}:
            errors.append(
                fail(path, "unsupported assertion request has unexpected or missing fields")
            )
        anchor_ids, anchor_errors = _list_of_unique_strings(
            path,
            request.get("source_anchor_ids"),
            "request.source_anchor_ids",
        )
        errors.extend(anchor_errors)
        for anchor_id in anchor_ids:
            anchor = anchors.get(anchor_id)
            if anchor is None:
                errors.append(
                    fail(path, f"unsupported assertion anchor {anchor_id} does not resolve")
                )
            elif anchor.get("anchor_type") != "factual_claim":
                errors.append(
                    fail(path, f"unsupported assertion anchor {anchor_id} must be factual")
                )
            elif request["assertion"] in anchor.get("exact_quote", ""):
                errors.append(
                    fail(path, "unsupported assertion is directly present in cited quote")
                )
        return errors

    if fixture_id == SUMMARY_FOREIGN:
        errors.extend(
            _require_response_shape(
                path, document, status="rejected", error_code="foreign_anchor"
            )
        )
        request = document.get("request")
        if isinstance(request, dict) and set(request) != {"source_anchor_ids"}:
            errors.append(
                fail(path, "foreign-anchor request has unexpected or missing fields")
            )
        anchor_ids, anchor_errors = _list_of_unique_strings(
            path,
            request.get("source_anchor_ids") if isinstance(request, dict) else None,
            "request.source_anchor_ids",
        )
        errors.extend(anchor_errors)
        if anchor_ids and not any(anchor_id not in anchors for anchor_id in anchor_ids):
            errors.append(
                fail(path, "foreign-anchor rejection must contain an unresolved anchor")
            )
        return errors

    if fixture_id == SUMMARY_INJECTION:
        errors.extend(
            _require_response_shape(
                path,
                document,
                status="rejected",
                error_code="source_prompt_injection",
            )
        )
        request = document.get("request")
        if isinstance(request, dict) and set(request) != {"source_anchor_ids"}:
            errors.append(
                fail(path, "prompt-injection request has unexpected or missing fields")
            )
        anchor_ids, anchor_errors = _list_of_unique_strings(
            path,
            request.get("source_anchor_ids") if isinstance(request, dict) else None,
            "request.source_anchor_ids",
        )
        errors.extend(anchor_errors)
        for anchor_id in anchor_ids:
            anchor = anchors.get(anchor_id)
            if anchor is None:
                errors.append(fail(path, f"injection anchor {anchor_id} does not resolve"))
            elif anchor.get("anchor_type") != "instruction_like_content":
                errors.append(
                    fail(
                        path,
                        f"injection anchor {anchor_id} must be instruction_like_content",
                    )
                )
        return errors

    if fixture_id == SUMMARY_TIMEOUT:
        errors.extend(
            _require_response_shape(
                path,
                document,
                status="failed",
                error_code="provider_timeout",
                expected_keys={"error_code", "retryable", "status"},
            )
        )
        response = document.get("response")
        if not isinstance(response, dict) or response.get("retryable") is not True:
            errors.append(fail(path, "provider timeout must set retryable=true"))
        return errors

    if fixture_id == SUMMARY_MALFORMED:
        errors.extend(
            _require_response_shape(
                path, document, status="rejected", error_code="malformed_schema"
            )
        )
        return errors

    if fixture_id == SUMMARY_RETRY:
        if document.get("expected_rejection") is True:
            errors.append(fail(path, "retry fixture must not be rejected"))
        response = document.get("response")
        if not isinstance(response, dict):
            return errors + [fail(path, "retry response must be an object")]
        if set(response) != {"attempts", "retry_key"}:
            errors.append(fail(path, "retry response has unexpected or missing fields"))
        if response.get("retry_key") != "meeting-pack-001:summary-grounded-001":
            errors.append(
                fail(
                    path,
                    "retry_key must equal meeting-pack-001:summary-grounded-001",
                )
            )
        attempts = response.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 2:
            return errors + [fail(path, "retry response requires exactly two attempts")]
        first, second = attempts
        if isinstance(first, dict) and set(first) != {
            "attempt",
            "error_code",
            "status",
        }:
            errors.append(fail(path, "retry attempt 1 has unexpected or missing fields"))
        if not isinstance(first, dict) or (
            first.get("attempt"),
            first.get("status"),
            first.get("error_code"),
        ) != (1, "failed", "provider_timeout"):
            errors.append(
                fail(path, "retry attempt 1 must be failed provider_timeout")
            )
        if not isinstance(second, dict) or (
            second.get("attempt"),
            second.get("status"),
        ) != (2, "succeeded"):
            errors.append(fail(path, "retry attempt 2 must succeed"))
        else:
            errors.extend(
                _validate_summary_item(
                    path,
                    second,
                    anchors,
                    "response.attempts[1]",
                    expected_keys={
                        "attempt",
                        "source_anchor_ids",
                        "status",
                        "supporting_quotes",
                        "text",
                    },
                )
            )
        errors.extend(_validate_summary_isolation(path, response))
        return errors

    errors.append(fail(path, f"unknown summary fixture family {fixture_id}"))
    return errors


def _read_schema(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [fail(path, "required schema artifact is missing")]
    raw = path.read_bytes()
    try:
        document = parse_json_bytes(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [fail(path, f"invalid schema JSON: {exc}")]
    if raw != canonical_bytes(document):
        errors.append(fail(path, "schema JSON is not canonical key-sorted UTF-8"))
    if not isinstance(document, dict):
        errors.append(fail(path, "schema top-level JSON must be an object"))
        return None, errors
    return document, errors


def _validate_schema_artifacts(root: Path) -> list[str]:
    errors: list[str] = []
    schema_root = root / "schema"
    actual_schema_paths = {
        path.relative_to(root) for path in schema_root.glob("**/*.json")
    } if schema_root.is_dir() else set()
    for unexpected in sorted(actual_schema_paths - REQUIRED_SCHEMA_PATHS):
        errors.append(fail(root / unexpected, "unexpected schema artifact"))

    common_path = root / "schema/provider-fixture.v1.schema.json"
    source_path = root / "schema/source-pack.v1.schema.json"
    common, common_errors = _read_schema(common_path)
    source, source_errors = _read_schema(source_path)
    errors.extend(common_errors)
    errors.extend(source_errors)

    if common is not None:
        if digest(common) != COMMON_SCHEMA_DIGEST:
            errors.append(fail(common_path, "common schema contract has drifted"))
        if common.get("$schema") != JSON_SCHEMA_DRAFT:
            errors.append(fail(common_path, "common schema has invalid $schema draft"))
        if common.get("$id") != COMMON_SCHEMA_ID:
            errors.append(fail(common_path, "common schema has invalid absolute $id"))
        if digest(common.get("allOf")) != COMMON_ALLOF_DIGEST:
            errors.append(
                fail(
                    common_path,
                    "common schema allOf/summary conditional contract has drifted",
                )
            )
        definitions = common.get("$defs")
        if not isinstance(definitions, dict) or not COMMON_SCHEMA_DEFS.issubset(
            definitions
        ):
            errors.append(fail(common_path, "common schema lacks required family $defs"))
        elif not all(
            isinstance(definitions[name], dict) for name in COMMON_SCHEMA_DEFS
        ):
            errors.append(
                fail(common_path, "common schema family $defs must be objects")
            )
        elif not all(
            definitions[name].get("additionalProperties") is False
            and isinstance(definitions[name].get("required"), list)
            for name in COMMON_SCHEMA_DEFS
        ):
            errors.append(
                fail(common_path, "common schema family $defs must be strict")
            )
        if isinstance(definitions, dict):
            opinion = definitions.get("opinionExclusion")
            expected_opinion_required = {
                "claim",
                "exclusion_reason",
                "expected_rejection",
                "fixture_id",
                "metadata",
                "schema_version",
                "selection_status",
                "source_anchor_id",
                "source_claim_quote",
            }
            if (
                not isinstance(opinion, dict)
                or not isinstance(opinion.get("required"), list)
                or set(opinion["required"]) != expected_opinion_required
            ):
                errors.append(
                    fail(common_path, "opinion exclusion schema contract has drifted")
                )

            web_evidence = definitions.get("webEvidence")
            expected_web_required = {
                "accessed_at",
                "domain",
                "evidence_kind",
                "fixture_id",
                "metadata",
                "schema_version",
                "snippet_hash",
                "statement",
                "synthetic",
                "title",
                "url",
                "web_evidence_id",
            }
            web_properties = (
                web_evidence.get("properties")
                if isinstance(web_evidence, dict)
                else None
            )
            web_url = (
                web_properties.get("url")
                if isinstance(web_properties, dict)
                else None
            )
            if (
                not isinstance(web_evidence, dict)
                or not isinstance(web_evidence.get("required"), list)
                or set(web_evidence["required"]) != expected_web_required
                or not isinstance(web_url, dict)
                or web_url.get("pattern")
                != r"^https://fixtures\.invalid/evidence/web-evidence-[0-9]{3}$"
            ):
                errors.append(
                    fail(common_path, "web evidence schema contract has drifted")
                )

            factcheck = definitions.get("factcheckResult")
            factcheck_properties = (
                factcheck.get("properties")
                if isinstance(factcheck, dict)
                else None
            )
            verdict_shape = (
                factcheck_properties.get("verdict")
                if isinstance(factcheck_properties, dict)
                else None
            )
            if (
                not isinstance(verdict_shape, dict)
                or not isinstance(verdict_shape.get("enum"), list)
                or set(verdict_shape["enum"]) != FOUR_VERDICTS
            ):
                errors.append(
                    fail(common_path, "fact-check verdict schema contract has drifted")
                )

            summary_item = definitions.get("summaryItem")
            summary_properties = (
                summary_item.get("properties")
                if isinstance(summary_item, dict)
                else None
            )
            summary_text = (
                summary_properties.get("text")
                if isinstance(summary_properties, dict)
                else None
            )
            if summary_text != {"minLength": 1, "type": "string"}:
                errors.append(
                    fail(common_path, "summary item text schema contract has drifted")
                )
        common_properties = common.get("properties")
        metadata_reference = (
            common_properties.get("metadata")
            if isinstance(common_properties, dict)
            else None
        )
        metadata = (
            definitions.get("metadata") if isinstance(definitions, dict) else None
        )
        if metadata_reference != {"$ref": "#/$defs/metadata"}:
            errors.append(
                fail(common_path, "common schema metadata must reference $defs")
            )
        if not isinstance(metadata, dict):
            errors.append(fail(common_path, "common schema lacks metadata shape"))
        else:
            metadata_properties = metadata.get("properties")
            metadata_required = metadata.get("required")
            if (
                metadata.get("additionalProperties") is not False
                or not isinstance(metadata_properties, dict)
                or set(metadata_properties) != METADATA_ALLOWED_KEYS
                or not isinstance(metadata_required, list)
                or set(metadata_required) != METADATA_REQUIRED_KEYS
            ):
                errors.append(
                    fail(common_path, "common schema metadata shape is not strict")
                )

    if source is not None:
        if digest(source) != SOURCE_SCHEMA_DIGEST:
            errors.append(fail(source_path, "source schema contract has drifted"))
        if source.get("$schema") != JSON_SCHEMA_DRAFT:
            errors.append(fail(source_path, "source schema has invalid $schema draft"))
        if source.get("$id") != SOURCE_SCHEMA_ID:
            errors.append(fail(source_path, "source schema has invalid absolute $id"))
        all_of = source.get("allOf")
        if (
            not isinstance(all_of, list)
            or {"$ref": COMMON_SCHEMA_ID} not in all_of
        ):
            errors.append(
                fail(source_path, "source schema must reference the absolute common $id")
            )
        properties = source.get("properties")
        source_required = source.get("required")
        fixture_id_shape = (
            properties.get("fixture_id") if isinstance(properties, dict) else None
        )
        if (
            not isinstance(properties, dict)
            or not isinstance(source_required, list)
            or set(source_required)
            != {
                "schema_version",
                "fixture_id",
                "metadata",
                "revisions",
                "anchors",
            }
            or not isinstance(fixture_id_shape, dict)
            or fixture_id_shape.get("const") != "meeting-pack-001"
            or source.get("additionalProperties") is not False
        ):
            errors.append(fail(source_path, "source schema lacks required source shape"))
        else:
            anchors_shape = properties.get("anchors")
            revisions_shape = properties.get("revisions")
            anchor_items = (
                anchors_shape.get("items")
                if isinstance(anchors_shape, dict)
                else None
            )
            revision_items = (
                revisions_shape.get("items")
                if isinstance(revisions_shape, dict)
                else None
            )
            anchor_required = {
                "anchor_id",
                "anchor_type",
                "atomic_quotes",
                "exact_quote",
                "participant",
                "revision_id",
            }
            anchor_required_value = (
                anchor_items.get("required")
                if isinstance(anchor_items, dict)
                else None
            )
            if (
                not isinstance(anchor_items, dict)
                or anchor_items.get("additionalProperties") is not False
                or not isinstance(anchor_required_value, list)
                or set(anchor_required_value) != anchor_required
            ):
                errors.append(
                    fail(source_path, "source schema anchor shape is not strict")
                )
            else:
                anchor_properties = anchor_items.get("properties")
                atomic_quotes = (
                    anchor_properties.get("atomic_quotes")
                    if isinstance(anchor_properties, dict)
                    else None
                )
                atomic_items = (
                    atomic_quotes.get("items")
                    if isinstance(atomic_quotes, dict)
                    else None
                )
                if (
                    not isinstance(atomic_quotes, dict)
                    or atomic_quotes.get("type") != "array"
                    or atomic_quotes.get("minItems") != 1
                    or atomic_quotes.get("uniqueItems") is not True
                    or not isinstance(atomic_items, dict)
                    or atomic_items.get("type") != "string"
                ):
                    errors.append(
                        fail(
                            source_path,
                            "source schema atomic_quotes shape is not strict",
                        )
                    )
            revision_required_value = (
                revision_items.get("required")
                if isinstance(revision_items, dict)
                else None
            )
            if (
                not isinstance(revision_items, dict)
                or revision_items.get("additionalProperties") is not False
                or not isinstance(revision_required_value, list)
                or set(revision_required_value)
                != {"revision_id", "text"}
            ):
                errors.append(
                    fail(source_path, "source schema revision shape is not strict")
                )
    return errors


def _candidate_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.glob("**/*.json"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == "schema":
            continue
        candidates.append(path)
    return sorted(candidates)


def validate(root: Path) -> list[str]:
    """Validate the exact fixture inventory and all cross-document contracts."""

    root = root.resolve()
    files = _candidate_paths(root)
    errors: list[str] = _validate_schema_artifacts(root)
    documents: dict[Path, dict[str, Any]] = {}
    actual_paths: set[Path] = set()

    # Pass 1: canonical parse, envelope validation, path/ID indexing.
    for path in files:
        relative = path.relative_to(root)
        actual_paths.add(relative)
        if relative not in EXPECTED_PATHS:
            errors.append(fail(path, f"unexpected fixture path {relative.as_posix()}"))
        raw = path.read_bytes()
        if not raw.endswith(b"\n"):
            errors.append(fail(path, "JSON must end with newline"))
        try:
            document = parse_json_bytes(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(fail(path, f"invalid JSON: {exc}"))
            continue
        if raw != canonical_bytes(document):
            errors.append(fail(path, "JSON is not canonical key-sorted UTF-8"))
        errors.extend(validate_document(path, document))
        if not isinstance(document, dict):
            continue
        documents[relative] = document
        expected_id = EXPECTED_PATHS.get(relative)
        if expected_id is not None and document.get("fixture_id") != expected_id:
            errors.append(
                fail(path, f"fixture_id must be {expected_id} for this path")
            )

    for missing in sorted(set(EXPECTED_PATHS) - actual_paths):
        errors.append(f"{missing.as_posix()}: required fixture is missing")
    if not files:
        errors.append("provider_fixtures: no JSON fixtures found")

    fixture_id_paths: dict[str, Path] = {}
    for relative, document in documents.items():
        fixture_id = document.get("fixture_id")
        if not isinstance(fixture_id, str):
            continue
        previous = fixture_id_paths.get(fixture_id)
        if previous is not None:
            errors.append(
                fail(
                    root / relative,
                    f"duplicate fixture_id {fixture_id}; first seen at {previous.as_posix()}",
                )
            )
        else:
            fixture_id_paths[fixture_id] = relative

    # Pass 2: build the source/evidence graph, then resolve every dependent doc.
    source_relative = Path("source/meeting-pack-001.json")
    source_document = documents.get(source_relative)
    source_hash: str | None = None
    anchors: dict[str, dict[str, Any]] = {}
    if source_document is not None:
        source_errors, source_hash, _, anchors = _source_graph(
            root / source_relative, source_document
        )
        errors.extend(source_errors)

    if source_hash is not None:
        for relative, document in documents.items():
            metadata = document.get("metadata")
            actual_hash = (
                metadata.get("source_hash") if isinstance(metadata, dict) else None
            )
            if actual_hash != source_hash:
                errors.append(
                    fail(
                        root / relative,
                        "metadata.source_hash does not match meeting-pack-001",
                    )
                )

    evidence_hashes: dict[str, str] = {}
    for fixture_id in sorted(REQUIRED_FIXTURES["web_evidence"]):
        relative = Path("web_evidence") / f"{fixture_id}.json"
        document = documents.get(relative)
        if document is None:
            continue
        web_errors, evidence_hash = _validate_web_evidence(
            root / relative, document
        )
        errors.extend(web_errors)
        if evidence_hash is not None:
            evidence_hashes[fixture_id] = evidence_hash

    for fixture_id in sorted(REQUIRED_FIXTURES["summary"]):
        relative = Path("summary") / f"{fixture_id}.json"
        document = documents.get(relative)
        if document is not None:
            errors.extend(_validate_summary(root / relative, document, anchors))

    for fixture_id in sorted(REQUIRED_FIXTURES["research"]):
        relative = Path("research") / f"{fixture_id}.json"
        document = documents.get(relative)
        if document is not None:
            errors.extend(
                _validate_research(
                    root / relative, document, anchors, evidence_hashes
                )
            )

    for fixture_id in sorted(REQUIRED_FIXTURES["factcheck"]):
        relative = Path("factcheck") / f"{fixture_id}.json"
        document = documents.get(relative)
        if document is not None:
            errors.extend(
                _validate_factcheck(
                    root / relative, document, anchors, evidence_hashes
                )
            )
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=FIXTURES)
    args = parser.parse_args()
    failures = validate(args.root)
    if failures:
        print("FAIL:\n" + "\n".join(failures))
    else:
        print("PASS: provider fixtures are canonical and valid")
    raise SystemExit(bool(failures))

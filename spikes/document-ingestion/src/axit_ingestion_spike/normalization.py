"""Canonical text, JSON, and hashing helpers used by every parser adapter."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from typing import TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

NORMALIZATION_PROFILE = "nfc-lf-v1"
CANONICAL_NUMBER_DECIMALS = 6


def normalize_text(value: str) -> str:
    """Normalize line endings and Unicode while preserving meaningful whitespace."""

    lf_value = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", lf_value)


def text_fingerprint(value: str) -> str:
    """Return a content hash over the canonical text representation."""

    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def _normalize_float(value: float) -> int | float:
    if not math.isfinite(value):
        raise ValueError("canonical JSON numbers must be finite")
    rounded = round(value, CANONICAL_NUMBER_DECIMALS)
    if rounded == 0:
        return 0
    if rounded.is_integer():
        return int(rounded)
    return rounded


def canonicalize_json(value: object) -> JsonValue:
    """Convert supported values to the versioned canonical JSON value domain."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _normalize_float(value)
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            normalized_key = normalize_text(key)
            if normalized_key in normalized:
                raise ValueError("canonical JSON contains colliding normalized keys")
            normalized[normalized_key] = canonicalize_json(child)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        return [canonicalize_json(child) for child in value]
    raise ValueError(f"unsupported canonical JSON value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serialize canonical JSON with stable keys, separators, strings, and numbers."""

    return json.dumps(
        canonicalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def config_profile_hash(profile: object) -> str:
    """Name the exact deterministic parser/OCR configuration without raw secrets."""

    return canonical_sha256(profile)

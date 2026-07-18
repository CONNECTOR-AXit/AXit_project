"""Generate the checked Phase 2 OpenAPI, JSON Schema, and TypeScript client.

This intentionally uses the FastAPI/Pydantic source already required by the
API rather than adding a second generator runtime.  Generated artifacts are
byte-stable and ``--check`` makes contract drift fail before a client can be
silently out of date.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from pydantic import BaseModel  # noqa: E402

from app.contracts import (  # noqa: E402
    CitationTarget,
    ConversationMessage,
    ResearchResult,
    SourceAnchor,
    SummaryResult,
    contract_app,
)


SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "summary-result.v1.schema.json": SummaryResult,
    "research-result.v1.schema.json": ResearchResult,
    "citation-target.v1.schema.json": CitationTarget,
    "source-anchor.v1.schema.json": SourceAnchor,
    "conversation-message.v1.schema.json": ConversationMessage,
}


def canonical_bytes(value: object) -> bytes:
    """Emit canonical UTF-8 JSON without timestamps or whitespace drift."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _ts_type(schema: Mapping[str, Any]) -> str:
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            return "unknown"
        return reference.rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    enum = schema.get("enum")
    if isinstance(enum, list):
        return " | ".join(json.dumps(item, ensure_ascii=False) for item in enum)
    for combinator in ("anyOf", "oneOf", "allOf"):
        items = schema.get(combinator)
        if isinstance(items, list):
            rendered_union = [
                _ts_type(item) for item in items if isinstance(item, Mapping)
            ]
            return " | ".join(rendered_union) if rendered_union else "unknown"
    schema_type = schema.get("type")
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        items = schema.get("items")
        item_type = _ts_type(items) if isinstance(items, Mapping) else "unknown"
        return f"Array<{item_type}>"
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, Mapping):
            return "Record<string, unknown>"
        required_names = set(required) if isinstance(required, list) else set()
        members: list[str] = []
        for name in sorted(properties):
            property_schema = properties[name]
            if not isinstance(name, str) or not isinstance(property_schema, Mapping):
                continue
            optional = "" if name in required_names else "?"
            members.append(
                f"{json.dumps(name, ensure_ascii=False)}{optional}: "
                f"{_ts_type(property_schema)}"
            )
        return "{ " + "; ".join(members) + " }"
    return "unknown"


def _typescript_client(openapi: Mapping[str, Any]) -> bytes:
    components = openapi.get("components")
    schemas: Mapping[str, Any] = {}
    if isinstance(components, Mapping):
        possible_schemas = components.get("schemas")
        if isinstance(possible_schemas, Mapping):
            schemas = possible_schemas
    lines = [
        "/*",
        " * GENERATED FILE — do not edit by hand.",
        " * Source: tools/generate_contracts.py and app.contracts.",
        " */",
        "",
        "export const apiContractVersion = \"0.1.0-phase2\" as const;",
        "",
    ]
    for name in sorted(schemas):
        schema = schemas[name]
        if isinstance(name, str) and isinstance(schema, Mapping):
            lines.append(f"export type {name} = {_ts_type(schema)};")
    lines.extend(("", "export const operations = {"))
    paths = openapi.get("paths")
    if isinstance(paths, Mapping):
        for path in sorted(paths):
            operation_map = paths[path]
            if not isinstance(path, str) or not isinstance(operation_map, Mapping):
                continue
            for method in sorted(operation_map):
                operation = operation_map[method]
                if method not in {"get", "post", "put", "delete", "patch"}:
                    continue
                if not isinstance(operation, Mapping):
                    continue
                operation_id = operation.get("operationId")
                if not isinstance(operation_id, str):
                    continue
                lines.append(
                    "  "
                    + json.dumps(operation_id)
                    + ": { method: "
                    + json.dumps(method.upper())
                    + ", path: "
                    + json.dumps(path)
                    + " },"
                )
    lines.extend(("} as const;", ""))
    return "\n".join(lines).encode("utf-8")


def generated_artifacts() -> dict[Path, bytes]:
    """Return all deterministic artifacts relative to the repository root."""

    openapi = contract_app.openapi()
    artifacts: dict[Path, bytes] = {
        Path("packages/schemas/openapi.v1.json"): canonical_bytes(openapi),
        Path("packages/api-client/src/generated.ts"): _typescript_client(openapi),
    }
    for filename, model in SCHEMA_MODELS.items():
        artifacts[Path("packages/schemas") / filename] = canonical_bytes(
            model.model_json_schema()
        )
    return artifacts


def write_artifacts() -> None:
    """Write the generated artifact set into the working tree."""

    for relative_path, content in generated_artifacts().items():
        destination = ROOT / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def check_artifacts() -> list[Path]:
    """Return every missing or byte-stale generated contract artifact."""

    stale: list[Path] = []
    for relative_path, content in generated_artifacts().items():
        destination = ROOT / relative_path
        if not destination.exists() or destination.read_bytes() != content:
            stale.append(relative_path)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of writing drift")
    arguments = parser.parse_args(argv)
    if arguments.check:
        stale = check_artifacts()
        if stale:
            for path in stale:
                print(f"stale generated contract: {path.as_posix()}")
            return 1
        return 0
    write_artifacts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

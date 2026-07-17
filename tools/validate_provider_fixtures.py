#!/usr/bin/env python3
"""Validate deterministic provider-fixture.v1 JSON without third-party packages."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "provider_fixtures"
SCHEMA_VERSION = "provider-fixture.v1"
PROMPT_VERSION = "mock-provider.prompt.v1"
SOURCE_IDS = {"meeting-pack-001"}
REVISION_IDS = {"revision-agenda-001", "revision-alice-001", "revision-bob-001"}
ANCHOR_IDS = {"anchor-agenda-001", "anchor-alice-001", "anchor-alice-002", "anchor-bob-001", "anchor-bob-opinion-001"}
EVIDENCE_IDS = {f"web-evidence-{i:03d}" for i in range(1, 7)}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def fail(path: Path, message: str) -> str:
    try:
        display = path.relative_to(ROOT)
    except ValueError:
        display = path
    return f"{display}: {message}"


def refs(value: object, key: str) -> list[str]:
    if isinstance(value, dict):
        own = value.get(key)
        result = ([own] if isinstance(own, str) else own if isinstance(own, list) else [])
        return [item for item in result if isinstance(item, str)] + [r for child in value.values() for r in refs(child, key)]
    if isinstance(value, list):
        return [r for child in value for r in refs(child, key)]
    return []


def validate_document(path: Path, doc: object) -> list[str]:
    if not isinstance(doc, dict): return [fail(path, "top-level JSON must be an object")]
    errors: list[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION: errors.append(fail(path, "invalid schema_version"))
    if not isinstance(doc.get("fixture_id"), str): errors.append(fail(path, "missing fixture_id"))
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict): return errors + [fail(path, "missing metadata object")]
    for field in ("author_role", "reviewer_role", "created_at", "prompt_version", "source_hash"):
        if not metadata.get(field): errors.append(fail(path, f"metadata.{field} is required"))
    if metadata.get("author_role") != "coding-agent": errors.append(fail(path, "metadata.author_role must be coding-agent"))
    if metadata.get("prompt_version") != PROMPT_VERSION: errors.append(fail(path, "invalid metadata.prompt_version"))
    for field in ("source_hash", "evidence_hash"):
        if field in metadata and not isinstance(metadata[field], str) or field in metadata and not SHA256.fullmatch(metadata[field]): errors.append(fail(path, f"invalid metadata.{field}"))
    expected_rejection = bool(doc.get("expected_rejection"))
    for anchor in refs(doc, "anchor_id") + refs(doc, "source_anchor_id") + refs(doc, "source_anchor_ids"):
        if anchor not in ANCHOR_IDS and not expected_rejection: errors.append(fail(path, f"unknown anchor ID {anchor}"))
    for revision in refs(doc, "revision_id"):
        if revision not in REVISION_IDS: errors.append(fail(path, f"unknown revision ID {revision}"))
    for evidence in refs(doc, "web_evidence_id") + refs(doc, "web_evidence_ids"):
        if evidence not in EVIDENCE_IDS: errors.append(fail(path, f"unknown web evidence ID {evidence}"))
    if path.parent.name == "factcheck" and not expected_rejection:
        if not set(refs(doc, "source_anchor_id") + refs(doc, "source_anchor_ids")):
            errors.append(fail(path, "fact-check requires a participant anchor"))
        if not set(refs(doc, "web_evidence_id") + refs(doc, "web_evidence_ids")):
            errors.append(fail(path, "fact-check requires web evidence"))
        if "opinion" in json.dumps(doc, ensure_ascii=False).lower():
            errors.append(fail(path, "opinion/value-judgment claims must be excluded"))
    if path.parent.name == "summary":
        rendered = json.dumps(doc, ensure_ascii=False).lower()
        if "http://" in rendered or "https://" in rendered: errors.append(fail(path, "summary must not contain URLs"))
        if any(word in rendered for word in ("supported", "refuted", "mixed", "unverifiable", "verdict")): errors.append(fail(path, "summary must not contain verdicts"))
    return errors


def validate_source_pack(path: Path, doc: object) -> list[str]:
    errors = validate_document(path, doc)
    if not isinstance(doc, dict): return errors
    if doc.get("fixture_id") != "meeting-pack-001": errors.append(fail(path, "source fixture_id must be meeting-pack-001"))
    source_payload = {key: value for key, value in doc.items() if key != "metadata"}
    if doc.get("metadata", {}).get("source_hash") != digest(source_payload):
        errors.append(fail(path, "metadata.source_hash must hash canonical payload excluding metadata"))
    revisions = doc.get("revisions", [])
    anchors = doc.get("anchors", [])
    if {x.get("revision_id") for x in revisions if isinstance(x, dict)} != REVISION_IDS: errors.append(fail(path, "source revisions must use all fixed revision IDs"))
    if {x.get("anchor_id") for x in anchors if isinstance(x, dict)} != ANCHOR_IDS: errors.append(fail(path, "source anchors must use all fixed anchor IDs"))
    for anchor in anchors if isinstance(anchors, list) else []:
        if not isinstance(anchor, dict) or not anchor.get("exact_quote"): errors.append(fail(path, "each source anchor needs exact_quote"))
    return errors


def validate(root: Path) -> list[str]:
    files = sorted(path for path in root.glob("**/*.json") if "schema" not in path.parts)
    if not files: return ["provider_fixtures: no JSON fixtures found"]
    errors: list[str] = []
    for path in files:
        raw = path.read_bytes()
        if not raw.endswith(b"\n"): errors.append(fail(path, "JSON must end with newline"))
        try: doc = json.loads(raw)
        except json.JSONDecodeError as exc: errors.append(fail(path, f"invalid JSON: {exc.msg}")); continue
        if raw != canonical_bytes(doc): errors.append(fail(path, "JSON is not canonical key-sorted UTF-8"))
        errors.extend(validate_source_pack(path, doc) if path.parent.name == "source" else validate_document(path, doc))
    return errors

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("root", nargs="?", type=Path, default=FIXTURES)
    args = parser.parse_args(); failures = validate(args.root)
    print("PASS: provider fixtures are canonical and valid" if not failures else "FAIL:\n" + "\n".join(failures))
    raise SystemExit(bool(failures))

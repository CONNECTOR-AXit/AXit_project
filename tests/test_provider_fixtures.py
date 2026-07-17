from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "provider_fixtures"
SPEC = importlib.util.spec_from_file_location(
    "fixture_validator", ROOT / "tools" / "validate_provider_fixtures.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ProviderFixtureTests(unittest.TestCase):
    def copy_corpus(self, destination: Path) -> Path:
        root = destination / "provider_fixtures"
        shutil.copytree(FIXTURES, root)
        return root

    def read_doc(self, root: Path, relative: str) -> dict:
        return json.loads((root / relative).read_text(encoding="utf-8"))

    def write_doc(self, root: Path, relative: str, document: dict) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(validator.canonical_bytes(document))

    def rewrite_all_source_hashes(self, root: Path, source_hash: str) -> None:
        for path in root.glob("**/*.json"):
            if "schema" in path.relative_to(root).parts:
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            document["metadata"]["source_hash"] = source_hash
            path.write_bytes(validator.canonical_bytes(document))

    def rewrite_all_evidence_manifest_hashes(self, root: Path) -> None:
        evidence_hashes = {}
        for path in root.glob("web_evidence/*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            evidence_hashes[document["web_evidence_id"]] = document["metadata"][
                "evidence_hash"
            ]
        for family in ("research", "factcheck"):
            for path in root.glob(f"{family}/*.json"):
                document = json.loads(path.read_text(encoding="utf-8"))
                evidence_ids = document.get("web_evidence_ids")
                if not evidence_ids:
                    continue
                document["metadata"]["evidence_hash"] = (
                    validator._evidence_manifest_hash(
                        evidence_ids, evidence_hashes
                    )
                )
                path.write_bytes(validator.canonical_bytes(document))

    def errors_after(self, relative: str, mutate) -> list[str]:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            document = self.read_doc(root, relative)
            mutate(document)
            self.write_doc(root, relative, document)
            return validator.validate(root)

    def assert_rejected(self, errors: list[str], fragment: str) -> None:
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected error containing {fragment!r}, got:\n" + "\n".join(errors),
        )

    def test_complete_corpus_is_valid_and_canonical(self) -> None:
        self.assertEqual([], validator.validate(FIXTURES))
        for path in FIXTURES.glob("**/*.json"):
            document = json.loads(path.read_bytes())
            self.assertEqual(path.read_bytes(), validator.canonical_bytes(document))

    def test_noncanonical_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            path = root / "summary/summary-grounded-001.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.assert_rejected(validator.validate(root), "not canonical")

    def test_nonstandard_json_numbers_are_rejected_and_never_emitted(self) -> None:
        for constant, value in (
            ("NaN", float("nan")),
            ("Infinity", float("inf")),
            ("-Infinity", float("-inf")),
        ):
            with self.subTest(constant=constant):
                with self.assertRaises(ValueError):
                    validator.canonical_bytes({"value": value})
                with tempfile.TemporaryDirectory() as temp:
                    root = self.copy_corpus(Path(temp))
                    path = root / "summary/summary-grounded-001.json"
                    raw = path.read_text(encoding="utf-8")
                    path.write_text(
                        '{"nonfinite":' + constant + "," + raw[1:],
                        encoding="utf-8",
                    )
                    self.assert_rejected(
                        validator.validate(root), "non-standard JSON numeric constant"
                    )

    def test_surrogate_code_points_are_validation_errors_not_crashes(self) -> None:
        with self.assertRaises(ValueError):
            validator.canonical_bytes({"bad": "\ud800"})

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            path = root / "summary/summary-grounded-001.json"
            raw = path.read_text(encoding="utf-8")
            path.write_text(
                '{"bad":"\\ud800",' + raw[1:],
                encoding="utf-8",
            )
            self.assert_rejected(
                validator.validate(root), "UTF-16 surrogate code point"
            )

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            path = root / "schema/source-pack.v1.schema.json"
            raw = path.read_text(encoding="utf-8")
            path.write_text(
                '{"bad":"\\ud800",' + raw[1:],
                encoding="utf-8",
            )
            self.assert_rejected(
                validator.validate(root), "UTF-16 surrogate code point"
            )

    def test_required_inventory_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            (root / "summary/summary-grounded-001.json").unlink()
            self.assert_rejected(validator.validate(root), "required fixture is missing")

            extra = self.read_doc(root, "summary/summary-provider-timeout-001.json")
            extra["fixture_id"] = "summary-extra-001"
            self.write_doc(root, "summary/summary-extra-001.json", extra)
            self.assert_rejected(validator.validate(root), "unexpected fixture path")

    def test_duplicate_fixture_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            source = self.read_doc(root, "research/research-supported-001.json")
            target = self.read_doc(root, "research/research-refuted-001.json")
            target["fixture_id"] = source["fixture_id"]
            self.write_doc(root, "research/research-refuted-001.json", target)
            errors = validator.validate(root)
            self.assert_rejected(errors, "duplicate fixture_id")
            self.assert_rejected(errors, "fixture_id must be research-refuted-001")

    def test_every_document_must_record_completed_cross_review(self) -> None:
        errors = self.errors_after(
            "summary/summary-grounded-001.json",
            lambda document: document["metadata"].update(
                reviewer_role="pending-cross-review"
            ),
        )
        self.assert_rejected(errors, "coding-agent-cross-review")

    def test_metadata_rejects_unknown_keys(self) -> None:
        errors = self.errors_after(
            "summary/summary-grounded-001.json",
            lambda document: document["metadata"].update(live_provider="forbidden"),
        )
        self.assert_rejected(errors, "metadata has unexpected keys")

    def test_created_at_must_be_utc(self) -> None:
        for timestamp in (
            "2026-07-17T12:43:34+00:00",
            "2026-07-17T12:43:34.123Z",
            "2026-07-17T21:43:34+09:00",
            "2026-07-17T12:43:34",
        ):
            with self.subTest(timestamp=timestamp):
                errors = self.errors_after(
                    "summary/summary-grounded-001.json",
                    lambda document, value=timestamp: document["metadata"].update(
                        created_at=value
                    ),
                )
                self.assert_rejected(
                    errors, "metadata.created_at must be a UTC timestamp"
                )

    def test_source_exact_quote_must_resolve_to_revision(self) -> None:
        def mutate(document: dict) -> None:
            document["anchors"][0]["exact_quote"] = "span absent from every revision"
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        errors = self.errors_after("source/meeting-pack-001.json", mutate)
        self.assert_rejected(errors, "exact_quote is not contained")

    def test_source_anchor_type_is_closed(self) -> None:
        def mutate(document: dict) -> None:
            document["anchors"][0]["anchor_type"] = "unknown"
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        errors = self.errors_after("source/meeting-pack-001.json", mutate)
        self.assert_rejected(errors, "invalid anchor_type")

    def test_source_atomic_quotes_are_nonempty_unique_and_resolved(self) -> None:
        def mutate(document: dict) -> None:
            document["anchors"][0]["atomic_quotes"] = [
                "not contained in the source anchor"
            ]
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        errors = self.errors_after("source/meeting-pack-001.json", mutate)
        self.assert_rejected(errors, "atomic quote is not contained in exact_quote")

    def test_atomic_quotes_must_completely_segment_the_anchor_in_order(self) -> None:
        def mutate(document: dict) -> None:
            document["anchors"][1]["atomic_quotes"].append("Alice")
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        errors = self.errors_after("source/meeting-pack-001.json", mutate)
        self.assert_rejected(
            errors, "atomic_quotes must completely segment exact_quote in order"
        )

    def test_source_metadata_forbids_evidence_hash(self) -> None:
        errors = self.errors_after(
            "source/meeting-pack-001.json",
            lambda document: document["metadata"].update(
                evidence_hash="sha256:" + "0" * 64
            ),
        )
        self.assert_rejected(
            errors, "source metadata must not contain evidence_hash"
        )

    def test_source_revision_and_anchor_id_sets_are_fixed(self) -> None:
        def mutate_revision(document: dict) -> None:
            old_id = document["revisions"][0]["revision_id"]
            document["revisions"][0]["revision_id"] = "revision-replacement-001"
            for anchor in document["anchors"]:
                if anchor["revision_id"] == old_id:
                    anchor["revision_id"] = "revision-replacement-001"
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        revision_errors = self.errors_after(
            "source/meeting-pack-001.json", mutate_revision
        )
        self.assert_rejected(revision_errors, "fixed revision ID set")

        def mutate_anchor(document: dict) -> None:
            document["anchors"][0]["anchor_id"] = "anchor-replacement-001"
            document["metadata"]["source_hash"] = validator.digest(
                validator.payload_without_metadata(document)
            )

        anchor_errors = self.errors_after("source/meeting-pack-001.json", mutate_anchor)
        self.assert_rejected(anchor_errors, "fixed anchor ID set")

    def test_source_revision_and_anchor_fields_are_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            relative = "source/meeting-pack-001.json"
            source = self.read_doc(root, relative)
            source["anchors"][0]["raw_provider"] = "forbidden"
            source["revisions"][0]["url"] = "https://fixtures.invalid/forbidden"
            source_hash = validator.digest(
                validator.payload_without_metadata(source)
            )
            source["metadata"]["source_hash"] = source_hash
            self.write_doc(root, relative, source)
            self.rewrite_all_source_hashes(root, source_hash)
            errors = validator.validate(root)
            self.assert_rejected(
                errors, "anchors[0] has unexpected or missing fields"
            )
            self.assert_rejected(
                errors, "revisions[0] has unexpected or missing fields"
            )

    def test_all_documents_must_match_source_hash(self) -> None:
        errors = self.errors_after(
            "summary/summary-grounded-001.json",
            lambda document: document["metadata"].update(
                source_hash="sha256:" + "0" * 64
            ),
        )
        self.assert_rejected(errors, "does not match meeting-pack-001")

    def test_web_evidence_requires_reserved_normalized_citation(self) -> None:
        errors = self.errors_after(
            "web_evidence/web-evidence-001.json",
            lambda document: document.update(
                url="https://example.com/evidence",
                domain="example.com",
                accessed_at="not-a-date",
                title="",
                evidence_kind="",
            ),
        )
        self.assert_rejected(errors, "must equal https://fixtures.invalid")
        self.assert_rejected(errors, "domain must be fixtures.invalid")
        self.assert_rejected(errors, "UTC timestamp")
        self.assert_rejected(errors, "web evidence title is required")
        self.assert_rejected(errors, "web evidence evidence_kind is required")

    def test_malformed_web_url_returns_validation_error_without_crashing(self) -> None:
        errors = self.errors_after(
            "web_evidence/web-evidence-001.json",
            lambda document: document.update(url="https://[invalid"),
        )
        self.assert_rejected(errors, "web evidence URL must equal")

    def test_web_evidence_statement_and_hash_tampering_is_rejected(self) -> None:
        errors = self.errors_after(
            "web_evidence/web-evidence-001.json",
            lambda document: document.update(statement="tampered evidence statement"),
        )
        self.assert_rejected(errors, "snippet_hash")
        self.assert_rejected(errors, "metadata.evidence_hash")

    def test_missing_web_document_breaks_actual_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            (root / "web_evidence/web-evidence-001.json").unlink()
            errors = validator.validate(root)
            self.assert_rejected(errors, "required fixture is missing")
            self.assert_rejected(errors, "web_evidence_id web-evidence-001 does not resolve")

    def test_research_requires_factual_anchor_quote_and_evidence(self) -> None:
        def mutate(document: dict) -> None:
            document.pop("source_claim_quote")
            document["web_evidence_ids"] = []
            document["metadata"].pop("evidence_hash")

        errors = self.errors_after("research/research-supported-001.json", mutate)
        self.assert_rejected(errors, "source_claim_quote is required")
        self.assert_rejected(errors, "web_evidence_ids must be a non-empty list")
        self.assert_rejected(errors, "metadata.evidence_hash is required")

    def test_claim_and_source_quote_must_exactly_match_resolved_anchor(self) -> None:
        quote_errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document.update(
                claim="a quote that is absent",
                source_claim_quote="a quote that is absent",
            ),
        )
        self.assert_rejected(quote_errors, "must select a declared atomic quote")

        claim_errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document.update(claim="A paraphrase is not the quote."),
        )
        self.assert_rejected(claim_errors, "claim must exactly equal source_claim_quote")

    def test_atomic_claim_substrings_within_multi_sentence_anchor_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            relative = "source/meeting-pack-001.json"
            source = self.read_doc(root, relative)
            anchor = next(
                item
                for item in source["anchors"]
                if item["anchor_id"] == "anchor-alice-001"
            )
            original_quote = anchor["exact_quote"]
            added_atomic_quote = (
                "Alice: I will send the completed checklist to the facilitator."
            )
            expanded_quote = original_quote + " " + added_atomic_quote
            anchor["exact_quote"] = expanded_quote
            anchor["atomic_quotes"].append(added_atomic_quote)
            revision = next(
                item
                for item in source["revisions"]
                if item["revision_id"] == anchor["revision_id"]
            )
            revision["text"] = revision["text"].replace(original_quote, expanded_quote)
            source_hash = validator.digest(
                validator.payload_without_metadata(source)
            )
            source["metadata"]["source_hash"] = source_hash
            self.write_doc(root, relative, source)
            self.rewrite_all_source_hashes(root, source_hash)

            self.assertEqual([], validator.validate(root))

    def test_arbitrary_anchor_substrings_are_not_atomic_claims_or_support(self) -> None:
        research_errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document.update(
                claim="Alice",
                source_claim_quote="Alice",
            ),
        )
        self.assert_rejected(
            research_errors, "must select a declared atomic quote"
        )

        def mutate_summary(document: dict) -> None:
            document["response"]["sections"][0]["items"][1][
                "supporting_quotes"
            ][0]["exact_quote"] = "Alice"

        summary_errors = self.errors_after(
            "summary/summary-grounded-001.json", mutate_summary
        )
        self.assert_rejected(
            summary_errors, "must select a declared atomic quote"
        )

    def test_research_evidence_manifest_hash_is_verified(self) -> None:
        errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document["metadata"].update(
                evidence_hash="sha256:" + "0" * 64
            ),
        )
        self.assert_rejected(errors, "sorted resolved evidence manifest")

    def test_research_outcome_and_factcheck_verdict_are_closed(self) -> None:
        research_errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document.update(outcome="probably"),
        )
        self.assert_rejected(research_errors, "four-verdict")

        factcheck_errors = self.errors_after(
            "factcheck/factcheck-supported-001.json",
            lambda document: document.update(verdict="probably"),
        )
        self.assert_rejected(factcheck_errors, "four-verdict")

    def test_outcome_and_verdict_must_match_fixture_id(self) -> None:
        research_errors = self.errors_after(
            "research/research-supported-001.json",
            lambda document: document.update(outcome="refuted"),
        )
        self.assert_rejected(research_errors, "value encoded in fixture_id")

        factcheck_errors = self.errors_after(
            "factcheck/factcheck-supported-001.json",
            lambda document: document.update(verdict="refuted"),
        )
        self.assert_rejected(factcheck_errors, "value encoded in fixture_id")

    def test_non_rejected_factcheck_cannot_use_opinion_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            source = self.read_doc(root, "source/meeting-pack-001.json")
            opinion = next(
                anchor
                for anchor in source["anchors"]
                if anchor["anchor_type"] == "opinion"
            )
            relative = "factcheck/factcheck-supported-001.json"
            document = self.read_doc(root, relative)
            document["source_anchor_id"] = opinion["anchor_id"]
            document["source_claim_quote"] = opinion["exact_quote"]
            self.write_doc(root, relative, document)
            self.assert_rejected(
                validator.validate(root), "must have anchor_type factual_claim"
            )

    def test_excluded_opinion_has_no_evidence_hash_refs_or_verdict(self) -> None:
        def mutate(document: dict) -> None:
            document["selection_status"] = "selected"
            document["web_evidence_ids"] = ["web-evidence-001"]
            document["verdict"] = "supported"
            document["metadata"]["evidence_hash"] = "sha256:" + "0" * 64

        errors = self.errors_after(
            "factcheck/factcheck-opinion-excluded-001.json", mutate
        )
        self.assert_rejected(errors, "selection_status=excluded")
        self.assert_rejected(errors, "must not reference web evidence")
        self.assert_rejected(errors, "must not have evidence_hash")
        self.assert_rejected(errors, "must not have a verdict")

    def test_research_factcheck_and_opinion_top_level_fields_are_closed(self) -> None:
        cases = (
            (
                "research/research-supported-001.json",
                "url",
                "research fixture has unexpected or missing fields",
            ),
            (
                "factcheck/factcheck-supported-001.json",
                "live_web",
                "fact-check fixture has unexpected or missing fields",
            ),
            (
                "factcheck/factcheck-opinion-excluded-001.json",
                "raw_provider",
                "opinion exclusion fixture has unexpected or missing fields",
            ),
        )
        for relative, field, message in cases:
            with self.subTest(relative=relative):
                errors = self.errors_after(
                    relative,
                    lambda document, key=field: document.update({key: "forbidden"}),
                )
                self.assert_rejected(errors, message)

    def test_source_web_and_summary_top_level_fields_are_closed(self) -> None:
        grounded_errors = self.errors_after(
            "summary/summary-grounded-001.json",
            lambda document: document.update(url="https://fixtures.invalid/forbidden"),
        )
        self.assert_rejected(
            grounded_errors, "summary fixture has unexpected or missing fields"
        )

        rejection_errors = self.errors_after(
            "summary/summary-ungrounded-assertion-rejection-001.json",
            lambda document: document.update(
                web_evidence_ids=["web-evidence-001"]
            ),
        )
        self.assert_rejected(
            rejection_errors, "summary fixture has unexpected or missing fields"
        )

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            relative = "source/meeting-pack-001.json"
            source = self.read_doc(root, relative)
            source["raw_provider"] = "forbidden"
            source_hash = validator.digest(
                validator.payload_without_metadata(source)
            )
            source["metadata"]["source_hash"] = source_hash
            self.write_doc(root, relative, source)
            self.rewrite_all_source_hashes(root, source_hash)
            self.assert_rejected(
                validator.validate(root),
                "source fixture has unexpected or missing fields",
            )

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            relative = "web_evidence/web-evidence-001.json"
            evidence = self.read_doc(root, relative)
            evidence["raw_provider"] = "forbidden"
            evidence["metadata"]["evidence_hash"] = validator.digest(
                validator.payload_without_metadata(evidence)
            )
            self.write_doc(root, relative, evidence)
            self.rewrite_all_evidence_manifest_hashes(root)
            self.assert_rejected(
                validator.validate(root),
                "web evidence fixture has unexpected or missing fields",
            )

    def test_grounded_summary_requires_exact_supporting_quotes(self) -> None:
        def mutate(document: dict) -> None:
            item = document["response"]["sections"][0]["items"][0]
            item["supporting_quotes"][0]["exact_quote"] = "not the source quote"

        errors = self.errors_after("summary/summary-grounded-001.json", mutate)
        self.assert_rejected(errors, "must select a declared atomic quote")

    def test_grounded_summary_requires_item_citations(self) -> None:
        def mutate(document: dict) -> None:
            item = document["response"]["sections"][0]["items"][0]
            item.pop("source_anchor_ids")
            item.pop("supporting_quotes")

        errors = self.errors_after("summary/summary-grounded-001.json", mutate)
        self.assert_rejected(errors, "source_anchor_ids must be a non-empty list")
        self.assert_rejected(errors, "supporting_quotes must be a non-empty list")

    def test_summary_research_and_web_contamination_is_rejected(self) -> None:
        def mutate(document: dict) -> None:
            item = document["response"]["sections"][0]["items"][0]
            item["web_evidence_ids"] = ["web-evidence-001"]
            item["verdict"] = "supported"
            document["metadata"]["evidence_hash"] = "sha256:" + "0" * 64

        errors = self.errors_after("summary/summary-grounded-001.json", mutate)
        self.assert_rejected(errors, "research/web/verdict fields")
        self.assert_rejected(errors, "verdict language")
        self.assert_rejected(errors, "metadata must not contain evidence_hash")

    def test_accepted_summary_item_and_quote_fields_are_exact(self) -> None:
        def mutate(document: dict) -> None:
            item = document["response"]["sections"][0]["items"][0]
            item["raw_provider"] = "forbidden"
            item["supporting_quotes"][0]["url"] = "https://fixtures.invalid/"

        errors = self.errors_after("summary/summary-grounded-001.json", mutate)
        self.assert_rejected(errors, "exactly the accepted summary item fields")
        self.assert_rejected(
            errors, "must contain exactly source_anchor_id and exact_quote"
        )

    def test_summary_nested_request_response_and_section_fields_are_closed(
        self,
    ) -> None:
        def mutate_grounded(document: dict) -> None:
            document["response"]["raw_provider"] = "forbidden"
            document["response"]["sections"][0]["live_web"] = True

        grounded_errors = self.errors_after(
            "summary/summary-grounded-001.json", mutate_grounded
        )
        self.assert_rejected(
            grounded_errors,
            "grounded summary response has unexpected or missing fields",
        )
        self.assert_rejected(
            grounded_errors,
            "response.sections[0] has unexpected or missing fields",
        )

        def mutate_rejection(document: dict) -> None:
            document["request"]["url"] = "https://fixtures.invalid/forbidden"
            document["response"]["web_evidence_ids"] = ["web-evidence-001"]

        rejection_errors = self.errors_after(
            "summary/summary-ungrounded-assertion-rejection-001.json",
            mutate_rejection,
        )
        self.assert_rejected(
            rejection_errors,
            "unsupported assertion request has unexpected or missing fields",
        )
        self.assert_rejected(
            rejection_errors, "response has unexpected or missing fields"
        )

        for relative, message in (
            (
                "summary/summary-foreign-anchor-rejection-001.json",
                "foreign-anchor request has unexpected or missing fields",
            ),
            (
                "summary/summary-source-prompt-injection-rejection-001.json",
                "prompt-injection request has unexpected or missing fields",
            ),
        ):
            with self.subTest(relative=relative):
                errors = self.errors_after(
                    relative,
                    lambda document: document["request"].update(live_web=True),
                )
                self.assert_rejected(errors, message)

        timeout_errors = self.errors_after(
            "summary/summary-provider-timeout-001.json",
            lambda document: document["response"].update(live_web=True),
        )
        self.assert_rejected(
            timeout_errors, "response has unexpected or missing fields"
        )

        malformed_errors = self.errors_after(
            "summary/summary-malformed-schema-001.json",
            lambda document: document["response"].update(raw_provider="forbidden"),
        )
        self.assert_rejected(
            malformed_errors, "response has unexpected or missing fields"
        )

        def mutate_retry(document: dict) -> None:
            document["response"]["raw_provider"] = "forbidden"
            document["response"]["attempts"][0]["url"] = "forbidden"
            document["response"]["attempts"][1]["live_web"] = True

        retry_errors = self.errors_after(
            "summary/summary-deterministic-retry-001.json", mutate_retry
        )
        self.assert_rejected(
            retry_errors, "retry response has unexpected or missing fields"
        )
        self.assert_rejected(
            retry_errors, "retry attempt 1 has unexpected or missing fields"
        )
        self.assert_rejected(
            retry_errors, "must contain exactly the accepted summary item fields"
        )

    def test_accepted_summary_rejects_instruction_and_opinion_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            source = self.read_doc(root, "source/meeting-pack-001.json")
            by_type = {anchor["anchor_type"]: anchor for anchor in source["anchors"]}
            relative = "summary/summary-grounded-001.json"
            original = self.read_doc(root, relative)
            for anchor_type in ("instruction_like_content", "opinion"):
                with self.subTest(anchor_type=anchor_type):
                    document = copy.deepcopy(original)
                    anchor = by_type[anchor_type]
                    item = document["response"]["sections"][0]["items"][0]
                    item["source_anchor_ids"] = [anchor["anchor_id"]]
                    item["supporting_quotes"] = [
                        {
                            "source_anchor_id": anchor["anchor_id"],
                            "exact_quote": anchor["exact_quote"],
                        }
                    ]
                    self.write_doc(root, relative, document)
                    self.assert_rejected(
                        validator.validate(root),
                        "accepted summary anchor",
                    )

    def test_required_rejection_shapes_are_enforced(self) -> None:
        cases = (
            (
                "summary/summary-ungrounded-assertion-rejection-001.json",
                "assertion_not_grounded",
            ),
            ("summary/summary-foreign-anchor-rejection-001.json", "foreign_anchor"),
            (
                "summary/summary-source-prompt-injection-rejection-001.json",
                "source_prompt_injection",
            ),
            ("summary/summary-provider-timeout-001.json", "provider_timeout"),
            ("summary/summary-malformed-schema-001.json", "malformed_schema"),
        )
        for relative, expected_code in cases:
            with self.subTest(relative=relative):
                errors = self.errors_after(
                    relative,
                    lambda document: document["response"].update(
                        error_code="wrong_error"
                    ),
                )
                self.assert_rejected(
                    errors, f"response.error_code must be {expected_code}"
                )

    def test_retry_requires_timeout_then_grounded_success(self) -> None:
        def mutate(document: dict) -> None:
            document["response"]["attempts"][0]["error_code"] = "wrong"
            document["response"]["attempts"][1].pop("supporting_quotes")

        errors = self.errors_after("summary/summary-deterministic-retry-001.json", mutate)
        self.assert_rejected(errors, "attempt 1 must be failed provider_timeout")
        self.assert_rejected(errors, "supporting_quotes must be a non-empty list")

    def test_retry_key_is_fixed(self) -> None:
        errors = self.errors_after(
            "summary/summary-deterministic-retry-001.json",
            lambda document: document["response"].update(retry_key="arbitrary:key"),
        )
        self.assert_rejected(
            errors,
            "retry_key must equal meeting-pack-001:summary-grounded-001",
        )

    def test_required_schema_artifacts_cannot_be_deleted_or_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            (root / "schema/provider-fixture.v1.schema.json").unlink()
            self.assert_rejected(
                validator.validate(root), "required schema artifact is missing"
            )

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            path = root / "schema/source-pack.v1.schema.json"
            path.write_bytes(b'{"invalid":NaN}\\n')
            self.assert_rejected(validator.validate(root), "invalid schema JSON")

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            path = root / "schema/source-pack.v1.schema.json"
            path.write_bytes(b"\xff\xfe\x00")
            self.assert_rejected(validator.validate(root), "invalid schema JSON")

    def test_schema_artifacts_are_canonical_and_structurally_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            common_path = root / "schema/provider-fixture.v1.schema.json"
            common = json.loads(common_path.read_text(encoding="utf-8"))
            common["$id"] = "provider-fixture.v1"
            common["$defs"].pop("summaryItem")
            self.write_doc(
                root, "schema/provider-fixture.v1.schema.json", common
            )
            errors = validator.validate(root)
            self.assert_rejected(errors, "invalid absolute $id")
            self.assert_rejected(errors, "lacks required family $defs")

        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            source_path = root / "schema/source-pack.v1.schema.json"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["allOf"] = [{"$ref": "provider-fixture.v1"}]
            source_path.write_text(
                json.dumps(source, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            errors = validator.validate(root)
            self.assert_rejected(errors, "schema JSON is not canonical")
            self.assert_rejected(errors, "absolute common $id")

    def test_contract_critical_common_schema_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self.copy_corpus(Path(temp))
            relative = "schema/provider-fixture.v1.schema.json"
            common = self.read_doc(root, relative)
            common["allOf"][0]["then"] = {}
            common["$defs"]["opinionExclusion"]["required"].remove(
                "source_claim_quote"
            )
            common["$defs"]["webEvidence"]["required"].remove("title")
            common["$defs"]["webEvidence"]["properties"]["url"][
                "pattern"
            ] = "^https://.+"
            common["$defs"]["factcheckResult"]["properties"]["verdict"][
                "enum"
            ].append("probable")
            common["$defs"]["summaryItem"]["properties"]["text"]["type"] = "number"
            self.write_doc(root, relative, common)
            errors = validator.validate(root)
            self.assert_rejected(errors, "allOf/summary conditional contract")
            self.assert_rejected(errors, "opinion exclusion schema contract")
            self.assert_rejected(errors, "web evidence schema contract")
            self.assert_rejected(errors, "fact-check verdict schema contract")
            self.assert_rejected(errors, "summary item text schema contract")


if __name__ == "__main__":
    unittest.main()

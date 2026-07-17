from __future__ import annotations
import copy, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fixture_validator", ROOT / "tools" / "validate_provider_fixtures.py")
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(validator)

class ProviderFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_path = ROOT / "provider_fixtures/source/meeting-pack-001.json"
        self.source = json.loads(self.source_path.read_text(encoding="utf-8"))

    def write_doc(self, root: Path, name: str, doc: dict) -> None:
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(validator.canonical_bytes(doc))

    def test_source_pack_is_valid_and_canonical(self) -> None:
        self.assertEqual([], validator.validate(ROOT / "provider_fixtures"))
        self.assertEqual(self.source_path.read_bytes(), validator.canonical_bytes(self.source))

    def test_fixed_ids_and_exact_supporting_spans_resolve(self) -> None:
        self.assertEqual(validator.REVISION_IDS, {item["revision_id"] for item in self.source["revisions"]})
        self.assertEqual(validator.ANCHOR_IDS, {item["anchor_id"] for item in self.source["anchors"]})
        revisions = {item["revision_id"]: item["text"] for item in self.source["revisions"]}
        for anchor in self.source["anchors"]:
            self.assertIn(anchor["exact_quote"], revisions[anchor["revision_id"]])

    def test_noncanonical_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / "source/meeting-pack-001.json"; path.parent.mkdir()
            path.write_text(json.dumps(self.source, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertTrue(any("canonical" in error or "newline" in error for error in validator.validate(root)))

    def test_unknown_anchor_is_only_allowed_in_expected_rejection(self) -> None:
        bad = copy.deepcopy(self.source); bad["anchors"][0]["anchor_id"] = "foreign-anchor-999"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.write_doc(root, "source/meeting-pack-001.json", bad)
            self.assertTrue(any("fixed anchor" in error or "unknown anchor" in error for error in validator.validate(root)))

    def test_summary_url_and_verdict_contamination_are_rejected(self) -> None:
        summary = {"fixture_id":"summary-contaminated-001","metadata":{"author_role":"coding-agent","created_at":"2026-07-17T12:43:34Z","prompt_version":"mock-provider.prompt.v1","reviewer_role":"reviewer","source_hash":"sha256:" + "0" * 64},"schema_version":"provider-fixture.v1","items":[{"text":"https://example.test is supported","source_anchor_ids":["anchor-alice-001"]}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.write_doc(root, "summary/summary-contaminated-001.json", summary)
            self.assertTrue(any("summary must not" in error for error in validator.validate(root)))

if __name__ == "__main__": unittest.main()

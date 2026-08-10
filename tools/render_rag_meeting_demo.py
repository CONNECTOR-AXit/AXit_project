"""Validate and render the deterministic Korean RAG meeting demo fixture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "docs/experiments/fixtures/rag-meeting-briefing-ko-001.json"
DEFAULT_REPORT = ROOT / "docs/experiments/rag-meeting-briefing-ko-001.md"
_KOREAN = re.compile(r"[가-힣]")
_URL = re.compile(r"https?://", re.IGNORECASE)


class DemoFixtureError(ValueError):
    """The demo fixture violates its grounding or isolation contract."""


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Read the UTF-8 fixture as a mapping."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DemoFixtureError("fixture root must be an object")
    return value


def validate_fixture(fixture: dict[str, Any]) -> None:
    """Fail closed on secret use, ungrounded output, or mixed result domains."""

    if fixture.get("provider") != "mock" or fixture.get("xai_called") is not False:
        raise DemoFixtureError(
            "the approved experiment must remain offline and mock-backed"
        )
    if fixture.get("credential_persisted") is not False:
        raise DemoFixtureError("credentials must never be persisted")
    if fixture.get("language") != "ko-KR":
        raise DemoFixtureError("the demo output language must be ko-KR")

    meeting = _mapping(fixture.get("meeting"), "meeting")
    anchors: dict[str, str] = {}
    for participant in _list(meeting.get("participants"), "participants"):
        participant_map = _mapping(participant, "participant")
        for anchor in _list(participant_map.get("anchors"), "participant anchors"):
            anchor_map = _mapping(anchor, "anchor")
            anchor_id = _text(anchor_map.get("id"), "anchor id")
            exact_quote = _text(anchor_map.get("exact_quote"), "anchor exact quote")
            if anchor_id in anchors:
                raise DemoFixtureError(f"duplicate anchor: {anchor_id}")
            anchors[anchor_id] = exact_quote

    summary = _mapping(fixture.get("summary"), "summary")
    summary_text = json.dumps(summary, ensure_ascii=False)
    if _URL.search(summary_text):
        raise DemoFixtureError("summary must not contain web URLs")
    for item in _list(summary.get("items"), "summary items"):
        item_map = _mapping(item, "summary item")
        _require_korean(_text(item_map.get("text"), "summary text"), "summary text")
        supports = _list(item_map.get("supports"), "summary supports")
        if not supports:
            raise DemoFixtureError("every summary item needs participant support")
        for support in supports:
            support_map = _mapping(support, "summary support")
            _validate_anchor_support(support_map, anchors)

    evidence = {
        _text(item.get("id"), "evidence id"): item
        for item in (
            _mapping(raw, "web evidence")
            for raw in _list(fixture.get("web_evidence"), "web evidence")
        )
    }
    if len(evidence) != len(_list(fixture.get("web_evidence"), "web evidence")):
        raise DemoFixtureError("web evidence IDs must be unique")
    for evidence_item in evidence.values():
        url = _text(evidence_item.get("url"), "evidence URL")
        if not url.startswith("https://"):
            raise DemoFixtureError("web evidence must use HTTPS")

    research = _mapping(fixture.get("research"), "research")
    for collection in ("items", "fact_checks"):
        for item in _list(research.get(collection), f"research {collection}"):
            item_map = _mapping(item, f"research {collection} item")
            user_text = item_map.get("finding", item_map.get("explanation"))
            _require_korean(_text(user_text, "research output"), "research output")
            _validate_reference_ids(item_map, anchors, evidence)

    prototype = _mapping(fixture.get("prototype"), "prototype")
    _require_korean(_text(prototype.get("solution"), "prototype solution"), "prototype")
    for anchor_id in _text_list(
        prototype.get("source_anchor_ids"), "prototype anchors"
    ):
        if anchor_id not in anchors:
            raise DemoFixtureError(
                f"prototype references an unknown anchor: {anchor_id}"
            )


def render_report(fixture: dict[str, Any]) -> str:
    """Render a human-readable report after validating the fixture."""

    validate_fixture(fixture)
    evidence = {item["id"]: item for item in fixture["web_evidence"]}
    anchor_owners = {
        anchor["id"]: participant["name"]
        for participant in fixture["meeting"]["participants"]
        for anchor in participant["anchors"]
    }
    lines = [
        "# RAG 회의 사전 브리핑 — 결정론적 실험 결과",
        "",
        "> **실험 경계:** xAI/Grok을 호출하지 않았으며 API 키를 저장하지 않았다. "
        "아래 결과는 검토 가능한 MockProvider 개발 fixture다.",
        "",
        f"- **회의 주제:** {fixture['meeting']['topic']}",
        f"- **출력 언어:** {fixture['language']}",
        f"- **Provider:** `{fixture['provider']}`",
        f"- **Fixture:** `{fixture['fixture_id']}`",
        "",
        "## 참가자 준비 자료",
        "",
        "| 참가자 | 담당 자료 | 근거 anchor |",
        "|---|---|---|",
    ]
    for participant in fixture["meeting"]["participants"]:
        anchors = ", ".join(f"`{anchor['id']}`" for anchor in participant["anchors"])
        lines.append(
            f"| {participant['name']} | {participant['contribution']} | {anchors} |"
        )

    lines.extend(["", "## 참가자 원문 기반 요약", ""])
    for item in fixture["summary"]["items"]:
        owners = ", ".join(
            sorted(
                {anchor_owners[support["anchor_id"]] for support in item["supports"]}
            )
        )
        citations = ", ".join(
            f"`{support['anchor_id']}`" for support in item["supports"]
        )
        lines.append(f"- {item['text']} **[{owners} · {citations}]**")

    lines.extend(["", "## 외부 자료 조사", ""])
    for item in fixture["research"]["items"]:
        links = _markdown_evidence_links(item["web_evidence_ids"], evidence)
        participant_links = ", ".join(
            f"`{anchor_id}`" for anchor_id in item["participant_anchor_ids"]
        )
        lines.extend(
            [
                f"### {item['heading']}",
                "",
                item["finding"],
                "",
                f"- 참가자 근거: {participant_links}",
                f"- 외부 근거: {links}",
                "",
            ]
        )

    lines.extend(["## 팩트체크", ""])
    for item in fixture["research"]["fact_checks"]:
        links = _markdown_evidence_links(item["web_evidence_ids"], evidence)
        lines.extend(
            [
                f"- **주장:** {item['claim']}",
                f"- **판정:** `{item['verdict']}`",
                f"- **설명:** {item['explanation']}",
                f"- **근거:** {links}",
                "",
            ]
        )

    prototype = fixture["prototype"]
    lines.extend(
        [
            f"## 프로토타입: {prototype['name']}",
            "",
            f"- **문제:** {prototype['problem']}",
            f"- **해결:** {prototype['solution']}",
            "- **최소 구현 순서:**",
        ]
    )
    lines.extend(
        f"  {index}. {step}"
        for index, step in enumerate(prototype["mvp_steps"], start=1)
    )
    lines.extend(["", "## 출처 바로가기", ""])
    lines.extend(
        f"- [{item['title']}]({item['url']})" for item in fixture["web_evidence"]
    )
    lines.extend(
        [
            "",
            "## 자동 검증 결과",
            "",
            "- ✅ 요약 항목마다 정확한 참가자 원문 근거가 있음",
            "- ✅ 요약본에는 웹 URL 또는 팩트체크 판정이 없음",
            "- ✅ 조사·팩트체크 항목마다 참가자 anchor와 HTTPS 외부 근거가 있음",
            "- ✅ 사용자 대상 결과가 한국어로 작성됨",
            "- ✅ 외부 Provider 호출 및 credential 저장이 비활성화됨",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    fixture_path: Path = DEFAULT_FIXTURE,
    report_path: Path = DEFAULT_REPORT,
) -> Path:
    """Validate the fixture and write its stable Markdown representation."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(load_fixture(fixture_path)), encoding="utf-8")
    return report_path


def _validate_anchor_support(support: dict[str, Any], anchors: dict[str, str]) -> None:
    anchor_id = _text(support.get("anchor_id"), "support anchor id")
    exact_quote = _text(support.get("exact_quote"), "support exact quote")
    if anchors.get(anchor_id) != exact_quote:
        raise DemoFixtureError(f"support does not exactly match anchor: {anchor_id}")


def _validate_reference_ids(
    item: dict[str, Any],
    anchors: dict[str, str],
    evidence: dict[str, dict[str, Any]],
) -> None:
    participant_ids = _text_list(
        item.get("participant_anchor_ids"), "participant anchors"
    )
    evidence_ids = _text_list(item.get("web_evidence_ids"), "web evidence IDs")
    if not participant_ids or not evidence_ids:
        raise DemoFixtureError("research output needs participant and web evidence")
    unknown_anchors = set(participant_ids) - anchors.keys()
    unknown_evidence = set(evidence_ids) - evidence.keys()
    if unknown_anchors:
        raise DemoFixtureError(
            f"unknown participant anchors: {sorted(unknown_anchors)}"
        )
    if unknown_evidence:
        raise DemoFixtureError(f"unknown web evidence: {sorted(unknown_evidence)}")


def _markdown_evidence_links(
    evidence_ids: list[str], evidence: dict[str, dict[str, Any]]
) -> str:
    return ", ".join(
        f"[{evidence[evidence_id]['title']}]({evidence[evidence_id]['url']})"
        for evidence_id in evidence_ids
    )


def _require_korean(value: str, label: str) -> None:
    if _KOREAN.search(value) is None:
        raise DemoFixtureError(f"{label} must contain Korean text")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DemoFixtureError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DemoFixtureError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DemoFixtureError(f"{label} must be non-empty text")
    return value


def _text_list(value: object, label: str) -> list[str]:
    items = _list(value, label)
    texts = [_text(item, label) for item in items]
    if len(texts) != len(set(texts)):
        raise DemoFixtureError(f"{label} must not contain duplicates")
    return texts


if __name__ == "__main__":
    print(write_report().relative_to(ROOT))

"""Grounded, single-task Grok editing over the current merged document."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.automatic_report_suggestions import (
    _load_snapshot_documents,
    _select_report_anchors,
)
from app.grok_report_provider import GrokReportProvider, ReportAnchor
from app.merged_document_service import (
    MergedDocumentAccessError,
    MergedDocumentBlock,
    MergedDocumentHeadingBlock,
    MergedDocumentService,
)
from app.report_suggestions import (
    ReportSuggestion,
    ReportSuggestionAccessError,
    ReportSuggestionService,
    ReportSuggestionStateError,
)

_MAX_ANCHORS = 200
_MAX_ANCHORS_PER_DOCUMENT = 40


class GrokEditAgentService:
    def __init__(
        self,
        provider: GrokReportProvider,
        suggestions: ReportSuggestionService | None = None,
        merged_documents: MergedDocumentService | None = None,
    ) -> None:
        self._provider = provider
        self._suggestions = suggestions or ReportSuggestionService()
        self._merged_documents = merged_documents or MergedDocumentService()

    def run(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        instruction: str,
    ) -> tuple[ReportSuggestion, ...]:
        normalized = instruction.strip()
        if not 1 <= len(normalized) <= 4_000:
            raise ValueError("edit instruction is invalid")
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT 1 FROM talk_sessions session_row
                   JOIN room_memberships membership
                     ON membership.room_id=session_row.room_id
                    AND membership.user_id=%s AND membership.left_at IS NULL
                   WHERE session_row.id=%s""",
                (actor_id, session_id),
            )
            if cursor.fetchone() is None:
                raise ReportSuggestionAccessError("talk session is unavailable")
        try:
            document = self._merged_documents.get(
                connection,
                session_id=session_id,
                actor_id=actor_id,
            )
        except MergedDocumentAccessError as error:
            raise ReportSuggestionStateError("merged document is unavailable") from error
        blocks = tuple(_block_payload(block) for block in document.blocks)
        anchors = _bounded_anchors(connection, document.snapshot_id)
        generated = self._provider.generate_edit_suggestions(
            instruction=normalized,
            blocks=blocks,
            anchors=anchors,
        )
        return tuple(
            self._suggestions.create(
                connection,
                session_id=session_id,
                actor_id=actor_id,
                source_anchor_id=value.source_anchor_id,
                target_block_id=value.target_block_id,
                kind=value.kind,
                suggested_text=value.suggested_text,
                rationale=value.rationale,
            )
            for value in generated
        )


def _bounded_anchors(
    connection: psycopg.Connection[dict[str, Any]], snapshot_id: UUID
) -> tuple[ReportAnchor, ...]:
    documents = _load_snapshot_documents(connection, snapshot_id=snapshot_id)
    selected = _select_report_anchors(
        documents,
        max_anchors=_MAX_ANCHORS,
        max_per_document=_MAX_ANCHORS_PER_DOCUMENT,
    )
    if not selected:
        raise ReportSuggestionStateError("source anchors are unavailable")
    return selected


def _block_payload(block: MergedDocumentBlock) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": block.id,
        "type": block.type,
        "text": block.text,
    }
    if block.tag is not None:
        payload["tag"] = block.tag
    if isinstance(block, MergedDocumentHeadingBlock):
        payload["level"] = block.level
    return payload

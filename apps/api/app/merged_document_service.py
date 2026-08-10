"""Snapshot-scoped merged-document editing state.

The merged document a member sees in the editor starts as a read-only
derivation of the immutable generated summary. The first time anyone saves an
edit, that becomes the persisted, optimistically-concurrent state for that
(session, snapshot) pair — mirroring comments' expected_version pattern so
two collaborators editing at once get a clear conflict instead of a silent
overwrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.generation_repository import GenerationRepository
from app.integrated_report import load_report_identity


class MergedDocumentAccessError(PermissionError):
    pass


class MergedDocumentStaleVersionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MergedDocumentHeadingBlock:
    id: str
    level: Literal[1, 2, 3]
    text: str
    tag: str | None = None
    type: Literal["heading"] = "heading"


@dataclass(frozen=True, slots=True)
class MergedDocumentParagraphBlock:
    id: str
    text: str
    tag: str | None = None
    type: Literal["paragraph"] = "paragraph"


MergedDocumentBlock = MergedDocumentHeadingBlock | MergedDocumentParagraphBlock


@dataclass(frozen=True, slots=True)
class MergedDocumentState:
    session_id: UUID
    snapshot_id: UUID
    version: int
    blocks: tuple[MergedDocumentBlock, ...]
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class MergedDocumentVersionSnapshot:
    """An immutable, named copy of the document at one point in time.

    Unlike ``merged_document_states`` (the single live row autosave keeps
    overwriting), these rows are never updated — each one is a permanent
    entry in the "변경 내역" (version history) timeline, created only when a
    member explicitly asks to keep the current document as a version.
    """

    id: UUID
    session_id: UUID
    snapshot_id: UUID
    label: str
    blocks: tuple[MergedDocumentBlock, ...]
    document_version: int
    created_by: UUID
    created_at: datetime


class MergedDocumentService:
    def __init__(
        self,
        generation_repository: GenerationRepository | None = None,
        activity_service: ActivityService | None = None,
    ) -> None:
        self._generation_repository = generation_repository or GenerationRepository()
        self._activities = activity_service or ActivityService()

    def get(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> MergedDocumentState:
        with connection.cursor(row_factory=dict_row) as cursor:
            self._require_member(cursor, session_id, actor_id)
            identity = load_report_identity(connection, session_id=session_id)
            if identity is None:
                raise MergedDocumentAccessError("integrated report is unavailable")
            cursor.execute(
                """SELECT version, blocks_json, updated_at FROM merged_document_states
                   WHERE session_id=%s AND snapshot_id=%s""",
                (session_id, identity.snapshot_id),
            )
            row = cursor.fetchone()
        if row is not None:
            blocks = _blocks_from_json(row["blocks_json"])
            if (
                any(block.id.startswith("ai-") for block in blocks)
                and not any(block.id == "source-coverage-heading" for block in blocks)
            ):
                # Existing Grok documents predate exhaustive source coverage.
                # Add it at read time without overwriting collaborative edits;
                # the next normal autosave persists the augmented document.
                from app.automatic_report_suggestions import (
                    _build_source_coverage_blocks,
                    _load_snapshot_documents,
                )

                documents = _load_snapshot_documents(
                    connection,
                    snapshot_id=identity.snapshot_id,
                )
                coverage = _blocks_from_json(
                    list(_build_source_coverage_blocks(documents))
                )
                if len(blocks) + len(coverage) > 500:
                    raise ValueError("complete merged document exceeds editor block limit")
                blocks += coverage
            return MergedDocumentState(
                session_id=session_id,
                snapshot_id=identity.snapshot_id,
                version=cast(int, row["version"]),
                blocks=blocks,
                updated_at=cast(datetime, row["updated_at"]),
            )
        summary = self._generation_repository.get_summary_for_member(
            connection, session_id=session_id, actor_id=actor_id
        )
        anchor_titles = _resolve_anchor_titles(connection, _anchor_ids_in(summary))
        return MergedDocumentState(
            session_id=session_id,
            snapshot_id=identity.snapshot_id,
            version=0,
            blocks=_baseline_blocks(summary, anchor_titles),
            updated_at=None,
        )

    def save(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        expected_version: int,
        blocks: tuple[MergedDocumentBlock, ...],
    ) -> MergedDocumentState:
        if not blocks:
            raise ValueError("merged document requires at least one block")
        if expected_version < 0:
            raise ValueError("expected_version must not be negative")
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            room_id = self._require_member(cursor, session_id, actor_id)
            identity = load_report_identity(connection, session_id=session_id)
            if identity is None:
                raise MergedDocumentAccessError("integrated report is unavailable")
            cursor.execute(
                """SELECT version FROM merged_document_states
                   WHERE session_id=%s AND snapshot_id=%s FOR UPDATE""",
                (session_id, identity.snapshot_id),
            )
            current = cursor.fetchone()
            payload = Jsonb(_blocks_to_json(blocks))
            if current is None:
                if expected_version != 0:
                    raise MergedDocumentStaleVersionError("stale merged document version")
                cursor.execute(
                    """INSERT INTO merged_document_states
                       (id, session_id, snapshot_id, version, blocks_json, updated_by)
                       VALUES (%s,%s,%s,1,%s,%s)
                       RETURNING version, updated_at""",
                    (uuid4(), session_id, identity.snapshot_id, payload, actor_id),
                )
            else:
                if cast(int, current["version"]) != expected_version:
                    raise MergedDocumentStaleVersionError("stale merged document version")
                cursor.execute(
                    """UPDATE merged_document_states
                       SET version=version+1, blocks_json=%s, updated_by=%s,
                           updated_at=clock_timestamp()
                       WHERE session_id=%s AND snapshot_id=%s
                       RETURNING version, updated_at""",
                    (payload, actor_id, session_id, identity.snapshot_id),
                )
            updated = cursor.fetchone()
            assert updated is not None
            new_version = cast(int, updated["version"])
            self._activities.record(
                cursor,
                event_key=build_event_key(
                    "merged_document.saved",
                    session_id=session_id,
                    snapshot_id=identity.snapshot_id,
                    version=new_version,
                ),
                event_type="merged_document.saved",
                actor_id=actor_id,
                scope_type="session",
                room_id=room_id,
                session_id=session_id,
                entity_type="merged_document",
                entity_id=identity.snapshot_id,
                metadata={"version": new_version},
            )
        return MergedDocumentState(
            session_id=session_id,
            snapshot_id=identity.snapshot_id,
            version=new_version,
            blocks=blocks,
            updated_at=cast(datetime, updated["updated_at"]),
        )

    def create_version(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        label: str,
    ) -> MergedDocumentVersionSnapshot:
        """Snapshot whatever the member currently sees as a permanent, named version.

        Reuses ``get()`` for "what is the current document" so this always
        matches exactly what the editor renders — the live saved state, or
        the generated baseline if nothing has been saved yet.
        """

        normalized_label = label.strip()
        if not 1 <= len(normalized_label) <= 200:
            raise ValueError("version label is invalid")
        current = self.get(connection, session_id=session_id, actor_id=actor_id)
        version_id = uuid4()
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            room_id = self._require_member(cursor, session_id, actor_id)
            cursor.execute(
                """INSERT INTO merged_document_version_snapshots
                   (id, session_id, snapshot_id, label, blocks_json, document_version, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   RETURNING created_at""",
                (
                    version_id,
                    session_id,
                    current.snapshot_id,
                    normalized_label,
                    Jsonb(_blocks_to_json(current.blocks)),
                    current.version,
                    actor_id,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            self._activities.record(
                cursor,
                event_key=build_event_key(
                    "merged_document.version_created", version_id=version_id
                ),
                event_type="merged_document.version_created",
                actor_id=actor_id,
                scope_type="session",
                room_id=room_id,
                session_id=session_id,
                entity_type="merged_document_version",
                entity_id=version_id,
                metadata={"document_version": current.version},
            )
        return MergedDocumentVersionSnapshot(
            id=version_id,
            session_id=session_id,
            snapshot_id=current.snapshot_id,
            label=normalized_label,
            blocks=current.blocks,
            document_version=current.version,
            created_by=actor_id,
            created_at=cast(datetime, row["created_at"]),
        )

    def list_versions(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> tuple[MergedDocumentVersionSnapshot, ...]:
        with connection.cursor(row_factory=dict_row) as cursor:
            self._require_member(cursor, session_id, actor_id)
            identity = load_report_identity(connection, session_id=session_id)
            if identity is None:
                return ()
            cursor.execute(
                """SELECT id, label, blocks_json, document_version, created_by, created_at
                   FROM merged_document_version_snapshots
                   WHERE session_id=%s AND snapshot_id=%s
                   ORDER BY created_at DESC""",
                (session_id, identity.snapshot_id),
            )
            rows = cursor.fetchall()
        return tuple(
            MergedDocumentVersionSnapshot(
                id=cast(UUID, row["id"]),
                session_id=session_id,
                snapshot_id=identity.snapshot_id,
                label=str(row["label"]),
                blocks=_blocks_from_json(row["blocks_json"]),
                document_version=cast(int, row["document_version"]),
                created_by=cast(UUID, row["created_by"]),
                created_at=cast(datetime, row["created_at"]),
            )
            for row in rows
        )

    def get_version(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        version_id: UUID,
    ) -> MergedDocumentVersionSnapshot:
        """Fetch one past version's full content, e.g. to preview it read-only."""

        with connection.cursor(row_factory=dict_row) as cursor:
            self._require_member(cursor, session_id, actor_id)
            identity = load_report_identity(connection, session_id=session_id)
            if identity is None:
                raise MergedDocumentAccessError("integrated report is unavailable")
            cursor.execute(
                """SELECT id, label, blocks_json, document_version, created_by, created_at
                   FROM merged_document_version_snapshots
                   WHERE id=%s AND session_id=%s AND snapshot_id=%s""",
                (version_id, session_id, identity.snapshot_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise MergedDocumentAccessError("merged document version is unavailable")
        return MergedDocumentVersionSnapshot(
            id=cast(UUID, row["id"]),
            session_id=session_id,
            snapshot_id=identity.snapshot_id,
            label=str(row["label"]),
            blocks=_blocks_from_json(row["blocks_json"]),
            document_version=cast(int, row["document_version"]),
            created_by=cast(UUID, row["created_by"]),
            created_at=cast(datetime, row["created_at"]),
        )

    @staticmethod
    def _require_member(cursor: Any, session_id: UUID, actor_id: UUID) -> UUID:
        cursor.execute(
            """SELECT s.room_id FROM talk_sessions s JOIN room_memberships m
               ON m.room_id=s.room_id AND m.user_id=%s AND m.left_at IS NULL
               WHERE s.id=%s""",
            (actor_id, session_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise MergedDocumentAccessError("talk session is unavailable")
        return cast(UUID, row["room_id"])


def _anchor_ids_in(summary: dict[str, object]) -> set[str]:
    sections = cast(list[dict[str, Any]], summary.get("sections") or [])
    return {
        anchor_id
        for section in sections
        for item in cast(list[dict[str, Any]], section.get("items") or [])
        for anchor_id in cast(list[str], item.get("source_anchor_ids") or [])
    }


def _resolve_anchor_titles(
    connection: psycopg.Connection[dict[str, Any]], anchor_ids: set[str]
) -> dict[str, str]:
    """Map each source anchor to the title of the document a member uploaded it in.

    This is what makes a merged-document block's tag a real RAG citation
    (which uploaded document backs this paragraph) instead of a constant,
    meaningless "공통"/"통합" label.
    """

    valid_ids: list[UUID] = []
    for raw in anchor_ids:
        try:
            valid_ids.append(UUID(raw))
        except ValueError:
            continue
    if not valid_ids:
        return {}
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT sa.id AS anchor_id, sub.title AS document_title
               FROM source_anchors sa
               JOIN source_revisions sr ON sr.id = sa.source_revision_id
               JOIN submissions sub ON sub.id = sr.submission_id
               WHERE sa.id = ANY(%s)""",
            (valid_ids,),
        )
        rows = cursor.fetchall()
    return {str(row["anchor_id"]): str(row["document_title"]) for row in rows}


def _baseline_blocks(
    summary: dict[str, object], anchor_titles: dict[str, str]
) -> tuple[MergedDocumentBlock, ...]:
    """The same "AI 통합 문서" shape the editor showed before persistence existed,
    now tagged with the real source document each paragraph was drawn from."""

    blocks: list[MergedDocumentBlock] = []
    sections = cast(list[dict[str, Any]], summary.get("sections") or [])
    for section_index, section in enumerate(sections):
        heading = str(section.get("heading") or "").strip()
        if heading:
            blocks.append(MergedDocumentHeadingBlock(id=f"b-h-{section_index}", level=1, text=heading))
        items = cast(list[dict[str, Any]], section.get("items") or [])
        for item_index, item in enumerate(items):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            anchor_ids = cast(list[str], item.get("source_anchor_ids") or [])
            titles = sorted({anchor_titles[a] for a in anchor_ids if a in anchor_titles})
            blocks.append(
                MergedDocumentParagraphBlock(
                    id=f"b-p-{section_index}-{item_index}",
                    text=text,
                    tag=", ".join(titles) if titles else None,
                )
            )
    if not blocks:
        raise ValueError("summary has no content to seed a merged document")
    return tuple(blocks)


def _blocks_to_json(blocks: tuple[MergedDocumentBlock, ...]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for block in blocks:
        entry: dict[str, object] = {"id": block.id, "type": block.type, "text": block.text}
        if block.tag is not None:
            entry["tag"] = block.tag
        if isinstance(block, MergedDocumentHeadingBlock):
            entry["level"] = block.level
        result.append(entry)
    return result


def _blocks_from_json(value: object) -> tuple[MergedDocumentBlock, ...]:
    if not isinstance(value, list):
        raise ValueError("persisted merged document blocks must be an array")
    blocks: list[MergedDocumentBlock] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("persisted merged document block must be an object")
        block_id = str(raw.get("id") or "")
        text = str(raw.get("text") or "")
        tag = raw.get("tag")
        tag_value = str(tag) if isinstance(tag, str) else None
        if raw.get("type") == "heading":
            level = raw.get("level")
            if level not in (1, 2, 3):
                raise ValueError("persisted heading block has an invalid level")
            blocks.append(
                MergedDocumentHeadingBlock(
                    id=block_id, level=cast(Literal[1, 2, 3], level), text=text, tag=tag_value
                )
            )
        elif raw.get("type") == "paragraph":
            blocks.append(MergedDocumentParagraphBlock(id=block_id, text=text, tag=tag_value))
        else:
            raise ValueError("persisted merged document block has an unknown type")
    return tuple(blocks)

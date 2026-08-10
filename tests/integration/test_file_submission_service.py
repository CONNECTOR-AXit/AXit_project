"""Real-PostgreSQL contracts for atomic file submission and original access."""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.auth_service import AuthService
from app.collaboration_service import CollaborationService
from app.db import open_connection
from app.migrations import upgrade_database
from app.sandbox_ipc import (
    SandboxExecution,
    SandboxFailure,
    SandboxFailureCode,
    SandboxRequest,
    canonical_sha256,
)


pytestmark = pytest.mark.integration


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for file submission integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_file_submission_" + uuid4().hex
    maintenance_info = dict(connection_info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(connection_info)
    target_info["dbname"] = database_name
    target_url = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            yield target_url
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


@pytest.fixture
def file_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


@pytest.fixture
def seeded_open_session(file_database_url: str) -> tuple[UUID, UUID, UUID]:
    auth = AuthService()
    collaboration = CollaborationService()
    with open_connection(file_database_url) as connection:
        member = auth.register(
            connection,
            email="member-file@example.test",
            password="member-file-password",
            display_name="Member",
        )
        outsider = auth.register(
            connection,
            email="outsider-file@example.test",
            password="outsider-file-password",
            display_name="Outsider",
        )
        room = collaboration.create_room(connection, actor_id=member.id, name="File room")
        session = collaboration.create_talk_session(
            connection,
            actor_id=member.id,
            room_id=room.id,
            topic="Upload evidence",
        )
    return member.id, outsider.id, session.id


def _service(blob_root: Path) -> object:
    from app.file_submission_service import FileSubmissionService, LocalBlobStore

    return FileSubmissionService(blob_store=LocalBlobStore(blob_root))


def _submit_pdf(
    service: object,
    connection: psycopg.Connection[dict[str, object]],
    *,
    session_id: UUID,
    actor_id: UUID,
    content: bytes,
) -> object:
    return service.submit(  # type: ignore[attr-defined, no-any-return]
        connection,
        session_id=session_id,
        actor_id=actor_id,
        filename="agenda.pdf",
        declared_mime_type="application/pdf",
        stream=io.BytesIO(content),
        content_length=len(content),
    )


def test_submit_atomically_persists_blob_revision_and_extraction_job(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    member_id, _, session_id = seeded_open_session
    content = b"%PDF-1.7\natomic fixture"
    service = _service(tmp_path)

    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            service,
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=content,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.kind, r.id, r.filename, r.mime_type, r.byte_size, r.sha256,
                       r.storage_key, r.processing_state, j.kind AS job_kind,
                       j.state AS job_state, j.payload_json
                FROM submissions s
                JOIN source_revisions r ON r.submission_id = s.id AND r.is_current
                JOIN jobs j ON j.kind = 'extraction'
                           AND j.payload_json->>'revision_id' = r.id::text
                WHERE s.id = %s
                """,
                (submission.id,),  # type: ignore[attr-defined]
            )
            persisted = cursor.fetchone()

    assert persisted is not None
    assert persisted["kind"] == "file"
    assert persisted["filename"] == "agenda.pdf"
    assert persisted["mime_type"] == "application/pdf"
    assert persisted["byte_size"] == len(content)
    assert persisted["sha256"] == hashlib.sha256(content).hexdigest()
    assert persisted["storage_key"]
    assert persisted["processing_state"] == "queued"
    assert persisted["job_kind"] == "extraction"
    assert persisted["job_state"] == "pending"
    # Queue payloads address immutable revisions, never filesystem paths or bytes.
    assert set(persisted["payload_json"]) >= {"revision_id", "media_type"}
    assert "storage_key" not in persisted["payload_json"]
    assert [path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()] == [content]


@pytest.mark.parametrize(
    "declared_mime_type",
    (
        "application/haansofthwp",
        "application/vnd.hancom.hwp",
        "application/octet-stream",
    ),
)
def test_hwp_browser_mime_alias_is_stored_as_the_canonical_type(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
    declared_mime_type: str,
) -> None:
    member_id, _, session_id = seeded_open_session
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1browser HWP"
    service = _service(tmp_path)

    with open_connection(file_database_url) as connection:
        submission = service.submit(  # type: ignore[attr-defined]
            connection,
            session_id=session_id,
            actor_id=member_id,
            filename="minutes.hwp",
            declared_mime_type=declared_mime_type,
            stream=io.BytesIO(content),
            content_length=len(content),
        )
        persisted = connection.execute(
            "SELECT mime_type FROM source_revisions WHERE id = %s",
            (submission.current_revision_id,),  # type: ignore[attr-defined]
        ).fetchone()

    assert persisted is not None
    assert persisted["mime_type"] == "application/x-hwp"


def test_jpeg_labelled_png_upload_is_queued_as_png(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    member_id, _, session_id = seeded_open_session
    content = b"\x89PNG\r\n\x1a\nfixture\x00\x00\x00\x00IEND\xaeB`\x82"
    service = _service(tmp_path)

    with open_connection(file_database_url) as connection:
        submission = service.submit(  # type: ignore[attr-defined]
            connection,
            session_id=session_id,
            actor_id=member_id,
            filename="사람1_RAG_img.jpeg",
            declared_mime_type="image/jpeg",
            stream=io.BytesIO(content),
            content_length=len(content),
        )
        persisted = connection.execute(
            "SELECT filename, mime_type FROM source_revisions WHERE id = %s",
            (submission.current_revision_id,),  # type: ignore[attr-defined]
        ).fetchone()
        queued = connection.execute(
            "SELECT payload_json FROM jobs WHERE payload_json->>'revision_id' = %s",
            (str(submission.current_revision_id),),  # type: ignore[attr-defined]
        ).fetchone()

    assert persisted == {"filename": "사람1_RAG_img.jpeg", "mime_type": "image/png"}
    assert queued is not None
    assert queued["payload_json"]["media_type"] == "image/png"
    assert queued["payload_json"]["parser"] == {
        "name": "pillow+tesseract-cli",
        "version": "12.3.0+5.3.0",
    }


def test_utf8_txt_upload_is_extracted_into_stable_line_anchors(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import FileSubmissionService, LocalBlobStore

    member_id, _, session_id = seeded_open_session
    source = "첫 번째 안건\r\n\r\n두 번째 결정".encode("utf-8")
    store = LocalBlobStore(tmp_path)
    with open_connection(file_database_url) as connection:
        submission = FileSubmissionService(blob_store=store).submit(
            connection,
            session_id=session_id,
            actor_id=member_id,
            filename="회의록.txt",
            declared_mime_type="text/plain",
            stream=io.BytesIO(source),
            content_length=len(source),
        )

    adapter = _FakeSandboxAdapter(
        SandboxExecution(False, None, SandboxFailure(SandboxFailureCode.PARSER_CRASH), "0" * 64, 1, 0, 0, 0, False)
    )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=store,
        sandbox_adapter=adapter,
    )

    outcome = worker.run_once(owner="txt-worker")

    assert outcome["block_count"] == 2
    assert adapter.requests == []
    with open_connection(file_database_url) as connection:
        rows = connection.execute(
            "SELECT ordinal, block_type, text, anchor_json FROM source_anchors "
            "WHERE source_revision_id = %s ORDER BY ordinal",
            (submission.current_revision_id,),
        ).fetchall()
    assert [(row["ordinal"], row["block_type"], row["text"]) for row in rows] == [
        (0, "text_line", "첫 번째 안건"),
        (1, "text_line", "두 번째 결정"),
    ]
    assert [row["anchor_json"]["locator"]["line"] for row in rows] == [1, 3]


def test_session_fts_returns_ranked_member_scoped_hits_with_metadata_filters(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import FileSubmissionService, LocalBlobStore
    from app.source_retrieval import SourceRetrievalAccessError, SourceRetrievalService

    member_id, outsider_id, session_id = seeded_open_session
    source = "예산 검토 결과를 공유합니다\n일정은 다음 회의에서 검토합니다".encode()
    store = LocalBlobStore(tmp_path)
    with open_connection(file_database_url) as connection:
        submission = FileSubmissionService(blob_store=store).submit(
            connection, session_id=session_id, actor_id=member_id,
            filename="검토.txt", declared_mime_type="text/plain",
            stream=io.BytesIO(source), content_length=len(source), title="예산 자료",
        )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=store,
        sandbox_adapter=_FakeSandboxAdapter(
            SandboxExecution(False, None, SandboxFailure(SandboxFailureCode.PARSER_CRASH), "0" * 64, 1, 0, 0, 0, False)
        ),
    )
    assert worker.run_once(owner="fts-worker")["block_count"] == 2

    retrieval = SourceRetrievalService()
    with open_connection(file_database_url) as connection:
        hits = retrieval.search(
            connection, session_id=session_id, actor_id=member_id,
            query="검토", limit=5, mime_type="text/plain",
        )
        assert [hit.text for hit in hits] == [
            "예산 검토 결과를 공유합니다", "일정은 다음 회의에서 검토합니다"
        ]
        assert all(hit.submission_id == submission.id for hit in hits)
        assert retrieval.search(
            connection, session_id=session_id, actor_id=member_id,
            query="검토", author_id=uuid4(),
        ) == ()
        with pytest.raises(SourceRetrievalAccessError):
            retrieval.search(
                connection, session_id=session_id, actor_id=outsider_id, query="검토"
            )


def test_document_comparison_reports_duplicates_and_bilateral_omissions(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.document_comparison import DocumentComparisonAccessError, DocumentComparisonService
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import FileSubmissionService, LocalBlobStore

    member_id, outsider_id, session_id = seeded_open_session
    store = LocalBlobStore(tmp_path)
    revisions: list[UUID] = []
    for filename, text in (
        ("left.txt", "공통 예산 검토 결과\n왼쪽 전용 일정"),
        ("right.txt", "공통 예산 검토 결과\n오른쪽 전용 담당자"),
    ):
        content = text.encode()
        with open_connection(file_database_url) as connection:
            submitted = FileSubmissionService(blob_store=store).submit(
                connection, session_id=session_id, actor_id=member_id,
                filename=filename, declared_mime_type="text/plain",
                stream=io.BytesIO(content), content_length=len(content), title=filename,
            )
        revisions.append(submitted.current_revision_id)
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url), blob_store=store,
        sandbox_adapter=_FakeSandboxAdapter(
            SandboxExecution(False, None, SandboxFailure(SandboxFailureCode.PARSER_CRASH), "0" * 64, 1, 0, 0, 0, False)
        ),
    )
    assert worker.run_once(owner="compare-worker")["block_count"] == 2
    assert worker.run_once(owner="compare-worker")["block_count"] == 2

    with open_connection(file_database_url) as connection:
        result = DocumentComparisonService().compare(
            connection, session_id=session_id, actor_id=member_id,
            left_revision_id=revisions[0], right_revision_id=revisions[1],
        )
        assert [(match.left.text, match.relation) for match in result.matches] == [
            ("공통 예산 검토 결과", "duplicate")
        ]
        assert [item.text for item in result.left_only] == ["왼쪽 전용 일정"]
        assert [item.text for item in result.right_only] == ["오른쪽 전용 담당자"]
        with pytest.raises(DocumentComparisonAccessError):
            DocumentComparisonService().compare(
                connection, session_id=session_id, actor_id=outsider_id,
                left_revision_id=revisions[0], right_revision_id=revisions[1],
            )


def test_report_suggestions_are_member_visible_and_host_resolved_once(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
) -> None:
    from app.report_suggestions import (
        ReportSuggestionAccessError, ReportSuggestionService, ReportSuggestionStateError,
    )

    host_id, outsider_id, session_id = seeded_open_session
    service = ReportSuggestionService()
    with open_connection(file_database_url) as connection:
        snapshot_id = uuid4()
        connection.execute(
            """INSERT INTO generation_snapshots
               (id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,anchor_schema_version)
               VALUES (%s,%s,1,%s,'Topic','test-v1','1')""",
            (snapshot_id, session_id, host_id),
        )
        for kind in ("summary", "research"):
            run_id, document_id = uuid4(), uuid4()
            connection.execute(
                """INSERT INTO generation_runs
                   (id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state,completed_at)
                   VALUES (%s,%s,%s,'mock','fixture-v1','test','test-v1','succeeded',CURRENT_TIMESTAMP)""",
                (run_id, snapshot_id, kind),
            )
            connection.execute(
                """INSERT INTO generated_documents
                   (id,run_id,kind,structured_content_json,content_hash)
                   VALUES (%s,%s,%s,'{}',%s)""",
                (document_id, run_id, kind, ("a" if kind == "summary" else "b") * 64),
            )
        connection.commit()
        suggestion = service.create(
            connection, session_id=session_id, actor_id=host_id,
            suggested_text="결정 담당자를 명시해 주세요.", rationale="실행 책임이 불명확합니다.",
        )
        assert service.list(connection, session_id=session_id, actor_id=host_id) == (suggestion,)
        with pytest.raises(psycopg.Error, match="content hash provenance mismatch"):
            connection.execute(
                "UPDATE report_suggestions SET report_content_hash=%s WHERE id=%s",
                ("f" * 64, suggestion.id),
            )
        connection.rollback()
        departed_target = service.create(
            connection, session_id=session_id, actor_id=host_id,
            suggested_text="탈퇴 후에는 처리할 수 없습니다.",
        )
        with pytest.raises(ReportSuggestionAccessError):
            service.list(connection, session_id=session_id, actor_id=outsider_id)
        resolved = service.resolve(
            connection, suggestion_id=suggestion.id, actor_id=host_id, decision="accepted"
        )
        assert resolved.status == "accepted"
        assert resolved.resolved_by == host_id
        with pytest.raises(ReportSuggestionStateError):
            service.resolve(
                connection, suggestion_id=suggestion.id, actor_id=host_id,
                decision="rejected",
            )
        connection.execute(
            """UPDATE room_memberships SET left_at=CURRENT_TIMESTAMP
               WHERE user_id=%s AND room_id=(SELECT room_id FROM talk_sessions WHERE id=%s)""",
            (host_id, session_id),
        )
        connection.commit()
        with pytest.raises(ReportSuggestionAccessError):
            service.resolve(
                connection, suggestion_id=departed_target.id,
                actor_id=host_id, decision="accepted",
            )
def test_nonmember_cannot_submit_a_file(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_submission_service import FileSubmissionAccessError

    _, outsider_id, session_id = seeded_open_session
    with open_connection(file_database_url) as connection:
        with pytest.raises(FileSubmissionAccessError):
            _submit_pdf(
                _service(tmp_path),
                connection,
                session_id=session_id,
                actor_id=outsider_id,
                content=b"%PDF-1.7\nprivate",
            )

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_database_failure_removes_staged_blob_and_rolls_back_domain_rows(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    member_id, _, session_id = seeded_open_session
    with open_connection(file_database_url) as connection:
        connection.execute(
            """
            CREATE FUNCTION reject_extraction_job() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced extraction enqueue failure'; END $$
            """
        )
        connection.execute(
            "CREATE TRIGGER reject_extraction_job BEFORE INSERT ON jobs "
            "FOR EACH ROW WHEN (NEW.kind = 'extraction') EXECUTE FUNCTION reject_extraction_job()"
        )
        connection.commit()

        with pytest.raises(psycopg.Error):
            _submit_pdf(
                _service(tmp_path),
                connection,
                session_id=session_id,
                actor_id=member_id,
                content=b"%PDF-1.7\nrollback",
            )
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS count FROM submissions")
            assert cursor.fetchone()["count"] == 0
            cursor.execute("SELECT count(*) AS count FROM source_revisions")
            assert cursor.fetchone()["count"] == 0
            cursor.execute("SELECT count(*) AS count FROM jobs")
            assert cursor.fetchone()["count"] == 0

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_member_download_returns_the_exact_immutable_original(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    member_id, _, session_id = seeded_open_session
    content = b"%PDF-1.7\nexact original"
    service = _service(tmp_path)
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            service,
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=content,
        )
        original = service.download_original(  # type: ignore[attr-defined]
            connection,
            revision_id=submission.current_revision_id,  # type: ignore[attr-defined]
            actor_id=member_id,
        )

    assert original.filename == "agenda.pdf"
    assert original.mime_type == "application/pdf"
    assert original.byte_size == len(content)
    digest = hashlib.sha256()
    with original.open() as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    assert digest.hexdigest() == hashlib.sha256(content).hexdigest()
    assert not hasattr(original, "path")
    assert not hasattr(original, "storage_key")


def test_nonmember_cannot_download_an_original(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_submission_service import FileSubmissionAccessError

    member_id, outsider_id, session_id = seeded_open_session
    service = _service(tmp_path)
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            service,
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=b"%PDF-1.7\nprivate original",
        )
        with pytest.raises(FileSubmissionAccessError):
            service.download_original(  # type: ignore[attr-defined]
                connection,
                revision_id=submission.current_revision_id,  # type: ignore[attr-defined]
                actor_id=outsider_id,
            )


def test_membership_revoke_stops_an_original_before_the_next_chunk(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_submission_service import (
        READ_CHUNK_BYTES,
        FileSubmissionAccessError,
    )

    member_id, _, session_id = seeded_open_session
    content = b"%PDF-1.7\n" + b"x" * (READ_CHUNK_BYTES * 2)
    service = _service(tmp_path)
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            service,
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=content,
        )
        original = service.download_original(  # type: ignore[attr-defined]
            connection,
            revision_id=submission.current_revision_id,  # type: ignore[attr-defined]
            actor_id=member_id,
        )

    with open_connection(file_database_url) as stream_connection:
        chunks = service.stream_original(  # type: ignore[attr-defined]
            stream_connection,
            download=original,
            revision_id=submission.current_revision_id,  # type: ignore[attr-defined]
            actor_id=member_id,
        )
        assert next(chunks) == content[:READ_CHUNK_BYTES]
        with open_connection(file_database_url) as revocation_connection:
            revocation_connection.execute(
                """
                UPDATE room_memberships SET left_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                  AND room_id = (
                      SELECT room_id FROM talk_sessions WHERE id = %s
                  )
                """,
                (member_id, session_id),
            )
            revocation_connection.commit()

        with pytest.raises(FileSubmissionAccessError):
            next(chunks)


@dataclass(slots=True)
class _FakeSandboxAdapter:
    execution: SandboxExecution
    requests: list[SandboxRequest] = field(default_factory=list)

    def execute(self, request: SandboxRequest) -> SandboxExecution:
        self.requests.append(request)
        return self.execution


def _worker_success(source: bytes) -> tuple[SandboxExecution, dict[str, object]]:
    source_hash = hashlib.sha256(source).hexdigest()
    profile_hash = "66c3e4fb17d97a94b56511982ba9624ce168d35aa391087b2c414b3eb65f4cc2"
    text = "Exact canonical agenda block"
    anchor: dict[str, object] = {
        "schema_version": 1,
        "kind": "pdf_block",
        "source_sha256": source_hash,
        "extraction_profile_hash": profile_hash,
        "locator": {"page": 0, "block_id": "page-0-block-0", "bbox": [0, 0, 1, 0.25]},
        "text_fingerprint": hashlib.sha256(text.encode()).hexdigest(),
    }
    block: dict[str, object] = {
        "ordinal": 0,
        "text": text,
        "block_type": "pdf_text",
        "confidence": 0.99,
        "anchor": anchor,
        "anchor_hash": canonical_sha256(anchor),
    }
    result: dict[str, object] = {
        "source_sha256": source_hash,
        "media_type": "application/pdf",
        "parser": {"name": "pypdfium2", "version": "5.12.1"},
        "normalization_profile": "nfc-lf-v1",
        "config_profile_hash": profile_hash,
        "anchor_set_hash": canonical_sha256({"anchors": [block["anchor_hash"]]}),
        "blocks": [block],
        "warnings": [],
    }
    return (
        SandboxExecution(
            ok=True,
            payload={"schema_version": 1, "ok": True, "result": result},
            failure=None,
            source_sha256=source_hash,
            exit_code=0,
            duration_ms=5,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
        ),
        block,
    )


def test_extraction_success_persists_exact_blocks_anchors_and_ready_state(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\nworker success"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    execution, expected_block = _worker_success(source)
    adapter = _FakeSandboxAdapter(execution)
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=adapter,
    )

    outcome = worker.run_once(owner="file-test-worker")

    assert outcome["revision_id"] == str(submission.current_revision_id)
    assert outcome["block_count"] == 1
    assert len(adapter.requests) == 1
    assert adapter.requests[0].input_bytes == source
    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision.processing_state, revision.approved_extraction_run_id,
                       run.status, run.error_code, run.parser_name, run.parser_version
                FROM source_revisions revision
                JOIN extraction_runs run ON run.id = revision.approved_extraction_run_id
                WHERE revision.id = %s
                """,
                (submission.current_revision_id,),
            )
            state = cursor.fetchone()
            cursor.execute(
                """
                SELECT ordinal, block_type, text, confidence, anchor_json, canonical_hash
                FROM source_anchors WHERE source_revision_id = %s ORDER BY ordinal
                """,
                (submission.current_revision_id,),
            )
            blocks = cursor.fetchall()
    assert state is not None
    assert state["processing_state"] == "ready"
    assert state["approved_extraction_run_id"] is not None
    assert state["status"] == "succeeded"
    assert state["error_code"] is None
    assert (state["parser_name"], state["parser_version"]) == ("pypdfium2", "5.12.1")
    assert len(blocks) == 1
    assert blocks[0]["ordinal"] == expected_block["ordinal"]
    assert blocks[0]["block_type"] == expected_block["block_type"]
    assert blocks[0]["text"] == expected_block["text"]
    assert blocks[0]["confidence"] == expected_block["confidence"]
    assert blocks[0]["anchor_json"] == expected_block["anchor"]
    assert blocks[0]["canonical_hash"] == expected_block["anchor_hash"]


def test_extraction_failure_persists_typed_run_and_failed_revision_state(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\nworker failure"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    adapter = _FakeSandboxAdapter(
        SandboxExecution(
            ok=False,
            payload=None,
            failure=SandboxFailure(
                SandboxFailureCode.PARSER_REPORTED_FAILURE,
                parser_code="CORRUPT_DOCUMENT",
                retryable=False,
            ),
            source_sha256=hashlib.sha256(source).hexdigest(),
            exit_code=2,
            duration_ms=4,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
        )
    )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=adapter,
    )

    outcome = worker.run_once(owner="file-test-worker")

    assert outcome == {"outcome": "failed"}
    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision.processing_state, revision.approved_extraction_run_id,
                       run.status, run.error_code
                FROM source_revisions revision
                JOIN extraction_runs run ON run.source_revision_id = revision.id
                WHERE revision.id = %s
                """,
                (submission.current_revision_id,),
            )
            failed = cursor.fetchone()
    assert failed is not None
    assert failed["processing_state"] == "failed"
    assert failed["approved_extraction_run_id"] is None
    assert failed["status"] == "failed"
    assert failed["error_code"] == "CORRUPT_DOCUMENT"


def test_retryable_extraction_requeues_twice_then_becomes_terminal(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\nretry bounded"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    adapter = _FakeSandboxAdapter(
        SandboxExecution(
            ok=False,
            payload=None,
            failure=SandboxFailure(
                SandboxFailureCode.PARSER_TIMEOUT,
                retryable=True,
            ),
            source_sha256=hashlib.sha256(source).hexdigest(),
            exit_code=None,
            duration_ms=20_000,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=True,
        )
    )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=adapter,
    )

    for _ in range(3):
        assert worker.run_once(owner="bounded-retry-worker") == {"outcome": "failed"}

    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.state, job.attempts, revision.processing_state,
                       count(run.id) AS run_count
                FROM jobs AS job
                JOIN source_revisions AS revision
                  ON job.payload_json->>'revision_id' = revision.id::text
                JOIN extraction_runs AS run ON run.source_revision_id = revision.id
                WHERE revision.id = %s
                GROUP BY job.state, job.attempts, revision.processing_state
                """,
                (submission.current_revision_id,),
            )
            bounded = cursor.fetchone()
    assert bounded == {
        "state": "failed_terminal",
        "attempts": 3,
        "processing_state": "failed",
        "run_count": 3,
    }
    assert len(adapter.requests) == 3
    assert worker.run_once(owner="bounded-retry-worker") is None


def test_next_worker_reconciles_crash_after_retryable_completion(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore
    from app.queue_repository import PostgresJobQueue

    class _CrashBeforeRequeue(PostgresJobQueue):
        def requeue_retryable(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("simulated host crash boundary")

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\nrecover durable retry"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    timeout = SandboxExecution(
        ok=False,
        payload=None,
        failure=SandboxFailure(SandboxFailureCode.PARSER_TIMEOUT, retryable=True),
        source_sha256=hashlib.sha256(source).hexdigest(),
        exit_code=None,
        duration_ms=20_000,
        stdout_bytes=0,
        stderr_bytes=0,
        killed=True,
    )
    crashed_worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=_FakeSandboxAdapter(timeout),
        queue=_CrashBeforeRequeue(),
    )

    with pytest.raises(RuntimeError, match="simulated host crash boundary"):
        crashed_worker.run_once(owner="crashing-worker")

    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.state, job.lease_generation, revision.processing_state
                FROM jobs AS job
                JOIN source_revisions AS revision
                  ON job.payload_json->>'revision_id' = revision.id::text
                WHERE revision.id = %s
                """,
                (submission.current_revision_id,),
            )
            stranded = cursor.fetchone()
    assert stranded == {
        "state": "failed_retryable",
        "lease_generation": 1,
        "processing_state": "queued",
    }

    recovered_worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=_FakeSandboxAdapter(timeout),
    )
    assert recovered_worker.run_once(owner="replacement-worker") == {"outcome": "failed"}
    assert recovered_worker.run_once(owner="replacement-worker") == {"outcome": "failed"}

    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.state, job.attempts, revision.processing_state
                FROM jobs AS job
                JOIN source_revisions AS revision
                  ON job.payload_json->>'revision_id' = revision.id::text
                WHERE revision.id = %s
                """,
                (submission.current_revision_id,),
            )
            recovered = cursor.fetchone()
    assert recovered == {
        "state": "failed_terminal",
        "attempts": 3,
        "processing_state": "failed",
    }


def test_explicit_requeue_treats_another_workers_higher_generation_claim_as_benign(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import (
        FileExtractionWorker,
        _reconcile_retryable_extractions,
    )
    from app.file_submission_service import LocalBlobStore
    from app.queue_repository import PostgresJobQueue

    claimed_by_worker_b: list[object] = []

    class _TwoWorkerRaceQueue(PostgresJobQueue):
        def requeue_retryable(
            self,
            connection: object,
            *,
            job_id: UUID,
            expected_lease_generation: int,
        ) -> None:
            with open_connection(file_database_url) as other_connection:
                _reconcile_retryable_extractions(other_connection)
                claimed = PostgresJobQueue().claim_next(
                    other_connection,
                    owner="worker-b",
                    lease_seconds=60,
                    kinds=("extraction",),
                )
            assert claimed is not None
            claimed_by_worker_b.append(claimed)
            super().requeue_retryable(  # type: ignore[arg-type]
                connection,
                job_id=job_id,
                expected_lease_generation=expected_lease_generation,
            )

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\ntwo worker race"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    adapter = _FakeSandboxAdapter(
        SandboxExecution(
            ok=False,
            payload=None,
            failure=SandboxFailure(SandboxFailureCode.PARSER_TIMEOUT, retryable=True),
            source_sha256=hashlib.sha256(source).hexdigest(),
            exit_code=None,
            duration_ms=20_000,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=True,
        )
    )
    worker_a = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=adapter,
        queue=_TwoWorkerRaceQueue(),
    )

    # Worker B wins reconciliation/claim between A's completion and explicit
    # requeue. A must return normally rather than terminate its polling loop.
    assert worker_a.run_once(owner="worker-a") == {"outcome": "failed"}

    assert len(claimed_by_worker_b) == 1
    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.state, job.lease_generation, job.lease_owner,
                       revision.processing_state
                FROM jobs AS job
                JOIN source_revisions AS revision
                  ON job.payload_json->>'revision_id' = revision.id::text
                WHERE revision.id = %s
                """,
                (submission.current_revision_id,),
            )
            winner = cursor.fetchone()
    assert winner == {
        "state": "running",
        "lease_generation": 2,
        "lease_owner": "worker-b",
        "processing_state": "queued",
    }


def test_explicit_requeue_accepts_higher_generation_retryable_completion(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.domain import JobState
    from app.file_extraction_worker import (
        FileExtractionWorker,
        _reconcile_retryable_extractions,
    )
    from app.file_submission_service import LocalBlobStore
    from app.queue_repository import PostgresJobQueue

    class _WorkerBCompletesThenCrashesQueue(PostgresJobQueue):
        def requeue_retryable(
            self,
            connection: object,
            *,
            job_id: UUID,
            expected_lease_generation: int,
        ) -> None:
            worker_b_queue = PostgresJobQueue()
            with open_connection(file_database_url) as other_connection:
                _reconcile_retryable_extractions(other_connection)
                claimed = worker_b_queue.claim_next(
                    other_connection,
                    owner="worker-b",
                    lease_seconds=60,
                    kinds=("extraction",),
                )
            assert claimed is not None
            assert claimed.lease_generation == 2
            with open_connection(file_database_url) as other_connection:
                worker_b_queue.complete(
                    other_connection,
                    claimed,
                    target_state=JobState.FAILED_RETRYABLE,
                    result={"outcome": "failed"},
                    error_code="PARSER_TIMEOUT",
                )
            # Simulate B crashing here, before B's explicit requeue. A now
            # observes a stale generation-1 target with durable gen-2 progress.
            super().requeue_retryable(  # type: ignore[arg-type]
                connection,
                job_id=job_id,
                expected_lease_generation=expected_lease_generation,
            )

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\ngeneration two retryable"
    with open_connection(file_database_url) as connection:
        submission = _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    worker_a = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=_FakeSandboxAdapter(
            SandboxExecution(
                ok=False,
                payload=None,
                failure=SandboxFailure(
                    SandboxFailureCode.PARSER_TIMEOUT,
                    retryable=True,
                ),
                source_sha256=hashlib.sha256(source).hexdigest(),
                exit_code=None,
                duration_ms=20_000,
                stdout_bytes=0,
                stderr_bytes=0,
                killed=True,
            )
        ),
        queue=_WorkerBCompletesThenCrashesQueue(),
    )

    assert worker_a.run_once(owner="worker-a") == {"outcome": "failed"}

    with open_connection(file_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT state, lease_generation, error_code
                FROM jobs
                WHERE payload_json->>'revision_id' = %s
                """,
                (str(submission.current_revision_id),),
            )
            progressed = cursor.fetchone()
    assert progressed == {
        "state": "failed_retryable",
        "lease_generation": 2,
        "error_code": "PARSER_TIMEOUT",
    }


def test_explicit_requeue_does_not_swallow_queue_invariant_errors(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore
    from app.queue_repository import PostgresJobQueue, QueueInvariantError

    class _InvariantFailureQueue(PostgresJobQueue):
        def requeue_retryable(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise QueueInvariantError("synthetic invariant violation")

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\ninvariant propagation"
    with open_connection(file_database_url) as connection:
        _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=_FakeSandboxAdapter(
            SandboxExecution(
                ok=False,
                payload=None,
                failure=SandboxFailure(
                    SandboxFailureCode.PARSER_TIMEOUT,
                    retryable=True,
                ),
                source_sha256=hashlib.sha256(source).hexdigest(),
                exit_code=None,
                duration_ms=20_000,
                stdout_bytes=0,
                stderr_bytes=0,
                killed=True,
            )
        ),
        queue=_InvariantFailureQueue(),
    )

    with pytest.raises(QueueInvariantError, match="synthetic invariant violation"):
        worker.run_once(owner="invariant-worker")


def test_explicit_requeue_rejects_stale_error_without_a_durable_winner(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.domain import StaleLeaseError
    from app.file_extraction_worker import FileExtractionWorker
    from app.file_submission_service import LocalBlobStore
    from app.queue_repository import PostgresJobQueue

    class _FalseStaleQueue(PostgresJobQueue):
        def requeue_retryable(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise StaleLeaseError("synthetic stale response")

    member_id, _, session_id = seeded_open_session
    source = b"%PDF-1.7\nfalse stale"
    with open_connection(file_database_url) as connection:
        _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=source,
        )
    worker = FileExtractionWorker(
        connection_factory=lambda: open_connection(file_database_url),
        blob_store=LocalBlobStore(tmp_path),
        sandbox_adapter=_FakeSandboxAdapter(
            SandboxExecution(
                ok=False,
                payload=None,
                failure=SandboxFailure(
                    SandboxFailureCode.PARSER_TIMEOUT,
                    retryable=True,
                ),
                source_sha256=hashlib.sha256(source).hexdigest(),
                exit_code=None,
                duration_ms=20_000,
                stdout_bytes=0,
                stderr_bytes=0,
                killed=True,
            )
        ),
        queue=_FalseStaleQueue(),
    )

    with pytest.raises(StaleLeaseError, match="synthetic stale response"):
        worker.run_once(owner="false-stale-worker")


def test_orphan_sweeper_removes_only_unreferenced_files_older_than_24_hours(
    file_database_url: str,
    seeded_open_session: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    from app.file_submission_service import LocalBlobStore

    member_id, _, session_id = seeded_open_session
    store = LocalBlobStore(tmp_path)
    with open_connection(file_database_url) as connection:
        _submit_pdf(
            _service(tmp_path),
            connection,
            session_id=session_id,
            actor_id=member_id,
            content=b"%PDF-1.7\nreferenced",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT storage_key FROM source_revisions WHERE storage_key IS NOT NULL"
            )
            referenced_key = cursor.fetchone()["storage_key"]

        old_orphan = tmp_path / f"{uuid4().hex}.blob"
        old_temp = tmp_path / f".upload-{uuid4().hex}.tmp"
        recent_orphan = tmp_path / f"{uuid4().hex}.blob"
        unrelated = tmp_path / "operator-note.txt"
        for path in (old_orphan, old_temp, recent_orphan, unrelated):
            path.write_bytes(b"local")
        for path in (store.path_for(referenced_key), old_orphan, old_temp, unrelated):
            os.utime(path, (1, 1))
        os.utime(recent_orphan, (199_999, 199_999))

        removed = store.sweep_orphans(
            connection,
            minimum_age_seconds=24 * 60 * 60,
            now=200_000,
        )

    assert removed == 2
    assert store.path_for(referenced_key).is_file()
    assert not old_orphan.exists()
    assert not old_temp.exists()
    assert recent_orphan.is_file()
    assert unrelated.is_file()

"""Phase 2 wire contracts and the contract-only FastAPI surface.

These Pydantic models are the source of truth for generated JSON Schema,
OpenAPI, and the checked TypeScript client.  The contract application is kept
separate from the disposable Phase 0 transport harness so freezing a schema
does not accidentally claim that a Phase 3 business endpoint already exists.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, NoReturn, cast
from urllib.parse import quote, urlsplit
from uuid import UUID

import psycopg
from fastapi import (
    APIRouter,
    FastAPI,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    model_validator,
)

from app.api_errors import ApiProblem
from app.auth_service import (
    AuthService,
    AuthenticatedSession,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    RegistrationValidationError,
    SessionAuthenticationError,
    UserRecord,
)
from app.citation_resolver import (
    CitationResolver,
    CitationResolverInvariantError,
    CitationUnavailableError,
)
from app.collaboration_service import (
    CollaborationAccessError,
    CollaborationError,
    CollaborationHostRequiredError,
    CollaborationService,
    FriendView,
    FriendshipConflictError,
    FriendshipRequiredError,
    FriendshipStateError,
    FriendshipView,
    RoomMemberView,
    RoomInvitationView,
    RoomView,
    SessionUnavailableError,
    TalkSessionView,
    UserUnavailableError,
)
from app.db import open_connection
from app.description_assist_service import (
    DescriptionInterviewTurn as _DescriptionInterviewTurn,
    advance_description_interview,
    finalize_description,
)
from app.domain import CloseBlockedError
from app.document_comparison import (
    DocumentComparisonAccessError,
    DocumentComparisonService,
)
from app.activity_service import ActivityService
from app.comments_service import CommentReplayConflictError, CommentsService
from app.generation_repository import (
    GenerationDocumentUnavailableError,
    GenerationRepository,
)
from app.grok_provider import GrokProviderError, XaiResponsesTransport
from app.grok_report_provider import GrokReportProvider
from app.grok_edit_agent import GrokEditAgentService
from app.integrated_report import load_report_identity
from app.merged_document_service import (
    MergedDocumentAccessError,
    MergedDocumentHeadingBlock,
    MergedDocumentParagraphBlock,
    MergedDocumentService,
    MergedDocumentStaleVersionError,
    MergedDocumentVersionSnapshot,
)
from app.merged_document_service import MergedDocumentBlock as _MergedDocumentBlockDomain
from app.notification_service import NotificationService
from app.notification_activity_routes import resolve_visible_comment_session
from app.profile_repository import DEFAULT_PREFERENCES, ProfileInvariantError
from app.profile_service import ProfileService, StaleProfileVersionError
from app.file_submission_service import (
    FileSubmissionAccessError,
    FileSubmissionError,
    FileSubmissionLimitError,
    FileSubmissionService,
    FileSubmissionStateError,
    FileSubmissionValidationError,
    LocalBlobStore,
)
from app.security import (
    CSRF_HEADER_NAME,
    ORIGINAL_HOST_HEADER_NAME,
    BrowserSecurityPolicy,
    SecurityPolicyError,
    require_pre_auth_request,
    require_trusted_original_host,
    session_cookie,
)
from app.report_suggestions import (
    ReportSuggestionAccessError,
    ReportSuggestionService,
    ReportSuggestionStateError,
)
from app.source_retrieval import SourceRetrievalAccessError, SourceRetrievalService
from app.session_retry_service import (
    SessionRetryAccessError,
    SessionRetryHostRequiredError,
    SessionRetryService,
    SessionRetryUnavailableError,
)
from app.session_service import (
    CloseExclusionRequest,
    ExtractionAnchorSchemaMismatchError,
    ExtractionRunMissingError,
    SessionAccessError,
    SessionCloseService,
    SessionHostRequiredError,
    SessionStateError as CloseSessionStateError,
)
from app.text_submission_service import (
    SourceRevisionView,
    SubmissionMetadataView,
    SubmissionView,
    TextAnchorView,
    TextSubmissionAccessError,
    TextSubmissionError,
    TextSubmissionLimitError,
    TextSubmissionOwnerError,
    TextSubmissionService,
    TextSubmissionStateError,
    TextViewerUnavailableError,
    TextViewerView,
)


class _WireModel(BaseModel):
    """Reject unknown wire fields at every public contract boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _CanonicalAnchorWireModel(_WireModel):
    """Wire model that must not normalize hash-identity strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class SessionState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_ATTENTION = "needs_attention"


class SourceProcessingState(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


class GenerationRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class GenerationKind(StrEnum):
    SUMMARY = "summary"
    RESEARCH = "research"


class AnchorKind(StrEnum):
    TEXT_LINE = "text_line"
    PDF_BLOCK = "pdf_block"
    IMAGE_BBOX = "image_bbox"
    HWP_PARAGRAPH = "hwp_paragraph"
    DOCX_PARAGRAPH = "docx_paragraph"
    XLSX_CELL = "xlsx_cell"


class FactCheckVerdict(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    MIXED = "mixed"
    UNVERIFIABLE = "unverifiable"


class NormalizedBoundingBox(RootModel[list[float]]):
    """Canonical G0 ``[left, top, right, bottom]`` bounds.

    G0 hashes a JSON array rather than a named-coordinate object.  Keeping
    that representation in the public DTO lets a browser consume the exact
    persisted locator without a lossy adapter or a second hash identity.
    """

    root: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def _has_nonempty_area(self) -> NormalizedBoundingBox:
        left, top, right, bottom = self.root
        if not all(0 <= coordinate <= 1 for coordinate in self.root):
            raise ValueError("normalized bbox coordinates must be in [0, 1]")
        if right <= left or bottom <= top:
            raise ValueError("normalized bbox must have positive area")
        return self


class TextLineLocator(_CanonicalAnchorWireModel):
    line: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _has_ordered_range(self) -> TextLineLocator:
        if self.end <= self.start:
            raise ValueError("text-line locator range must be ordered and non-empty")
        return self


class PdfBlockLocator(_CanonicalAnchorWireModel):
    page: int = Field(ge=0)
    block_id: str = Field(min_length=1, max_length=128)
    bbox: NormalizedBoundingBox


class ImageBBoxLocator(_CanonicalAnchorWireModel):
    image_id: str = Field(min_length=1, max_length=128)
    bbox: NormalizedBoundingBox


class HwpTablePath(_CanonicalAnchorWireModel):
    index: int = Field(ge=0)
    block: int = Field(ge=0)
    row: int = Field(ge=0)
    cell: int = Field(ge=0)
    paragraph: int = Field(ge=0)


class HwpFootnotePath(_CanonicalAnchorWireModel):
    index: int = Field(ge=0)
    paragraph: int = Field(ge=0)


class HwpParagraphLocator(_CanonicalAnchorWireModel):
    parser: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    section: int = Field(ge=0)
    paragraph: int = Field(ge=0)
    table: HwpTablePath | None = None
    footnote: HwpFootnotePath | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null_structural_paths(cls, value: object) -> object:
        if isinstance(value, dict) and (
            ("table" in value and value["table"] is None)
            or ("footnote" in value and value["footnote"] is None)
        ):
            raise ValueError("HWP structural paths must be absent or complete objects")
        return value

    @model_validator(mode="after")
    def _has_one_optional_structural_path(self) -> HwpParagraphLocator:
        if self.table is not None and self.footnote is not None:
            raise ValueError("HWP table and footnote paths are mutually exclusive")
        return self


class DocxTablePath(_CanonicalAnchorWireModel):
    index: int = Field(ge=0)
    row: int = Field(ge=0)
    cell: int = Field(ge=0)
    paragraph: int = Field(ge=0)


class DocxParagraphLocator(_CanonicalAnchorWireModel):
    paragraph: int = Field(ge=0)
    table: DocxTablePath | None = None


class XlsxCellLocator(_CanonicalAnchorWireModel):
    sheet: str = Field(min_length=1, max_length=128)
    cell: str = Field(min_length=1, max_length=128)
    row: int = Field(ge=1)
    column: int = Field(ge=1)


AnchorLocator = (
    TextLineLocator
    | PdfBlockLocator
    | ImageBBoxLocator
    | HwpParagraphLocator
    | DocxParagraphLocator
    | XlsxCellLocator
)

_CANONICAL_SOURCE_ANCHOR_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "source_sha256",
        "extraction_profile_hash",
        "locator",
        "text_fingerprint",
    }
)


class SourceAnchor(_CanonicalAnchorWireModel):
    """Server UUID envelope over the lossless, canonical G0 anchor payload."""

    id: UUID
    revision_id: UUID
    schema_version: Literal[1]
    kind: AnchorKind
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: AnchorLocator
    text_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=1, max_length=20_000)

    @model_validator(mode="before")
    @classmethod
    def _requires_exact_g0_schema_version(cls, value: object) -> object:
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
            raise ValueError("source anchor schema_version must be the integer 1")
        if value["schema_version"] != 1:
            raise ValueError("source anchor schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def _locator_matches_anchor_kind(self) -> SourceAnchor:
        matches = (
            (
                self.kind is AnchorKind.TEXT_LINE
                and isinstance(self.locator, TextLineLocator)
            )
            or (
                self.kind is AnchorKind.PDF_BLOCK
                and isinstance(self.locator, PdfBlockLocator)
            )
            or (
                self.kind is AnchorKind.IMAGE_BBOX
                and isinstance(self.locator, ImageBBoxLocator)
            )
            or (
                self.kind is AnchorKind.HWP_PARAGRAPH
                and isinstance(self.locator, HwpParagraphLocator)
            )
            or (
                self.kind is AnchorKind.DOCX_PARAGRAPH
                and isinstance(self.locator, DocxParagraphLocator)
            )
            or (
                self.kind is AnchorKind.XLSX_CELL
                and isinstance(self.locator, XlsxCellLocator)
            )
        )
        if not matches:
            raise ValueError("source anchor kind must match typed locator kind")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        """Return exactly the G0 hash-identity fields, never API envelope fields."""

        return self.model_dump(
            mode="json",
            include=set(_CANONICAL_SOURCE_ANCHOR_FIELDS),
            exclude_none=True,
        )


class SummarySupport(_WireModel):
    citation_id: UUID
    source_anchor_id: UUID
    exact_quote: str = Field(min_length=1, max_length=20_000)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _has_nonempty_span(self) -> SummarySupport:
        if self.end <= self.start:
            raise ValueError("support end must be greater than start")
        return self


class SummaryItem(_WireModel):
    text: str = Field(min_length=1, max_length=10_000)
    source_anchor_ids: list[UUID] = Field(min_length=1, max_length=50)
    supports: list[SummarySupport] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _declares_exactly_the_supported_anchors(self) -> SummaryItem:
        declared = set(self.source_anchor_ids)
        supported = {support.source_anchor_id for support in self.supports}
        if len(declared) != len(self.source_anchor_ids):
            raise ValueError("summary source_anchor_ids must be unique")
        if declared != supported:
            raise ValueError("summary source_anchor_ids must match support anchor IDs")
        return self


class SummarySection(_WireModel):
    heading: str = Field(min_length=1, max_length=240)
    items: list[SummaryItem] = Field(min_length=1, max_length=100)


class SummaryResult(_WireModel):
    snapshot_id: UUID
    sections: list[SummarySection] = Field(min_length=1, max_length=50)


class WebEvidence(_WireModel):
    id: UUID
    url: str = Field(pattern=r"^https?://", max_length=2_048)
    title: str = Field(min_length=1, max_length=1_000)
    domain: str = Field(min_length=1, max_length=253)
    accessed_at: AwareDatetime
    snippet_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _has_safe_normalized_origin(self) -> WebEvidence:
        if any(ord(character) < 32 or ord(character) == 127 for character in self.url):
            raise ValueError("web evidence URL must not contain control characters")
        try:
            parsed = urlsplit(self.url)
            hostname = parsed.hostname
            # Accessing ``port`` validates malformed port syntax too.
            _ = parsed.port
        except ValueError as error:
            raise ValueError("web evidence URL is invalid") from error
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ValueError("web evidence URL must use http(s) with a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("web evidence URL must not contain userinfo")
        normalized_hostname = hostname.rstrip(".").lower()
        if self.domain != normalized_hostname:
            raise ValueError(
                "web evidence domain must equal the normalized URL hostname"
            )
        return self


class ResearchItem(_WireModel):
    text: str = Field(min_length=1, max_length=10_000)
    web_evidence_ids: list[UUID] = Field(min_length=1, max_length=50)


class FactCheckItem(_WireModel):
    source_anchor_id: UUID
    source_claim_quote: str = Field(min_length=1, max_length=20_000)
    verdict: FactCheckVerdict
    explanation: str = Field(min_length=1, max_length=10_000)
    # A pure cross-document conflict (two sections disagree with each other)
    # needs no external web evidence to be well-formed; only claims actually
    # verified against the live web carry citations here.
    web_evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ResearchResult(_WireModel):
    snapshot_id: UUID
    topic_items: list[ResearchItem] = Field(default_factory=list, max_length=100)
    fact_checks: list[FactCheckItem] = Field(default_factory=list, max_length=100)


class RagDocumentContribution(_WireModel):
    document_id: UUID
    revision_id: UUID
    title: str = Field(min_length=1, max_length=500)
    rag_unit_count: int = Field(ge=1)
    used_rag_unit_count: int = Field(ge=0)
    used_anchor_ids: list[UUID] = Field(default_factory=list, max_length=10_000)


class SourceQualitySummary(_WireModel):
    status: Literal["clean", "filtered"]
    total_anchor_count: int = Field(ge=0)
    accepted_anchor_count: int = Field(ge=0)
    excluded_anchor_count: int = Field(ge=0)
    reason_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> SourceQualitySummary:
        if self.accepted_anchor_count + self.excluded_anchor_count != self.total_anchor_count:
            raise ValueError("source quality anchor counts are inconsistent")
        if sum(self.reason_counts.values()) != self.excluded_anchor_count:
            raise ValueError("source quality reason counts are inconsistent")
        if any(not reason.strip() or count < 1 for reason, count in self.reason_counts.items()):
            raise ValueError("source quality reasons are invalid")
        expected_status = "filtered" if self.excluded_anchor_count else "clean"
        if self.status != expected_status:
            raise ValueError("source quality status is inconsistent")
        return self


class IntegratedReportResponse(_WireModel):
    snapshot_id: UUID
    summary: SummaryResult
    research: ResearchResult
    rag_contributions: list[RagDocumentContribution] = Field(default_factory=list)
    source_quality: SourceQualitySummary
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MergedDocumentHeadingBlockWire(_WireModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["heading"] = "heading"
    level: Literal[1, 2, 3]
    text: str = Field(min_length=1, max_length=2_000)
    # RAG 인용 태그 — 이 블록이 실제로 참고한 원본 문서명(들)입니다.
    tag: str | None = Field(default=None, max_length=1_000)


class MergedDocumentParagraphBlockWire(_WireModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=20_000)
    # RAG 인용 태그 — 이 블록이 실제로 참고한 원본 문서명(들)입니다.
    tag: str | None = Field(default=None, max_length=1_000)


MergedDocumentBlockWire = Annotated[
    MergedDocumentHeadingBlockWire | MergedDocumentParagraphBlockWire,
    Field(discriminator="type"),
]


class MergedDocumentResponse(_WireModel):
    session_id: UUID
    snapshot_id: UUID
    version: int = Field(ge=0)
    blocks: list[MergedDocumentBlockWire] = Field(min_length=1, max_length=500)
    updated_at: AwareDatetime | None = None


class MergedDocumentSaveRequest(_WireModel):
    expected_version: int = Field(ge=0)
    blocks: list[MergedDocumentBlockWire] = Field(min_length=1, max_length=500)


class MergedDocumentVersionCreateRequest(_WireModel):
    label: str = Field(min_length=1, max_length=200)


class MergedDocumentVersionResponse(_WireModel):
    id: UUID
    label: str = Field(min_length=1, max_length=200)
    document_version: int = Field(ge=0)
    created_by: UUID
    created_at: AwareDatetime


class MergedDocumentVersionListResponse(_WireModel):
    items: list[MergedDocumentVersionResponse]


class MergedDocumentVersionDetailResponse(_WireModel):
    id: UUID
    label: str = Field(min_length=1, max_length=200)
    document_version: int = Field(ge=0)
    created_by: UUID
    created_at: AwareDatetime
    blocks: list[MergedDocumentBlockWire] = Field(min_length=1, max_length=500)


class ReportSuggestionCreate(_WireModel):
    source_anchor_id: UUID | None = None
    target_block_id: str | None = Field(default=None, max_length=200)
    kind: Literal["add", "edit", "remove"] = "add"
    suggested_text: str = Field(min_length=1, max_length=10_000)
    rationale: str = Field(default="", max_length=2_000)


class GrokEditTaskRequest(_WireModel):
    instruction: str = Field(min_length=1, max_length=4_000)


class ReportSuggestionDecision(_WireModel):
    decision: Literal["accepted", "rejected"]


class ReportSuggestionResponse(_WireModel):
    id: UUID
    session_id: UUID
    author_id: UUID
    source_anchor_id: UUID | None = None
    target_block_id: str | None = None
    snapshot_id: UUID
    report_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["add", "edit", "remove"]
    origin: Literal["member", "automatic_comparison"]
    suggested_text: str
    rationale: str
    status: Literal["open", "accepted", "rejected"]
    resolved_by: UUID | None = None
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None


class CitationTarget(_WireModel):
    citation_id: UUID
    target_type: Literal["source_anchor", "web_evidence"]
    source_anchor_id: UUID | None = None
    source_revision_id: UUID | None = None
    web_evidence_id: UUID | None = None

    @model_validator(mode="after")
    def _has_exactly_one_target(self) -> CitationTarget:
        if self.target_type == "source_anchor":
            valid = (
                self.source_anchor_id is not None
                and self.source_revision_id is not None
                and self.web_evidence_id is None
            )
        else:
            valid = (
                self.web_evidence_id is not None
                and self.source_anchor_id is None
                and self.source_revision_id is None
            )
        if not valid:
            raise ValueError("citation target does not match target_type")
        return self


class SourceAnchorTarget(_WireModel):
    source_anchor_id: UUID
    source_revision_id: UUID
    exact_quote: str = Field(min_length=1, max_length=20_000)


class ChatMessageAnchor(_WireModel):
    """Future-only contract; no chat UI or realtime implementation exists."""

    kind: Literal["chat_message"] = "chat_message"
    message_id: UUID
    author_id: UUID
    sent_at: AwareDatetime


class ConversationMessage(_WireModel):
    id: UUID
    room_id: UUID
    author_id: UUID
    sent_at: AwareDatetime
    body: str = Field(min_length=1, max_length=10_000)


class RevisionExclusion(_WireModel):
    revision_id: UUID
    reason: str = Field(min_length=1, max_length=1_000)


class CloseSessionRequest(_WireModel):
    exclusions: list[RevisionExclusion] = Field(default_factory=list, max_length=20)


class CloseSessionResponse(_WireModel):
    snapshot_id: UUID
    generation_epoch: int = Field(ge=1)
    state: Annotated[SessionState, Field(description="Aggregate session state")]
    idempotent: bool


class RetrySessionResponse(_WireModel):
    snapshot_id: UUID
    state: SessionState


class ErrorResponse(_WireModel):
    code: str = Field(min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=1_000)


class ContractOnlyError(Exception):
    """Signal that a frozen endpoint deliberately has no Phase 2 handler."""


class RoomRole(StrEnum):
    HOST = "host"
    MEMBER = "member"


class FriendshipStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class UserResponse(_WireModel):
    id: UUID
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)


class RegisterRequest(_WireModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1_024)
    display_name: str = Field(min_length=1, max_length=200)


class LoginRequest(_WireModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1_024)


class CsrfResponse(_WireModel):
    csrf_token: str = Field(min_length=20, max_length=512)


class FriendRequestCreate(_WireModel):
    addressee_id: UUID


class FriendRequestResponse(_WireModel):
    id: UUID
    requester: UserResponse
    addressee: UserResponse
    status: FriendshipStatus
    created_at: AwareDatetime


class FriendResponse(_WireModel):
    user: UserResponse
    friendship_id: UUID


class DescriptionInterviewTurn(_WireModel):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=500)


class DescriptionSuggestionRequest(_WireModel):
    title: str = Field(min_length=1, max_length=200)
    draft: str = Field(default="", max_length=4_000)
    history: list[DescriptionInterviewTurn] = Field(default_factory=list, max_length=5)
    # 사용자가 "그만 묻고 지금까지 답변으로 정리해줘"를 눌렀을 때 True —
    # 질문을 더 하지 않고 history가 짧아도 바로 확정 설명으로 넘어갑니다.
    force_final: bool = False


class DescriptionSuggestionQuestion(_WireModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=4)
    # OMX deep-interview 방식의 명확도(clarity) 자가 채점 — 0.0(모호함)~1.0(명확함).
    clarity: float = Field(ge=0.0, le=1.0)


class DescriptionSuggestionResponse(_WireModel):
    step: Literal["question", "final"]
    question: DescriptionSuggestionQuestion | None = None
    # final 단계에서는 후보 여러 개가 아니라 확장된 설명 하나만 돌려줍니다 —
    # 사용자가 체크(적용)/취소로 직접 확인하고 반영 여부를 결정합니다.
    description: str | None = None


class RoomCreateRequest(_WireModel):
    name: str = Field(min_length=1, max_length=240)


class RoomResponse(_WireModel):
    id: UUID
    name: str = Field(min_length=1, max_length=240)
    owner_id: UUID
    role: RoomRole


class RoomMemberResponse(_WireModel):
    user: UserResponse
    role: RoomRole


class RoomInvitationCreate(_WireModel):
    invitee_id: UUID


class RoomInvitationResponse(_WireModel):
    id: UUID
    room_id: UUID
    invitee_id: UUID
    status: FriendshipStatus


class TalkSessionCreateRequest(_WireModel):
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    deadline: AwareDatetime | None = None


class TalkSessionResponse(_WireModel):
    id: UUID
    room_id: UUID
    host_id: UUID
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(max_length=10_000)
    deadline: AwareDatetime | None = None
    state: SessionState
    generation_epoch: int = Field(ge=0)
    created_at: AwareDatetime
    closed_at: AwareDatetime | None


class TextSubmissionCreate(_WireModel):
    title: str = Field(default="공유 자료", min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=100_000)


class SubmissionResponse(_WireModel):
    id: UUID
    session_id: UUID
    author_id: UUID
    kind: Literal["text", "file"]
    title: str = Field(min_length=1, max_length=500)
    current_revision_id: UUID
    processing_state: SourceProcessingState


class SubmissionMetadataResponse(SubmissionResponse):
    filename: str = Field(min_length=1, max_length=1_024)
    mime_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0, le=200 * 1024 * 1024)
    author: UserResponse
    created_at: AwareDatetime


class SubmissionReplaceRequest(_WireModel):
    text: str = Field(min_length=1, max_length=100_000)


class SourceRevisionResponse(_WireModel):
    id: UUID
    submission_id: UUID
    filename: str = Field(min_length=1, max_length=1_024)
    mime_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0, le=200 * 1024 * 1024)
    processing_state: SourceProcessingState


class SourceViewerResponse(_WireModel):
    revision: SourceRevisionResponse
    text: str = Field(min_length=1, max_length=100_000)
    highlighted_anchor: SourceAnchor | None = None


class SourcePreviewResponse(_WireModel):
    revision_id: UUID
    text: str
    truncated: bool


class SourceSearchHitResponse(_WireModel):
    anchor_id: UUID
    revision_id: UUID
    submission_id: UUID
    title: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=1_024)
    mime_type: str = Field(min_length=1, max_length=255)
    author_id: UUID
    text: str = Field(min_length=1, max_length=100_000)
    rank: float = Field(ge=0)


class ComparisonAnchorResponse(_WireModel):
    anchor_id: UUID
    revision_id: UUID
    text: str = Field(min_length=1, max_length=100_000)


class ComparisonMatchResponse(_WireModel):
    left: ComparisonAnchorResponse
    right: ComparisonAnchorResponse
    similarity: float = Field(ge=0, le=1)
    relation: Literal["duplicate", "similar"]


class DocumentComparisonResponse(_WireModel):
    left_revision_id: UUID
    right_revision_id: UUID
    matches: list[ComparisonMatchResponse]
    left_only: list[ComparisonAnchorResponse]
    right_only: list[ComparisonAnchorResponse]


class NotificationKind(StrEnum):
    ANALYSIS_COMPLETED = "analysis_completed"
    MENTION = "mention"
    COMMENT = "comment"
    FRIEND_REQUEST = "friend_request"
    ROOM_MEMBER_ADDED = "room_member_added"


class NotificationResourceType(StrEnum):
    FRIEND_REQUEST = "friend_request"
    ROOM = "room"
    SESSION = "session"
    COMMENT = "comment"


class NotificationActionKind(StrEnum):
    RESPOND_FRIEND_REQUEST = "respond_friend_request"
    OPEN_ROOM = "open_room"
    OPEN_SESSION = "open_session"
    OPEN_COMMENT = "open_comment"
    NONE = "none"


class NotificationResponse(_WireModel):
    id: UUID
    kind: NotificationKind
    actor_id: UUID | None
    resource_type: NotificationResourceType
    resource_id: UUID
    action_kind: NotificationActionKind
    href: str = Field(max_length=256, pattern=r"^/($|[^/])")
    title: str = Field(max_length=120)
    body: str = Field(max_length=240)
    created_at: AwareDatetime
    read_at: AwareDatetime | None


class NotificationPageResponse(_WireModel):
    items: list[NotificationResponse]
    next_cursor: str | None
    unread_count: int = Field(ge=0)


class ReadReceiptResponse(_WireModel):
    updated_count: int = Field(ge=0)


class EmailOutboxResponse(_WireModel):
    id: UUID
    notification_kind: NotificationKind
    template_key: str
    template_data: dict[str, Any]
    status: Literal["queued_local"]
    created_at: AwareDatetime
    delivery_notice: Literal["로컬 큐에만 저장되었으며 외부로 발송되지 않았습니다."]


class EmailOutboxPageResponse(_WireModel):
    items: list[EmailOutboxResponse]
    next_cursor: str | None


class ProfileResponse(_WireModel):
    user_id: UUID
    email: str
    display_name: str
    job_title: str | None
    language: Literal["ko", "en", "ja"]
    profile_version: int = Field(ge=0)
    profile_updated_at: AwareDatetime


class ProfileUpdateRequest(_WireModel):
    """Mutable profile fields only; email changes are rejected as extra input."""

    expected_version: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, min_length=1, max_length=200)
    language: Literal["ko", "en", "ja"]


class ProfileUpdateResponse(ProfileResponse):
    updated: bool


class NotificationChannelSettings(_WireModel):
    in_app: bool
    email_intent: bool


class NotificationPreferenceMatrix(_WireModel):
    analysis_completed: NotificationChannelSettings
    mention: NotificationChannelSettings
    comment: NotificationChannelSettings


class NotificationPreferencesResponse(_WireModel):
    values: NotificationPreferenceMatrix
    preferences_version: int = Field(ge=0)
    preferences_updated_at: AwareDatetime


class NotificationPreferencesUpdateRequest(_WireModel):
    expected_version: int = Field(ge=0)
    values: NotificationPreferenceMatrix


class NotificationPreferencesUpdateResponse(NotificationPreferencesResponse):
    updated: bool


class CommentAnchorKind(StrEnum):
    REPORT = "report"
    GENERATED_SEGMENT = "generated_segment"


class CommentResponse(_WireModel):
    id: UUID
    session_id: UUID
    author_id: UUID
    version: int = Field(ge=1)
    body: str
    anchor_kind: CommentAnchorKind | None
    anchor_id: UUID | None
    mentioned_user_ids: list[UUID]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: AwareDatetime | None


class CommentPageResponse(_WireModel):
    items: list[CommentResponse]
    next_cursor: str | None


class CommentCreateRequest(_WireModel):
    client_request_id: UUID
    body: str = Field(min_length=1, max_length=5_000)
    anchor_kind: CommentAnchorKind | None = None
    anchor_id: UUID | None = None
    mentioned_user_ids: list[UUID] = Field(default_factory=list, max_length=20)


class CommentUpdateRequest(_WireModel):
    expected_version: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=5_000)
    anchor_kind: CommentAnchorKind | None = None
    anchor_id: UUID | None = None
    mentioned_user_ids: list[UUID] = Field(default_factory=list, max_length=20)


class CommentDeleteRequest(_WireModel):
    expected_version: int = Field(ge=1)


class CommentMutationResponse(_WireModel):
    id: UUID
    version: int = Field(ge=1)
    idempotent: bool


class AuditScope(StrEnum):
    ALL = "all"
    PERSONAL = "personal"
    ROOM = "room"
    SESSION = "session"


class AuditEventResponse(_WireModel):
    id: UUID
    ledger_sequence: int = Field(ge=1)
    event_type: str
    actor_id: UUID | None
    actor_display_name: str | None
    scope_type: Literal["personal", "room", "session"]
    audience_user_id: UUID | None
    room_id: UUID | None
    session_id: UUID | None
    entity_type: str
    entity_id: UUID
    metadata_json: dict[str, Any]
    created_at: AwareDatetime


class AuditEventPageResponse(_WireModel):
    coverage_started_at: AwareDatetime
    items: list[AuditEventResponse]
    next_cursor: str | None


def _not_implemented() -> NoReturn:
    """Prevent the contract surface from pretending Phase 3 has shipped."""

    raise ContractOnlyError()


async def _contract_only_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Keep every advertised 501 body faithful to ``ErrorResponse``."""

    if not isinstance(exc, ContractOnlyError):
        raise exc
    del request
    body = ErrorResponse(
        code="contract_only",
        detail="phase 2 contract only; implementation is scheduled for a later phase",
    )
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=body.model_dump(mode="json"),
    )


def install_contract_only_exception_handler(app: FastAPI) -> None:
    """Install the frozen-contract error shape on any app serving this router."""

    app.add_exception_handler(ContractOnlyError, _contract_only_exception_handler)


_auth_service = AuthService()
_collaboration_service = CollaborationService()
_text_submission_service = TextSubmissionService()
_source_retrieval_service = SourceRetrievalService()
_document_comparison_service = DocumentComparisonService()
_report_suggestion_service = ReportSuggestionService()
_merged_document_service = MergedDocumentService()
_session_close_service = SessionCloseService()
_session_retry_service = SessionRetryService()
_generation_repository = GenerationRepository()
_citation_resolver = CitationResolver()
_notification_service = NotificationService()
_profile_service = ProfileService()
_comments_service = CommentsService()
_activity_service = ActivityService()


def _file_submission_service() -> FileSubmissionService:
    """Resolve local storage at request time for explicit runtime/test isolation."""

    return FileSubmissionService(
        blob_store=LocalBlobStore(Path(os.environ.get("AXIT_BLOB_ROOT", ".axit-blobs")))
    )


def _phase3_policy() -> BrowserSecurityPolicy:
    """Load local same-origin settings without recording secrets in a DTO."""

    secure_value = os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower()
    if secure_value not in {"true", "false"}:
        raise RuntimeError("SESSION_COOKIE_SECURE must be either true or false")
    return BrowserSecurityPolicy(
        public_origin=os.environ.get("PUBLIC_ORIGIN", "http://localhost:3000"),
        public_host=os.environ.get("PUBLIC_HOST", "localhost:3000"),
        cookie_secure=secure_value == "true",
    )


def _raise_service_problem(error: Exception) -> NoReturn:
    """Map typed domain failures to stable, non-disclosing API errors."""

    if isinstance(error, (InvalidCredentialsError, SessionAuthenticationError)):
        raise ApiProblem(401, "authentication_required", "authentication is required")
    if isinstance(error, SecurityPolicyError):
        raise ApiProblem(403, "forbidden", "request is not permitted")
    if isinstance(
        error,
        (
            CollaborationHostRequiredError,
            FriendshipRequiredError,
            TextSubmissionOwnerError,
            SessionHostRequiredError,
            SessionRetryHostRequiredError,
        ),
    ):
        raise ApiProblem(403, "forbidden", "request is not permitted")
    if isinstance(
        error,
        (
            CollaborationAccessError,
            DocumentComparisonAccessError,
            FileSubmissionAccessError,
            SessionUnavailableError,
            TextSubmissionAccessError,
            SessionAccessError,
            SessionRetryAccessError,
            CitationUnavailableError,
            CitationResolverInvariantError,
            GenerationDocumentUnavailableError,
            ReportSuggestionAccessError,
            SourceRetrievalAccessError,
            UserUnavailableError,
            MergedDocumentAccessError,
        ),
    ):
        raise ApiProblem(404, "not_found", "resource is unavailable")
    if isinstance(error, EmailAlreadyRegisteredError):
        raise ApiProblem(409, "conflict", "request conflicts with current state")
    if isinstance(
        error,
        (StaleProfileVersionError, CommentReplayConflictError, MergedDocumentStaleVersionError),
    ):
        raise ApiProblem(409, "conflict", "request conflicts with current state")
    if isinstance(
        error,
        (
            FriendshipConflictError,
            FileSubmissionLimitError,
            FileSubmissionStateError,
            FriendshipStateError,
            TextSubmissionStateError,
            TextSubmissionLimitError,
            CloseBlockedError,
            CloseSessionStateError,
            ExtractionRunMissingError,
            ExtractionAnchorSchemaMismatchError,
            SessionRetryUnavailableError,
            ReportSuggestionStateError,
            TextViewerUnavailableError,
        ),
    ):
        raise ApiProblem(409, "conflict", "request conflicts with current state")
    if isinstance(error, (PermissionError, LookupError)):
        raise ApiProblem(404, "not_found", "resource is unavailable")
    if isinstance(error, ProfileInvariantError):
        raise ApiProblem(500, "internal_error", "service is temporarily unavailable")
    if isinstance(
        error,
        (
            RegistrationValidationError,
            TextSubmissionError,
            FileSubmissionValidationError,
            FileSubmissionError,
            CollaborationError,
            ValueError,
        ),
    ):
        raise ApiProblem(422, "invalid_request", "request is invalid")
    raise error


def _require_pre_auth_transport(request: Request) -> BrowserSecurityPolicy:
    policy = _phase3_policy()
    try:
        require_pre_auth_request(
            policy,
            origin=request.headers.get("Origin"),
            original_host=request.headers.get(ORIGINAL_HOST_HEADER_NAME),
        )
    except SecurityPolicyError as error:
        _raise_service_problem(error)
    return policy


def _authenticate(
    connection: psycopg.Connection[dict[str, Any]],
    request: Request,
) -> AuthenticatedSession:
    try:
        return _auth_service.authenticate(
            connection,
            session_token=request.cookies.get(_phase3_policy().cookie_name),
        )
    except SessionAuthenticationError as error:
        _raise_service_problem(error)


def _authenticated_read(
    connection: psycopg.Connection[dict[str, Any]],
    request: Request,
) -> AuthenticatedSession:
    policy = _phase3_policy()
    try:
        require_trusted_original_host(
            policy,
            request.headers.get(ORIGINAL_HOST_HEADER_NAME),
        )
    except SecurityPolicyError as error:
        _raise_service_problem(error)
    return _authenticate(connection, request)


def _authenticated_mutation(
    connection: psycopg.Connection[dict[str, Any]],
    request: Request,
) -> AuthenticatedSession:
    authenticated = _authenticate(connection, request)
    policy = _phase3_policy()
    try:
        _auth_service.require_unsafe_request(
            policy,
            authenticated,
            origin=request.headers.get("Origin"),
            original_host=request.headers.get(ORIGINAL_HOST_HEADER_NAME),
            csrf_token=request.headers.get(CSRF_HEADER_NAME),
        )
    except SecurityPolicyError as error:
        _raise_service_problem(error)
    return authenticated


def _user_response(user: UserRecord) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)


def _friend_request_response(view: FriendshipView) -> FriendRequestResponse:
    return FriendRequestResponse(
        id=view.id,
        requester=_user_response(view.requester),
        addressee=_user_response(view.addressee),
        status=FriendshipStatus(view.status),
        created_at=view.created_at,
    )


def _friend_response(view: FriendView) -> FriendResponse:
    return FriendResponse(
        user=_user_response(view.user), friendship_id=view.friendship_id
    )


def _room_response(view: RoomView) -> RoomResponse:
    return RoomResponse(
        id=view.id,
        name=view.name,
        owner_id=view.owner_id,
        role=RoomRole(view.role),
    )


def _room_member_response(view: RoomMemberView) -> RoomMemberResponse:
    return RoomMemberResponse(user=_user_response(view.user), role=RoomRole(view.role))


def _room_invitation_response(view: RoomInvitationView) -> RoomInvitationResponse:
    return RoomInvitationResponse(
        id=view.id,
        room_id=view.room_id,
        invitee_id=view.invitee_id,
        status=FriendshipStatus(view.status),
    )


def _talk_session_response(view: TalkSessionView) -> TalkSessionResponse:
    return TalkSessionResponse(
        id=view.id,
        room_id=view.room_id,
        host_id=view.host_id,
        topic=view.topic,
        description=view.description,
        deadline=view.deadline,
        state=SessionState(view.state),
        generation_epoch=view.generation_epoch,
        created_at=view.created_at,
        closed_at=view.closed_at,
    )


def _submission_response(view: SubmissionView) -> SubmissionResponse:
    return SubmissionResponse(
        id=view.id,
        session_id=view.session_id,
        author_id=view.author_id,
        kind=view.kind,
        title=view.title,
        current_revision_id=view.current_revision_id,
        processing_state=SourceProcessingState(view.processing_state),
    )


def _submission_metadata_response(
    view: SubmissionMetadataView,
) -> SubmissionMetadataResponse:
    return SubmissionMetadataResponse(
        id=view.id,
        session_id=view.session_id,
        author_id=view.author_id,
        kind=view.kind,
        title=view.title,
        current_revision_id=view.current_revision_id,
        processing_state=SourceProcessingState(view.processing_state),
        filename=view.filename,
        mime_type=view.mime_type,
        byte_size=view.byte_size,
        author=_user_response(view.author),
        created_at=view.created_at,
    )


def _source_revision_response(view: SourceRevisionView) -> SourceRevisionResponse:
    return SourceRevisionResponse(
        id=view.id,
        submission_id=view.submission_id,
        filename=view.filename,
        mime_type=view.mime_type,
        byte_size=view.byte_size,
        processing_state=SourceProcessingState(view.processing_state),
    )


def _source_anchor_response(view: TextAnchorView) -> SourceAnchor:
    return SourceAnchor.model_validate(
        {
            "id": view.id,
            "revision_id": view.revision_id,
            "exact_quote": view.exact_quote,
            **view.canonical_payload,
        }
    )


def _source_viewer_response(view: TextViewerView) -> SourceViewerResponse:
    return SourceViewerResponse(
        revision=_source_revision_response(view.revision),
        text=view.revision.source_text,
        highlighted_anchor=(
            _source_anchor_response(view.highlighted_anchor)
            if view.highlighted_anchor is not None
            else None
        ),
    )


contract_router = APIRouter(prefix="/api")


_CONTRACT_ONLY_RESPONSES: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorResponse}
}

_PHASE3_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
_PROFILE_ERROR_RESPONSES = {
    **_PHASE3_ERROR_RESPONSES,
    500: {
        "model": ErrorResponse,
        "description": "Persisted profile invariant failure.",
    },
}


@contract_router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="register",
)
def register_contract(payload: RegisterRequest, request: Request) -> UserResponse:
    _require_pre_auth_transport(request)
    with open_connection() as connection:
        try:
            user = _auth_service.register(
                connection,
                email=payload.email,
                password=payload.password,
                display_name=payload.display_name,
            )
        except (EmailAlreadyRegisteredError, RegistrationValidationError) as error:
            _raise_service_problem(error)
    return _user_response(user)


@contract_router.post(
    "/auth/login",
    response_model=UserResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="login",
)
def login_contract(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> UserResponse:
    policy = _require_pre_auth_transport(request)
    with open_connection() as connection:
        try:
            login = _auth_service.login(
                connection,
                email=payload.email,
                password=payload.password,
            )
        except (InvalidCredentialsError, SessionAuthenticationError) as error:
            _raise_service_problem(error)
    cookie = session_cookie(policy, login.session_token)
    response.set_cookie(
        key=cookie.name,
        value=cookie.value,
        max_age=cookie.max_age,
        path=cookie.path,
        secure=cookie.secure,
        httponly=cookie.httponly,
        samesite="lax",
    )
    return _user_response(login.user)


@contract_router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="logout",
)
def logout_contract(request: Request, response: Response) -> None:
    policy = _phase3_policy()
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _auth_service.logout(connection, authenticated=authenticated)
        except SessionAuthenticationError as error:
            _raise_service_problem(error)
    response.delete_cookie(
        key=policy.cookie_name,
        path="/",
        secure=policy.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@contract_router.get(
    "/me",
    response_model=UserResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getMe",
)
def get_me_contract(request: Request) -> UserResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
    return _user_response(authenticated.user)


@contract_router.get(
    "/csrf",
    response_model=CsrfResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getCsrf",
)
def get_csrf_contract(request: Request) -> CsrfResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            csrf_token = _auth_service.csrf_token_for(authenticated)
        except SessionAuthenticationError as error:
            _raise_service_problem(error)
    return CsrfResponse(csrf_token=csrf_token)


@contract_router.post(
    "/friend-requests",
    response_model=FriendRequestResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createFriendRequest",
)
def create_friend_request_contract(
    payload: FriendRequestCreate,
    request: Request,
) -> FriendRequestResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            friendship = _collaboration_service.create_friend_request(
                connection,
                actor_id=authenticated.user.id,
                addressee_id=payload.addressee_id,
            )
        except (
            CollaborationAccessError,
            CollaborationError,
            FriendshipConflictError,
            UserUnavailableError,
        ) as error:
            _raise_service_problem(error)
    return _friend_request_response(friendship)


@contract_router.get(
    "/friend-requests",
    response_model=list[FriendRequestResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listFriendRequests",
)
def list_friend_requests_contract(request: Request) -> list[FriendRequestResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        friendships = _collaboration_service.list_friend_requests(
            connection,
            actor_id=authenticated.user.id,
        )
    return [_friend_request_response(friendship) for friendship in friendships]


@contract_router.post(
    "/friend-requests/{friend_request_id}/accept",
    response_model=FriendRequestResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="acceptFriendRequest",
)
def accept_friend_request_contract(
    friend_request_id: UUID,
    request: Request,
) -> FriendRequestResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            friendship = _collaboration_service.respond_to_friend_request(
                connection,
                actor_id=authenticated.user.id,
                friendship_id=friend_request_id,
                accept=True,
            )
        except (CollaborationAccessError, FriendshipStateError) as error:
            _raise_service_problem(error)
    return _friend_request_response(friendship)


@contract_router.post(
    "/friend-requests/{friend_request_id}/reject",
    response_model=FriendRequestResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="rejectFriendRequest",
)
def reject_friend_request_contract(
    friend_request_id: UUID,
    request: Request,
) -> FriendRequestResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            friendship = _collaboration_service.respond_to_friend_request(
                connection,
                actor_id=authenticated.user.id,
                friendship_id=friend_request_id,
                accept=False,
            )
        except (CollaborationAccessError, FriendshipStateError) as error:
            _raise_service_problem(error)
    return _friend_request_response(friendship)


@contract_router.get(
    "/friends",
    response_model=list[FriendResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listFriends",
)
def list_friends_contract(request: Request) -> list[FriendResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        friends = _collaboration_service.list_friends(
            connection,
            actor_id=authenticated.user.id,
        )
    return [_friend_response(friend) for friend in friends]


# DescriptionSuggestionRequest.history의 max_length와 반드시 같아야 합니다 —
# 서버가 그 이상 history를 받을 수 없으므로 안전장치로 여기서 확정 단계로 넘어갑니다.
_DESCRIPTION_INTERVIEW_MAX_TURNS: Final = 5


@contract_router.post(
    "/projects/description-suggestions",
    response_model=DescriptionSuggestionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="suggestProjectDescriptions",
)
def suggest_project_descriptions_contract(
    payload: DescriptionSuggestionRequest, request: Request
) -> DescriptionSuggestionResponse:
    # 승인 범위: docs/provider-experiment-description-assist-amendment.md
    # 업로드된 문서나 회의 내용은 전송하지 않고, 사용자가 이 화면에 직접
    # 입력한 프로젝트명/설명 초안/인터뷰 질문-답변만 xAI로 보냅니다.
    with open_connection() as connection:
        _authenticated_mutation(connection, request)

    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        raise ApiProblem(
            503,
            "description_assist_unavailable",
            "AI 설명 제안 기능이 아직 설정되지 않았습니다.",
        )
    model = os.environ.get("GROK_MODEL", "grok-4.5").strip() or "grok-4.5"
    transport = XaiResponsesTransport(
        api_key_supplier=lambda: api_key,
        enabled=True,
        # 명확도 채점을 곁들이는 라운드는 느릴 수 있어 여유 있게 잡습니다
        # (웹 프록시의 INTERNAL_API_TIMEOUT_MS=60s보다는 작게 유지).
        timeout_seconds=50.0,
    )
    history = tuple(
        _DescriptionInterviewTurn(question=turn.question, answer=turn.answer)
        for turn in payload.history
    )
    # 라운드 수는 AI가 정보가 충분한지 스스로 판단해서 정합니다 — 서버는
    # 정해진 라운드 수를 강제하지 않습니다. 다만 두 가지 예외로 곧바로
    # 확정 단계로 넘어갑니다: (1) force_final — 사용자가 "그만 묻고 지금까지
    # 답변으로 정리해줘"를 직접 눌렀을 때, (2) history가 요청 스키마의
    # 최대치(5턴)에 도달했을 때 — 끝없이 이어지지 않도록 하는 안전장치일
    # 뿐, 평소 흐름을 끊는 정상적인 정지 조건은 아닙니다.
    try:
        if not payload.force_final and len(history) < _DESCRIPTION_INTERVIEW_MAX_TURNS:
            step = advance_description_interview(
                transport,
                title=payload.title,
                draft=payload.draft,
                history=history,
                model=model,
            )
            if not step.sufficient:
                assert step.question is not None
                return DescriptionSuggestionResponse(
                    step="question",
                    question=DescriptionSuggestionQuestion(
                        question=step.question.question,
                        options=list(step.question.options),
                        clarity=step.clarity,
                    ),
                )
        description = finalize_description(
            transport,
            title=payload.title,
            draft=payload.draft,
            history=history,
            model=model,
        )
    except GrokProviderError:
        raise ApiProblem(
            502,
            "description_assist_failed",
            "지금은 설명 제안을 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        ) from None
    return DescriptionSuggestionResponse(step="final", description=description)


@contract_router.post(
    "/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createRoom",
)
def create_room_contract(payload: RoomCreateRequest, request: Request) -> RoomResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            room = _collaboration_service.create_room(
                connection,
                actor_id=authenticated.user.id,
                name=payload.name,
            )
        except CollaborationError as error:
            _raise_service_problem(error)
    return _room_response(room)


@contract_router.get(
    "/rooms",
    response_model=list[RoomResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listRooms",
)
def list_rooms_contract(request: Request) -> list[RoomResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        rooms = _collaboration_service.list_rooms(
            connection, actor_id=authenticated.user.id
        )
    return [_room_response(room) for room in rooms]


@contract_router.get(
    "/rooms/{room_id}/members",
    response_model=list[RoomMemberResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listRoomMembers",
)
def list_room_members_contract(
    room_id: UUID,
    request: Request,
) -> list[RoomMemberResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            members = _collaboration_service.list_room_members(
                connection,
                actor_id=authenticated.user.id,
                room_id=room_id,
            )
        except CollaborationAccessError as error:
            _raise_service_problem(error)
    return [_room_member_response(member) for member in members]


@contract_router.delete(
    "/rooms/{room_id}/membership",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="leaveRoom",
)
def leave_room_contract(room_id: UUID, request: Request) -> None:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _collaboration_service.leave_room(
                connection,
                actor_id=authenticated.user.id,
                room_id=room_id,
            )
        except (CollaborationAccessError, CollaborationHostRequiredError) as error:
            _raise_service_problem(error)


@contract_router.post(
    "/rooms/{room_id}/invitations",
    response_model=RoomInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createRoomInvitation",
)
def create_room_invitation_contract(
    room_id: UUID,
    payload: RoomInvitationCreate,
    request: Request,
) -> RoomInvitationResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            invitation = _collaboration_service.create_room_invitation(
                connection,
                actor_id=authenticated.user.id,
                room_id=room_id,
                invitee_id=payload.invitee_id,
            )
        except (
            CollaborationAccessError,
            CollaborationHostRequiredError,
            FriendshipRequiredError,
            FriendshipConflictError,
            UserUnavailableError,
        ) as error:
            _raise_service_problem(error)
    return _room_invitation_response(invitation)


@contract_router.post(
    "/rooms/{room_id}/sessions",
    response_model=TalkSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createTalkSession",
)
def create_talk_session_contract(
    room_id: UUID,
    payload: TalkSessionCreateRequest,
    request: Request,
) -> TalkSessionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            talk_session = _collaboration_service.create_talk_session(
                connection,
                actor_id=authenticated.user.id,
                room_id=room_id,
                topic=payload.topic,
                description=payload.description,
                deadline=payload.deadline,
            )
        except (
            CollaborationAccessError,
            CollaborationHostRequiredError,
            CollaborationError,
        ) as error:
            _raise_service_problem(error)
    return _talk_session_response(talk_session)


@contract_router.get(
    "/rooms/{room_id}/sessions",
    response_model=list[TalkSessionResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listTalkSessions",
)
def list_talk_sessions_contract(
    room_id: UUID,
    request: Request,
) -> list[TalkSessionResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            talk_sessions = _collaboration_service.list_talk_sessions(
                connection,
                actor_id=authenticated.user.id,
                room_id=room_id,
            )
        except CollaborationAccessError as error:
            _raise_service_problem(error)
    return [_talk_session_response(talk_session) for talk_session in talk_sessions]


@contract_router.get(
    "/sessions/{session_id}",
    response_model=TalkSessionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getTalkSession",
)
def get_talk_session_contract(
    session_id: UUID, request: Request
) -> TalkSessionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            talk_session = _collaboration_service.get_talk_session(
                connection,
                actor_id=authenticated.user.id,
                session_id=session_id,
            )
        except SessionUnavailableError as error:
            _raise_service_problem(error)
    return _talk_session_response(talk_session)


@contract_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="archiveTalkSession",
)
def archive_talk_session_contract(session_id: UUID, request: Request) -> None:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _collaboration_service.archive_talk_session(
                connection,
                actor_id=authenticated.user.id,
                session_id=session_id,
            )
        except (SessionUnavailableError, CollaborationHostRequiredError) as error:
            _raise_service_problem(error)


@contract_router.post(
    "/sessions/{session_id}/submissions/text",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="submitText",
)
def submit_text_contract(
    session_id: UUID,
    payload: TextSubmissionCreate,
    request: Request,
) -> SubmissionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            submission = _text_submission_service.submit(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                title=payload.title,
                text=payload.text,
            )
        except (
            TextSubmissionAccessError,
            TextSubmissionStateError,
            TextSubmissionLimitError,
            TextSubmissionError,
        ) as error:
            _raise_service_problem(error)
    return _submission_response(submission)


@contract_router.get(
    "/sessions/{session_id}/submissions",
    response_model=list[SubmissionMetadataResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listSessionSubmissions",
)
def list_session_submissions_contract(
    session_id: UUID,
    request: Request,
) -> list[SubmissionMetadataResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            submissions = _text_submission_service.list_current(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
            )
        except TextSubmissionAccessError as error:
            _raise_service_problem(error)
    return [_submission_metadata_response(submission) for submission in submissions]


@contract_router.post(
    "/sessions/{session_id}/submissions/files",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="submitFile",
)
async def submit_file_contract(
    session_id: UUID,
    request: Request,
    title: str = Form(default="공유 자료", min_length=1, max_length=500),
    file: UploadFile = File(...),
) -> SubmissionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            if not file.filename:
                raise FileSubmissionValidationError("file metadata is required")
            submission = _file_submission_service().submit(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                title=title,
                filename=file.filename,
                declared_mime_type=file.content_type or "application/octet-stream",
                stream=file.file,
                content_length=file.size,
            )
        except FileSubmissionLimitError as error:
            if "upload limit" in str(error) or "file size" in str(error):
                raise ApiProblem(413, "file_too_large", "file exceeds the upload limit")
            _raise_service_problem(error)
        except (
            FileSubmissionAccessError,
            FileSubmissionStateError,
            FileSubmissionValidationError,
            FileSubmissionError,
        ) as error:
            _raise_service_problem(error)
        finally:
            await file.close()
    return _submission_response(submission)


@contract_router.put(
    "/submissions/{submission_id}",
    response_model=SubmissionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="replaceTextSubmission",
)
def replace_submission_contract(
    submission_id: UUID,
    payload: SubmissionReplaceRequest,
    request: Request,
) -> SubmissionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            submission = _text_submission_service.replace(
                connection,
                submission_id=submission_id,
                actor_id=authenticated.user.id,
                text=payload.text,
            )
        except (
            TextSubmissionAccessError,
            TextSubmissionOwnerError,
            TextSubmissionStateError,
            TextSubmissionError,
        ) as error:
            _raise_service_problem(error)
    return _submission_response(submission)


@contract_router.delete(
    "/submissions/{submission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="deleteSubmission",
)
def delete_submission_contract(submission_id: UUID, request: Request) -> None:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _text_submission_service.delete(
                connection,
                submission_id=submission_id,
                actor_id=authenticated.user.id,
            )
        except (
            TextSubmissionAccessError,
            TextSubmissionOwnerError,
            TextSubmissionStateError,
            TextSubmissionError,
        ) as error:
            _raise_service_problem(error)


@contract_router.get(
    "/source-revisions/{revision_id}/original",
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
            "description": "Attachment-only original source bytes.",
        },
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    operation_id="downloadSourceOriginal",
)
def download_original_contract(revision_id: UUID, request: Request) -> Response:
    service = _file_submission_service()
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            download = service.download_original(
                connection,
                revision_id=revision_id,
                actor_id=authenticated.user.id,
            )
        except (FileSubmissionAccessError, FileSubmissionError) as error:
            _raise_service_problem(error)

    def content() -> Any:
        with open_connection() as authorization_connection:
            yield from service.stream_original(
                authorization_connection,
                download=download,
                revision_id=revision_id,
                actor_id=authenticated.user.id,
            )

    encoded_name = quote(download.filename, safe="")
    return StreamingResponse(
        content(),
        media_type=download.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Content-Length": str(download.byte_size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@contract_router.post(
    "/source-revisions/{revision_id}/retry-extraction",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="retryExtraction",
)
def retry_extraction_contract(revision_id: UUID, request: Request) -> None:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _file_submission_service().retry_extraction(
                connection,
                revision_id=revision_id,
                actor_id=authenticated.user.id,
            )
        except (FileSubmissionAccessError, FileSubmissionError) as error:
            _raise_service_problem(error)


@contract_router.get(
    "/source-revisions/{revision_id}/preview",
    response_model=SourcePreviewResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getSourcePreview",
)
def get_source_preview_contract(
    revision_id: UUID, request: Request
) -> SourcePreviewResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            preview = _file_submission_service().preview_extracted_text(
                connection,
                revision_id=revision_id,
                actor_id=authenticated.user.id,
            )
        except (FileSubmissionAccessError, FileSubmissionError) as error:
            _raise_service_problem(error)
    return SourcePreviewResponse(
        revision_id=revision_id, text=preview.text, truncated=preview.truncated
    )


@contract_router.get(
    "/source-revisions/{revision_id}/viewer",
    response_model=SourceViewerResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getSourceViewer",
)
def get_source_viewer_contract(
    revision_id: UUID,
    request: Request,
    anchor: UUID | None = None,
) -> SourceViewerResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            viewer = _text_submission_service.get_viewer(
                connection,
                actor_id=authenticated.user.id,
                revision_id=revision_id,
                anchor_id=anchor,
            )
        except (TextSubmissionAccessError, TextViewerUnavailableError) as error:
            _raise_service_problem(error)
    return _source_viewer_response(viewer)


@contract_router.get(
    "/sessions/{session_id}/search",
    response_model=list[SourceSearchHitResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="searchSessionSources",
)
def search_session_sources_contract(
    session_id: UUID,
    request: Request,
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=8, ge=1, le=20),
    author_id: UUID | None = None,
    mime_type: str | None = None,
) -> list[SourceSearchHitResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            hits = _source_retrieval_service.search(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                query=q,
                limit=limit,
                author_id=author_id,
                mime_type=mime_type,
            )
        except (SourceRetrievalAccessError, ValueError) as error:
            _raise_service_problem(error)
    return [
        SourceSearchHitResponse(
            anchor_id=hit.anchor_id,
            revision_id=hit.revision_id,
            submission_id=hit.submission_id,
            title=hit.title,
            filename=hit.filename,
            mime_type=hit.mime_type,
            author_id=hit.author_id,
            text=hit.text,
            rank=hit.rank,
        )
        for hit in hits
    ]


@contract_router.get(
    "/sessions/{session_id}/comparison",
    response_model=DocumentComparisonResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="compareSessionDocuments",
)
def compare_session_documents_contract(
    session_id: UUID,
    request: Request,
    left_revision_id: UUID,
    right_revision_id: UUID,
    similarity_threshold: float = Query(default=0.72, ge=0.5, le=1),
) -> DocumentComparisonResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            comparison = _document_comparison_service.compare(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                left_revision_id=left_revision_id,
                right_revision_id=right_revision_id,
                similarity_threshold=similarity_threshold,
            )
        except (DocumentComparisonAccessError, ValueError) as error:
            _raise_service_problem(error)

    def anchor(value: Any) -> ComparisonAnchorResponse:
        return ComparisonAnchorResponse(
            anchor_id=value.anchor_id, revision_id=value.revision_id, text=value.text
        )

    return DocumentComparisonResponse(
        left_revision_id=comparison.left_revision_id,
        right_revision_id=comparison.right_revision_id,
        matches=[
            ComparisonMatchResponse(
                left=anchor(match.left),
                right=anchor(match.right),
                similarity=match.similarity,
                relation=match.relation,
            )
            for match in comparison.matches
        ],
        left_only=[anchor(value) for value in comparison.left_only],
        right_only=[anchor(value) for value in comparison.right_only],
    )


@contract_router.post(
    "/sessions/{session_id}/close",
    response_model=CloseSessionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="closeSession",
)
def close_session_contract(
    session_id: UUID,
    payload: CloseSessionRequest,
    request: Request,
) -> CloseSessionResponse:
    exclusions = tuple(
        CloseExclusionRequest(revision_id=item.revision_id, reason=item.reason)
        for item in payload.exclusions
    )
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            closed = _session_close_service.close(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                exclusions=exclusions,
                pipeline_version="phase3-text-v1",
            )
        except (
            SessionAccessError,
            SessionHostRequiredError,
            CloseBlockedError,
            CloseSessionStateError,
            ExtractionRunMissingError,
            ExtractionAnchorSchemaMismatchError,
        ) as error:
            _raise_service_problem(error)
    return CloseSessionResponse(
        snapshot_id=closed.snapshot_id,
        generation_epoch=closed.generation_epoch,
        state=SessionState(closed.state.value),
        idempotent=closed.idempotent,
    )


@contract_router.post(
    "/sessions/{session_id}/reopen",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="reopenSession",
)
def reopen_session_contract(session_id: UUID, request: Request) -> None:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            _session_close_service.reopen(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
            )
        except (
            SessionAccessError,
            SessionHostRequiredError,
            CloseSessionStateError,
        ) as error:
            _raise_service_problem(error)


@contract_router.post(
    "/sessions/{session_id}/retry",
    response_model=RetrySessionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="retrySession",
)
def retry_session_contract(session_id: UUID, request: Request) -> RetrySessionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            retried = _session_retry_service.retry(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
            )
        except (
            SessionRetryAccessError,
            SessionRetryHostRequiredError,
            SessionRetryUnavailableError,
        ) as error:
            _raise_service_problem(error)
    return RetrySessionResponse(
        snapshot_id=retried.snapshot_id,
        state=SessionState(retried.state),
    )


@contract_router.get(
    "/sessions/{session_id}/summary",
    response_model=SummaryResult,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getSessionSummary",
)
def get_summary_contract(session_id: UUID, request: Request) -> SummaryResult:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            document = _generation_repository.get_summary_for_member(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
            )
        except GenerationDocumentUnavailableError as error:
            _raise_service_problem(error)
    return SummaryResult.model_validate(document)


@contract_router.get(
    "/sessions/{session_id}/research",
    response_model=ResearchResult,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getSessionResearch",
)
def get_research_contract(session_id: UUID, request: Request) -> ResearchResult:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            document = _generation_repository.get_research_for_member(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
            )
        except GenerationDocumentUnavailableError as error:
            _raise_service_problem(error)
    return ResearchResult.model_validate(document)


@contract_router.get(
    "/sessions/{session_id}/report",
    response_model=IntegratedReportResponse,
    responses={
        **_PHASE3_ERROR_RESPONSES,
        304: {"description": "Cached report is current."},
    },
    operation_id="getSessionReport",
)
def get_integrated_report_contract(
    session_id: UUID, request: Request, response: Response
) -> IntegratedReportResponse | Response:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            summary_document = _generation_repository.get_summary_for_member(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
            research_document = _generation_repository.get_research_for_member(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
            report_identity = load_report_identity(connection, session_id=session_id)
            rag_contributions = _generation_repository.get_rag_contributions_for_member(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
            source_quality = _generation_repository.get_source_quality_for_member(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
        except GenerationDocumentUnavailableError as error:
            _raise_service_problem(error)
    summary = SummaryResult.model_validate(summary_document)
    research = ResearchResult.model_validate(research_document)
    if summary.snapshot_id != research.snapshot_id:
        raise ApiProblem(
            409, "report_snapshot_mismatch", "report artifacts are inconsistent"
        )
    if report_identity is None or report_identity.snapshot_id != summary.snapshot_id:
        raise ApiProblem(
            409, "report_snapshot_mismatch", "report artifacts are inconsistent"
        )
    content_hash = report_identity.content_hash
    etag = f'"{content_hash}"'
    cache_headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=60, must-revalidate",
        "Vary": "Cookie",
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=cache_headers)
    for name, value in cache_headers.items():
        response.headers[name] = value
    return IntegratedReportResponse(
        snapshot_id=summary.snapshot_id,
        summary=summary,
        research=research,
        rag_contributions=[RagDocumentContribution.model_validate(value) for value in rag_contributions],
        source_quality=SourceQualitySummary.model_validate(source_quality),
        content_hash=content_hash,
    )


@contract_router.get(
    "/sessions/{session_id}/merged-document",
    response_model=MergedDocumentResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getMergedDocument",
)
def get_merged_document_contract(
    session_id: UUID, request: Request
) -> MergedDocumentResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            state = _merged_document_service.get(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
        except (MergedDocumentAccessError, ValueError) as error:
            _raise_service_problem(error)
    return _merged_document_response(state)


@contract_router.put(
    "/sessions/{session_id}/merged-document",
    response_model=MergedDocumentResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="saveMergedDocument",
)
def save_merged_document_contract(
    session_id: UUID, payload: MergedDocumentSaveRequest, request: Request
) -> MergedDocumentResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            state = _merged_document_service.save(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                expected_version=payload.expected_version,
                blocks=tuple(_domain_block(block) for block in payload.blocks),
            )
        except (
            MergedDocumentAccessError,
            MergedDocumentStaleVersionError,
            ValueError,
        ) as error:
            _raise_service_problem(error)
    return _merged_document_response(state)


@contract_router.get(
    "/sessions/{session_id}/merged-document/versions",
    response_model=MergedDocumentVersionListResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listMergedDocumentVersions",
)
def list_merged_document_versions_contract(
    session_id: UUID, request: Request
) -> MergedDocumentVersionListResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            versions = _merged_document_service.list_versions(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
        except (MergedDocumentAccessError, ValueError) as error:
            _raise_service_problem(error)
    return MergedDocumentVersionListResponse(
        items=[_merged_document_version_response(version) for version in versions]
    )


@contract_router.post(
    "/sessions/{session_id}/merged-document/versions",
    response_model=MergedDocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createMergedDocumentVersion",
)
def create_merged_document_version_contract(
    session_id: UUID, payload: MergedDocumentVersionCreateRequest, request: Request
) -> MergedDocumentVersionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            version = _merged_document_service.create_version(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                label=payload.label,
            )
        except (MergedDocumentAccessError, ValueError) as error:
            _raise_service_problem(error)
    return _merged_document_version_response(version)


@contract_router.get(
    "/sessions/{session_id}/merged-document/versions/{version_id}",
    response_model=MergedDocumentVersionDetailResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getMergedDocumentVersion",
)
def get_merged_document_version_contract(
    session_id: UUID, version_id: UUID, request: Request
) -> MergedDocumentVersionDetailResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            version = _merged_document_service.get_version(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                version_id=version_id,
            )
        except (MergedDocumentAccessError, ValueError) as error:
            _raise_service_problem(error)
    blocks: list[MergedDocumentBlockWire] = []
    for block in version.blocks:
        if isinstance(block, MergedDocumentHeadingBlock):
            blocks.append(
                MergedDocumentHeadingBlockWire(
                    id=block.id, level=block.level, text=block.text, tag=block.tag
                )
            )
        else:
            blocks.append(
                MergedDocumentParagraphBlockWire(id=block.id, text=block.text, tag=block.tag)
            )
    return MergedDocumentVersionDetailResponse(
        id=version.id,
        label=version.label,
        document_version=version.document_version,
        created_by=version.created_by,
        created_at=version.created_at,
        blocks=blocks,
    )


def _merged_document_version_response(
    version: MergedDocumentVersionSnapshot,
) -> MergedDocumentVersionResponse:
    return MergedDocumentVersionResponse(
        id=version.id,
        label=version.label,
        document_version=version.document_version,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def _domain_block(block: MergedDocumentBlockWire) -> _MergedDocumentBlockDomain:
    if isinstance(block, MergedDocumentHeadingBlockWire):
        return MergedDocumentHeadingBlock(
            id=block.id, level=block.level, text=block.text, tag=block.tag
        )
    return MergedDocumentParagraphBlock(id=block.id, text=block.text, tag=block.tag)


def _merged_document_response(state: Any) -> MergedDocumentResponse:
    blocks: list[MergedDocumentBlockWire] = []
    for block in state.blocks:
        if isinstance(block, MergedDocumentHeadingBlock):
            blocks.append(
                MergedDocumentHeadingBlockWire(
                    id=block.id, level=block.level, text=block.text, tag=block.tag
                )
            )
        else:
            blocks.append(
                MergedDocumentParagraphBlockWire(id=block.id, text=block.text, tag=block.tag)
            )
    return MergedDocumentResponse(
        session_id=state.session_id,
        snapshot_id=state.snapshot_id,
        version=state.version,
        blocks=blocks,
        updated_at=state.updated_at,
    )


def _suggestion_response(value: Any) -> ReportSuggestionResponse:
    return ReportSuggestionResponse(
        id=value.id,
        session_id=value.session_id,
        author_id=value.author_id,
        source_anchor_id=value.source_anchor_id,
        target_block_id=value.target_block_id,
        snapshot_id=value.snapshot_id,
        report_content_hash=value.report_content_hash,
        kind=value.kind,
        origin=value.origin,
        suggested_text=value.suggested_text,
        rationale=value.rationale,
        status=value.status,
        resolved_by=value.resolved_by,
        created_at=value.created_at,
        resolved_at=value.resolved_at,
    )


@contract_router.get(
    "/sessions/{session_id}/suggestions",
    response_model=list[ReportSuggestionResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listReportSuggestions",
)
def list_report_suggestions_contract(
    session_id: UUID, request: Request
) -> list[ReportSuggestionResponse]:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            values = _report_suggestion_service.list(
                connection, session_id=session_id, actor_id=authenticated.user.id
            )
        except ReportSuggestionAccessError as error:
            _raise_service_problem(error)
    return [_suggestion_response(value) for value in values]


@contract_router.post(
    "/sessions/{session_id}/suggestions",
    response_model=ReportSuggestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="createReportSuggestion",
)
def create_report_suggestion_contract(
    session_id: UUID, payload: ReportSuggestionCreate, request: Request
) -> ReportSuggestionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            value = _report_suggestion_service.create(
                connection,
                session_id=session_id,
                actor_id=authenticated.user.id,
                source_anchor_id=payload.source_anchor_id,
                target_block_id=payload.target_block_id,
                kind=payload.kind,
                suggested_text=payload.suggested_text,
                rationale=payload.rationale,
            )
        except (ReportSuggestionAccessError, ValueError) as error:
            _raise_service_problem(error)
    return _suggestion_response(value)


@contract_router.post(
    "/sessions/{session_id}/grok-edit-suggestions",
    response_model=list[ReportSuggestionResponse],
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="runGrokEditTask",
)
def run_grok_edit_task_contract(
    session_id: UUID, payload: GrokEditTaskRequest, request: Request
) -> list[ReportSuggestionResponse]:
    authenticated_id: UUID
    with open_connection() as connection:
        authenticated_id = _authenticated_mutation(connection, request).user.id
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        raise ApiProblem(503, "grok_edit_unavailable", "AI 문서 수정 기능이 설정되지 않았습니다.")
    model = os.environ.get("GROK_MODEL", "grok-4.5").strip() or "grok-4.5"
    provider = GrokReportProvider(
        transport=XaiResponsesTransport(
            api_key_supplier=lambda: api_key,
            enabled=True,
            timeout_seconds=50.0,
        ),
        model=model,
    )
    try:
        with open_connection() as connection:
            values = GrokEditAgentService(provider).run(
                connection,
                session_id=session_id,
                actor_id=authenticated_id,
                instruction=payload.instruction,
            )
    except (ReportSuggestionAccessError, ReportSuggestionStateError, ValueError) as error:
        _raise_service_problem(error)
    except GrokProviderError as error:
        raise ApiProblem(
            502,
            error.code,
            "AI가 문서 수정 제안을 만들지 못했습니다. 다시 시도해주세요.",
        ) from None
    return [_suggestion_response(value) for value in values]


@contract_router.post(
    "/suggestions/{suggestion_id}/resolve",
    response_model=ReportSuggestionResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="resolveReportSuggestion",
)
def resolve_report_suggestion_contract(
    suggestion_id: UUID, payload: ReportSuggestionDecision, request: Request
) -> ReportSuggestionResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            value = _report_suggestion_service.resolve(
                connection,
                suggestion_id=suggestion_id,
                actor_id=authenticated.user.id,
                decision=payload.decision,
            )
        except (
            ReportSuggestionAccessError,
            ReportSuggestionStateError,
            ValueError,
        ) as error:
            _raise_service_problem(error)
    return _suggestion_response(value)


@contract_router.get(
    "/citations/{citation_id}/resolve",
    response_model=CitationTarget,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="resolveCitation",
)
def resolve_citation_contract(citation_id: UUID, request: Request) -> CitationTarget:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            citation = _citation_resolver.resolve(
                connection,
                citation_id=citation_id,
                actor_id=authenticated.user.id,
            )
        except (CitationUnavailableError, CitationResolverInvariantError) as error:
            _raise_service_problem(error)
    return CitationTarget(
        citation_id=citation.citation_id,
        target_type=citation.target_type,
        source_anchor_id=citation.source_anchor_id,
        source_revision_id=citation.source_revision_id,
        web_evidence_id=citation.web_evidence_id,
    )


@contract_router.get(
    "/web-evidence/{web_evidence_id}",
    response_model=WebEvidence,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="getWebEvidence",
)
def get_web_evidence_contract(web_evidence_id: UUID, request: Request) -> WebEvidence:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            evidence = _citation_resolver.resolve_web_evidence_for_member(
                connection,
                web_evidence_id=web_evidence_id,
                actor_id=authenticated.user.id,
            )
        except (CitationUnavailableError, CitationResolverInvariantError) as error:
            _raise_service_problem(error)
    snippet_hash = evidence.snippet_hash
    if not snippet_hash.startswith("sha256:"):
        snippet_hash = f"sha256:{snippet_hash}"
    return WebEvidence(
        id=evidence.id,
        url=evidence.url,
        title=evidence.title,
        domain=evidence.domain,
        accessed_at=evidence.accessed_at,
        snippet_hash=snippet_hash,
    )


@contract_router.get(
    "/source-anchors/{source_anchor_id}/resolve",
    response_model=SourceAnchorTarget,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="resolveSourceAnchor",
)
def resolve_source_anchor_contract(
    source_anchor_id: UUID, request: Request
) -> SourceAnchorTarget:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            anchor = _citation_resolver.resolve_source_anchor_for_member(
                connection,
                source_anchor_id=source_anchor_id,
                actor_id=authenticated.user.id,
            )
        except (CitationUnavailableError, CitationResolverInvariantError) as error:
            _raise_service_problem(error)
    return SourceAnchorTarget(
        source_anchor_id=anchor.id,
        source_revision_id=anchor.revision_id,
        exact_quote=anchor.exact_quote,
    )


def _preference_matrix(
    values: dict[tuple[str, str], bool],
) -> NotificationPreferenceMatrix:
    return NotificationPreferenceMatrix(
        **{
            kind: NotificationChannelSettings(
                in_app=values[(kind, "in_app")],
                email_intent=values[(kind, "email_intent")],
            )
            for kind in ("analysis_completed", "mention", "comment")
        }
    )


def _preference_values(
    matrix: NotificationPreferenceMatrix,
) -> dict[tuple[str, str], bool]:
    values: dict[tuple[str, str], bool] = {}
    for kind in ("analysis_completed", "mention", "comment"):
        channels = getattr(matrix, kind)
        values[(kind, "in_app")] = channels.in_app
        values[(kind, "email_intent")] = channels.email_intent
    assert set(values) == set(DEFAULT_PREFERENCES)
    return values


@contract_router.get(
    "/notifications",
    response_model=NotificationPageResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listNotifications",
)
def list_notifications_contract(
    request: Request,
    page_cursor: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=50, ge=1, le=100),
) -> NotificationPageResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                page, unread_count = _notification_service.list_notifications(
                    cursor,
                    recipient_id=authenticated.user.id,
                    page_cursor=page_cursor,
                    limit=limit,
                )
        except (PermissionError, ValueError) as error:
            _raise_service_problem(error)
    return NotificationPageResponse(
        items=[NotificationResponse.model_validate(item) for item in page.items],
        next_cursor=page.next_cursor,
        unread_count=unread_count,
    )


@contract_router.post(
    "/notifications/{notification_id}/read",
    response_model=ReadReceiptResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="readNotification",
)
def mark_notification_read_contract(
    notification_id: UUID, request: Request
) -> ReadReceiptResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        with connection.cursor() as cursor:
            updated = _notification_service.mark_read(
                cursor,
                recipient_id=authenticated.user.id,
                notification_id=notification_id,
            )
        if not updated:
            raise ApiProblem(404, "not_found", "resource is unavailable")
    return ReadReceiptResponse(updated_count=1)


@contract_router.post(
    "/notifications/read-all",
    response_model=ReadReceiptResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="readAllNotifications",
)
def mark_all_notifications_read_contract(request: Request) -> ReadReceiptResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        with connection.cursor() as cursor:
            updated_count = _notification_service.mark_all_read(
                cursor, recipient_id=authenticated.user.id
            )
    return ReadReceiptResponse(updated_count=updated_count)


@contract_router.get(
    "/me/email-outbox",
    response_model=EmailOutboxPageResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listMyEmailOutbox",
)
def list_my_email_outbox_contract(
    request: Request,
    page_cursor: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=50, ge=1, le=100),
) -> EmailOutboxPageResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                page = _notification_service.queued_local_outbox(
                    cursor,
                    recipient_id=authenticated.user.id,
                    page_cursor=page_cursor,
                    limit=limit,
                )
        except (PermissionError, ValueError) as error:
            _raise_service_problem(error)
    return EmailOutboxPageResponse(
        items=[
            EmailOutboxResponse(
                id=item["id"],
                notification_kind=item["notification_kind"],
                template_key=item["template_key"],
                template_data=item["template_data"],
                status=item["status"],
                created_at=item["created_at"],
                delivery_notice="로컬 큐에만 저장되었으며 외부로 발송되지 않았습니다.",
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@contract_router.get(
    "/me/profile",
    response_model=ProfileResponse,
    responses=_PROFILE_ERROR_RESPONSES,
    operation_id="getMyProfile",
)
def get_my_profile_contract(request: Request) -> ProfileResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                value = _profile_service.get_profile(
                    cursor, user_id=authenticated.user.id
                )
        except ProfileInvariantError as error:
            _raise_service_problem(error)
    return ProfileResponse.model_validate(value)


@contract_router.put(
    "/me/profile",
    response_model=ProfileUpdateResponse,
    responses=_PROFILE_ERROR_RESPONSES,
    operation_id="updateProfile",
)
def update_my_profile_contract(
    payload: ProfileUpdateRequest, request: Request
) -> ProfileUpdateResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            with connection.cursor() as cursor:
                result = _profile_service.update_profile(
                    cursor,
                    user_id=authenticated.user.id,
                    expected_version=payload.expected_version,
                    display_name=payload.display_name,
                    job_title=payload.job_title,
                    language=payload.language,
                )
                value = _profile_service.get_profile(
                    cursor, user_id=authenticated.user.id
                )
        except (StaleProfileVersionError, ProfileInvariantError, ValueError) as error:
            _raise_service_problem(error)
    return ProfileUpdateResponse(**value, updated=result.updated)


@contract_router.get(
    "/me/preferences",
    response_model=NotificationPreferencesResponse,
    responses=_PROFILE_ERROR_RESPONSES,
    operation_id="getMyNotificationPreferences",
)
def get_my_notification_preferences_contract(
    request: Request,
) -> NotificationPreferencesResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                value = _profile_service.get_preferences(
                    cursor, user_id=authenticated.user.id
                )
        except ProfileInvariantError as error:
            _raise_service_problem(error)
    return NotificationPreferencesResponse(
        values=_preference_matrix(value["values"]),
        preferences_version=value["preferences_version"],
        preferences_updated_at=value["preferences_updated_at"],
    )


@contract_router.put(
    "/me/preferences",
    response_model=NotificationPreferencesUpdateResponse,
    responses=_PROFILE_ERROR_RESPONSES,
    operation_id="updateNotificationPreferences",
)
def update_my_notification_preferences_contract(
    payload: NotificationPreferencesUpdateRequest, request: Request
) -> NotificationPreferencesUpdateResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            with connection.cursor() as cursor:
                result = _profile_service.update_preferences(
                    cursor,
                    user_id=authenticated.user.id,
                    expected_version=payload.expected_version,
                    values=_preference_values(payload.values),
                )
                value = _profile_service.get_preferences(
                    cursor, user_id=authenticated.user.id
                )
        except (StaleProfileVersionError, ProfileInvariantError, ValueError) as error:
            _raise_service_problem(error)
    return NotificationPreferencesUpdateResponse(
        values=_preference_matrix(value["values"]),
        preferences_version=value["preferences_version"],
        preferences_updated_at=value["preferences_updated_at"],
        updated=result.updated,
    )


def _comment_response(item: dict[str, Any]) -> CommentResponse:
    return CommentResponse(
        id=item["id"],
        session_id=item["session_id"],
        author_id=item["author_id"],
        version=item["version"],
        body=item["body"],
        anchor_kind=item["anchor_kind"],
        anchor_id=item["anchor_id"],
        mentioned_user_ids=list(item["mentioned_user_ids"]),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        deleted_at=item["deleted_at"],
    )


@contract_router.get(
    "/sessions/{session_id}/comments",
    response_model=CommentPageResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listSessionComments",
)
def list_session_comments_contract(
    session_id: UUID,
    request: Request,
    page_cursor: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=50, ge=1, le=100),
) -> CommentPageResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                page = _comments_service.list(
                    cursor,
                    session_id=session_id,
                    requester_id=authenticated.user.id,
                    page_cursor=page_cursor,
                    limit=limit,
                )
        except (PermissionError, ValueError) as error:
            _raise_service_problem(error)
    return CommentPageResponse(
        items=[_comment_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@contract_router.post(
    "/sessions/{session_id}/comments",
    response_model=CommentMutationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_PHASE3_ERROR_RESPONSES,
        status.HTTP_200_OK: {
            "model": CommentMutationResponse,
            "description": "Idempotent replay of the canonical comment.",
        },
    },
    operation_id="createComment",
)
def create_session_comment_contract(
    session_id: UUID,
    payload: CommentCreateRequest,
    request: Request,
    response: Response,
) -> CommentMutationResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            with connection.cursor() as cursor:
                result = _comments_service.create(
                    cursor,
                    session_id=session_id,
                    author_id=authenticated.user.id,
                    client_request_id=payload.client_request_id,
                    body=payload.body,
                    anchor_kind=cast(
                        Literal["report", "generated_segment"] | None,
                        payload.anchor_kind,
                    ),
                    anchor_id=payload.anchor_id,
                    mentioned_user_ids=tuple(payload.mentioned_user_ids),
                )
        except (PermissionError, CommentReplayConflictError, ValueError) as error:
            _raise_service_problem(error)
    if result.idempotent:
        response.status_code = status.HTTP_200_OK
    return CommentMutationResponse(
        id=result.id, version=result.version, idempotent=result.idempotent
    )


@contract_router.put(
    "/comments/{comment_id}",
    response_model=CommentMutationResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="updateComment",
)
def update_comment_contract(
    comment_id: UUID, payload: CommentUpdateRequest, request: Request
) -> CommentMutationResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            with connection.cursor() as cursor:
                session_id = resolve_visible_comment_session(
                    cursor,
                    comment_id=comment_id,
                    requester_id=authenticated.user.id,
                )
                result = _comments_service.update(
                    cursor,
                    session_id=session_id,
                    actor_id=authenticated.user.id,
                    comment_id=comment_id,
                    expected_version=payload.expected_version,
                    body=payload.body,
                    anchor_kind=cast(
                        Literal["report", "generated_segment"] | None,
                        payload.anchor_kind,
                    ),
                    anchor_id=payload.anchor_id,
                    mentioned_user_ids=tuple(payload.mentioned_user_ids),
                )
        except (PermissionError, CommentReplayConflictError, ValueError) as error:
            _raise_service_problem(error)
    return CommentMutationResponse(
        id=result.id, version=result.version, idempotent=result.idempotent
    )


@contract_router.delete(
    "/comments/{comment_id}",
    response_model=CommentMutationResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="deleteComment",
)
def delete_comment_contract(
    comment_id: UUID, payload: CommentDeleteRequest, request: Request
) -> CommentMutationResponse:
    with open_connection() as connection:
        authenticated = _authenticated_mutation(connection, request)
        try:
            with connection.cursor() as cursor:
                session_id = resolve_visible_comment_session(
                    cursor,
                    comment_id=comment_id,
                    requester_id=authenticated.user.id,
                )
                result = _comments_service.delete(
                    cursor,
                    session_id=session_id,
                    actor_id=authenticated.user.id,
                    comment_id=comment_id,
                    expected_version=payload.expected_version,
                )
        except (PermissionError, CommentReplayConflictError, ValueError) as error:
            _raise_service_problem(error)
    return CommentMutationResponse(
        id=result.id, version=result.version, idempotent=result.idempotent
    )


@contract_router.get(
    "/audit-events",
    response_model=AuditEventPageResponse,
    responses=_PHASE3_ERROR_RESPONSES,
    operation_id="listAuditEvents",
)
def list_audit_events_contract(
    request: Request,
    scope: AuditScope = AuditScope.ALL,
    scope_id: UUID | None = None,
    page_cursor: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=50, ge=1, le=100),
) -> AuditEventPageResponse:
    with open_connection() as connection:
        authenticated = _authenticated_read(connection, request)
        try:
            with connection.cursor() as cursor:
                page = _activity_service.list(
                    cursor,
                    requester_id=authenticated.user.id,
                    scope=scope.value,
                    scope_id=scope_id,
                    page_cursor=page_cursor,
                    limit=limit,
                )
        except (PermissionError, ValueError) as error:
            _raise_service_problem(error)
    fields = set(AuditEventResponse.model_fields)
    return AuditEventPageResponse(
        coverage_started_at=page.coverage_started_at,
        items=[
            AuditEventResponse.model_validate({key: item[key] for key in fields})
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


contract_app = FastAPI(
    title="AXit Meeting RAG API",
    version="0.1.0-phase2",
    description="Frozen Phase 2 durable-core wire contract.",
)
install_contract_only_exception_handler(contract_app)
contract_app.include_router(contract_router)

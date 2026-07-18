"""Phase 2 wire contracts and the contract-only FastAPI surface.

These Pydantic models are the source of truth for generated JSON Schema,
OpenAPI, and the checked TypeScript client.  The contract application is kept
separate from the disposable Phase 0 transport harness so freezing a schema
does not accidentally claim that a Phase 3 business endpoint already exists.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, NoReturn
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, FastAPI, File, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel, model_validator


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


AnchorLocator = (
    TextLineLocator
    | PdfBlockLocator
    | ImageBBoxLocator
    | HwpParagraphLocator
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
            (self.kind is AnchorKind.TEXT_LINE and isinstance(self.locator, TextLineLocator))
            or (self.kind is AnchorKind.PDF_BLOCK and isinstance(self.locator, PdfBlockLocator))
            or (self.kind is AnchorKind.IMAGE_BBOX and isinstance(self.locator, ImageBBoxLocator))
            or (
                self.kind is AnchorKind.HWP_PARAGRAPH
                and isinstance(self.locator, HwpParagraphLocator)
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
            raise ValueError("web evidence domain must equal the normalized URL hostname")
        return self


class ResearchItem(_WireModel):
    text: str = Field(min_length=1, max_length=10_000)
    web_evidence_ids: list[UUID] = Field(min_length=1, max_length=50)


class FactCheckItem(_WireModel):
    source_anchor_id: UUID
    source_claim_quote: str = Field(min_length=1, max_length=20_000)
    verdict: FactCheckVerdict
    explanation: str = Field(min_length=1, max_length=10_000)
    web_evidence_ids: list[UUID] = Field(min_length=1, max_length=50)


class ResearchResult(_WireModel):
    snapshot_id: UUID
    topic_items: list[ResearchItem] = Field(default_factory=list, max_length=100)
    fact_checks: list[FactCheckItem] = Field(default_factory=list, max_length=100)


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
    password: str = Field(min_length=12, max_length=1_024)
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


class FriendResponse(_WireModel):
    user: UserResponse
    friendship_id: UUID


class RoomCreateRequest(_WireModel):
    name: str = Field(min_length=1, max_length=240)


class RoomResponse(_WireModel):
    id: UUID
    name: str = Field(min_length=1, max_length=240)
    owner_id: UUID
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


class TextSubmissionCreate(_WireModel):
    text: str = Field(min_length=1, max_length=100_000)


class SubmissionResponse(_WireModel):
    id: UUID
    session_id: UUID
    author_id: UUID
    kind: Literal["text", "file"]
    current_revision_id: UUID
    processing_state: SourceProcessingState


class SubmissionReplaceRequest(_WireModel):
    text: str = Field(min_length=1, max_length=100_000)


class SourceRevisionResponse(_WireModel):
    id: UUID
    submission_id: UUID
    filename: str = Field(min_length=1, max_length=1_024)
    mime_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0, le=20 * 1024 * 1024)
    processing_state: SourceProcessingState


class SourceViewerResponse(_WireModel):
    revision: SourceRevisionResponse
    highlighted_anchor: SourceAnchor | None = None


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


contract_router = APIRouter(prefix="/api")


_CONTRACT_ONLY_RESPONSES: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorResponse}
}


@contract_router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="register",
)
def register_contract(request: RegisterRequest) -> UserResponse:
    del request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/auth/login",
    response_model=UserResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="login",
)
def login_contract(request: LoginRequest) -> UserResponse:
    del request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="logout",
)
def logout_contract() -> None:
    _not_implemented()


@contract_router.get(
    "/me",
    response_model=UserResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="getMe",
)
def get_me_contract() -> UserResponse:
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/csrf",
    response_model=CsrfResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="getCsrf",
)
def get_csrf_contract() -> CsrfResponse:
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/friend-requests",
    response_model=FriendRequestResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="createFriendRequest",
)
def create_friend_request_contract(request: FriendRequestCreate) -> FriendRequestResponse:
    del request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/friend-requests/{friend_request_id}/accept",
    response_model=FriendRequestResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="acceptFriendRequest",
)
def accept_friend_request_contract(friend_request_id: UUID) -> FriendRequestResponse:
    del friend_request_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/friend-requests/{friend_request_id}/reject",
    response_model=FriendRequestResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="rejectFriendRequest",
)
def reject_friend_request_contract(friend_request_id: UUID) -> FriendRequestResponse:
    del friend_request_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/friends",
    response_model=list[FriendResponse],
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="listFriends",
)
def list_friends_contract() -> list[FriendResponse]:
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="createRoom",
)
def create_room_contract(request: RoomCreateRequest) -> RoomResponse:
    del request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/rooms",
    response_model=list[RoomResponse],
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="listRooms",
)
def list_rooms_contract() -> list[RoomResponse]:
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/rooms/{room_id}/invitations",
    response_model=RoomInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="createRoomInvitation",
)
def create_room_invitation_contract(
    room_id: UUID,
    request: RoomInvitationCreate,
) -> RoomInvitationResponse:
    del room_id, request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/rooms/{room_id}/sessions",
    response_model=TalkSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="createTalkSession",
)
def create_talk_session_contract(
    room_id: UUID,
    request: TalkSessionCreateRequest,
) -> TalkSessionResponse:
    del room_id, request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/sessions/{session_id}",
    response_model=TalkSessionResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="getTalkSession",
)
def get_talk_session_contract(session_id: UUID) -> TalkSessionResponse:
    del session_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/sessions/{session_id}/submissions/text",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="submitText",
)
def submit_text_contract(
    session_id: UUID,
    request: TextSubmissionCreate,
) -> SubmissionResponse:
    del session_id, request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/sessions/{session_id}/submissions/files",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="submitFile",
)
async def submit_file_contract(
    session_id: UUID,
    file: UploadFile = File(...),
) -> SubmissionResponse:
    del session_id, file
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.put(
    "/submissions/{submission_id}",
    response_model=SubmissionResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="replaceTextSubmission",
)
def replace_submission_contract(
    submission_id: UUID,
    request: SubmissionReplaceRequest,
) -> SubmissionResponse:
    del submission_id, request
    _not_implemented()
    raise AssertionError("unreachable")


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
        501: {"model": ErrorResponse},
    },
    operation_id="downloadSourceOriginal",
)
def download_original_contract(revision_id: UUID) -> Response:
    del revision_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/source-revisions/{revision_id}/viewer",
    response_model=SourceViewerResponse,
    responses=_CONTRACT_ONLY_RESPONSES,
    operation_id="getSourceViewer",
)
def get_source_viewer_contract(
    revision_id: UUID,
    anchor: UUID | None = None,
) -> SourceViewerResponse:
    del revision_id, anchor
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/sessions/{session_id}/close",
    response_model=CloseSessionResponse,
    responses={501: {"model": ErrorResponse}},
    operation_id="closeSession",
)
def close_session_contract(session_id: UUID, request: CloseSessionRequest) -> CloseSessionResponse:
    del session_id, request
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.post(
    "/sessions/{session_id}/retry",
    response_model=RetrySessionResponse,
    responses={501: {"model": ErrorResponse}},
    operation_id="retrySession",
)
def retry_session_contract(session_id: UUID) -> RetrySessionResponse:
    del session_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/sessions/{session_id}/summary",
    response_model=SummaryResult,
    responses={501: {"model": ErrorResponse}},
    operation_id="getSessionSummary",
)
def get_summary_contract(session_id: UUID) -> SummaryResult:
    del session_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/sessions/{session_id}/research",
    response_model=ResearchResult,
    responses={501: {"model": ErrorResponse}},
    operation_id="getSessionResearch",
)
def get_research_contract(session_id: UUID) -> ResearchResult:
    del session_id
    _not_implemented()
    raise AssertionError("unreachable")


@contract_router.get(
    "/citations/{citation_id}/resolve",
    response_model=CitationTarget,
    responses={501: {"model": ErrorResponse}},
    operation_id="resolveCitation",
)
def resolve_citation_contract(citation_id: UUID) -> CitationTarget:
    del citation_id
    _not_implemented()
    raise AssertionError("unreachable")


contract_app = FastAPI(
    title="AXit Meeting RAG API",
    version="0.1.0-phase2",
    description="Frozen Phase 2 durable-core wire contract.",
)
install_contract_only_exception_handler(contract_app)
contract_app.include_router(contract_router)

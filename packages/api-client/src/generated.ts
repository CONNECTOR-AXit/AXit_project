/*
 * GENERATED FILE — do not edit by hand.
 * Source: tools/generate_contracts.py and app.contracts.
 */

export const apiContractVersion = "0.1.0-phase2" as const;

export type AnchorKind = "text_line" | "pdf_block" | "image_bbox" | "hwp_paragraph";
export type Body_submitFile = { "file": string };
export type CitationTarget = { "citation_id": string; "source_anchor_id"?: string | null; "source_revision_id"?: string | null; "target_type": "source_anchor" | "web_evidence"; "web_evidence_id"?: string | null };
export type CloseSessionRequest = { "exclusions"?: Array<RevisionExclusion> };
export type CloseSessionResponse = { "generation_epoch": number; "idempotent": boolean; "snapshot_id": string; "state": SessionState };
export type CsrfResponse = { "csrf_token": string };
export type ErrorResponse = { "code": string; "detail": string };
export type FactCheckItem = { "explanation": string; "source_anchor_id": string; "source_claim_quote": string; "verdict": FactCheckVerdict; "web_evidence_ids": Array<string> };
export type FactCheckVerdict = "supported" | "refuted" | "mixed" | "unverifiable";
export type FriendRequestCreate = { "addressee_id": string };
export type FriendRequestResponse = { "addressee": UserResponse; "id": string; "requester": UserResponse; "status": FriendshipStatus };
export type FriendResponse = { "friendship_id": string; "user": UserResponse };
export type FriendshipStatus = "pending" | "accepted" | "rejected";
export type HTTPValidationError = { "detail"?: Array<ValidationError> };
export type HwpFootnotePath = { "index": number; "paragraph": number };
export type HwpParagraphLocator = { "footnote"?: HwpFootnotePath | null; "paragraph": number; "parser": string; "parser_version": string; "section": number; "table"?: HwpTablePath | null };
export type HwpTablePath = { "block": number; "cell": number; "index": number; "paragraph": number; "row": number };
export type ImageBBoxLocator = { "bbox": NormalizedBoundingBox; "image_id": string };
export type LoginRequest = { "email": string; "password": string };
export type NormalizedBoundingBox = Array<number>;
export type PdfBlockLocator = { "bbox": NormalizedBoundingBox; "block_id": string; "page": number };
export type RegisterRequest = { "display_name": string; "email": string; "password": string };
export type ResearchItem = { "text": string; "web_evidence_ids": Array<string> };
export type ResearchResult = { "fact_checks"?: Array<FactCheckItem>; "snapshot_id": string; "topic_items"?: Array<ResearchItem> };
export type RetrySessionResponse = { "snapshot_id": string; "state": SessionState };
export type RevisionExclusion = { "reason": string; "revision_id": string };
export type RoomCreateRequest = { "name": string };
export type RoomInvitationCreate = { "invitee_id": string };
export type RoomInvitationResponse = { "id": string; "invitee_id": string; "room_id": string; "status": FriendshipStatus };
export type RoomResponse = { "id": string; "name": string; "owner_id": string; "role": RoomRole };
export type RoomRole = "host" | "member";
export type SessionState = "draft" | "open" | "closed" | "processing" | "ready" | "needs_attention";
export type SourceAnchor = { "exact_quote": string; "extraction_profile_hash": string; "id": string; "kind": AnchorKind; "locator": TextLineLocator | PdfBlockLocator | ImageBBoxLocator | HwpParagraphLocator; "revision_id": string; "schema_version": 1; "source_sha256": string; "text_fingerprint": string };
export type SourceProcessingState = "uploaded" | "queued" | "extracting" | "ready" | "failed";
export type SourceRevisionResponse = { "byte_size": number; "filename": string; "id": string; "mime_type": string; "processing_state": SourceProcessingState; "submission_id": string };
export type SourceViewerResponse = { "highlighted_anchor"?: SourceAnchor | null; "revision": SourceRevisionResponse };
export type SubmissionReplaceRequest = { "text": string };
export type SubmissionResponse = { "author_id": string; "current_revision_id": string; "id": string; "kind": "text" | "file"; "processing_state": SourceProcessingState; "session_id": string };
export type SummaryItem = { "source_anchor_ids": Array<string>; "supports": Array<SummarySupport>; "text": string };
export type SummaryResult = { "sections": Array<SummarySection>; "snapshot_id": string };
export type SummarySection = { "heading": string; "items": Array<SummaryItem> };
export type SummarySupport = { "citation_id": string; "end": number; "exact_quote": string; "source_anchor_id": string; "start": number };
export type TalkSessionCreateRequest = { "deadline"?: string | null; "description"?: string; "topic": string };
export type TalkSessionResponse = { "deadline"?: string | null; "description": string; "generation_epoch": number; "host_id": string; "id": string; "room_id": string; "state": SessionState; "topic": string };
export type TextLineLocator = { "end": number; "line": number; "start": number };
export type TextSubmissionCreate = { "text": string };
export type UserResponse = { "display_name": string; "email": string; "id": string };
export type ValidationError = { "ctx"?: Record<string, unknown>; "input"?: unknown; "loc": Array<string | number>; "msg": string; "type": string };

export const operations = {
  "login": { method: "POST", path: "/api/auth/login" },
  "logout": { method: "POST", path: "/api/auth/logout" },
  "register": { method: "POST", path: "/api/auth/register" },
  "resolveCitation": { method: "GET", path: "/api/citations/{citation_id}/resolve" },
  "getCsrf": { method: "GET", path: "/api/csrf" },
  "createFriendRequest": { method: "POST", path: "/api/friend-requests" },
  "acceptFriendRequest": { method: "POST", path: "/api/friend-requests/{friend_request_id}/accept" },
  "rejectFriendRequest": { method: "POST", path: "/api/friend-requests/{friend_request_id}/reject" },
  "listFriends": { method: "GET", path: "/api/friends" },
  "getMe": { method: "GET", path: "/api/me" },
  "listRooms": { method: "GET", path: "/api/rooms" },
  "createRoom": { method: "POST", path: "/api/rooms" },
  "createRoomInvitation": { method: "POST", path: "/api/rooms/{room_id}/invitations" },
  "createTalkSession": { method: "POST", path: "/api/rooms/{room_id}/sessions" },
  "getTalkSession": { method: "GET", path: "/api/sessions/{session_id}" },
  "closeSession": { method: "POST", path: "/api/sessions/{session_id}/close" },
  "getSessionResearch": { method: "GET", path: "/api/sessions/{session_id}/research" },
  "retrySession": { method: "POST", path: "/api/sessions/{session_id}/retry" },
  "submitFile": { method: "POST", path: "/api/sessions/{session_id}/submissions/files" },
  "submitText": { method: "POST", path: "/api/sessions/{session_id}/submissions/text" },
  "getSessionSummary": { method: "GET", path: "/api/sessions/{session_id}/summary" },
  "downloadSourceOriginal": { method: "GET", path: "/api/source-revisions/{revision_id}/original" },
  "getSourceViewer": { method: "GET", path: "/api/source-revisions/{revision_id}/viewer" },
  "replaceTextSubmission": { method: "PUT", path: "/api/submissions/{submission_id}" },
} as const;

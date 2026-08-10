/*
 * GENERATED FILE — do not edit by hand.
 * Source: tools/generate_contracts.py and app.contracts.
 */

export const apiContractVersion = "0.1.0-phase2" as const;

export type AnchorKind = "text_line" | "pdf_block" | "image_bbox" | "hwp_paragraph" | "docx_paragraph" | "xlsx_cell";
export type AuditEventPageResponse = { "coverage_started_at": string; "items": Array<AuditEventResponse>; "next_cursor": string | null };
export type AuditEventResponse = { "actor_display_name": string | null; "actor_id": string | null; "audience_user_id": string | null; "created_at": string; "entity_id": string; "entity_type": string; "event_type": string; "id": string; "ledger_sequence": number; "metadata_json": Record<string, unknown>; "room_id": string | null; "scope_type": "personal" | "room" | "session"; "session_id": string | null };
export type AuditScope = "all" | "personal" | "room" | "session";
export type Body_submitFile = { "file": string; "title"?: string };
export type CitationTarget = { "citation_id": string; "source_anchor_id"?: string | null; "source_revision_id"?: string | null; "target_type": "source_anchor" | "web_evidence"; "web_evidence_id"?: string | null };
export type CloseSessionRequest = { "exclusions"?: Array<RevisionExclusion> };
export type CloseSessionResponse = { "generation_epoch": number; "idempotent": boolean; "snapshot_id": string; "state": SessionState };
export type CommentAnchorKind = "report" | "generated_segment";
export type CommentCreateRequest = { "anchor_id"?: string | null; "anchor_kind"?: CommentAnchorKind | null; "body": string; "client_request_id": string; "mentioned_user_ids"?: Array<string> };
export type CommentDeleteRequest = { "expected_version": number };
export type CommentMutationResponse = { "id": string; "idempotent": boolean; "version": number };
export type CommentPageResponse = { "items": Array<CommentResponse>; "next_cursor": string | null };
export type CommentResponse = { "anchor_id": string | null; "anchor_kind": CommentAnchorKind | null; "author_id": string; "body": string; "created_at": string; "deleted_at": string | null; "id": string; "mentioned_user_ids": Array<string>; "session_id": string; "updated_at": string; "version": number };
export type CommentUpdateRequest = { "anchor_id"?: string | null; "anchor_kind"?: CommentAnchorKind | null; "body": string; "expected_version": number; "mentioned_user_ids"?: Array<string> };
export type ComparisonAnchorResponse = { "anchor_id": string; "revision_id": string; "text": string };
export type ComparisonMatchResponse = { "left": ComparisonAnchorResponse; "relation": "duplicate" | "similar"; "right": ComparisonAnchorResponse; "similarity": number };
export type CsrfResponse = { "csrf_token": string };
export type DescriptionInterviewTurn = { "answer": string; "question": string };
export type DescriptionSuggestionQuestion = { "clarity": number; "options": Array<string>; "question": string };
export type DescriptionSuggestionRequest = { "draft"?: string; "force_final"?: boolean; "history"?: Array<DescriptionInterviewTurn>; "title": string };
export type DescriptionSuggestionResponse = { "description"?: string | null; "question"?: DescriptionSuggestionQuestion | null; "step": "question" | "final" };
export type DocumentComparisonResponse = { "left_only": Array<ComparisonAnchorResponse>; "left_revision_id": string; "matches": Array<ComparisonMatchResponse>; "right_only": Array<ComparisonAnchorResponse>; "right_revision_id": string };
export type DocxParagraphLocator = { "paragraph": number; "table"?: DocxTablePath | null };
export type DocxTablePath = { "cell": number; "index": number; "paragraph": number; "row": number };
export type EmailOutboxPageResponse = { "items": Array<EmailOutboxResponse>; "next_cursor": string | null };
export type EmailOutboxResponse = { "created_at": string; "delivery_notice": "로컬 큐에만 저장되었으며 외부로 발송되지 않았습니다."; "id": string; "notification_kind": NotificationKind; "status": "queued_local"; "template_data": Record<string, unknown>; "template_key": string };
export type ErrorResponse = { "code": string; "detail": string };
export type FactCheckItem = { "explanation": string; "source_anchor_id": string; "source_claim_quote": string; "verdict": FactCheckVerdict; "web_evidence_ids"?: Array<string> };
export type FactCheckVerdict = "supported" | "refuted" | "mixed" | "unverifiable";
export type FriendRequestCreate = { "addressee_id": string };
export type FriendRequestResponse = { "addressee": UserResponse; "created_at": string; "id": string; "requester": UserResponse; "status": FriendshipStatus };
export type FriendResponse = { "friendship_id": string; "user": UserResponse };
export type FriendshipStatus = "pending" | "accepted" | "rejected";
export type GrokEditTaskRequest = { "instruction": string };
export type HTTPValidationError = { "detail"?: Array<ValidationError> };
export type HwpFootnotePath = { "index": number; "paragraph": number };
export type HwpParagraphLocator = { "footnote"?: HwpFootnotePath | null; "paragraph": number; "parser": string; "parser_version": string; "section": number; "table"?: HwpTablePath | null };
export type HwpTablePath = { "block": number; "cell": number; "index": number; "paragraph": number; "row": number };
export type ImageBBoxLocator = { "bbox": NormalizedBoundingBox; "image_id": string };
export type IntegratedReportResponse = { "content_hash": string; "rag_contributions"?: Array<RagDocumentContribution>; "research": ResearchResult; "snapshot_id": string; "source_quality": SourceQualitySummary; "summary": SummaryResult };
export type LoginRequest = { "email": string; "password": string };
export type MergedDocumentHeadingBlockWire = { "id": string; "level": 1 | 2 | 3; "tag"?: string | null; "text": string; "type"?: "heading" };
export type MergedDocumentParagraphBlockWire = { "id": string; "tag"?: string | null; "text": string; "type"?: "paragraph" };
export type MergedDocumentResponse = { "blocks": Array<MergedDocumentHeadingBlockWire | MergedDocumentParagraphBlockWire>; "session_id": string; "snapshot_id": string; "updated_at"?: string | null; "version": number };
export type MergedDocumentSaveRequest = { "blocks": Array<MergedDocumentHeadingBlockWire | MergedDocumentParagraphBlockWire>; "expected_version": number };
export type MergedDocumentVersionCreateRequest = { "label": string };
export type MergedDocumentVersionDetailResponse = { "blocks": Array<MergedDocumentHeadingBlockWire | MergedDocumentParagraphBlockWire>; "created_at": string; "created_by": string; "document_version": number; "id": string; "label": string };
export type MergedDocumentVersionListResponse = { "items": Array<MergedDocumentVersionResponse> };
export type MergedDocumentVersionResponse = { "created_at": string; "created_by": string; "document_version": number; "id": string; "label": string };
export type NormalizedBoundingBox = Array<number>;
export type NotificationActionKind = "respond_friend_request" | "open_room" | "open_session" | "open_comment" | "none";
export type NotificationChannelSettings = { "email_intent": boolean; "in_app": boolean };
export type NotificationKind = "analysis_completed" | "mention" | "comment" | "friend_request" | "room_member_added";
export type NotificationPageResponse = { "items": Array<NotificationResponse>; "next_cursor": string | null; "unread_count": number };
export type NotificationPreferenceMatrix = { "analysis_completed": NotificationChannelSettings; "comment": NotificationChannelSettings; "mention": NotificationChannelSettings };
export type NotificationPreferencesResponse = { "preferences_updated_at": string; "preferences_version": number; "values": NotificationPreferenceMatrix };
export type NotificationPreferencesUpdateRequest = { "expected_version": number; "values": NotificationPreferenceMatrix };
export type NotificationPreferencesUpdateResponse = { "preferences_updated_at": string; "preferences_version": number; "updated": boolean; "values": NotificationPreferenceMatrix };
export type NotificationResourceType = "friend_request" | "room" | "session" | "comment";
export type NotificationResponse = { "action_kind": NotificationActionKind; "actor_id": string | null; "body": string; "created_at": string; "href": string; "id": string; "kind": NotificationKind; "read_at": string | null; "resource_id": string; "resource_type": NotificationResourceType; "title": string };
export type PdfBlockLocator = { "bbox": NormalizedBoundingBox; "block_id": string; "page": number };
export type ProfileResponse = { "display_name": string; "email": string; "job_title": string | null; "language": "ko" | "en" | "ja"; "profile_updated_at": string; "profile_version": number; "user_id": string };
export type ProfileUpdateRequest = { "display_name": string; "expected_version": number; "job_title"?: string | null; "language": "ko" | "en" | "ja" };
export type ProfileUpdateResponse = { "display_name": string; "email": string; "job_title": string | null; "language": "ko" | "en" | "ja"; "profile_updated_at": string; "profile_version": number; "updated": boolean; "user_id": string };
export type RagDocumentContribution = { "document_id": string; "rag_unit_count": number; "revision_id": string; "title": string; "used_anchor_ids"?: Array<string>; "used_rag_unit_count": number };
export type ReadReceiptResponse = { "updated_count": number };
export type RegisterRequest = { "display_name": string; "email": string; "password": string };
export type ReportSuggestionCreate = { "kind"?: "add" | "edit" | "remove"; "rationale"?: string; "source_anchor_id"?: string | null; "suggested_text": string; "target_block_id"?: string | null };
export type ReportSuggestionDecision = { "decision": "accepted" | "rejected" };
export type ReportSuggestionResponse = { "author_id": string; "created_at": string; "id": string; "kind": "add" | "edit" | "remove"; "origin": "member" | "automatic_comparison"; "rationale": string; "report_content_hash": string; "resolved_at"?: string | null; "resolved_by"?: string | null; "session_id": string; "snapshot_id": string; "source_anchor_id"?: string | null; "status": "open" | "accepted" | "rejected"; "suggested_text": string; "target_block_id"?: string | null };
export type ResearchItem = { "text": string; "web_evidence_ids": Array<string> };
export type ResearchResult = { "fact_checks"?: Array<FactCheckItem>; "snapshot_id": string; "topic_items"?: Array<ResearchItem> };
export type RetrySessionResponse = { "snapshot_id": string; "state": SessionState };
export type RevisionExclusion = { "reason": string; "revision_id": string };
export type RoomCreateRequest = { "name": string };
export type RoomInvitationCreate = { "invitee_id": string };
export type RoomInvitationResponse = { "id": string; "invitee_id": string; "room_id": string; "status": FriendshipStatus };
export type RoomMemberResponse = { "role": RoomRole; "user": UserResponse };
export type RoomResponse = { "id": string; "name": string; "owner_id": string; "role": RoomRole };
export type RoomRole = "host" | "member";
export type SessionState = "draft" | "open" | "closed" | "processing" | "ready" | "needs_attention";
export type SourceAnchor = { "exact_quote": string; "extraction_profile_hash": string; "id": string; "kind": AnchorKind; "locator": TextLineLocator | PdfBlockLocator | ImageBBoxLocator | HwpParagraphLocator | DocxParagraphLocator | XlsxCellLocator; "revision_id": string; "schema_version": 1; "source_sha256": string; "text_fingerprint": string };
export type SourceAnchorTarget = { "exact_quote": string; "source_anchor_id": string; "source_revision_id": string };
export type SourcePreviewResponse = { "revision_id": string; "text": string; "truncated": boolean };
export type SourceProcessingState = "uploaded" | "queued" | "extracting" | "ready" | "failed";
export type SourceQualitySummary = { "accepted_anchor_count": number; "excluded_anchor_count": number; "reason_counts"?: Record<string, unknown>; "status": "clean" | "filtered"; "total_anchor_count": number };
export type SourceRevisionResponse = { "byte_size": number; "filename": string; "id": string; "mime_type": string; "processing_state": SourceProcessingState; "submission_id": string };
export type SourceSearchHitResponse = { "anchor_id": string; "author_id": string; "filename": string; "mime_type": string; "rank": number; "revision_id": string; "submission_id": string; "text": string; "title": string };
export type SourceViewerResponse = { "highlighted_anchor"?: SourceAnchor | null; "revision": SourceRevisionResponse; "text": string };
export type SubmissionMetadataResponse = { "author": UserResponse; "author_id": string; "byte_size": number; "created_at": string; "current_revision_id": string; "filename": string; "id": string; "kind": "text" | "file"; "mime_type": string; "processing_state": SourceProcessingState; "session_id": string; "title": string };
export type SubmissionReplaceRequest = { "text": string };
export type SubmissionResponse = { "author_id": string; "current_revision_id": string; "id": string; "kind": "text" | "file"; "processing_state": SourceProcessingState; "session_id": string; "title": string };
export type SummaryItem = { "source_anchor_ids": Array<string>; "supports": Array<SummarySupport>; "text": string };
export type SummaryResult = { "sections": Array<SummarySection>; "snapshot_id": string };
export type SummarySection = { "heading": string; "items": Array<SummaryItem> };
export type SummarySupport = { "citation_id": string; "end": number; "exact_quote": string; "source_anchor_id": string; "start": number };
export type TalkSessionCreateRequest = { "deadline"?: string | null; "description"?: string; "topic": string };
export type TalkSessionResponse = { "closed_at": string | null; "created_at": string; "deadline"?: string | null; "description": string; "generation_epoch": number; "host_id": string; "id": string; "room_id": string; "state": SessionState; "topic": string };
export type TextLineLocator = { "end": number; "line": number; "start": number };
export type TextSubmissionCreate = { "text": string; "title"?: string };
export type UserResponse = { "display_name": string; "email": string; "id": string };
export type ValidationError = { "ctx"?: Record<string, unknown>; "input"?: unknown; "loc": Array<string | number>; "msg": string; "type": string };
export type WebEvidence = { "accessed_at": string; "domain": string; "id": string; "snippet_hash": string; "title": string; "url": string };
export type XlsxCellLocator = { "cell": string; "column": number; "row": number; "sheet": string };

export const operations = {
  "listAuditEvents": { method: "GET", path: "/api/audit-events" },
  "login": { method: "POST", path: "/api/auth/login" },
  "logout": { method: "POST", path: "/api/auth/logout" },
  "register": { method: "POST", path: "/api/auth/register" },
  "resolveCitation": { method: "GET", path: "/api/citations/{citation_id}/resolve" },
  "deleteComment": { method: "DELETE", path: "/api/comments/{comment_id}" },
  "updateComment": { method: "PUT", path: "/api/comments/{comment_id}" },
  "getCsrf": { method: "GET", path: "/api/csrf" },
  "listFriendRequests": { method: "GET", path: "/api/friend-requests" },
  "createFriendRequest": { method: "POST", path: "/api/friend-requests" },
  "acceptFriendRequest": { method: "POST", path: "/api/friend-requests/{friend_request_id}/accept" },
  "rejectFriendRequest": { method: "POST", path: "/api/friend-requests/{friend_request_id}/reject" },
  "listFriends": { method: "GET", path: "/api/friends" },
  "getMe": { method: "GET", path: "/api/me" },
  "listMyEmailOutbox": { method: "GET", path: "/api/me/email-outbox" },
  "getMyNotificationPreferences": { method: "GET", path: "/api/me/preferences" },
  "updateNotificationPreferences": { method: "PUT", path: "/api/me/preferences" },
  "getMyProfile": { method: "GET", path: "/api/me/profile" },
  "updateProfile": { method: "PUT", path: "/api/me/profile" },
  "listNotifications": { method: "GET", path: "/api/notifications" },
  "readAllNotifications": { method: "POST", path: "/api/notifications/read-all" },
  "readNotification": { method: "POST", path: "/api/notifications/{notification_id}/read" },
  "suggestProjectDescriptions": { method: "POST", path: "/api/projects/description-suggestions" },
  "listRooms": { method: "GET", path: "/api/rooms" },
  "createRoom": { method: "POST", path: "/api/rooms" },
  "createRoomInvitation": { method: "POST", path: "/api/rooms/{room_id}/invitations" },
  "listRoomMembers": { method: "GET", path: "/api/rooms/{room_id}/members" },
  "leaveRoom": { method: "DELETE", path: "/api/rooms/{room_id}/membership" },
  "listTalkSessions": { method: "GET", path: "/api/rooms/{room_id}/sessions" },
  "createTalkSession": { method: "POST", path: "/api/rooms/{room_id}/sessions" },
  "archiveTalkSession": { method: "DELETE", path: "/api/sessions/{session_id}" },
  "getTalkSession": { method: "GET", path: "/api/sessions/{session_id}" },
  "closeSession": { method: "POST", path: "/api/sessions/{session_id}/close" },
  "listSessionComments": { method: "GET", path: "/api/sessions/{session_id}/comments" },
  "createComment": { method: "POST", path: "/api/sessions/{session_id}/comments" },
  "compareSessionDocuments": { method: "GET", path: "/api/sessions/{session_id}/comparison" },
  "runGrokEditTask": { method: "POST", path: "/api/sessions/{session_id}/grok-edit-suggestions" },
  "getMergedDocument": { method: "GET", path: "/api/sessions/{session_id}/merged-document" },
  "saveMergedDocument": { method: "PUT", path: "/api/sessions/{session_id}/merged-document" },
  "listMergedDocumentVersions": { method: "GET", path: "/api/sessions/{session_id}/merged-document/versions" },
  "createMergedDocumentVersion": { method: "POST", path: "/api/sessions/{session_id}/merged-document/versions" },
  "getMergedDocumentVersion": { method: "GET", path: "/api/sessions/{session_id}/merged-document/versions/{version_id}" },
  "reopenSession": { method: "POST", path: "/api/sessions/{session_id}/reopen" },
  "getSessionReport": { method: "GET", path: "/api/sessions/{session_id}/report" },
  "getSessionResearch": { method: "GET", path: "/api/sessions/{session_id}/research" },
  "retrySession": { method: "POST", path: "/api/sessions/{session_id}/retry" },
  "searchSessionSources": { method: "GET", path: "/api/sessions/{session_id}/search" },
  "listSessionSubmissions": { method: "GET", path: "/api/sessions/{session_id}/submissions" },
  "submitFile": { method: "POST", path: "/api/sessions/{session_id}/submissions/files" },
  "submitText": { method: "POST", path: "/api/sessions/{session_id}/submissions/text" },
  "listReportSuggestions": { method: "GET", path: "/api/sessions/{session_id}/suggestions" },
  "createReportSuggestion": { method: "POST", path: "/api/sessions/{session_id}/suggestions" },
  "getSessionSummary": { method: "GET", path: "/api/sessions/{session_id}/summary" },
  "resolveSourceAnchor": { method: "GET", path: "/api/source-anchors/{source_anchor_id}/resolve" },
  "downloadSourceOriginal": { method: "GET", path: "/api/source-revisions/{revision_id}/original" },
  "getSourcePreview": { method: "GET", path: "/api/source-revisions/{revision_id}/preview" },
  "retryExtraction": { method: "POST", path: "/api/source-revisions/{revision_id}/retry-extraction" },
  "getSourceViewer": { method: "GET", path: "/api/source-revisions/{revision_id}/viewer" },
  "deleteSubmission": { method: "DELETE", path: "/api/submissions/{submission_id}" },
  "replaceTextSubmission": { method: "PUT", path: "/api/submissions/{submission_id}" },
  "resolveReportSuggestion": { method: "POST", path: "/api/suggestions/{suggestion_id}/resolve" },
  "getWebEvidence": { method: "GET", path: "/api/web-evidence/{web_evidence_id}" },
} as const;

"""Opaque cursor codecs shared by private activity repositories."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID


class InvalidCursorError(ValueError):
    pass


def encode_event_cursor(event_id: UUID) -> str:
    return base64.urlsafe_b64encode(event_id.bytes).rstrip(b"=").decode("ascii")


def decode_event_cursor(cursor: str) -> UUID:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        if len(raw) != 16:
            raise ValueError
        return UUID(bytes=raw)
    except (ValueError, TypeError) as error:
        raise InvalidCursorError("invalid event cursor") from error


def encode_time_cursor(created_at: datetime, item_id: UUID) -> str:
    payload = json.dumps([created_at.isoformat(), str(item_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_time_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
            raise ValueError
        created_at = datetime.fromisoformat(value[0])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(value[1])
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise InvalidCursorError("invalid page cursor") from error

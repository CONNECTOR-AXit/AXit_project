"""Fixed, local-only N4 proof that a stale queue lease cannot emit notifications."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.db import open_connection
from app.domain import JobState, StaleLeaseError
from app.queue_repository import PostgresJobQueue


class ProbeError(RuntimeError):
    """A bounded probe failure safe to report outside the container."""


def run_probe(*, session_id: UUID, recipient_ids: tuple[UUID, UUID]) -> dict[str, object]:
    if len(set(recipient_ids)) != 2:
        raise ProbeError("invalid_scope")

    queue = PostgresJobQueue()
    marker = uuid4().hex
    logical_key = f"n4-stale-probe:{marker}"
    dedupe_prefix = f"n4-stale-probe:{marker}"

    with open_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT count(DISTINCT membership.user_id) AS member_count
                FROM talk_sessions AS session_row
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.left_at IS NULL
                WHERE session_row.id = %s
                  AND membership.user_id = ANY(%s)
                """,
                (session_id, list(recipient_ids)),
            )
            row = cursor.fetchone()
        if row is None or int(row["member_count"]) != 2:
            raise ProbeError("invalid_scope")

        job = queue.enqueue(
            connection,
            logical_key=logical_key,
            kind="extraction",
            payload={"probe": "stale_completion"},
        )
        claimed = queue.claim_next(
            connection,
            owner="n4-stale-probe-winner",
            lease_seconds=30,
            kinds={"extraction"},
        )
        if claimed is None or claimed.id != job.id:
            raise ProbeError("claim_unavailable")
        queue.complete_with_effects(
            connection,
            claimed,
            target_state=JobState.SUCCEEDED,
            result={"outcome": "winner_completed"},
        )

        def forbidden_effect(cursor: Any) -> None:
            cursor.execute(
                """
                INSERT INTO notifications(
                    id,recipient_id,kind,actor_id,resource_type,resource_id,
                    action_kind,title,body,dedupe_key
                )
                SELECT batch.id,batch.recipient_id,'analysis_completed',NULL,
                       'session',%s,'open_session','Stale probe','Must not persist',
                       %s || ':' || batch.recipient_id::text || ':in_app'
                FROM unnest(%s::uuid[],%s::uuid[]) WITH ORDINALITY
                     AS batch(id,recipient_id,position)
                ORDER BY batch.position
                """,
                (
                    session_id,
                    dedupe_prefix,
                    [uuid4() for _ in recipient_ids],
                    list(recipient_ids),
                ),
            )
            cursor.execute(
                """
                INSERT INTO email_outbox(
                    id,recipient_id,notification_kind,dedupe_key,
                    template_key,template_data
                )
                SELECT batch.id,batch.recipient_id,'analysis_completed',
                       %s || ':' || batch.recipient_id::text || ':email_intent',
                       'analysis_completed',%s
                FROM unnest(%s::uuid[],%s::uuid[]) WITH ORDINALITY
                     AS batch(id,recipient_id,position)
                ORDER BY batch.position
                """,
                (
                    dedupe_prefix,
                    Jsonb({"session_id": str(session_id), "probe": "stale_completion"}),
                    [uuid4() for _ in recipient_ids],
                    list(recipient_ids),
                ),
            )

        stale = False
        try:
            queue.complete_with_effects(
                connection,
                claimed,
                target_state=JobState.SUCCEEDED,
                result={"outcome": "stale_completion"},
                effect=forbidden_effect,
            )
        except StaleLeaseError:
            stale = True

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT count(*) FROM notifications WHERE dedupe_key LIKE %s) AS in_app_rows,
                  (SELECT count(*) FROM email_outbox WHERE dedupe_key LIKE %s) AS outbox_rows
                """,
                (f"{dedupe_prefix}%", f"{dedupe_prefix}%"),
            )
            counts = cursor.fetchone()
        if not stale:
            raise ProbeError("stale_not_observed")
        if counts is None or int(counts["in_app_rows"]) != 0 or int(counts["outbox_rows"]) != 0:
            raise ProbeError("effect_escaped_fence")
    return {"stale": True, "in_app_rows": 0, "outbox_rows": 0}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", type=UUID, required=True)
    parser.add_argument("--recipient-id", type=UUID, action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        recipients = tuple(args.recipient_id)
        if len(recipients) != 2:
            raise ProbeError("invalid_scope")
        result = run_probe(session_id=args.session_id, recipient_ids=recipients)
    except ProbeError as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")))
        return 2
    except Exception:
        print('{"error":"probe_failed"}')
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

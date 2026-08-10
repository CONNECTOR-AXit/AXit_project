"""Canonical identity for the immutable summary+research report pair."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID
import psycopg
from psycopg.rows import dict_row

@dataclass(frozen=True, slots=True)
class IntegratedReportIdentity:
    snapshot_id: UUID
    content_hash: str

def report_content_hash(summary_hash: str, research_hash: str) -> str:
    return hashlib.sha256((summary_hash + research_hash).encode("ascii")).hexdigest()

def load_report_identity(connection: psycopg.Connection[dict[str, Any]], *, session_id: UUID) -> IntegratedReportIdentity | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("""SELECT snapshot.id AS snapshot_id,
          max(document.content_hash) FILTER (WHERE document.kind='summary') AS summary_hash,
          max(document.content_hash) FILTER (WHERE document.kind='research') AS research_hash
          FROM generation_snapshots snapshot
          JOIN generation_runs run ON run.snapshot_id=snapshot.id AND run.state='succeeded'
            AND run.pipeline_version=snapshot.pipeline_version
          JOIN generated_documents document ON document.run_id=run.id
          WHERE snapshot.session_id=%s GROUP BY snapshot.id,snapshot.generation_epoch
          HAVING count(*)=2 AND count(DISTINCT document.kind)=2
          ORDER BY snapshot.generation_epoch DESC LIMIT 1""", (session_id,))
        row = cursor.fetchone()
    if row is None:
        return None
    return IntegratedReportIdentity(row["snapshot_id"], report_content_hash(str(row["summary_hash"]), str(row["research_hash"])))

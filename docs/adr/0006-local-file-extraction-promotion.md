# ADR 0006: Promote G0 extraction through a host-side local worker

- **Status:** Accepted for the local hackathon runtime
- **Date:** 2026-08-03

## Context

Phase 4 needs real file submission and parsing, while ADR 0002 requires each
untrusted document to run in the pinned, short-lived, secretless G0 container.
ADR 0003 also prohibits mounting the Docker socket into the API or the Compose
orchestrator. The existing extraction runner is injection-only and the file
routes are contract-only.

## Decision

The API stores a bounded immutable blob beneath a configured local blob root
and atomically enqueues a revision-ID-only extraction job. A host-side local
worker reads that durable queue through the published localhost PostgreSQL
port, resolves the blob by the server-issued revision ID, and launches the
already pinned G0 image by directly reusing
`spikes/document-ingestion/sandbox_runner.py::execute_sandbox`. This preserves
the gate-proven bounded capture, timeout kill, forced container cleanup, and
the exact approved Docker restrictions:

- `--rm`, `--pull=never`, and no parser logs;
- `--network=none`, read-only root filesystem, non-root UID/GID;
- all capabilities dropped, `no-new-privileges`, and no IPC namespace;
- fixed CPU, memory/swap, PID, file-descriptor, tmpfs, input, output, and wall
  limits;
- a read-only one-file input mount and no credentials or inherited secrets.

The worker validates the typed parser envelope before atomically applying
`extraction_runs`, `source_anchors`, revision state, and fenced job completion.
Only opaque revision IDs and parser identity enter the durable job payload.
The API and Compose orchestrator continue to have no Docker socket.

Retryable parser/sandbox failures are automatically requeued using the same
logical job. The third failed claim is terminal and marks the current revision
failed, preventing an indefinitely queued document. Because fenced failure
completion and explicit requeue are separate transactions, every worker poll
first reconciles extraction-only `failed_retryable` rows: attempts below the
limit return to `pending`, while legacy rows already at the limit become
terminal with their current revision failed. This makes a host crash in that
small transaction boundary recoverable without changing generation jobs.
If another worker reconciles and claims the job before the completing worker's
explicit requeue, the resulting stale-lease response is treated as a benign
winner. A higher-generation `failed_retryable` completion is also durable
progress when that worker crashes before its own requeue; the same-generation
state is still rejected as unexplained staleness. Queue invariant and database
errors continue to fail loudly.
At worker startup and once
per hour, the blob store also compares immediate-child blob/temp files against
durable `source_revisions.storage_key` references and removes only unreferenced
regular files older than 24 hours. Symlinks, recent files, referenced blobs,
and unrelated operator files are never removed.

This is a local-runtime decision, not an external deployment design. The API
blob root is a repo-local, gitignored bind mount so the host worker and API can
resolve the same immutable bytes. Production deployment requires a separate
launcher trust-boundary decision rather than copying this host topology.

## Rejected alternatives

- **Parse inside the API/orchestrator:** rejected because local subprocess IPC
  does not provide the approved UID/network/cgroup boundary.
- **Mount Docker socket into orchestrator:** rejected because database and
  application credentials would share a process with host-level container
  control.
- **Long-lived parser service:** rejected because it weakens per-document
  isolation and allows cross-job state retention.

## Verification

Completion requires a fresh end-to-end extraction for every approved format,
malicious type-mismatch/traversal rejection, stable anchor validation,
member-only original download, queue stale-lease coverage, and the existing G0
containment suite.

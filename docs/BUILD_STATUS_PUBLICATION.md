# D-097: resilient Windows status publication

## Behavior

Status JSON remains a whole-document, same-directory atomic replacement. Each
write uses a unique temporary file, flushes and fsyncs it, then replaces the
destination. A Windows `PermissionError` during replace is retried with bounded
backoff for at most two seconds. Exhaustion, non-permission errors, serialization
errors and write failures still propagate into the existing fail-closed runtime
and supervisor paths. Until replacement succeeds, readers retain the prior whole
document; no partial destination is published.

Repository-owned live/supervisor status readers open files with Windows
read/write/delete sharing so they do not themselves prevent replacement. This
does not control unrelated external programs, which is why the bounded writer
retry remains necessary. Unique temporary names avoid collisions between a final
error report and another process-local publication attempt. Cleanup is bounded
and never converts a failed publication into success.

The status writer runs off the live event loop during periodic publication. The
two-second bound does not change venue mutation, recovery, risk, configuration,
capital, ranking or reward logic.

## Verification and limits

A native Windows regression opens the current destination while deliberately
denying delete sharing, releases that handle after 100ms, and verifies the writer
retries to a complete current document. Synthetic regressions prove transient
retry and permanent-denial behavior, including retention of the old whole status
and temporary-file cleanup. Live-runtime, host-continuity and production-
supervisor suites pass. The complete suite runs 1,557 tests with one expected
Windows symlink-privilege skip.

The exact external handle involved in the historical live failures was not
identified. The repair covers the demonstrated Windows contention class; only a
separately authorized sustained live restart can establish operational acceptance.

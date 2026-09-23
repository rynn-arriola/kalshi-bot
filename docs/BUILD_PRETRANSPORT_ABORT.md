# Proven pre-transport abort — D-089

## Incident and mechanism

Two recovery cancellations were durably marked `UNKNOWN` even though structured
diagnostics showed `CommandDenied` at the `proof_changed_before_submission`
branch and no transport invocation. Those false unknowns prevented safe
reauthorization, leaving two resting orders after the progress-aware D-088 drain
had otherwise advanced from nine to two.

The executor used `SENDING` as the uncertainty boundary. That was too early:
after `begin_send`, it still performs source/account/revision checks before
calling the injected transport. A failed check in that interval proves the
request was not submitted.

## Repair

The single writer now provides a transactional `SENDING` to `NOT_SENT` abort
that also changes the matching authorization to `ABORTED` and releases create
intent capacity. Only the writer's claimed executor can request it. Batch aborts
are all-or-none. The executor uses it only on the two explicit proof-change
branches before transport invocation, emits `mutation_not_submitted`, remains
available, and re-signals recovery. Once transport invocation begins, timeout,
bad acknowledgement, transport failure and other uncertainty remain `UNKNOWN`.

This changes no market, quote, capital, loss, selection or retry policy.

## Verification

Focused command, dispatch, lifecycle, live-runtime, logging, capacity,
account-release and recovery tests cover single and batch aborts, ownership,
capacity release, recovery signaling and zero transport calls. The complete
suite passes **1,481 tests with one expected Windows privilege skip** in
157.863 seconds. Exact diff review found and corrected writer revision tracking,
executor ownership and batch atomicity before the final run.

The two historical false-UNKNOWN rows require a separate stopped-owner,
backed-up, exact operational correction before recovery can cancel their still
resting orders. No general UNKNOWN retry or relabeling is authorized.

# D-090 lifecycle snapshot buffer

## Observed failure

The production lifecycle reader repeatedly failed at
`transport._receive` with `QueueFull`. Its unscoped initial snapshot contained
about 5,018 active-market rows, but `readonly_reader_factory` overrode every
single-stream reader to 256 events / 2 MiB. Reconnect replayed the same snapshot,
so the reader could not converge and the runtime correctly paused entries.

## Implemented boundary

- `lifecycle`: 8,192 events / 16 MiB, the existing bounded transport defaults.
- `account` and scoped `book-*`: unchanged at 256 events / 2 MiB.
- No reward, ranking, order, risk, stop-loss or configuration rule changed.
- Overflow still fails closed; this does not introduce an unbounded queue.

## Acceptance

- A regression test proves the larger bound applies only to lifecycle.
- Feed, lifecycle, diagnostics and live-runtime tests pass: 127 tests.
- Complete suite passes: 1,482 tests, one expected Windows privilege skip.
- Live acceptance requires one complete initial lifecycle generation without
  queue overflow, plus current account/catalog/admission proof.

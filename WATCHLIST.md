# Watchlist — ideas and questions, not authority

Accepted requirements belong in [DECISIONS.md](DECISIONS.md); active work in
[NEXT.md](NEXT.md). Nothing here authorizes trading or increased risk.

- Define CPU, memory and latency budgets against actual laptop capacity and
  operator-approved market count before implementation.
- Resolve field-level stream completeness, account bootstrap and gap recovery.
- Add CPU workers only if profiling establishes a bottleneck; not per-market
  threads/processes by default.
- Complete compact root indexes and a documentation audit while preserving
  historical evidence and links. See [layout](docs/DOCUMENTATION_STRUCTURE.md).

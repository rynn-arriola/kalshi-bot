# D-043 — Canonical GitHub publication

Date: September 20, 2026. Operator authorized replacing the contents of
`https://github.com/rynn-arriola/kalshi-bot` with the active native Windows
project at `C:/Users/rynna/Bots/kalshi`.

## Result

- GitHub's default branch was and remains `master`. Its old 31-file measurement
  tree was replaced by 170 current project files. The replacement commit is
  `b2d7f26`; merge commit `d83584f` also preserved the divergent former `main`
  branch's history without reintroducing its old files. The obsolete `main`
  branch was then deleted. Both prior branch tips remain ancestors of `master`
  and can be inspected or restored from Git history.
- The active Windows folder is now a Git checkout on `master`, tracking
  `origin/master`. Future changes can be reviewed with `git status`/`git diff`
  and published from this folder. This publication record adds one further
  tracked file in the follow-up documentation commit.
- This publication covers source, tests, documentation, API reference snapshots,
  safe configuration and scripts. All 170 staged files were byte-identical to
  the active folder before commit. The published remote HEAD and `master`
  resolved to the same new commit; `main` no longer resolved.

## Exclusions and checks

Private keys, key ID files, `.env*`, captured `data/`, local `backups/`, logs,
databases, virtual environments, caches, package build metadata, the stale
`DEPLOYED_COMMIT` marker and the local `TRANSFER_MANIFEST.json` were not
published. The Git ignore rules cover these categories in the active folder.
A staged-content scan found no private-key header or GitHub token; broader
`sk_` matches were test identifiers containing `risk_`, not tokens. Only the
published project tree was changed remotely; local data and credentials were
not deleted.

This was a repository synchronization, not a new implementation. D-042's 778
passing tests remain the most recent complete-suite result. No tests or live
account calls were needed for this publication. Trading remains disabled.

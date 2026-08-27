# Isolated server measurement contract

## Authorization

Operator decision D-007 allows verified **read-only Kalshi measurement** to run
on the server that hosts the live Polymarket bot. It does not authorize Kalshi
orders, a production Kalshi bot, or any change to the Polymarket runtime.

## Required isolation

The Kalshi project must have its own:

- new standalone directory outside the Polymarket tree—for example, a
  `kalshi-bot` sibling beside the Polymarket directory. Resolve both absolute
  paths on the server before creating it; never nest it under Polymarket;
- virtual environment and dependency installation;
- environment/configuration file containing only the minimum Kalshi read
  credentials required by the instrument;
- process or service name, PID/lock files, working directory, and lifecycle
  commands;
- data, SQLite WAL, logs, temporary files, and backups.

Do not use imports, symlinks, working directories, configuration, credentials,
data files, log files, service units, supervisors, or shell wrappers from the
Polymarket project. Do not make Polymarket API calls from this project.

## Production protection

The Polymarket process has priority. Before the first server measurement run:

1. Inspect the server read-only and resolve the exact Polymarket directory,
   service names, ports, lock files, and current resource use.
2. Verify the Kalshi path resolves outside every Polymarket directory.
3. Run local tests and a credential/endpoint scan on the exact commit to deploy.
4. Confirm every network path used by the command is read-only and Kalshi-only.
5. Set conservative CPU, memory, disk, and request-rate limits appropriate to
   the instrument.
6. Print the exact command, commit, directory, database, log, duration, and stop
   procedure before starting it.

Installing, starting, stopping, or updating Kalshi measurement must never stop,
restart, deploy, signal, or edit the Polymarket process. If resource contention
or unexpected cross-project access appears, stop only the Kalshi measurement
and preserve its logs for diagnosis.

## Data and credential handling

- Keep `.env`, keys, captured books, databases, and logs outside Git.
- Never copy Polymarket credentials into the Kalshi project.
- Never display secret values in commands, logs, Markdown, or AI responses.
- Use a dedicated OS account for Kalshi measurement when practical; if that is
  not available, filesystem and process separation above remains mandatory.

## Scope boundary

Stages 0 and 1 may use local or isolated server computation. Stage 2 may make
read-only Kalshi market/account requests. Stage 3 remains unauthorized: D-007
does not permit order placement, cancellation, capital movement, or any other
authenticated write.

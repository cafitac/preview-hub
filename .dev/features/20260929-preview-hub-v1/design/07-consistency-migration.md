# Consistency and migration

## Transaction and aggregate boundaries

- Aggregate: `Environment` (row in `environments` + its `environment_services` rows). Every state change is one short SQLite transaction (`BEGIN IMMEDIATE`) that also bumps `version`.
- Long work (git, image build, container start, health wait) happens between transactions while the per-environment file lock is held. The registry never holds a DB transaction across an external call.
- `operations` records who is doing what for crash recovery and audit; it is written in the same transactions as the state changes it describes.

## Identity, idempotency, and result-unknown recovery

- Identity: `EnvName` (user-chosen, or `pr-<repo>-<number>` for the bot). Unique among non-DELETED rows via a partial unique index.
- `up` with an identical requested ref set on a READY environment returns the current state (no-op). `up` on an existing name with different refs is rejected; changing refs is the explicit `update` command. `down` on DELETED/unknown names is a no-op label sweep.
- Result-unknown (process killed mid-operation): the next command that takes the lock sees a RUNNING operation whose pid is gone or whose heartbeat is older than 10 minutes, marks it INTERRUPTED and the environment FAILED. Docker is the source of truth for what exists: `down` always removes by label, so a crash can never orphan untracked objects.
- Images are keyed by `(service, commit_sha)`; rebuilding the same commit is skipped, so retries are cheap and deterministic.

## Isolation, locks, and retry ownership

- Daemon isolation: the hub is itself a container inside the `preview-hub` Colima VM and mounts that VM's `/var/run/docker.sock`, so the only daemon it can reach is this VM's. At start it checks the daemon name (`colima-preview-hub`) and refuses to run elsewhere. Nothing of the hub runs on the Mac Studio host; the host only runs the VM.
- Environment isolation inside the daemon: Compose project `phub-<env>`, network `phub-<env>`, volumes `phub-<env>-<resource>`, labels `dev.phub.managed=true`, `dev.phub.env=<env>`, `dev.phub.service=<service>`. Each environment has its own PostgreSQL container and volume; no database is shared between environments.
- Cleanup scope: only objects labelled `dev.phub.env=<env>` for that environment; the global `gc` only touches `dev.phub.managed=true` objects whose environment is DELETED or unknown to the registry.
- Locks: one file lock per environment (`fcntl`, non-blocking, on the `phub-state` volume) held for the whole operation; CLI invocations all run inside the single `phub-hub` container, so locks are shared; a host-wide semaphore limits concurrent image builds to 2. Lock order: env lock, then build semaphore.
- Retry owner: the user/bot re-runs the command; the hub itself does not auto-retry builds. The expiry sweep retries deletions of DELETING environments.

## External effects and consistency protocol

- Git: read-only (`ls-remote`, shallow fetch of the exact commit) from inside the hub container. Source trees are cached per commit on the `phub-src` volume and treated read-only. Example repositories are public, so no credentials enter the VM.
- Routing: the shared `phub-proxy` (Traefik, Docker provider restricted to `dev.phub.managed=true`) is attached to each environment network on create and detached on delete. Hostname `<subdomain>.<env>.localhost`; the proxy publishes 18080 in the VM, Colima forwards it to the host's 127.0.0.1:18080, and the MacBook reaches it through `ssh -L 18080:127.0.0.1:18080`. No DNS, host network or Tailscale changes.
- GitHub comments (S3): posted after the operation's final state is committed; a failed comment post never changes environment state.

## Capacity and safety limits

- Max active environments: 5 (configurable). `up` beyond the limit is rejected before any work.
- Disk guard (two layers, because the hub inside the VM cannot see the host disk): the hub refuses `up`/`update` when the VM has < 5 GiB free; the MacBook `phub` wrapper reads the host's free space over SSH (read-only `df`) and refuses when the host volume has < 15 GiB free (the host is at 90%). The VM disk is capped at 40 GiB, which bounds the worst case on the host.
- Per-container memory limit from the manifest (default 512 MiB); the profile is capped at 8 GiB.
- Image GC: keep images referenced by active environments plus the 3 most recent commits per service; `phub gc` removes the rest (label-scoped).

## Current-to-target migration

- Compatibility and deploy order: greenfield; the hub stack (phub-hub + phub-proxy + volumes) is started by one Compose file inside the VM; registry schema revision 1 is created on first run (`schema_meta.version=1`). Later schema changes use numbered SQL migrations applied at hub start. Upgrading the hub = rebuild its image and recreate the container; volumes keep the registry.
- Backfill and verification: none.
- Rollback: environments are disposable; removing everything = `phub down` for each environment, then `colima delete --profile preview-hub` (the VM holds the hub, registry volumes, caches, proxy and images; nothing is left on the host).
- Shadow / cutover / kill switch: not applicable.

## Access paths and index evidence

- By name (every command): `uq_env_active_name`.
- Expiry sweep: `ix_env_expiry` on (state, ttl_expires_at).
- Stale operations: `ix_op_env_status`.
- Volumes: single user, at most tens of rows.

## Audit, privacy, and retention

- `operations` keeps who ran what (`cli:<user>`, `gh:<login>#<pr>`), when and the outcome; retained 90 days after the environment is DELETED.
- Example services use only synthetic seed data. Test credentials in the descriptor are generated per environment and stored in the registry only for the environment's lifetime.

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

## PR comment bot (revision 3)

- Exactly-once execution per comment: `bot_comments.comment_id` primary key is inserted before any side effect; a duplicate poll result conflicts and is skipped. Polling overlaps the cursor by 60 s so edits and clock skew never drop comments.
- Ordering: commands for the same PR run sequentially (the hub's per-environment lock already rejects overlap with exit 3; the bot replies "busy, retry" instead of queueing).
- Authorization before effects: author association OWNER/MEMBER/COLLABORATOR, base repository in the catalog, head repository == base repository (fork PRs refused), PR open. The service built from the PR is pinned to `head.sha` read at command time, never to a branch name.
- The bot has no Docker authority beyond `docker exec phub-hub phub ...`; hub guards (capacity, disk, labels) apply unchanged.
- Closed PRs: each loop lists PRs closed since the last scan and runs `phub down pr-<service>-<number>`; `down` of an unknown environment is already a no-op sweep.
- Token: fine-grained, catalog repositories only, created by the user and delivered as a Docker secret file (`/run/secrets/github_token`); never logged; rate limit ~ (repos × 2 requests) per 20 s ≈ 1,440/h for 4 repositories, under the 5,000/h limit.
- Crash recovery: RUNNING rows older than 10 min become FAILED with an "interrupted" reply; unsent replies retried up to 3 times.

## Capacity and safety limits

- Max active environments: 5 (configurable). `up` beyond the limit is rejected before any work.
- Disk guard (two layers, because the hub inside the VM cannot see the host disk): the hub refuses `up`/`update` when the VM has < 5 GiB free; the MacBook `phub` wrapper reads the host's free space over SSH (read-only `df`) and refuses when the host volume has < 15 GiB free (the host is at 90%). The VM disk is capped at 40 GiB, which bounds the worst case on the host.
- Per-container memory limit from the manifest (default 512 MiB); the profile is capped at 8 GiB.
- Image GC: keep images referenced by active environments plus the 3 most recent commits per service; `phub gc` removes the rest (label-scoped).

## Current-to-target migration

- Compatibility and deploy order: greenfield (registry schema revision 2 adds `bot_comments`/`bot_cursors` via migration 0002, additive); the hub stack (phub-hub + phub-proxy + volumes) is started by one Compose file inside the VM; registry schema revision 1 is created on first run (`schema_meta.version=1`). Later schema changes use numbered SQL migrations applied at hub start. Upgrading the hub = rebuild its image and recreate the container; volumes keep the registry.
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

## Revision 4 (S4): dashboard, `pr-<n>` refs, public access

### Authority and ownership

- The registry stays the single source of truth. The dashboard reads it and mutates only by running the same `phub` CLI entry point as a child process inside `phub-hub`; it holds no lifecycle logic of its own, so locks, guards, idempotency and the operations audit are unchanged.
- GitHub reads (branches, open PRs, PR head) happen in `phub-hub` with the existing fine-grained token mounted read-only (`/opt/phub/secrets` → `/run/secrets`). GitHub writes stay in `phub-bot` only (replies and cross-link comments).
- Cloudflare objects (tunnel, DNS, Access application) are owned and created by the user; the hub never calls a Cloudflare API and holds no Cloudflare token. The only Cloudflare interaction is the public JWKS fetch for JWT verification.

### Security model (defence in depth)

1. Cloudflare Access at the edge for `preview-hub.cafitac.com` and `phub-*.cafitac.com` (policy: owner's email).
2. The tunnel is the only public path: `phub-hub:8080` and `phub-proxy:80` are not published beyond the VM (the proxy's 18080 stays bound to host 127.0.0.1 for SSH debugging).
3. The hub verifies the Access JWT on every dashboard/API request, and Traefik forwardAuth asks the hub to verify it for every public environment route. A misconfigured or missing Access application therefore yields 401/403, not an open environment. Missing verifier configuration = fail closed.
4. Mutations additionally require the dashboard `Origin` (CSRF) and JSON content type.
5. `pr-<n>` refuses forks and closed PRs, so untrusted code is never built from the dashboard either.
6. Local `.localhost` routes are not behind forwardAuth: they are reachable only from the VM and the host's 127.0.0.1 (SSH forward), the same trust as revision 3.

### Identity and idempotency

- Dashboard create without a name generates `c-<6 base32>`; retries of the same POST are not deduplicated (each click is a new environment) but capacity (max 5) bounds the effect; the UI disables the button while the request is in flight.
- `pr-<n>` is re-resolved on `update`; a READY environment with `pr-<n>` whose PR head moved is *not* auto-updated (explicit `update`, same rule as branches).
- Cross-link comments: `pr_links` primary key (environment, repo, pr) = at most one hub comment per pair. Crash after POST before the DB commit is recovered by searching the PR's comments for the marker `<!-- phub-link env=<env> -->` authored by the token's user before posting again.

### Failure and recovery owners

| Effect | Starts | Observes | Reconciles / retries | Cleans up | Verifies |
|---|---|---|---|---|---|
| Environment containers/routes | CLI (via dashboard, bot or user) | registry + labels | user / bot re-run; gc sweep | `down`, TTL gc (label-scoped) | A3 inventory |
| Public route (Traefik labels) | ComposeRunner at apply | Traefik | recreated with the containers | removed with the containers | A12 404 after down |
| Tunnel connection | Docker restart policy | cloudflared logs, `/healthz` via tunnel | cloudflared reconnects | `compose --profile public down` | A12 |
| JWKS cache | first request | verifier | refresh on unknown kid / 1 h | in-memory | A13 tests |
| Cross-link comment | phub-bot reconcile | pr_links | every loop (attempts counter) | edited to "removed" (never deleted; history) | A14 |
| Dashboard child process | hub HTTP server | operations table | stale-op recovery (existing) | process exit | A10 |

### Cleanup inventory

- Per environment: unchanged (label-scoped). Public routes are container labels, so nothing extra remains after `down`.
- `pr_links` rows: kept as audit with status REMOVED; purged with the 90-day operations retention.
- Hub stack additions: container `phub-cloudflared` (label `dev.phub.managed=true`, `dev.phub.service=cloudflared`); files `/opt/phub/secrets/tunnel.json`, `/opt/phub/public.env` inside the VM.
- User-owned (outside the VM, removed by the user on rollback): DNS `preview-hub` and `*` records, the named tunnel, the Access application.

### Capacity, cost and limits

- No paid service: Cloudflare Tunnel, Access (≤ 50 users), Universal SSL and proxied DNS are free-plan features; JWKS fetches are free; GitHub API stays under the authenticated limit (dashboard listing cached 60 s: ≤ 3 repos × 2 calls per minute ≈ 360/h, plus the bot's ≈ 1,440/h and cross-link calls only on change).
- Wildcard DNS side effect: any unknown `*.cafitac.com` name now reaches this tunnel and gets 404 from Traefik (not an error page of another service). A future service on cafitac.com needs its own explicit DNS record, as today.

### Migration and rollback

- Migration 0003 adds `pr_links` (additive; no backfill). The catalog `public_access` block is optional; absent → revision 3 behaviour.
- Deploy order: hub image with C9/C10 support → user creates tunnel/DNS/Access and installs credentials → `vm-bootstrap` starts the `public` profile → set `public_access` in the catalog → recreate hub/bot.
- Rollback: remove `public_access` from the catalog and stop the `public` profile (environments created afterwards get local URLs again); the user may delete the DNS records, tunnel and Access app. Existing environments keep their injected URLs until `update`/`down`.

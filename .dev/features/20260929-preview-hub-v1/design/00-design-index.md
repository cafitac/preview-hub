# Design index

- Feature record: ../feature.md
- Feature ID: 20260929-preview-hub-v1
- Current slice: S4 central dashboard and public access (revision 4); S1–S3 delivered
- Current PR unit: pending (derived by feature-plan from this design)
- Design profile: STANDARD
- Design status: AWAITING_APPROVAL (revision 4)
- Target/base: main (new personal repositories)

## Source evidence

- Greenfield: no preview-hub code exists. No Earlypay code, configuration or rules are used (R11).
- Runtime host facts, read-only on 2026-09-29 (trading-macstudio):
  - macOS 26.5.2, arm64, 16 CPU, 128 GiB RAM; home volume 460 GiB with 44 GiB free (90% used).
  - Docker runs only through Colima profiles (vmType vz), each its own VM and daemon: earlypay-tests, judge, thread-example, thread-example-ops(-green) running; default and others stopped. Running profiles reserve about 61 GiB RAM. There is no default `/var/run/docker.sock`.
  - Docker Compose 5.5.1, Colima 0.10.3, gh, uv, python3.12 installed. No GitHub Actions runner installed.
  - Tailscale: trading-macstudio 100.126.255.39 reachable from macbook-pro-63.
  - Many host ports are taken (3000, 5000, 7000, 8080, 8081, 8088, 9090, 55432, …); the hub must not assume common ports.
- Planning record requirements R1–R11 and acceptance A1–A9.

## Artifact ledger

| Artifact | Status | Evidence / reason |
|---|---|---|
| Context map | REQUIRED | Hub, runtime host, GitHub, example service repositories, the polling bot and the future ai-qa consumer are separate authorities. |
| Domain model | REQUIRED | Environment aggregate, manifest/composition value objects and the runner/git boundaries. |
| Current schema | N/A | Greenfield: no existing schema or registry to observe. |
| Target schema | REQUIRED | Environment registry (SQLite) owned by the hub. |
| Transaction flows | REQUIRED | Create, update, delete, expire and PR-comment flows with lock, idempotency and cleanup. |
| State machines | REQUIRED | Environment lifecycle states drive idempotency, TTL and failure recovery (R3). |
| Consistency and migration | REQUIRED | Registry-versus-Docker reconciliation, locks, crash recovery, isolation and capacity. |
| Acceptance trace | REQUIRED | Maps A1–A15 (A10–A15 added in revision 4). |
| Visual review pack | REQUIRED | User-facing review in Korean. |

Supplementary (part of the reviewed set): `11-interface-contracts.md` — service manifest, catalog, composition spec, runner interface, CLI, PR command grammar, ai-qa descriptor and report schemas. Revision 4 adds the hub HTTP API (C9) and public ingress (C10) to that same file instead of a separate `10-api-contract.md`, so all external contracts stay in one reviewed artifact.

## Confirmed decisions

- D1 separate repositories: cafitac/preview-hub (Python 3.12, uv) plus one repository per example service.
- D2 Docker Compose runner first, behind a runner interface; runtime host trading-macstudio.
- D3 entry points: CLI (S1) and PR comment bot (S3).
- D4 example backend uses PostgreSQL; a per-environment database is part of the contract.
- D5 STANDARD design approved by the user before an autonomous sprint manifest.

## Proposed decisions

- P1 Dedicated Colima profile `preview-hub` (4 CPU, 8 GiB RAM, 40 GiB disk). The hub only ever talks to this profile's Docker socket, so other projects' containers are unreachable by construction; label-scoped cleanup still applies inside it.
- P2 Everything runs as containers inside the `preview-hub` Colima VM; nothing is installed or run directly on the Mac Studio host except that VM (user decision 2026-09-29: "실제 컴퓨터에 직접 띄우진 말고"). The hub runs as the long-lived container `phub-hub` (image built from the preview-hub repository) with the VM's Docker socket mounted, so it can reach only this VM's daemon. The `phub` CLI executes inside it: a thin MacBook wrapper runs `ssh trading-macstudio docker --context colima-preview-hub exec phub-hub phub ...`. The PR bot's runner (S3) will also be a container in the same VM.
- P3 Environment registry is SQLite at `/state/state.db` on the named volume `phub-state`; per-environment locks live under `/state/locks`; the git source cache is the named volume `phub-src` at `/src`. All three survive hub container restarts and vanish with the VM.
- P4 Every environment is one Compose project `phub-<env>` with its own network and named volumes, labelled `dev.phub.managed=true` and `dev.phub.env=<env>`.
- P5 One shared reverse proxy (Traefik) container `phub-proxy` routes `<subdomain>.<env>.localhost` to the right container. It publishes one port (18080) inside the VM, which Colima forwards to the host's 127.0.0.1 only. Access from the MacBook is an SSH local forward (`ssh -L 18080:127.0.0.1:18080 trading-macstudio`), so browsers open `http://api.feat-x.localhost:18080`; `*.localhost` resolves to the local machine in browsers without any DNS. No host network or Tailscale setting changes.
- P6 Refs resolve to commit SHAs with `git ls-remote` at create/update time; images are built once per (service, commit) and tagged `phub/<service>:<sha12>`, so the same commit is reused across environments.
- P7 Services are registered in a hub catalog file (configuration, not code). Adding a service = catalog entry + `preview.yaml` in its repository. Unspecified services use the catalog default ref.
- P8 Build-time inputs never depend on other services; cross-service values (URLs, DB URL) are injected at container start. Frontends read them at runtime (entrypoint writes a config script).
- P9 Example stacks: backend FastAPI + SQLAlchemy/Alembic + PostgreSQL 16; frontend Vite + React served by a small static server with runtime config; third service (S2) `notifier`, a small FastAPI API that the backend calls when `NOTIFIER_URL` is set.

- P10 (revision 3, user decision 2026-09-29 option A) PR comment bot is a long-lived container `phub-bot` in the `preview-hub` VM. Every 20 s (configurable) it lists new PR issue comments of every repository in the catalog via the GitHub REST API (`GET /repos/{repo}/issues/comments?since=`), parses `/preview` commands (C6), authorizes them, runs the hub CLI inside `phub-hub` (`docker exec`, the bot never touches Docker otherwise — it only has the Docker socket to exec into phub-hub), and replies with one comment. It also lists closed PRs and runs `down` for their environments. The repository set comes from the catalog, so adding a service adds its repository to the bot with no bot change. Authentication: a user-created fine-grained token (catalog repositories only; Pull requests read, Issues read/write, Contents read) stored as a Docker secret inside the VM; never the owner's broad gh login token.
- P11 (revision 3) Security: commands only from author_association OWNER/MEMBER/COLLABORATOR; PRs whose head repository differs from the base repository (forks) are refused before any build; a command runs only for a PR in a catalog repository; the service at the PR head is pinned to the exact head SHA read from the PR at command time.

- P12 (revision 4, D11) Public exposure = `phub-cloudflared` container in the VM (named tunnel, locally managed ingress), wildcard DNS `*.cafitac.com` + `preview-hub` created by the user; Access application covers `preview-hub.cafitac.com` and `phub-*.cafitac.com`. No Cloudflare token in the VM.
- P13 (revision 4) One origin per environment: `phub-<env>.cafitac.com`, entry service at `/`, other exposed services under `/_svc/<subdomain>` (prefix stripped). Needed because Access cookies are per hostname; cross-host API calls would be redirected to the login and fail CORS. Local `.localhost` routes stay for debugging.
- P14 (revision 4) The hub verifies the Access JWT (RS256, aud, iss, exp) on every dashboard/API request and, through Traefik forwardAuth, on every public environment route; fail closed without configuration.
- P15 (revision 4) Dashboard = `phub serve` HTTP server (Starlette + uvicorn + Jinja2 server-rendered pages with a small script; no frontend build) inside `phub-hub`; mutations spawn the same `phub` CLI, so the lifecycle has one implementation.
- P16 (revision 4) `pr-<n>` refs resolve through the GitHub API to the open, same-repository PR head SHA; the S3 GitHub client moves to a shared module used by hub and bot.
- P17 (revision 4) Cross-link comments are reconciled by `phub-bot` from the registry into `pr_links` (migration 0003): one comment per (environment, PR), edited on change, marked removed after deletion.
- P18 (revision 4) New dependencies: starlette, uvicorn, jinja2, PyJWT[crypto] (all open source); no paid services.

## Open questions

- O1 (resolved by P5) Exposure is an SSH local forward. Optional later: a Tailscale container inside the VM joined as its own tailnet node, which needs an auth key issued by the user; it would change only the public URL template (C2), not any other contract.
- O2 (resolved in revision 3 by P10) PR bot = polling bot container; no GitHub Actions runners and no inbound connectivity.

- O3 Source access on the runtime host: the host's gh is logged in to a company account. Proposed: the example repositories are public, so `git ls-remote`/fetch need no credentials; if a private repository is ever added, a cafitac fine-grained read-only token is stored for the hub only. Decided before U-RUN; does not change contracts.

- O4 (revision 4, SAFE_ASSUMPTION) Automated tests cannot pass Access without a credential; A10/A12 live checks use in-VM requests with a Host header for routing, unauthenticated public curls for the Access redirect, and one manual browser check by the owner. An Access service token for automation is deferred (free, but another user-created secret).

## Review findings

- R-1 (accepted, fixed): resource init runs again on update against the kept volume, so seeds must be idempotent — added to C1 together with the rule that update restarts only changed services.
- R-2 (accepted, recorded as O3): runtime-host git credentials belong to a company account; public example repositories avoid mixing identities.
- R-3 (superseded by the revision): the sslip.io public-DNS dependency is gone; `*.localhost` needs no DNS.
- R-5 (accepted, fixed): consumers running inside the VM (ai-qa later) cannot use `*.localhost` to reach the proxy, so the descriptor (C7) also carries the proxy's in-network address; such consumers map hostnames to it (browser host-resolver rules or `--add-host`).
- R-4 (rejected): a separate operation/outbox table per action — the single `operations` table plus label-based reconciliation already covers crash recovery and audit.
- Checklist pass (no independent agent review: not requested for this design): ownership, invariants-to-enforcement, lock order, idempotency, result-unknown recovery, cleanup inventory, capacity guards and A1–A9 trace reviewed; no remaining gap.

- Revision 4 checklist pass (no independent agent review; STANDARD profile): findings below.
  - RV4-1 (accepted, fixed in P13/C2): per-service public hostnames break Access for API calls (per-host cookie) → one origin per environment.
  - RV4-2 (accepted, fixed in C9/07): the dashboard reachable without Access (misconfigured app) → hub-side JWT verification + forwardAuth, fail closed.
  - RV4-3 (accepted, fixed in C9): CSRF on dashboard mutations → Origin + JSON content type checks.
  - RV4-4 (accepted, fixed in 07): crash after posting a cross-link comment → marker search before re-posting.
  - RV4-5 (accepted, recorded in C3): branches literally named `pr-<n>` become unaddressable by name → documented; commit SHA still works.
  - RV4-6 (rejected): let the hub call the Cloudflare API to create per-environment DNS/Access objects — contradicts D11 (wildcard DNS chosen) and adds a secret and an extra cleanup family.

## Validation evidence

- `python3 skills/feature-design/scripts/validate_design.py --record ../feature.md` (agent-skills 0a40840): valid, no errors or warnings; digest recorded in the feature record.
- `npx -p @dbml/cli dbml2sql 04-target-schema.dbml --postgres` (@dbml/cli 10.2.0): parsed, 4 tables generated. The partial unique index is created by migration SQL (SQLite), as noted in the schema.
- PlantUML renderer: not installed on this machine; `02`, `05`, `06` were not rendered. Their content is mirrored in the Mermaid review pack.
- Revision 3 (2026-09-29): P10/P11 polling bot; schema adds `bot_comments` and `bot_cursors` (rev 2 of the registry); flow adds the bot command sequence; C6 extended with reply format, deduplication and PR-close handling.
- Revision 4 (2026-09-29): P12–P18, C2/C3/C6/C7 extensions, C9 hub HTTP API, C10 public ingress; schema adds `pr_links` (migration 0003); rev4 flows and link state machine; A10–A15 trace. `validate_design.py` valid; `npx -p @dbml/cli dbml2sql 04-target-schema.dbml --postgres` parsed 7 tables; PlantUML still not rendered (no renderer installed), mirrored in the Mermaid review pack.

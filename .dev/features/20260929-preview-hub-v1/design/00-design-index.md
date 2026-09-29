# Design index

- Feature record: ../feature.md
- Feature ID: 20260929-preview-hub-v1
- Current slice: S0 contracts design (covers S1–S4 contracts; S1 is the first implementation slice)
- Current PR unit: pending (derived by feature-plan from this design)
- Design profile: STANDARD
- Design status: AWAITING_APPROVAL
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
| Context map | REQUIRED | Hub, runtime host, GitHub, example service repositories and the future ai-qa consumer are separate authorities. |
| Domain model | REQUIRED | Environment aggregate, manifest/composition value objects and the runner/git boundaries. |
| Current schema | N/A | Greenfield: no existing schema or registry to observe. |
| Target schema | REQUIRED | Environment registry (SQLite) owned by the hub. |
| Transaction flows | REQUIRED | Create, update, delete, expire and PR-comment flows with lock, idempotency and cleanup. |
| State machines | REQUIRED | Environment lifecycle states drive idempotency, TTL and failure recovery (R3). |
| Consistency and migration | REQUIRED | Registry-versus-Docker reconciliation, locks, crash recovery, isolation and capacity. |
| Acceptance trace | REQUIRED | Maps A1–A9. |
| Visual review pack | REQUIRED | User-facing review in Korean. |

Supplementary (part of the reviewed set): `11-interface-contracts.md` — service manifest, catalog, composition spec, runner interface, CLI, PR command grammar, ai-qa descriptor and report schemas. There is no HTTP API in v1, so `10-api-contract.md` is not produced.

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

## Open questions

- O1 (resolved by P5) Exposure is an SSH local forward. Optional later: a Tailscale container inside the VM joined as its own tailnet node, which needs an auth key issued by the user; it would change only the public URL template (C2), not any other contract.
- O2 PR bot authentication for a user account (not an organization): runners are per repository, so either one runner registration per example repository on the same host or a reusable workflow. Decided when S3 is planned; does not affect S1.

- O3 Source access on the runtime host: the host's gh is logged in to a company account. Proposed: the example repositories are public, so `git ls-remote`/fetch need no credentials; if a private repository is ever added, a cafitac fine-grained read-only token is stored for the hub only. Decided before U-RUN; does not change contracts.

## Review findings

- R-1 (accepted, fixed): resource init runs again on update against the kept volume, so seeds must be idempotent — added to C1 together with the rule that update restarts only changed services.
- R-2 (accepted, recorded as O3): runtime-host git credentials belong to a company account; public example repositories avoid mixing identities.
- R-3 (superseded by the revision): the sslip.io public-DNS dependency is gone; `*.localhost` needs no DNS.
- R-5 (accepted, fixed): consumers running inside the VM (ai-qa later) cannot use `*.localhost` to reach the proxy, so the descriptor (C7) also carries the proxy's in-network address; such consumers map hostnames to it (browser host-resolver rules or `--add-host`).
- R-4 (rejected): a separate operation/outbox table per action — the single `operations` table plus label-based reconciliation already covers crash recovery and audit.
- Checklist pass (no independent agent review: not requested for this design): ownership, invariants-to-enforcement, lock order, idempotency, result-unknown recovery, cleanup inventory, capacity guards and A1–A9 trace reviewed; no remaining gap.

## Validation evidence

- `python3 skills/feature-design/scripts/validate_design.py --record ../feature.md` (agent-skills 0a40840): valid, no errors or warnings; digest recorded in the feature record.
- `npx -p @dbml/cli dbml2sql 04-target-schema.dbml --postgres` (@dbml/cli 10.2.0): parsed, 4 tables generated. The partial unique index is created by migration SQL (SQLite), as noted in the schema.
- PlantUML renderer: not installed on this machine; `02`, `05`, `06` were not rendered. Their content is mirrored in the Mermaid review pack.

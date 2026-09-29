# 20260929-preview-hub-v1: Preview Hub v1 — branch-pinned multi-repo preview environments

- Record schema: 4
- Status: IN_PROGRESS
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: SPRINT_CONTROL
- Owner: cafitac (personal project)
- Repository: cafitac/preview-hub (new; companion repos cafitac/preview-example-backend, cafitac/preview-example-frontend)
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S2 extensibility + ai-qa descriptor (sprint 20260930-s2-v1)
- Current PR unit: CONTROL
- Delivery strategy: STANDALONE
- Current delivery bundle: N/A
- Bundle PR topology: N/A
- Architecture authoritative lifecycles: environment lifecycle state machine owned by preview-hub (unknown detail until design)
- Architecture durable effect families: Docker projects, networks, volumes, databases, proxy routes on the runtime host; PR comments on GitHub (S3)
- Architecture external authorities/gateways: GitHub (ref→commit resolution, PR comment events), Docker Engine on the runtime host
- Architecture public idempotency namespaces: environment ID (unknown format until design)
- Architecture runtime/deploy artifacts: per-service container images built from pinned commits; hub CLI
- Architecture failure/recovery owners: preview-hub lifecycle (unknown detail until design)
- Architecture cleanup owners: preview-hub runner (label-scoped cleanup only)
- Architecture repositories/ledgers: hub environment registry (storage choice unknown until design)
- Architecture security/resource parsers: service manifest parser, composition-spec parser, PR comment command parser
- Independent boundary categories: runtime-artifact, failure/recovery-owner
- Architecture split/replan decision: STANDALONE_REEVALUATED
- Failure/recovery owner map: create/update/delete failures owned by hub lifecycle; partial-create cleanup by runner (design input)
- Cleanup inventory map: per-environment Compose project, network, volumes, DB, proxy route, built images, workspace checkouts (design input)
- Parent control record: N/A (this record is the sprint control record)
- Sprint ID: 20260930-s2-v1
- Sprint manifest: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/sprints/20260930-s2-v1.md
- Sprint manifest SHA-256: 800dc41c4792b3c5d7e0c01406fa44b8155770f4972fe3e034053f74babbe8ff
- Authority grant: manifest 20260930-s2-v1 authority matrix + REPO_BOOTSTRAP + RUNTIME_HOST_SETUP + E2E_FIXTURES + MERGE (D7), confirmed by the user 2026-09-29
- Approved delivery scope: U5–U7 per manifest 20260930-s2-v1; merge by main task under D7
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U5, U6, U7 PRs in cafitac/preview-example-notifier, cafitac/preview-example-backend, cafitac/preview-hub (main)
- Delivery finalization evidence: user confirmation 2026-09-29 "응 이 범위로 확정하고 시작해줘" for manifest digest 800dc41c4792b3c5d7e0c01406fa44b8155770f4972fe3e034053f74babbe8ff
- Eligible unit IDs: U5, U6, U7
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U5=INHERIT, U6=INHERIT, U7=INHERIT
- Unit review cycle budget map: U5=INHERIT, U6=INHERIT, U7=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repositories; main is the only integration branch (no develop, no deployment coupling).
- Initialization base SHA: pending feature-init
- Worktree/branch: pending feature-init
- Verification topology: LOCAL_LIGHT + RUNTIME_HOST_E2E + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope); runtime host for Docker environments and E2E is trading-macstudio (user decision 2026-09-29)
- Remote test runner profile: N/A
- Remote test fallback: USER_OPT_IN
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: NOT_CREATED
- Worktree cleanup evidence:
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/feature.md
- Record provenance: Created by feature-plan on 2026-09-29 before any repository exists; no worktree handoff has occurred yet.
- External links: none yet
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/design
- Design approval: revision 2 APPROVED by user 2026-09-29 ("승인하고 계속 진행해줘") for digest 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2; revision 1 (75c46b73…) superseded
- Design evidence identity: artifact_set_sha256 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2 (revision 2, all-containerized runtime; 10 artifacts: 00,01,02,04,05,06,07,08,09,11)
- Service boundary E2E: RUNTIME_HOST_E2E (two example services + DB on trading-macstudio)
- Service boundary waiver: N/A
- Repository-wide checks: to be defined at repository creation (ruff, pyright/mypy, pytest for hub)

## Workflow cursor

- Workflow stage: FEATURE_PLAN
- Last completed stage: FEATURE_PLAN
- Next eligible action: AGENT_SQUAD (start sprint 20260929-s1-v2)
- Next action class: LOCAL_CONTINUE
- Gate state: NONE
- Gate reason:
- Active run:
- Evidence identity:

## Autonomous sprint

- Sprint state: SPRINT_COMPLETE
- Manifest version: 1 (S2)
- Manifest confirmation: user, 2026-09-29, "응 이 범위로 확정하고 시작해줘", digest 800dc41c4792b3c5d7e0c01406fa44b8155770f4972fe3e034053f74babbe8ff re-hashed unchanged
- Planning base SHA: preview-example-backend 885a373810a81e1db3972c11955d717a99b94a10; preview-hub 11d0aa87a9dfeb66582528e5d7cce2f4cd3c5296; notifier at bootstrap
- Base drift policy: ALLOW_IF_DISJOINT
- Execution base SHA: notifier 7ab7aa87caeb707e6847e9826fbfbe9876fa4cc6 (bootstrap); backend 885a373810a81e1db3972c11955d717a99b94a10; preview-hub 11d0aa87a9dfeb66582528e5d7cce2f4cd3c5296
- Started: 2026-09-29 (S2)
- Expires: 2026-10-06 23:59 KST
- Desired finish state: READY_FOR_USER_MERGE
- Learning mode: PROPOSE
- Eligible unit IDs: U1, U2, U3, U4
- WIP / unit / repair / retry budgets: WIP 2 / units 3 / repair 2 (+3 runtime) per unit / CI retry 2 (consumed: 0)
- Setup reservations: none (converted to claims)
- Active PR units: none
- Remaining eligible units: U5=MERGED bd5faec3, U6=MERGED 544fd35e, U7=MERGED fe3f5cbb
- Authority matrix: see manifest
- Selection rule: U5 and U6 in parallel; U7 after both merges are read back
- Stop and escalation: see manifest
- Boundary decision: S2 complete 2026-09-29; core value 2 proven (A6) and descriptor validated (A8); next: S3 PR comment bot needs planning (open O2)

## Outcome

One command (CLI, later a PR comment) creates an isolated environment that runs services from different repositories, each pinned to a chosen branch resolved to an exact commit, wired to each other, with its own database; adding a third service needs only that service's manifest, never a hub code change. The environment description is published in a stable format that a later ai-qa project can consume.

## Requirements

- R1 [MUST]: Service manifest contract (one file per service repository): build, ports, health check, dependencies on other services, injected environment (e.g. the frontend receives the backend URL), data needs (database, migrate, seed).
- R2 [MUST]: Composition spec: service → ref (branch/tag/SHA), resolved to an immutable commit at create time and stored so the same environment can be recreated exactly.
- R3 [MUST]: Environment lifecycle with explicit states (create, ready, update, expire, delete, failed), TTL, idempotent create/delete, list/status.
- R4 [MUST]: Isolation on a shared Docker host: per-environment Compose project, network, volumes and database; hostname routing through one reverse proxy; every created object labelled and cleaned up only by its own labels (the host runs other projects' containers).
- R5 [MUST]: Runner abstraction; v1 ships only the Docker Compose runner. Adding a k3d or cloud runner must not change lifecycle or composition code.
- R6 [MUST]: Extensibility proof: a third example service joins an environment through its manifest alone, with zero hub code change.
- R7 [MUST]: CLI: up / status / list / down (and update refs).
- R8 [SHOULD]: PR comment bot: a command in a PR comment (e.g. `/preview up backend=feat-x`) runs the hub on a self-hosted GitHub Actions runner on trading-macstudio and replies with URLs and pinned commits.
- R9 [MUST]: hub ↔ ai-qa contract: versioned environment descriptor (URLs, services, pinned commits, readiness, test credentials) and a QA result report schema; ai-qa itself is not built here.
- R10 [DEFERRED]: k3d and cloud runners, web dashboard, ai-qa implementation, multi-host scheduling.
- R11 [OUT_OF_SCOPE]: any Earlypay code, configuration, rules or data.

## Acceptance contract

- A1 (R1,R2,R7): Given backend branch `feat-x` and frontend `main`, `up` creates an environment whose status shows each service with the exact commit SHA the branch pointed to at create time; later branch moves do not change that environment. Evidence: runtime E2E on trading-macstudio.
- A2 (R4): Two environments with different branch combinations run at the same time; each frontend calls its own backend, each backend uses its own database; data written in one is absent in the other. Evidence: runtime E2E.
- A3 (R4): `down` removes exactly that environment's containers, networks, volumes, database and route; other environments and unrelated containers on the host are untouched. Evidence: before/after label and name inventory.
- A4 (R3): Repeating `up` for the same environment ID or `down` for an already deleted one is safe and reports the current state; an expired environment is removed by the TTL sweep. Evidence: automated tests + runtime E2E.
- A5 (R3): A build or health-check failure leaves the environment in a failed state with the failing service and log excerpt, and a subsequent `down` cleans every partial object. Evidence: runtime E2E with a deliberately broken branch.
- A6 (R6): Adding the third example service's manifest (and nothing in preview-hub) lets `up` include it and wire it to the backend. Evidence: diff shows zero preview-hub changes + runtime E2E.
- A7 (R5): The lifecycle and composition layers depend only on the runner interface; a fake runner in tests drives the full lifecycle. Evidence: automated tests.
- A8 (R9): `status --format descriptor` emits a document that validates against the published descriptor schema; a sample report validates against the report schema. Evidence: schema tests.
- A9 (R8): A `/preview up ...` comment on a PR in an example repository produces a reply with URLs and pinned commits; `/preview down` removes it; commands from non-collaborators are rejected. Evidence: live PR on a cafitac repository.

## Design contract

- Profile decision: STANDARD — new lifecycle state machine, multi-component composition, shared-host isolation and two public contracts (manifest, descriptor); no money or irreversible data.
- Required artifacts: service manifest schema + examples; composition spec schema and ref-resolution rules; lifecycle state diagram with transitions, idempotency and failure/cleanup rules; isolation model (naming, labels, networks, volumes, DB, proxy/hostnames reachable from the MacBook); runner interface; environment registry storage; ai-qa descriptor and report schemas; PR-comment command grammar and authorization.
- Current-system evidence: none (greenfield); runtime host facts to collect: trading-macstudio Docker version, existing containers/ports, Tailscale reachability, disk.
- Design-to-acceptance trace: every A1–A9 must map to a design artifact.
- Open design inputs: hostname scheme reachable from other machines (wildcard DNS vs sslip.io-style vs Tailscale), image build cache strategy, where the hub registry lives, runner host access for the PR bot.

## Delivery map

### S0: Contracts design

- Status: PLANNED
- Outcome: approved design artifacts for R1–R9
- Included acceptance: design traces for A1–A9
- Non-goals: code
- Estimate: 0.5–1 day (confidence medium)
- PR map:
  - N/A (design record only)
- QA checkpoint: user design approval (required before the sprint manifest)
- Rollout/rollback: N/A

### S1: Walking skeleton — two repos, two branches, one environment (core value 1)

- Status: PLANNED (coarse until design approval)
- Outcome: A1–A5, A7 on trading-macstudio
- Estimate: 2–4 days (confidence low-medium)
- PR map:
  - To be derived from the approved design (expected: example-backend repo, example-frontend repo, hub core)
- QA checkpoint: runtime E2E on trading-macstudio

### S2: Extensibility proof (core value 2)

- Status: PLANNED (coarse)
- Outcome: A6 with a third example service
- Estimate: 1–2 days

### S3: PR comment bot

- Status: PLANNED (coarse)
- Outcome: A9 via self-hosted runner on trading-macstudio
- Estimate: 1–2 days

### S4: ai-qa handoff contract

- Status: PLANNED (coarse)
- Outcome: A8 published schemas and a sample consumer check
- Estimate: 0.5–1 day

- Delivery bundles: none
- QA checkpoint: runtime E2E on trading-macstudio per slice
- Rollout/rollback: personal repositories; no deployment. Environments are disposable; cleanup is label-scoped.

## Safety and rollout

- Release state: N/A
- Activation mode: N/A
- Shared-host guard: never delete by port or broad filter on trading-macstudio; only objects carrying the hub's labels.

## Decisions and assumptions

### D1: Repository layout

- Status: CONFIRMED
- User answer: hub + 서비스별 저장소 (2026-09-29)
- Normalized value: cafitac/preview-hub (Python) + separate example service repositories

### D2: Runtime

- Status: CONFIRMED
- User answer: Docker Compose로 진행 (2026-09-29)
- Normalized value: Compose runner first behind a runner interface; runtime host trading-macstudio (user, 2026-09-29: 테스트는 macstudio에서, 인프라도 들어가야 하니까)

### D3: Entry points

- Status: CONFIRMED
- User answer: CLI 또는 PR comment 봇 (2026-09-29)
- Normalized value: CLI in S1, PR comment bot in S3

### D4: Database

- Status: CONFIRMED
- User answer: 넣는다
- Normalized value: example backend with PostgreSQL; per-environment database is part of the manifest contract

### D5: Design depth and execution style

- Status: CONFIRMED
- User answer: 표준 설계, 승인 범위 내 자율
- Normalized value: STANDARD design approved by the user first; then AUTONOMOUS_SPRINT manifest

### D6: Example stacks (SAFE_ASSUMPTION)

- Status: PENDING
- Options and recommendation: backend FastAPI + PostgreSQL, frontend Vite + React static build served by a small web server; third service a small worker/notification API
- Scope / authority: reversible; confirm with the design

### D7: Merge authority for cafitac repositories

- Status: CONFIRMED
- User answer: "너가 다 해줘도 돼 머지는 cafitac 프로젝트잖아" (2026-09-29)
- Normalized value: the main task may squash-merge a unit PR into main in the cafitac personal repositories after every exact-head gate (2-of-2 clean review, green required CI) and read back the merge; applies to this sprint and later cafitac sprints. The manifest's merge boundary (user-owned) is superseded by this explicit user decision; no other authority changes.
- Scope / authority: cafitac/preview-hub, cafitac/preview-example-* only; never Earlypay repositories.
- Confirmed at: 2026-09-29

### D8: U3 review cycle budget extension

- Status: CONFIRMED
- User answer: "1번으로 진행해줘" (2026-09-29) — option 1 of the budget-exhaustion packet
- Normalized value: U3 review cycle budget raised from 5 to 7 (U3 only); the 2-of-2 clean quorum gate is unchanged.
- Confirmed at: 2026-09-29

## Open questions

- None blocking planning. Design inputs listed under Design contract.

## Progress and evidence

- 2026-09-29: Planning record created; no repository, design, implementation or external write yet.
- 2026-09-29: S0 design produced (STANDARD). Runtime host facts collected read-only. validate_design valid; DBML parsed with @dbml/cli 10.2.0; PlantUML not rendered (no renderer). Review pass: 4 findings (3 accepted, 1 rejected). Awaiting Design Gate for digest 75c46b73d4e7dd8f9ed3efd8bbddbed3b99556b58918fffda5a09eb4528f21ef.
- 2026-09-29: Design Gate approved by the user for digest 75c46b73d4e7dd8f9ed3efd8bbddbed3b99556b58918fffda5a09eb4528f21ef (revalidated unchanged). Next: feature-plan builds the autonomous sprint manifest from the approved design.
- 2026-09-29: Before sprint start the user asked that every runtime resource be containerized and nothing run directly on the Mac Studio host. Design set to REVISE (previous approved digest 75c46b73… preserved in history); sprint manifest 20260929-s1-v1 (bc862eb5…) was never confirmed and is superseded.
- 2026-09-29: Design revision 2 (everything containerized inside the preview-hub Colima VM; hub as container phub-hub with registry/caches on volumes; *.localhost + SSH local forward instead of sslip.io/tailscale serve; two-layer disk guard; descriptor proxy address). validate_design valid, DBML parsed. Awaiting approval for digest 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2.
- 2026-09-29: Design revision 2 approved by the user for digest 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2 (revalidated unchanged).
- 2026-09-29: Sprint manifest 20260929-s1-v2 confirmed by the user (digest 29d5b493dca2f9fc689c59d237d07e82dc24b905b6e11cd99664e35477324b5d, re-hashed unchanged). Record converted to SPRINT_CONTROL, state SPRINT_PLANNED.
- 2026-09-29: SPRINT_RUNNING. Repositories created (public, MIT, bootstrap README/.gitignore/LICENSE): preview-hub c93fa5c2, preview-example-backend 25770cd8, preview-example-frontend 1ab3ef6b. Per-repo git identity = cafitac noreply; push credential fetched per call from the cafitac gh token (no token stored). U1–U3 reserved and initialized; claims activated.
- 2026-09-29: User granted merge authority for the cafitac repositories (D7).
- 2026-09-29: U3 exhausted review budget 5 (cycle 5: 3 minor findings); user extended U3 budget to 7 (D8).
- 2026-09-29: U1, U2, U3 merged (see unit records). U4 dependencies satisfied; U4 base = preview-hub main ee96ab0e (moved only by its own dependency U3; disjoint per ALLOW_IF_DISJOINT).
- 2026-09-29: U4 RUNTIME_HOST_SETUP: `colima start --profile preview-hub --cpu 4 --memory 8 --disk 40 --vm-type vz` on trading-macstudio (Docker 29.5.2). Incident: colima switched the host's current docker context to colima-preview-hub (a host setting change); restored immediately to `default` (verified) before any other command used it. Fix carried into U4: bootstrap uses `colima start --activate=false`.
- 2026-09-29: SPRINT_COMPLETE for 20260929-s1-v2: U1–U4 merged; runtime E2E A1–A5 green on trading-macstudio (hub stack left running in the preview-hub VM for S2). Review cycles used: U1 4, U2 3, U3 6 (budget 7 by D8), U4 5.
- 2026-09-29: S2 manifest 20260930-s2-v1 confirmed by the user (digest 800dc41c4792b3c5d7e0c01406fa44b8155770f4972fe3e034053f74babbe8ff); SPRINT_RUNNING.
- 2026-09-29: notifier repository created (public, MIT, bootstrap 7ab7aa87); U5/U6 reserved, initialized and claimed.
- 2026-09-29: SPRINT_PAUSED — codex worker lane unavailable: 'gpt-6-astra' not supported for Codex with a ChatGPT account (2 attempts, STOP_FOR_USER). Awaiting user decision on the worker route. U6 merged before the pause (544fd35e).
- 2026-09-29: Cause found: the MacBook Codex login changed at 14:25; after the user reconnected an account (14:29) a minimal probe with gpt-6-astra returned OK. Route unchanged. Sprint resumed. (Mac Studio Codex token is invalidated — user re-login pending; not needed for this sprint's local workers.)
- 2026-09-29: U5 merged (bd5faec3); U5 and U6 merges read back; U7 reserved and claimed.
- 2026-09-29: SPRINT_COMPLETE for 20260930-s2-v1: U5–U7 merged; E2E A1–A6 + A8 green on trading-macstudio; hub/schemas code unchanged by S2. Review cycles: U5 3, U6 1, U7 3. One pause: Codex worker lane unavailable after a login change (resolved by the user).

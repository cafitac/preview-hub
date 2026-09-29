# 20260929-preview-hub-v1/U1: Example backend (FastAPI + PostgreSQL)

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-example-backend
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S1 walking skeleton
- Current PR unit: U1
- Delivery strategy: STANDALONE
- Current delivery bundle: N/A
- Bundle PR topology: N/A
- Architecture authoritative lifecycles: see parent control record
- Architecture durable effect families: see parent control record
- Architecture external authorities/gateways: see parent control record
- Architecture public idempotency namespaces: see parent control record
- Architecture runtime/deploy artifacts: see parent control record
- Architecture failure/recovery owners: see parent control record
- Architecture cleanup owners: see parent control record
- Architecture repositories/ledgers: see parent control record
- Architecture security/resource parsers: see parent control record
- Independent boundary categories: NONE
- Architecture split/replan decision: STANDALONE_REEVALUATED
- Failure/recovery owner map: see parent control record
- Cleanup inventory map: see parent control record
- Parent control record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/feature.md
- Sprint ID: 20260929-s1-v2
- Sprint manifest: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/sprints/20260929-s1-v2.md
- Sprint manifest SHA-256: 29d5b493dca2f9fc689c59d237d07e82dc24b905b6e11cd99664e35477324b5d
- Authority grant: manifest 20260929-s1-v2 unit U1 authority subset
- Approved delivery scope: manifest 20260929-s1-v2 unit U1
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U1 PR in cafitac/preview-example-backend to main
- Delivery finalization evidence: user confirmation of manifest digest 29d5b493… on 2026-09-29
- Eligible unit IDs: U1
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U1=INHERIT
- Unit review cycle budget map: U1=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 25770cd8e5d5ccaec55ded09def7c2603b325166
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u1-example-backend (feat/u1-notes-api)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U1/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-example-backend/pull/1 (merged)
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/design
- Design approval: parent control record, digest 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2
- Design evidence identity: 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2
- Service boundary E2E: N/A (runtime E2E belongs to U4)
- Service boundary waiver: N/A
- Repository-wide checks: see Progress

## Workflow cursor

- Workflow stage: FEATURE_DEVELOP
- Last completed stage: CODE_PUSH
- Next eligible action: NONE (terminal)
- Next action class: LOCAL_CONTINUE
- Gate state: NONE
- Gate reason:
- Active run:
- Evidence identity:

## Outcome

FastAPI notes API (GET/POST /api/notes, GET /healthz) with SQLAlchemy + Alembic on PostgreSQL 16, idempotent seed, CORS from CORS_ORIGINS, Dockerfile, preview.yaml per contract C1, CI (ruff, type check, pytest against a PostgreSQL service).

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A2 backend side (per-environment DB), A5 health endpoint

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S1: Example backend (FastAPI + PostgreSQL)

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A2 backend side (per-environment DB), A5 health endpoint
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U1: feat/u1-notes-api -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260929-s1-v2 unit U1

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 25770cd8e5d5ccaec55ded09def7c2603b325166, worktree /Users/reddit/Project/cafitac/.worktrees/u1-example-backend.
- 2026-09-29: Local checks green (ruff, format, mypy, 26 pytest on PostgreSQL 16, docker build + migrate/seed x2/health/API smoke). Reviews: cycles 1–3 findings (6) fixed; cycle 4 clean 2/2 on patch 8d87b4f029b1. Commit 0fad617b pushed; PR #1 CI check success; Ready; squash-merged under D7 as 885a3738; branch and worktree removed.

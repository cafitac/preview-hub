# 20260929-preview-hub-v1/U2: Example frontend (Vite + React)

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-example-frontend
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S1 walking skeleton
- Current PR unit: U2
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
- Authority grant: manifest 20260929-s1-v2 unit U2 authority subset
- Approved delivery scope: manifest 20260929-s1-v2 unit U2
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U2 PR in cafitac/preview-example-frontend to main
- Delivery finalization evidence: user confirmation of manifest digest 29d5b493… on 2026-09-29
- Eligible unit IDs: U2
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U2=INHERIT
- Unit review cycle budget map: U2=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 1ab3ef6bf4f59f9f0e28aa207e5ef043f6398ae0
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u2-example-frontend (feat/u2-notes-ui)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U2/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-example-frontend/pull/1 (Ready, head 8290a2a2)
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

Vite + React notes page listing and creating notes; API base URL read at runtime from /config.js written by the container entrypoint from API_URL; static server image; preview.yaml per C1 (API_URL: ${services.backend.public_url}); CI (lint, type check, unit tests, build).

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A2 frontend side (calls its own environment's backend)

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S1: Example frontend (Vite + React)

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A2 frontend side (calls its own environment's backend)
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U2: feat/u2-notes-ui -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260929-s1-v2 unit U2

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 1ab3ef6bf4f59f9f0e28aa207e5ef043f6398ae0, worktree /Users/reddit/Project/cafitac/.worktrees/u2-example-frontend.
- 2026-09-29: Local checks (npm ci/lint/typecheck/52 tests + entrypoint 3/build/docker build) green. Reviews: cycle 1 (1 clean, 2 findings fixed), cycle 2 (1 clean, 1 finding fixed), cycle 3 clean 2/2 on patch af21626e15b8. Commit 8290a2a2 pushed; PR #1 CI `check` success; marked Ready.
- 2026-09-29: Squash-merged by the main task under user decision D7 after gate re-check (head 8290a2a2, CI pass): merge commit a9324753. Remote branch deleted; worktree removed; local branch deleted.

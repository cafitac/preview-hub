# 20260929-preview-hub-v1/U3: Hub core (contracts, registry, lifecycle)

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-hub
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S1 walking skeleton
- Current PR unit: U3
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
- Authority grant: manifest 20260929-s1-v2 unit U3 authority subset
- Approved delivery scope: manifest 20260929-s1-v2 unit U3
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U3 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 29d5b493… on 2026-09-29
- Eligible unit IDs: U3
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U3=INHERIT
- Unit review cycle budget map: U3=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: c93fa5c20acb4c946ed8f0161ab33865acff3dbb
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u3-hub-core (feat/u3-hub-core)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U3/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/1 (merged ee96ab0e)
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

Python 3.12 package (uv) with JSON Schemas for C1–C3, parsers/validators, catalog completion, GitSource (git ls-remote), PlanBuilder, SQLite registry schema rev 1 with migrations, lifecycle UseCases with per-environment file locks and stale-operation recovery, Runner protocol + FakeRunner, phub CLI.

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A1 pinning logic, A4, A5 state handling, A7

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S1: Hub core (contracts, registry, lifecycle)

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A1 pinning logic, A4, A5 state handling, A7
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U3: feat/u3-hub-core -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260929-s1-v2 unit U3

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base c93fa5c20acb4c946ed8f0161ab33865acff3dbb, worktree /Users/reddit/Project/cafitac/.worktrees/u3-hub-core.
- 2026-09-29: Local checks green (ruff, format, pyright strict, 235 pytest). Reviews: cycles 1–5 findings (14) fixed; budget extended to 7 (D8); cycle 6 clean 2/2 on patch e8eb5cf2283d. Commit 722be18d; PR #1 CI checks pass; Ready; squash-merged under D7 as ee96ab0e; worktree/branch removed. Deviation: the .dev record move is deferred to a record-only PR at sprint end (moving it would have changed the reviewed snapshot while the main task still writes it).

# 20260929-preview-hub-v1/U5: Notifier service

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-example-notifier
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S2 extensibility
- Current PR unit: U5
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
- Sprint ID: 20260930-s2-v1
- Sprint manifest: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/sprints/20260930-s2-v1.md
- Sprint manifest SHA-256: 800dc41c4792b3c5d7e0c01406fa44b8155770f4972fe3e034053f74babbe8ff
- Authority grant: manifest 20260930-s2-v1 unit U5 authority subset
- Approved delivery scope: manifest 20260930-s2-v1 unit U5
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U5 PR in cafitac/preview-example-notifier to main
- Delivery finalization evidence: user confirmation of manifest digest 800dc41c… on 2026-09-29
- Eligible unit IDs: U5
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U5=INHERIT
- Unit review cycle budget map: U5=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 7ab7aa87caeb707e6847e9826fbfbe9876fa4cc6
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u5-notifier (feat/u5-notifier)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U5/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-example-notifier/pull/1 (merged bd5faec3)
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

FastAPI notifier: POST /api/notify (202), GET /api/notifications (bounded in-memory 1000), /healthz; uv.lock-pinned non-root image; preview.yaml per C1 (service notifier, port 8000, internal only); CI.

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A6 notifier side

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S2: Notifier service

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A6 notifier side
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U5: feat/u5-notifier -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s2-v1 unit U5

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 7ab7aa87caeb707e6847e9826fbfbe9876fa4cc6, worktree /Users/reddit/Project/cafitac/.worktrees/u5-notifier.
- 2026-09-29: ruff/mypy/33 pytest/docker build + run smoke green. Reviews: cycle 1 (2 findings, same root cause) fixed; worker lane paused by a Codex login change and resumed after the user reconnected; cycle 2 (2 findings) fixed; cycle 3 clean 2/2. PR #1 CI pass; squash-merged under D7 as bd5faec3; worktree/branch removed.

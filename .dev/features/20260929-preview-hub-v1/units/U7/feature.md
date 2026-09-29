# 20260929-preview-hub-v1/U7: Catalog entry and A6/A8 E2E

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-hub
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S2 extensibility
- Current PR unit: U7
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
- Authority grant: manifest 20260930-s2-v1 unit U7 authority subset
- Approved delivery scope: manifest 20260930-s2-v1 unit U7
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U7 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 800dc41c… on 2026-09-29
- Eligible unit IDs: U7
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U7=INHERIT
- Unit review cycle budget map: U7=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 11d0aa87a9dfeb66582528e5d7cce2f4cd3c5296
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u7-notifier-catalog (feat/u7-notifier-catalog)
- Verification topology: LOCAL_LIGHT + RUNTIME_HOST_E2E + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U7/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/4 (merged fe3f5cbb)
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

Catalog entry notifier (include on_request), E2E A6 (a)-(d) and A8, README 'adding a service'; no change under preview_hub/.

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A6, A8, A1–A5 regression

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S2: Catalog entry and A6/A8 E2E

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A6, A8, A1–A5 regression
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U7: feat/u7-notifier-catalog -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s2-v1 unit U7

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 11d0aa87a9dfeb66582528e5d7cce2f4cd3c5296, worktree /Users/reddit/Project/cafitac/.worktrees/u7-notifier-catalog.
- 2026-09-29: Catalog line + A6/A8 E2E; no change under preview_hub/ or schemas/ (diff 0 lines, 11d0aa87..fe3f5cbb). Reviews: cycle 1 (1 finding: date-time format extra) fixed via pyproject jsonschema[format-nongpl] + lock; cycle 2 (1 finding: validator selection) fixed; cycle 3 clean 2/2 on 332611ce. E2E A1–A6 + A8 passed on a44bf12, 0b6cc0e and 332611c (logs in units/U7/evidence/). CI pass; squash-merged under D7 as fe3f5cbb.

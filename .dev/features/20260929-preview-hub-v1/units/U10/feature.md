# 20260929-preview-hub-v1/U10: pr-<n> refs and shared GitHub client

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-hub
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S4 central dashboard and public access
- Current PR unit: U10
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
- Sprint ID: 20260930-s4-v1
- Sprint manifest: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/sprints/20260930-s4-v1.md
- Sprint manifest SHA-256: 86c6c422c953e9b720732f674d0f29845dd385d2ef13e9cc07bf9d42669dd04d
- Authority grant: manifest 20260930-s4-v1 unit U10 authority subset
- Approved delivery scope: manifest 20260930-s4-v1 unit U10
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U10 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 86c6c422… on 2026-09-29
- Eligible unit IDs: U10
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U10=INHERIT
- Unit review cycle budget map: U10=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 1d95074fc6edd2aba988b7a0b17e1d739d30bed9
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u10-pr-refs (feat/u10-pr-refs)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA (live check in U14)
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U10/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/9
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/design
- Design approval: parent control record, digest 0093cda1e186286408260256f21573a131cc35c2d5e8c6aedfbdbe6185216199
- Design evidence identity: 0093cda1e186286408260256f21573a131cc35c2d5e8c6aedfbdbe6185216199
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

Shared GitHub client and pr-<n> ref resolution per manifest U10 (A11).

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A9 live, A1-A6/A8 regression

## Design contract

- Profile decision: STANDARD, parent design approved (digest 084565e1…); this unit implements the listed contracts without changing them.

## Delivery map

### S3: Live PR bot E2E

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A9 live, A1-A6/A8 regression
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U10: feat/u10-pr-refs -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s4-v1 unit U10

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 1d95074fc6edd2aba988b7a0b17e1d739d30bed9, worktree /Users/reddit/Project/cafitac/.worktrees/u10-pr-refs.
- 2026-09-29: Worker (Codex) implemented U10; main-task check: ruff clean, format clean, pyright 0 errors, pytest 485 passed, diff --check clean. Review cycle 1 dispatched.
- 2026-09-29: Review cycle 1: reviewer-1 clean, reviewer-2 1 finding (pr ref on a local-path repository reached GitHub) fixed by the worker; 486 passed. Cycle 2 dispatched.
- 2026-09-29: Review cycle 2 clean 2/2 on 05d7a74f. PR #9 CI pass; squash-merged under D7 as 541fa27c; worktree/branch removed.

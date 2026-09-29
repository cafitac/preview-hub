# 20260929-preview-hub-v1/U8: Polling PR comment bot

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-hub
- Created: 2026-09-29
- Updated: 2026-09-29
- Current slice: S3 PR comment bot
- Current PR unit: U8
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
- Sprint ID: 20260930-s3-v1
- Sprint manifest: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/sprints/20260930-s3-v1.md
- Sprint manifest SHA-256: ea1d996218f502805520967ea295895b25fa7d77e38840a0ef9a80fc303718a0
- Authority grant: manifest 20260930-s3-v1 unit U8 authority subset
- Approved delivery scope: manifest 20260930-s3-v1 unit U8
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U8 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest ea1d9962… on 2026-09-29
- Eligible unit IDs: U8
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U8=INHERIT
- Unit review cycle budget map: U8=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: ed54eed49aa708a59609f6ed7a1ddae6e6417a05
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u8-bot (feat/u8-polling-bot)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U8/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/6 (merged bce97aa2)
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/design
- Design approval: parent control record, digest 084565e1635122f4f8db354bd59709eebedd74bd4829bf023be8de054dd2581f
- Design evidence identity: 084565e1635122f4f8db354bd59709eebedd74bd4829bf023be8de054dd2581f
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

phub-bot per manifest U8.

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A9 (a)-(f) unit level

## Design contract

- Profile decision: STANDARD, parent design approved (digest 084565e1…); this unit implements the listed contracts without changing them.

## Delivery map

### S3: Polling PR comment bot

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A9 (a)-(f) unit level
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U8: feat/u8-polling-bot -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s3-v1 unit U8

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base ed54eed49aa708a59609f6ed7a1ddae6e6417a05, worktree /Users/reddit/Project/cafitac/.worktrees/u8-bot.
- 2026-09-29: Main-task validation found 2 issues (stack needed the token to start; bot data stored outside the approved schema) fixed with reviewer findings. Reviews: cycles 1–6 findings (19) fixed; budget extended to 7 (D9); cycle 7 clean 2/2 on 374c1df4. Live VM: stack starts without a token, bot idles. CI pass; squash-merged under D7 as bce97aa2; worktree/branch removed.

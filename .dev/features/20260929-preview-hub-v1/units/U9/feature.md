# 20260929-preview-hub-v1/U9: Live PR bot E2E

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
- Current PR unit: U9
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
- Authority grant: manifest 20260930-s3-v1 unit U9 authority subset
- Approved delivery scope: manifest 20260930-s3-v1 unit U9
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U9 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest ea1d9962… on 2026-09-29
- Eligible unit IDs: U9
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U9=INHERIT
- Unit review cycle budget map: U9=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: bce97aa294db4004090539dae4555856c69a0d9a
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u9-bot-e2e (feat/u9-bot-e2e)
- Verification topology: LOCAL_LIGHT + RUNTIME_HOST_E2E + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U9/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/7
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

e2e/bot.sh live PR scenario, README PR bot section, bot-token prompt, auth-failure cooldown fix.

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
  - U9: feat/u9-bot-e2e -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s3-v1 unit U9

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base bce97aa294db4004090539dae4555856c69a0d9a, worktree /Users/reddit/Project/cafitac/.worktrees/u9-bot-e2e.
- 2026-09-29: e2e/bot.sh (live PR E2E), auth-failure log distinction, bot-token prompt text, README bot section. First live run showed the reply POST rejected (token lacked Pull requests write; evidence/e2e-bot-run1-f9e24b2-reply-permission-missing.log); after the user fixed the token permissions, A9(a)-(e) passed live on f9e24b2 (evidence/e2e-bot-run2-f9e24b2.log) and regression A1-A6/A8 passed (evidence/e2e-regression-f9e24b2.log). Review cycle 1 clean 2/2 on f9e24b2; 453 tests pass. PR #7 CI pass; squash-merged under D7 as de6c5e03; worktree/branch removed; fixture branch e2e-alt-s3 deleted.

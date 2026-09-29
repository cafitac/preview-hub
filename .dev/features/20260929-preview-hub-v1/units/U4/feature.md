# 20260929-preview-hub-v1/U4: Compose runner, proxy and runtime-host E2E

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
- Current PR unit: U4
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
- Authority grant: manifest 20260929-s1-v2 unit U4 authority subset
- Approved delivery scope: manifest 20260929-s1-v2 unit U4
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U4 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 29d5b493… on 2026-09-29
- Eligible unit IDs: U4
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U4=INHERIT
- Unit review cycle budget map: U4=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: ee96ab0e592c5be896bb7a74eaf36cb8c9f8bf47
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u4-compose-runner (feat/u4-compose-runner)
- Verification topology: LOCAL_LIGHT + RUNTIME_HOST_E2E + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U4/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/2 (merged 96a46def)
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/design
- Design approval: parent control record, digest 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2
- Design evidence identity: 54b3d04db0dbab5bc42a20ddb2042601c86f8c3e701b18d8c199e67461ef98a2
- Service boundary E2E: RUNTIME_HOST_E2E A1–A5 in Colima VM preview-hub on trading-macstudio
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

ComposeRunner, hub container image + hub stack (phub-hub, phub-proxy Traefik, volumes phub-state/phub-src) with in-container gc loop, daemon-identity/VM-disk/capacity guards, MacBook phub wrapper (ssh + docker exec, host disk check, tunnel), VM bootstrap script, scripted E2E A1–A5.

## Requirements

- See parent control record R1–R11; this unit's scope is in Outcome.

## Acceptance contract

- A1, A2, A3, A4, A5 (runtime on trading-macstudio)

## Design contract

- Profile decision: STANDARD, parent design approved (digest 54b3d04d…); this unit implements the listed contracts without changing them.

## Delivery map

### S1: Compose runner, proxy and runtime-host E2E

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A1, A2, A3, A4, A5 (runtime on trading-macstudio)
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - U4: feat/u4-compose-runner -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260929-s1-v2 unit U4

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base ee96ab0e592c5be896bb7a74eaf36cb8c9f8bf47, worktree /Users/reddit/Project/cafitac/.worktrees/u4-compose-runner.
- 2026-09-29: Runtime-host findings fixed in two batches (BuildKit, remote PATH, colima --activate=false, --source-dir, migration file filter, typed YAML values). Review cycles 1–4 findings (8) fixed; cycle 5 clean 2/2 on head f0ce8c66. E2E A1–A5 passed on trading-macstudio on every pushed head (5446573, 2ee4d99, 0671fe1, f0ce8c6) via git-mode bootstrap; logs in units/U4/evidence/. CI checks pass; Ready; squash-merged under D7 as 96a46def; worktree/branch removed.

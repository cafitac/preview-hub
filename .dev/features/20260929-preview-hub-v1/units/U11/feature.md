# 20260929-preview-hub-v1/U11: public access (routing, verifier, cloudflared)

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
- Current PR unit: U11
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
- Authority grant: manifest 20260930-s4-v1 unit U11 authority subset
- Approved delivery scope: manifest 20260930-s4-v1 unit U11
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U11 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 86c6c422… on 2026-09-29
- Eligible unit IDs: U11
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U11=INHERIT
- Unit review cycle budget map: U11=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 541fa27ca1aba524ad356c89bc172e50c41eb9b4
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u11-public-access (feat/u11-public-access)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA + RUNTIME_HOST smoke (in-VM routing); live in U14
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U11/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/11
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

Catalog public_access, one-origin routing, Access JWT verifier, minimal HTTP server, cloudflared service per manifest U11 (A12, A13 unit level).

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
  - U11: feat/u11-public-access -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s4-v1 unit U11

## Open questions

- None.

## Progress and evidence

- 2026-09-29: Reserved and initialized by the main task: base 541fa27ca1aba524ad356c89bc172e50c41eb9b4, worktree /Users/reddit/Project/cafitac/.worktrees/u11-public-access.
- 2026-09-29: Worker (Codex) implemented U11 (sandbox could not install deps); main task ran uv lock/sync (starlette 1.7.0, uvicorn 0.54.0, jinja2, PyJWT[crypto]); ruff clean, format clean, pyright 0 errors, pytest 537 passed, sh -n ok. Review cycle 1 dispatched.
- 2026-09-29: Review cycle 1: 2 reviewers found the unguarded GC thread (fixed: per-iteration catch + log, test). Main check: pyright 0, pytest 538 passed. Cycle 2 dispatched.
- 2026-09-29: Review cycle 2 findings (path prefix overlap between similar subdomains; README catalog location) fixed; pyright 0, pytest 539 passed. Cycle 3 dispatched.
- 2026-09-29: Review cycle 3: reviewer-1 clean, reviewer-2 1 finding (update after enabling public_access skipped unchanged services while persisting new URLs) fixed by the worker. U13 merged meanwhile; main 28dd2db merged into the branch (README conflict resolved keeping both sections); pytest 569 passed. Cycle 4 dispatched against base 28dd2db.
- 2026-09-29: Runtime smoke on trading-macstudio VM (vm-bootstrap --source-dir, head 3483004): stack up, no restarts; public profile skipped ('public access not configured'); hub /healthz 200, /auth/verify 401, / 401, /api/environments 401 without JWT (fail closed). Note: colima prints a harmless 'fatal exit status 1' for the absent-file test. Host free 37 GiB, docker context default.
- 2026-09-29: Review cycle 4 clean 2/2 on 3483004a. PR #11 CI pass; squash-merged under D7 as c8e9a434; worktree/branch removed.

# 20260929-preview-hub-v1/U14: live public E2E and regression

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
- Current PR unit: U14
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
- Authority grant: manifest 20260930-s4-v1 unit U14 authority subset
- Approved delivery scope: manifest 20260930-s4-v1 unit U14
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: U14 PR in cafitac/preview-hub to main
- Delivery finalization evidence: user confirmation of manifest digest 86c6c422… on 2026-09-29
- Eligible unit IDs: U14
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: U14=INHERIT
- Unit review cycle budget map: U14=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 3e14240ddffdd3d0fe60e236f026d381fbbab01d
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/u14-public-e2e (feat/u14-public-e2e)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA + RUNTIME_HOST smoke (in-VM routing); live in U14
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/preview-hub/.dev/features/20260929-preview-hub-v1/units/U14/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-hub/pull/13
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

Live public E2E (A10–A14) and regression (A15) per manifest U14; public_access enabled in the deployed catalog.

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
  - U14: feat/u14-public-e2e -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-s4-v1 unit U14

## Open questions

- None.

## Progress and evidence

- 2026-09-30: User Cloudflare setup done with the agent in Chrome (user-approved each step): tunnel preview-hub 2e99fea2-11b3-4811-9a58-d8ce348c5c32 created by the user, DNS preview-hub and * CNAMEs added by the user, credentials installed by the user (presence checked only), Zero Trust Free activated ($0, user approved ToS and overage authorization), Access app preview-hub (preview-hub.cafitac.com, phub-*.cafitac.com; policy owner Allow cafitac99@gmail.com). Team domain cafitac.cloudflareaccess.com (JWKS 2 keys), AUD 5a2af938…; unauthenticated requests to both hostnames 302 to Access login; gather/interview 200 unchanged. /opt/phub/public.env written in the VM (3 non-secret keys).
- 2026-09-30: Reserved and initialized: base 3e14240ddffdd3d0fe60e236f026d381fbbab01d, worktree /Users/reddit/Project/cafitac/.worktrees/u14-public-e2e.
- 2026-09-30: Worker (Codex) implemented U14 (catalog public_access, e2e/public.sh, run.sh derives backend URL); 652 passed. Deployed working tree to the VM (vm-bootstrap --source-dir): phub-cloudflared registered 4 tunnel connections; host free 83 GiB; docker context default.
- 2026-09-30: e2e/public.sh runs 1–2 and debug runs failed on GitHub read-after-write races in the script (PR head read right after a push returned the old SHA; one empty gh response) — no hub defect; the worker added wait-until-head and bounded read retries with step markers (evidence/e2e-public-debug-race.log). Run 3 passed all steps: public 302/200, VM 401/404/forwardAuth 401/local 200, pr refs pinned, one cross-link per PR edited on update and marked removed on down, pr-999999 exit 2, cleanup 0 (evidence/e2e-public-run3-pass.log).
- 2026-09-30: Regression: e2e/run.sh A1–A6 and A8 passed with public_access enabled (e2e-alt moved a69129c7 -> d59f6f44 mid-run); e2e/bot.sh A9(a)-(e) passed on PR #10; cleanup 0.
- 2026-09-30: User added GitHub SSO to Access (user request): OAuth app "preview-hub access" created in the cafitac GitHub account (agent filled the form with user approval; the user generated the client secret and pasted it into Cloudflare; the agent never saw it), Cloudflare IdP GitHub added next to One-time PIN; the user authorized the app (user:email, read:org; no org grants). No hub change needed (JWT verification is IdP-agnostic).
- 2026-09-30: A10 owner check performed by the agent in the user's Chrome at the user's request after the user's GitHub SSO login: dashboard https://preview-hub.cafitac.com shows the signed-in email; catalog lists branches and temporary PR #11 after the 60 s cache; created c-tmxuf5 with backend=PR #11, frontend=main -> POST 202, READY, backend pinned 7712f73361f2 (= PR head), frontend a9324753c04b; https://phub-c-tmxuf5.cafitac.com loaded notes through /_svc/api (same origin) and saved a new note; PR #11 got exactly one cross-link comment (READY, table); dashboard delete -> DELETE 202, state DELETED, empty inventory, comment edited to "removed", host back to Access 302. Note: two automation clicks on "환경 만들기" missed the button (no DOM events reached it — tool coordinate issue, not a product defect); submit verified through the DOM click and the delete through a real click. Test PR #11 closed, branches e2e/dash-* and e2e-alt-s4 deleted; Chrome GitHub session switched back to the user's other account.
- 2026-09-30: Review cycle 1 findings (format; README public_access enable/disable and local-forward caveat; gather/interview wording; two unretried GitHub reads; fixed negative env name) fixed; 0 errors, 0 warnings, 0 informations | 670 passed, 1 warning in 55.16s | sh-ok; e2e/public.sh rerun: EXIT=0. Cycle 2 dispatched.
- 2026-09-30: Review cycle 2: reviewer-1 two low findings (hard-coded team domain; branch cleanup after ambiguous create) fixed; reviewer-2 needs-evidence (its session could not run git/tests; no defect found by static reading). 0 errors, 0 warnings, 0 informations | 688 passed, 1 warning in 50.05s | sh-ok; e2e/public.sh rerun: EXIT=0. Cycle 3 dispatched.
- 2026-09-30: Review cycle 3 clean 2/2 (pytest 688 passed; e2e/public.sh run 5 exit 0 on the reviewed snapshot).
- 2026-09-30: PR #13 CI pass on d16c2c74; squash-merged under D7 as f8c0f564; worktree/branch removed. VM redeployed from the merged SHA (vm-bootstrap f8c0f564): hub/bot/proxy/cloudflared up, no active environments, host free 74 GiB, docker context default; preview-hub 302 (Access), gather/interview 200.

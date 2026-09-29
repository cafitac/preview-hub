# preview-hub

Branch-pinned multi-repository preview environments. The hub provides contracts,
planning, a SQLite registry, lifecycle orchestration, and fake/Compose runners.

## Development

Python 3.12 or newer and uv:

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## CLI configuration

`PHUB_CONFIG` optionally names a YAML configuration file:

```yaml
state_dir: /state
catalog: /etc/phub/catalog.yaml
source_dir: /src
runner: fake
```

`PHUB_STATE_DIR`, `PHUB_CATALOG`, `PHUB_SOURCE_DIR` and `PHUB_RUNNER` override
these values. An unset or empty override uses the configuration value; a missing
or null configuration value uses the default (never the string `"None"`).
The defaults above match the intended container mounts. The VM
free-space guard requires 5 GiB; tests inject a free-space provider through
`lifecycle.Context`.

```sh
phub up feat-x --set backend=feature --ttl 24h
phub up -f composition.yaml
phub update feat-x --set backend=main
phub up pr-demo --set backend=pr-4
phub status feat-x --format descriptor
phub list --format json
phub logs feat-x backend --tail 100
phub down feat-x
phub gc
```

PR refs use `pr-<n>` (1–7 digits, no leading zero) and pin the current head of an open, same-repository PR.
Updates re-resolve the head. Branches literally named `pr-<n>` must be addressed by SHA.
The hub needs `/run/secrets/github_token` for PR refs (override with
`PHUB_GITHUB_TOKEN_FILE` for tests); the stack mounts the secrets directory read-only.

Exit codes: 0 success, 2 invalid input, 3 busy, 4 capacity/disk guard,
5 lifecycle failure. All commands accept `--format text|json|descriptor`;
descriptor output requires an individual environment result.

The fake runner keeps its runtime objects and images in memory. Inject one shared
`Context` when exercising multiple commands in tests; separate CLI processes
retain registry rows but do not share fake runtime objects. Fake logs are empty.

## Integration boundaries

- `contracts.py`: schema validation and manifest/catalog/composition dataclasses.
  Schemas C1, C2, C3, C7 and C8 are published in `schemas/` and bundled in wheels.
  A missing health timeout defaults to 90 seconds.
- `git.py`: `GitSource` and exact-commit `GitCliSource`; pass the catalog's
  repo-to-service mapping to store checkouts at `/src/<service>/<sha>`.
  Abbreviated SHAs must uniquely match an advertised remote commit. Full SHAs
  are verified by fetching the exact object, including commits behind branch tips.
- `runner.py`: the C4 `Runner` protocol and runner-neutral plan/result types.
  `ServicePlan.changed` identifies services to restart and whose resource init
  commands should run; unchanged services and resource volumes must be retained.
  `ResourcePlan.name` is environment-scoped; its URL uses the network-local
  `<service>--<resource>` hostname and its container name is
  `phub-<env>--<service>--<resource>`. Resource keys must match
  `^[a-z][a-z0-9]{0,20}$`; plans reject resource identity collisions, including
  hostnames already used by services. Resource credentials are synthetic preview data.
- `lifecycle.py`: the five use cases, each with an `execute()` entry point.
  Failures retain objects for inspection. A failed deletion remains DELETING
  until its inventory is empty. Failed provisioning retries reapply all services.
- `registry.py`: numbered atomic SQL migrations, short transactions, environment
  locks and stale-operation recovery. Builds use shared file-lock slots.
- CLI logs and image collection are optional runner capabilities, separate from
  C4. Image collection receives active image references and retains three recent
  images per service. A Compose runner must implement actual logs and image GC.

Descriptor `testAccounts` is empty: the core does not invent credentials for the
example applications. The approved registry schema has no credential storage
field. The parent integration must supply the account-generation/storage contract
before descriptors can advertise working per-environment accounts.

The test fixtures are copies of the U1 backend and U2 frontend `preview.yaml`
files. Tests use synthetic local Git repositories and never contact a remote.

## Container runtime (U4)

The dedicated Colima profile `preview-hub` contains the hub, Traefik and every
preview container. The host runs the VM only; no Python service or GC daemon is
installed there. `phub-state` stores SQLite, locks and rendered Compose files;
`phub-src` stores immutable checkouts. The hub mounts the VM Docker socket and
refuses any daemon whose `docker info` name is not `colima-preview-hub`.

`runner: compose` (or `PHUB_RUNNER=compose`) selects the real runner.
`daemon_name` / `PHUB_DAEMON_NAME` explicitly overrides the expected name.
The default remains `fake` for compatibility. The stack selects Compose.
`phub serve --interval 900` runs GC immediately and every 15 minutes, including
U3's stale-operation recovery. `PHUB_GC_INTERVAL` changes the default interval.
`phub inventory [environment] --format json` exposes label-scoped runtime objects.
Shared cached service images have service labels, not environment labels.

The image defaults to UID 1000. The stack explicitly uses root because Colima's
Docker socket is normally root-owned. The hub and bot use the same UID/GID.
To run both as UID 1000, grant their GID socket access and make both named volumes writable, then set
`PHUB_UID_GID=1000:<socket-gid>` when starting the stack. Socket access grants
control of the dedicated VM regardless of UID. Use the same `PHUB_UID_GID` when
running `scripts/vm-bootstrap.sh` and every `scripts/bot-token` install or rotation.
Both scripts set the secrets directory owner to that UID/GID (default `0:0`)
with mode `0700`; the token installer sets the token owner to it with mode `0400`.
Both services need socket access and writable volumes.
Traefik has a read-only socket mount, Docker-provider ownership constraint, and opt-in routing labels.

Application and init containers use the manifest memory limit; PostgreSQL uses
512 MiB. PostgreSQL starts and becomes healthy before ordered migration/seed
jobs run from the service image. Only changed services and their init jobs run
on update. HTTP health probes use `curlimages/curl:8.12.1` as disposable labelled
containers on the environment network; command checks use Docker healthchecks.
The Docker daemon therefore needs image-registry access, including that probe
image. `phub logs` includes application stdout and stderr. U3 persists its health
failure message in `last_error.log_excerpt`; retrieve full application logs with
`phub logs` before deleting a failed environment.

From a MacBook with SSH access to the Mac Studio (Colima and Docker CLI already
available there):

```sh
scripts/vm-bootstrap.sh <published-git-ref> [https://github.com/cafitac/preview-hub.git]
scripts/phub up demo --set backend=main --set frontend=main
scripts/phub tunnel
# In another terminal, open http://app.demo.localhost:18080
scripts/phub status demo --format descriptor
scripts/phub inventory demo
scripts/phub down demo
```

Bootstrap only starts profile `preview-hub` (4 CPU, 8 GiB, 40 GiB), builds from the
requested ref inside its VM, and brings up the stack. Repeating it preserves
state/source volumes. Stack files live in `/opt/phub` inside the VM; temporary
build files are removed. An existing running profile is preserved, so verify its
resource settings separately if it predates this bootstrap. It never restarts,
resizes or deletes another profile.

`PHUB_SSH_HOST` defaults to `trading-macstudio`; `PHUB_SSH_OPTS` is a whitespace
separated list of SSH options (use SSH config for values containing spaces).
The wrapper quotes each remote argument, checks host free space before up/update
(15 GiB minimum, exit 4), and leaves the separate VM guard at 5 GiB. Spec files
passed with `-f` must already exist inside the hub container. The SSH tunnel binds
local port 18080; the proxy host publication is loopback-only.

### Runtime acceptance

The E2E script requires local `curl`, `git`, `python3`, SSH access, published
example branches and a bootstrapped hub. It creates unique disposable environment
names and always attempts to delete them and verify empty inventories on exit.

```sh
E2E_ORIGINAL_SHA=<40-hex-original> E2E_MOVED_SHA=<40-hex-second> \
  E2E_BRANCH=e2e-alt E2E_FRONTEND_BRANCH=main E2E_BROKEN_BRANCH=e2e-broken \
  e2e/run.sh
```

After A1 creates the environment, move `e2e-alt` to the second commit **outside**
the script. It polls the branch for up to 5 minutes (`E2E_MOVE_POLLS`, 5 seconds
per poll) and never pushes. It verifies the original pinned SHA, isolation of
notes and frontend configuration, deletion isolation, repeated-up idempotency,
TTL GC, and broken-health failure cleanup. Every scenario prints before/after
inventories. `E2E_EXISTING_TUNNEL=1` reuses an already running tunnel;
`E2E_BACKEND_REPO` overrides the branch-observation URL. Live A1–A5 and image
build/bootstrap require a Docker-enabled networked machine; unit tests use a fake
executor and do not contact Docker.

Teardown is destructive and must be run deliberately after saving any evidence:

```sh
# First use scripts/phub down for each environment.
ssh trading-macstudio colima delete --profile preview-hub
```

This removes the dedicated VM and all hub state, source caches and preview data.

## Adding a service

Add a root-level `preview.yaml` in the service repository following
`schemas/service-manifest.schema.json` (build/run/health and any dependencies),
then add one entry under `services` in `deploy/hub-stack/catalog.yaml`:

```yaml
notifier: {repo: cafitac/preview-example-notifier, default_ref: main, include: on_request}
```

No change in `preview_hub/` is needed. Apply the updated catalog to the hub stack.
The service name in the manifest must match its catalog key. Omit `expose` for
internal-only services. `include: on_request` keeps the service out of ordinary
environments; select it with `scripts/phub up demo --set notifier=main` or add it
to a running environment with `scripts/phub update demo --set notifier=main`.
Consumers declare an optional dependency and interpolate
`${services.notifier.internal_url}` in their manifest environment variables;
the variable is omitted when notifier is absent.

The extended E2E retains A1–A5 and adds A6: three notes produce exactly three
`note.created` notifications, notes work without notifier, and adding notifier
restarts backend and delivers the next note exactly once. These scenarios use
fresh `main` environments, so backend and notifier changes must already be merged.
Internal notifications are read with Python's HTTP client inside the notifier
container over SSH, using only Docker context `colima-preview-hub` and the
wrapper's `PHUB_SSH_*` / `PHUB_REMOTE_*` configuration. Containers are selected
by exact environment, service, role and ownership labels.

A8 validates a live READY descriptor and
`e2e/fixtures/sample-qa-report.json` against the checked-out schemas, including
date-time formats. It uses local `python3` only if `jsonschema` imports and its
`FormatChecker` has a `date-time` checker;
otherwise it streams the schemas and documents to Python in `phub-hub` over
the same SSH connection. Nothing is installed on the remote host.
The sample is synthetic contract data, not evidence of a live QA run.
`E2E_BASE_REF` (default `11d0aa8`) controls the printed protected-path diff.
The exit trap deletes all six possible environment names and checks their
label inventories are empty. Live A6/A8 require the networked runtime host;
`pytest` validates both contracts without Docker.

## PR bot

Service arguments also accept PR refs, for example `/preview up frontend=pr-7`
or `/preview update backend=pr-4`. They pass unchanged to the hub CLI.

The `phub-bot` container polls catalog repositories every 20 seconds. Set
`PHUB_BOT_INTERVAL` to a finite positive number of seconds to change it.
It needs no webhook or inbound port.

Create a **fine-grained personal access token** limited to the catalog repositories,
with **Pull requests: read and write**, **Issues: read and write**,
**Contents: read**, and **Metadata: read** (implicit). PR conversation replies use
the issues endpoint but require Pull requests write permission.
Do not use the host's broad `gh` login token. From the MacBook, pipe the token from
its secure source into `scripts/bot-token` (never put the value in an argument),
or run `scripts/bot-token`, paste it at the hidden stdin prompt, then press Enter and Ctrl-D.
Run `scripts/bot-token --check` to check presence without reading its contents.
The installer uses `PHUB_SSH_HOST`, `PHUB_SSH_OPTS`, and `PHUB_REMOTE_PATH` like
`scripts/phub`, and writes only inside the `preview-hub` VM, using sudo, mode 0400,
at `/opt/phub/secrets/github_token`. Bootstrap creates `/opt/phub/secrets`
with mode 0700. Both directory and installed token are owned by
`PHUB_UID_GID` (default `0:0`); set it consistently on bootstrap, install,
rotation, and stack startup. Compose mounts that directory read-only at `/run/secrets`.
The stack starts without a token. The bot checks `/run/secrets/github_token` each
loop; if absent or empty it logs `token missing` once and idles. Installing or
rotating the token takes effect without restarting the container.

Post one command as the entire PR comment:

```text
/preview up
/preview up frontend=main ttl=24h
/preview update backend=main
/preview status
/preview down
```

The environment is `pr-<catalog-service>-<PR-number>`. The PR's service always
uses the exact current PR head SHA, even if its argument names another ref.
Other services use the supplied refs or catalog defaults. `ttl` is supported
only on `up`; `update` requires at least one `service=ref`. Replies show state,
12-character commits and URLs, or a failure stage/rejection reason. Closing a PR
removes its environment on a subsequent poll; failed cleanup is retried.

Only OWNER, MEMBER and COLLABORATOR comments on open, same-repository PRs in the
catalog are allowed. Forks, closed PRs and malformed commands run nothing.
Commands execute only through `docker exec phub-hub phub`; the mounted Docker
socket is privileged, so this is a code restriction, not daemon-enforced isolation.
The bot never includes the token in command arguments, logs, replies or its repr.
On first start, or when a repository cursor is missing (including a recreated
state volume), the bot initializes its comment cursor to its start time in UTC.
A comment is eligible only when its `created_at` is at or after the floor:
the process start time if no cursor existed, otherwise the persisted comment
cursor at startup minus the 60-second overlap. The floor stays fixed for that
process and is recomputed from the persisted cursor on restart. Editing a comment
created before the applicable floor never makes it eligible.
A durable comment-ID ledger prevents re-execution across overlapping polls and
restarts while the ledger is retained. Interrupted commands become FAILED after
ten minutes and need a new comment. Reply retries are best-effort, in memory,
with at most three POST attempts per process. The initial reply body is retained
until delivery succeeds. A restart can drop or repeat an unacknowledged reply:
it loses the original body, attempt count and retry delay. After restart, replies
are rebuilt from stored status, environment and error plus a fresh
`phub status <env> --format json` when an environment exists. GitHub provides no
idempotency key for issue comments, so acknowledgement loss can cause duplicates.
Bot data is stored only in the revision-2 bot tables, never in schema metadata.

A successful reply looks like:

```text
preview pr-backend-42: READY

| service | commit | URL |
| --- | --- | --- |
| backend | 0123456789ab | http://api.pr-backend-42.localhost:18080 |
```

From the MacBook, run `e2e/bot.sh` to exercise up, status, repeated polling,
down and PR-close cleanup against a temporary PR in
`cafitac/preview-example-backend`. It requires `gh`, `jq`, `python3`, a running
bot and working `scripts/phub` SSH access. Each GitHub command uses the
`cafitac` owner's `gh auth token --user cafitac` credentials; it does not read
the VM's bot token. Set `PHUB_BOT_INTERVAL` to the deployed interval if it differs
from 20 seconds. Replies are awaited for up to three minutes and PR-close
cleanup for two minutes. The exit trap closes the PR, removes its branch,
runs `phub down` and verifies empty label inventory. Rejection cases are unit
tested; the separate `e2e/run.sh` covers the existing hub regression scenarios.

If no reply appears, first run `scripts/bot-token --check`. `token present`
checks file presence only, not credential validity. A bot log line
`authentication failed: repo=...` means GitHub returned 401 or a non-rate-limit
403: check token expiry, repository access and the permissions above, then
reinstall with `scripts/bot-token`. The installer prints `token installed` on
success. Rate-limit responses remain retryable deferrals. Inspect the
`phub-bot` logs inside the `preview-hub` VM without printing the secret file.

### PR cross-link comments

Each bot poll links active environments to PRs referenced by `pr-<number>` service
refs. Each referenced PR gets one comment with the environment state, entry URL,
and service/ref/pinned-commit table. The originating `/preview` PR is skipped
because it already receives command replies. Version changes edit the comment;
removing a PR ref or deleting the environment edits it to `removed`.

The registry records delivery in `pr_links`. Retryable failures retry on the next
poll. Non-retryable failures pause after
five failed attempts until the environment version or instance changes. Deleted
comments are recreated on update or marked removed during cleanup. Retirement of
an old instance is best effort and does not block its replacement comment. Before
posting, the bot searches all comments on that PR for its own
`<!-- phub-link env=<name> -->` marker, recovering interrupted posts without
creating duplicates. Removed comments stay as history; reusing an environment
name creates a fresh comment. The existing token needs Issues/Pull requests write
permission.

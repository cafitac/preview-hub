# preview-hub

Branch-pinned multi-repository preview environments. The hub provides contracts,
planning, a SQLite registry, lifecycle orchestration, and fake and Kubernetes
runners.

## Production runtime (Kubernetes, since 2026-10-05)

Production runs on the homelab k3s cluster (`cafitac/homelab` `apps/preview-hub`,
deployed by Argo CD). One preview environment is one namespace `phub-<env>`.

```text
GitHub PR ── bot (hub pod sidecar) ── hub (ServiceAccount + RBAC)
                                       │ kubectl apply --server-side --field-manager phub
                                       ├─ kubernetes runner: environment = namespace phub-<env>
                                       └─ build: BuildKit Job → in-cluster registry
cluster Traefik (Ingress + Middleware) ◀── Cloudflare Tunnel (*.cafitac.com)
```

- `runner: kubernetes` (or `PHUB_RUNNER=kubernetes`) selects it. The runner port is
  unchanged: plans, registry and the environment description do not know about Docker
  or Kubernetes, so ai-qa needed no change.
- Isolation: a ResourceQuota and a NetworkPolicy (same namespace and Traefik only)
  per namespace. `destroy` deletes only namespaces carrying the owner label.
- Public routes use the same ForwardAuth (hub `/auth/verify`) and StripPrefix
  middlewares; the path-prefixed route outranks the entry service's catch-all route.
- The switch was accepted with an ai-qa end-to-end run (up → scenarios → down, nothing
  left behind). The first run failed: Service selectors also matched the same service's
  postgres and init pods. The fix (#20) added a role label and a "one selector = one
  workload" test.

The hub pod (`phub serve`) and the bot (`phub bot`) run as two containers of one pod
on the same state volume and ServiceAccount, so the bot runs `phub` itself
(`PHUB_HUB_EXEC=""`). The hub is configured through environment variables:

| Variable | Meaning | Default |
| --- | --- | --- |
| `PHUB_RUNNER` | `fake` or `kubernetes` | `fake` |
| `PHUB_BUILDKIT_ADDR` | BuildKit daemon | `tcp://buildkitd:1234` |
| `PHUB_REGISTRY` / `PHUB_REGISTRY_PULL` | registry address for pushes / for node pulls | `registry:5000` / `localhost:5000` |
| `PHUB_AUTH_URL` | ForwardAuth endpoint (hub `/auth/verify`) | `http://hub.preview-hub.svc.cluster.local:8080/auth/verify` |
| `PHUB_HUB_NAMESPACE` | namespace the hub itself runs in (cluster sanity check) | `preview-hub` |
| `PHUB_PROXY_ADDRESS` / `PHUB_PROXY_PORT` | router reported in environment descriptors | `phub-proxy:80` / port of the catalog URL template |
| `PHUB_GC_INTERVAL` | seconds between GC runs of `phub serve` | `900` |
| `PHUB_BOT_INTERVAL` | seconds between bot polls | `20` |
| `PHUB_HEALTH_POLL_INTERVAL` | seconds between health polls | `2` |
| `PHUB_ACCESS_TEAM_DOMAIN` / `PHUB_ACCESS_AUD` | Cloudflare Access verification | unset (fails closed) |

The hub image is built by `deploy/k8s-image.sh` (tag `phub/hub:<commit>`); its
`Dockerfile` bundles `kubectl` and `buildctl`.

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
The defaults above match the intended container mounts. `runner` accepts `fake` or
`kubernetes`; any other value (including the retired `compose`) is rejected with an
error listing the valid runners. The free-space guard on the state volume requires
5 GiB; tests inject a free-space provider through `lifecycle.Context`.

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
`PHUB_GITHUB_TOKEN_FILE` for tests); the deployment mounts that single file read-only.

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
  images per service. A real runner must implement actual logs and image GC.

Descriptor `testAccounts` is empty: the core does not invent credentials for the
example applications. The approved registry schema has no credential storage
field. The parent integration must supply the account-generation/storage contract
before descriptors can advertise working per-environment accounts.

The test fixtures are copies of the U1 backend and U2 frontend `preview.yaml`
files. Tests use synthetic local Git repositories and never contact a remote.

## Serving and GC

`phub serve --interval 900` runs GC immediately and every 15 minutes, including
stale-operation recovery; `PHUB_GC_INTERVAL` changes the default interval.
`phub inventory [environment] --format json` exposes label-scoped runtime objects.
Shared cached service images have service labels, not environment labels.
`phub logs` includes application stdout and stderr. The health failure message is
persisted in `last_error.log_excerpt`; retrieve full application logs with
`phub logs` before deleting a failed environment.

## Adding a service

Add a root-level `preview.yaml` in the service repository following
`schemas/service-manifest.schema.json` (build/run/health and any dependencies),
then add one entry under `services` in `deploy/catalog.yaml`:

```yaml
notifier: {repo: cafitac/preview-example-notifier, default_ref: main, include: on_request}
```

No change in `preview_hub/` is needed. The deployed copy of the catalog is the
`catalog` ConfigMap in `cafitac/homelab` `apps/preview-hub`; keep the two in sync.
The service name in the manifest must match its catalog key. Omit `expose` for
internal-only services. `include: on_request` keeps the service out of ordinary
environments; select it with `phub up demo --set notifier=main` or add it
to a running environment with `phub update demo --set notifier=main`.
Consumers declare an optional dependency and interpolate
`${services.notifier.internal_url}` in their manifest environment variables;
the variable is omitted when notifier is absent.

`e2e/fixtures/sample-qa-report.json` is a synthetic sample of the QA report contract;
`pytest` validates it against the schemas in `schemas/`. It is contract data, not
evidence of a live QA run.

## PR bot

Service arguments also accept PR refs, for example `/preview up frontend=pr-7`
or `/preview update backend=pr-4`. They pass unchanged to the hub CLI.

The `bot` container of the hub pod polls catalog repositories every 20 seconds. Set
`PHUB_BOT_INTERVAL` to a finite positive number of seconds to change it.
It needs no webhook or inbound port.

Create a **fine-grained personal access token** limited to the catalog repositories,
with **Pull requests: read and write**, **Issues: read and write**,
**Contents: read**, and **Metadata: read** (implicit). PR conversation replies use
the issues endpoint but require Pull requests write permission.
Do not use a broad `gh` login token. The token reaches the hub pod as the Kubernetes
Secret `hub-github`, mounted as the single file `/run/secrets/github_token`; never put
the value in a command argument. The bot checks that file each loop; if absent or
empty it logs `token missing` once and idles. Rotating the Secret takes effect after
the kubelet refreshes the mounted file, without restarting the container.

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
Commands execute only as `phub <action> ...` in the hub pod (an optional
`PHUB_HUB_EXEC` prefix can wrap them); the bot's ServiceAccount permissions bound
what they can do in the cluster.
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

Rejection cases are unit tested.

If no reply appears, check the bot container logs (`kubectl logs -n preview-hub
deploy/hub -c bot`). A log line `token missing` means the Secret file is absent or
empty. A line `authentication failed: repo=...` means GitHub returned 401 or a
non-rate-limit 403: check token expiry, repository access and the permissions above,
then update the Secret. Rate-limit responses remain retryable deferrals.

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

## Public access (Cloudflare, free)

Public access is optional, but the checked-in deploy catalog (`deploy/catalog.yaml`)
enables it for the cafitac.com deployment. Without the Cloudflare Access setup it
injects unreachable `https://phub-<env>.cafitac.com/...` URLs into services. To run
without public access, remove the `public_access` block from the catalog; local URLs
are then injected as before. The tunnel and DNS are part of the homelab cluster
(`cafitac/homelab`); the hub only verifies Access JWTs.

1. Make sure `preview-hub.cafitac.com` and `*.cafitac.com` reach the cluster's
   Traefik through the homelab Cloudflare Tunnel. Existing explicit records (such as
   `gather` and `interview`) take precedence over the wildcard.
2. Create one Access self-hosted application with destinations
   `preview-hub.cafitac.com` and `phub-*.cafitac.com`, with an Allow policy for
   your owner email. Copy its AUD tag and your team domain (for example,
   `example.cloudflareaccess.com`, without `https://`).
3. Give the hub both values as environment variables through the Secret
   `hub-access`: `PHUB_ACCESS_TEAM_DOMAIN` and `PHUB_ACCESS_AUD`. Without them the
   verifier fails closed.
4. Enable public access by including the following block in `deploy/catalog.yaml`
   (it is already checked in for the cafitac.com deployment) and applying the same
   catalog to the cluster. Disable it by removing the block.

   ```yaml
   public_access:
     host_template: phub-{env}.cafitac.com
     entry_service: frontend
     path_template: /_svc/{subdomain}
     dashboard_host: preview-hub.cafitac.com
   ```

   If using another zone, change the hostnames in the Access application and the
   cluster routing as well.
5. Update existing environments with their current refs (for example,
   `phub update demo --set backend=main`) to apply public routes and injected
   URLs even when the commits have not changed.

The entry service uses `https://phub-<env>.cafitac.com`; other exposed services
use paths such as `/_svc/api`, stripped before forwarding. Injected public URLs
share that origin. When public access is enabled, open environments through their
public URL. Local URLs remain in descriptors as `localUrl`. Every public
route verifies an Access JWT at the hub; absent verifier configuration fails
closed. `/healthz` is the only unauthenticated HTTP endpoint. This unit supplies
the authenticated HTTP foundation; dashboard routes are added separately.

## Dashboard

With public access configured (see Public access), open
`https://<public_access.dashboard_host>`. Cloudflare Access signs you in; the hub
verifies the JWT on every dashboard and API request and shows your email.

Choose a default ref, branch, or open same-repository PR per service, optionally
enter a name and TTL (for example `2h`), and select **환경 만들기**. Names default to
`c-` plus six lowercase base32 characters. The environment table shows states,
requested refs, 12-character pinned commits, entry links, expiry times and failure
summaries. It polls every five seconds while work is in progress. **삭제** asks for
confirmation; **새로고침** refreshes environments changed elsewhere.

The JSON API uses the same Access authentication:

- `GET /api/catalog`: service defaults, branches and non-fork open PRs, cached per
  repository for 60 seconds. A repository failure adds an `error` to its services.
- `GET /api/environments`: active registry entries, without lifecycle reconciliation.
- `GET /api/environments/{name}`: one entry; `?format=descriptor` uses the same
  descriptor implementation as `phub status --format descriptor`.
- `POST /api/environments`: `{ "services": { "backend": "pr-4" }, "ttl": "2h" }`,
  with optional `name`.
- `POST /api/environments/{name}/update`: `{ "services": { "backend": "main" } }`.
- `DELETE /api/environments/{name}`: delete an environment.

Mutations require the exact dashboard HTTPS Origin; POST requests require
`Content-Type: application/json`. Without `public_access`, mutations are refused.
The browser supplies Origin automatically. Mutations run detached CLI children
with `requested_by=web:<verified email>`, preserving CLI locks and capacity guards.
An exit within two seconds maps codes 2/3/4/5 to HTTP 400/409/429/500 and returns
only the final stderr line; otherwise the API returns `202 {"name": "..."}`.
A 202 acknowledges the command, not environment readiness. Each submission is a
new operation; automatic retries are not deduplicated.

Child stdout/stderr stay in separate per-operation files under
`$PHUB_STATE_DIR/logs/web/<operation>/` (default `/state/logs/web/`). The server logs
one mutation summary with email, action, environment and the early exit code
(`null` if still running or no child was started). Requests refused before a child
starts include a `rejected` reason and `exit_code: null`. No JWT or token is logged.

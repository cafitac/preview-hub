# Interface contracts (v1)

All files are YAML or JSON and carry `apiVersion: preview-hub/v1`. Unknown keys are rejected so contract drift fails loudly. JSON Schemas for each format ship in the hub repository under `schemas/` and are the executable form of this document.

## C1. Service manifest — `preview.yaml` at the root of each service repository

```yaml
apiVersion: preview-hub/v1
service: backend                 # ServiceName ^[a-z][a-z0-9-]{1,20}$; must equal the catalog key
build:
  context: .
  dockerfile: Dockerfile
  args: {}                       # constants only; may NOT reference other services
run:
  port: 8000                     # container port
  command: null                  # optional override
  memory: 512Mi
expose:                          # omit for internal-only services
  subdomain: api                 # -> api.<env>.localhost:18080 (catalog public_url_template)
health:
  http: /healthz                 # or: cmd: ["..."]
  timeout: 90s
requires:                        # start order + injected values
  - service: notifier
    optional: true               # absent from the environment -> variable not injected
resources:
  db:
    type: postgres
    version: "16"
    init:                        # run as one-off containers from this service's image, in order
      - ["alembic", "upgrade", "head"]
      - ["python", "-m", "app.seed"]
env:
  APP_ENV: preview
  DATABASE_URL: ${resources.db.url}
  CORS_ORIGINS: ${services.frontend.public_url}
  NOTIFIER_URL: ${services.notifier.internal_url}
```

Interpolation (evaluated at start, never at build):
- `${services.<name>.public_url}` — proxy URL from `public_url_template` (e.g. `http://api.feat-x.localhost:18080`), only for exposed services.
- `${services.<name>.internal_url}` — `http://<name>:<port>` on the environment network.
- `${resources.<id>.url}` — connection URL of this service's resource (per environment).
- `${env.name}`.
Resource `init` commands run on every create and on every update of the owning service, against the environment's existing volume, so they must be idempotent (migrations are naturally so; seeds must upsert or check before insert). `update` rebuilds and restarts only the services whose pinned commit changed; resource volumes are kept.

A reference to a service that is not in the environment is an error unless that `requires` entry is `optional`, in which case the variable is omitted. Dependency cycles are rejected.

## C2. Catalog — `catalog.yaml` in the hub configuration (runtime host)

```yaml
apiVersion: preview-hub/v1
public_url_template: http://{subdomain}.{env}.localhost:18080   # SSH local forward from the MacBook; the only thing a Tailscale container would change
services:
  backend:  {repo: cafitac/preview-example-backend,  default_ref: main}
  frontend: {repo: cafitac/preview-example-frontend, default_ref: main}
  # S2: adding a service is one entry here + preview.yaml in its repository
  notifier: {repo: cafitac/preview-example-notifier, default_ref: main, include: on_request}
limits: {max_environments: 5, build_concurrency: 2, default_ttl: 24h, max_ttl: 7d}
```

`include: always` (default) services join every environment at their default ref unless overridden; `on_request` services join only when named in the composition spec or required non-optionally by another included service.

## C3. Composition spec — what `up` asks for

```yaml
apiVersion: preview-hub/v1
name: feat-x                     # EnvName ^[a-z][a-z0-9-]{1,30}$
services:
  backend: feat-x                # branch, tag, or 7–40 hex commit
  frontend: main
ttl: 24h
```

CLI form: `phub up feat-x --set backend=feat-x --set frontend=main --ttl 24h` (or `-f spec.yaml`). Resolution: catalog completion -> each ref resolved to a 40-hex commit with `git ls-remote` (a hex ref is verified to exist) -> pins stored. The stored pins, not the refs, define the environment; `phub up -f <exported spec with commits>` recreates it exactly.

## C4. Runner interface (Python, in the hub)

```python
class Runner(Protocol):
    def build(self, service: str, commit: str, source: Path, manifest: ServiceManifest) -> str: ...  # image ref, idempotent
    def apply(self, plan: EnvironmentPlan) -> RunResult: ...                                           # create/start, idempotent
    def health(self, env: str) -> dict[str, Health]: ...
    def destroy(self, env: str) -> Inventory: ...                                                      # label-scoped, idempotent
    def inventory(self, env: str | None = None) -> Inventory: ...                                      # dev.phub.* objects
```

`EnvironmentPlan` is runner-neutral (services, images, ports, env, routes, resources, labels, order). `ComposeRunner` renders it to a Compose file under `/state/envs/<env>/compose.yaml` (volume `phub-state`); a future `K3dRunner` renders the same plan to manifests. Lifecycle and composition code import only `Runner` and `EnvironmentPlan`.

## C5. CLI

The CLI runs inside the `phub-hub` container. From the MacBook a wrapper forwards arguments:
`ssh trading-macstudio docker --context colima-preview-hub exec -i phub-hub phub "$@"`.

```
phub up <name> [--set svc=ref ...] [--ttl D] [-f spec.yaml]
phub update <name> --set svc=ref ...
phub status <name> [--format text|json|descriptor]
phub list
phub down <name>
phub logs <name> <service> [--tail N]
phub gc            # expiry sweep + stale-op recovery + image GC
```
Exit codes: 0 success/no-op, 2 invalid input, 3 busy (lock held), 4 capacity/disk guard, 5 operation failed (environment FAILED).

## C6. PR comment command grammar (S3)

```
/preview up [svc=ref ...] [ttl=D]     # default: this repository's service at the PR head, others at catalog defaults
/preview update svc=ref ...
/preview down
/preview status
```
- Environment name: `pr-<service>-<number>` (the repository's service name).
- Authorized only when the comment author association is OWNER, MEMBER or COLLABORATOR; others get a rejection reply and nothing runs.
- The bot replies once per command with the final state, URLs and pinned commits; PR close triggers `down`.
- Implementation (revision 3): polling bot `phub-bot` (see 07). The PR's own service is pinned to the PR head SHA; other services use `svc=ref` arguments or catalog defaults; `on_request` services join only when named.
- Reply format (Markdown): first line `preview <env>: <STATE>`; then a table of service | commit (12 hex) | URL; on failure the stage, service and log excerpt; on rejection the reason. Commands from forks, non-collaborators, closed PRs or with parse errors get a rejection reply and run nothing.
- Configuration: `PHUB_BOT_INTERVAL` (default 20 s, finite > 0), token file `/run/secrets/github_token`, repositories = catalog services' repos.

## C7. ai-qa environment descriptor — `environment-descriptor/v1` (JSON)

```json
{
  "apiVersion": "preview-hub/v1",
  "kind": "EnvironmentDescriptor",
  "name": "feat-x",
  "state": "READY",
  "createdAt": "2026-09-29T10:00:00Z",
  "expiresAt": "2026-09-30T10:00:00Z",
  "entryUrl": "http://app.feat-x.localhost:18080",
  "proxy": {"hostPort": 18080, "inNetworkAddress": "phub-proxy:80"},
  "services": [
    {"name": "backend", "repo": "cafitac/preview-example-backend", "ref": "feat-x",
     "commit": "<40 hex>", "publicUrl": "http://api.feat-x.localhost:18080", "health": "HEALTHY"}
  ],
  "testAccounts": [{"role": "user", "username": "qa-user", "password": "<generated per env>"}],
  "readiness": {"allHealthy": true, "checkedAt": "2026-09-29T10:03:00Z"}
}
```
ai-qa must only run against `state=READY` and `readiness.allHealthy=true`, and must record the commits it tested. A consumer outside the VM uses the public URLs through the SSH forward; a consumer running as a container inside the VM joins the environment network and maps `*.localhost` names to `proxy.inNetworkAddress`.

## C8. ai-qa report — `qa-report/v1` (JSON, produced by ai-qa, stored by ai-qa)

```json
{
  "apiVersion": "preview-hub/v1",
  "kind": "QaReport",
  "environment": "feat-x",
  "commits": {"backend": "<40 hex>", "frontend": "<40 hex>"},
  "startedAt": "...", "finishedAt": "...",
  "scenarios": [
    {"id": "create-note", "status": "PASSED|FAILED|SKIPPED", "summary": "...",
     "evidence": [{"type": "screenshot|log|http", "uri": "..."}]}
  ],
  "summary": {"passed": 1, "failed": 0, "skipped": 0}
}
```
The hub does not consume reports in v1; the schema is published so ai-qa and the PR bot (later) share one format.

## Revision 4 (S4): dashboard, `pr-<n>` refs and public access

All revision 4 changes are additive. With no `public_access` block in the catalog, every contract above behaves exactly as in revision 3 (S1–S3 evidence stays valid).

### C2 (extended). Catalog `public_access`

```yaml
public_access:                       # optional; enables public exposure (S4)
  host_template: phub-{env}.cafitac.com   # ONE hostname per environment, one label under the zone (free Universal SSL)
  entry_service: frontend            # served at "/" of the environment host
  path_template: /_svc/{subdomain}   # every other exposed service; prefix stripped before the container
  dashboard_host: preview-hub.cafitac.com
```

- `${services.<name>.public_url}` becomes `https://phub-<env>.cafitac.com` for the entry service and `https://phub-<env>.cafitac.com/_svc/<subdomain>` for other exposed services. All services of one environment therefore share one origin, so the browser sends the Cloudflare Access cookie to API calls and no CORS preflight crosses hosts.
- Local routes from `public_url_template` (`<subdomain>.<env>.localhost:18080`) remain as additional proxy routes for SSH-forward debugging and in-VM consumers; they are not injected into services when `public_access` is set.
- Rejected alternative: one hostname per service (`phub-<env>--api...`). Cross-host API calls would not carry the Access cookie of the API host, so the frontend's first fetch would be redirected to the Access login and fail CORS.
- The hub validates at start that `host_template` yields exactly one DNS label (`^phub-[a-z0-9-]+$` before the zone) no longer than 63 characters for the maximum EnvName length.

### C3 (extended). `pr-<n>` ref syntax

- A ref matching `^pr-[1-9][0-9]{0,6}$` names the open pull request `<n>` of that service's repository. Branch names of this exact form are therefore not addressable by name (use the commit SHA instead).
- Resolution (GitHub REST `GET /repos/{repo}/pulls/{n}`): the PR must exist, be `open`, and have `head.repo.full_name == base.repo.full_name` (no forks). The pin is `head.sha` at resolution time; `requested_ref` stores `pr-<n>`. `update` re-resolves it to the current head.
- Errors (exit 2, nothing created): not found, closed/merged, fork, token missing/unauthorized. The bot's own PR-head pinning (C6) uses the same resolver.
- Same syntax in CLI (`--set backend=pr-4`), bot (`/preview up frontend=pr-7`) and dashboard.

### C9. Hub HTTP server (dashboard + JSON API)

Served by `phub serve` inside `phub-hub` on in-network port 8080 (never published to the host). Only `cloudflared` and `phub-proxy` reach it.

| Method and path | Purpose |
|---|---|
| `GET /` | Dashboard HTML: environment list (state, pinned commits, URLs, TTL) and the compose form |
| `GET /api/catalog` | Services with default ref, branches (up to 100, newest first) and open non-fork PRs (number, title, head ref, head SHA); cached 60 s |
| `GET /api/environments` | Active environments (registry read) |
| `GET /api/environments/{name}` | One environment; `?format=descriptor` returns C7 |
| `POST /api/environments` | `{name?, services: {svc: ref}, ttl?}` → starts `phub up` asynchronously, 202 with the name; name defaults to `c-<6 base32>` |
| `POST /api/environments/{name}/update` | `{services: {svc: ref}}` → `phub update` |
| `DELETE /api/environments/{name}` | → `phub down` |
| `GET /auth/verify` | Traefik forwardAuth target for public environment routes: 200 if the forwarded request carries a valid Access JWT, else 401 |
| `GET /healthz` | Unauthenticated liveness (container health only) |

- Authentication: every path except `/healthz` requires the `Cf-Access-Jwt-Assertion` header, verified as RS256 against the team JWKS (`https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, cached 1 h, refreshed on unknown `kid`), `aud` = configured application AUD tag, `iss` = team domain, `exp`/`nbf` checked with 60 s leeway. Missing configuration → every request refused (fail closed). The identity (`email` claim) becomes `requested_by = web:<email>`.
- Mutations (`POST`, `DELETE`) also require `Origin` equal to `https://<dashboard_host>` (CSRF guard) and `Content-Type: application/json`.
- Mutations run the same CLI entry point as a detached child process (`phub up|update|down ...`), so the lock, capacity/disk guards, operations table and exit codes are identical to C5. Exit 3/4/2 are surfaced when they happen within the first 2 s; later results are visible through the environment state.
- Configuration (non-secret, VM file `/opt/phub/public.env`): `PHUB_ACCESS_TEAM_DOMAIN`, `PHUB_ACCESS_AUD`, `PHUB_TUNNEL_ID`.

### C10. Public ingress (`cloudflared`, locally managed)

Container `phub-cloudflared` (image `cloudflare/cloudflared`, pinned tag) in the hub stack, Compose profile `public`, started only when the credentials file exists. Outbound-only; no published port.

```yaml
tunnel: ${PHUB_TUNNEL_ID}
credentials-file: /etc/cloudflared/tunnel.json      # /opt/phub/secrets/tunnel.json in the VM, read-only
ingress:
  - hostname: preview-hub.cafitac.com
    service: http://phub-hub:8080
  - hostname: "*.cafitac.com"
    service: http://phub-proxy:80                   # Traefik routes only phub-<env> hosts; others 404
  - service: http_status:404
```

User-owned Cloudflare objects (free plan), created once: named tunnel + credentials (installed with `scripts/tunnel-credentials`, presence-only check like `bot-token`); DNS CNAME `preview-hub` and `*` → `<tunnel-id>.cfargotunnel.com` (proxied); one Access self-hosted application with destinations `preview-hub.cafitac.com` and `phub-*.cafitac.com`, policy Allow for the owner's email. Explicit DNS records (gather, interview) keep precedence over the wildcard.

Proxy routes per exposed service (ComposeRunner labels): router `<env>-<svc>-local` (Host `<subdomain>.<env>.localhost`, unchanged) and router `<env>-<svc>-public` (Host `phub-<env>.cafitac.com` [+ `PathPrefix(/_svc/<subdomain>)` with StripPrefix]) with the forwardAuth middleware → `http://phub-hub:8080/auth/verify`.

### C6 (extended). Cross-link comments

For every active environment that pins at least one `pr-<n>` ref, the bot keeps exactly one hub comment on each referenced PR (except the PR whose `/preview` command created the environment, which already has its reply). Body: first line `preview <env>: <STATE>` (marker `<!-- phub-link env=<env> -->`), the environment URL and a table service | ref | commit (12 hex). The comment is edited when the environment version changes and edited to `preview <env>: removed` after deletion. Requires token permission Pull requests/Issues write (already granted).

### C7 (extended). Descriptor

Optional additions (schema stays `preview-hub/v1`): `services[].localUrl` (the `.localhost` route) and `access: {"provider": "cloudflare-access"}` when public access is enabled. `entryUrl`/`publicUrl` carry the public URLs in that case.

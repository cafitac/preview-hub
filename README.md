# preview-hub

Branch-pinned multi-repository preview environments. This core provides contracts,
planning, a SQLite registry and lifecycle orchestration. The only bundled runner
is `fake`; Docker/Compose is a separate implementation unit.

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
phub status feat-x --format descriptor
phub list --format json
phub logs feat-x backend --tail 100
phub down feat-x
phub gc
```

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

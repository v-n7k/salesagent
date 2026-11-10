# CI Pipeline

Authoritative workflow: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

Legacy `.github/workflows/test.yml` is removed by PR #1372. Branch
protection must reference the new rendered check names — see
[Branch protection migration](#branch-protection-migration) below.

## Prerequisites

PR #1372 (**PR3**) depends on PR #1370 (**PR2**: uv.lock, pre-commit, dependency
groups). Merge PR2 first, then rebase PR3 onto `upstream/main`:

```bash
git fetch upstream
git checkout ci/pr3-ci-authoritative-pipeline
git rebase upstream/main
git diff upstream/main --stat   # target: ~20-30 files, no alembic/versions/ changes
```

## Required checks (20 rendered names after PR #1379, plus Tests Redden On Base)

Run `./scripts/capture-rendered-names.sh` after any job rename. The frozen guard
[`tests/unit/test_architecture_required_ci_checks_frozen.py`](../../tests/unit/test_architecture_required_ci_checks_frozen.py)
must stay in sync.

PR #1372 (PR3) establishes **18** checks. PR #1379 adds **2 BDD shard** checks
plus the aggregate `CI / BDD Tests` status proxy (replacing PR3's single BDD job).
The `tests-redden-on-base` job adds one more, `CI / Tests Redden On Base`, which is
advisory. See [Tests redden on base](#tests-redden-on-base).

| Rendered check name | Job |
|---------------------|-----|
| `CI / Quality Gate` | Static analysis (ruff, mypy, duplication) — **no pytest** |
| `CI / Type Check` | mypy |
| `CI / Schema Contract` | AdCP contract tests |
| `CI / Security Audit` | uv-secure against `uv.lock` |
| `CI / Quickstart` | docker compose health |
| `CI / Smoke Tests` | import smoke + skip-decorator guard |
| `CI / Unit Tests` | unit + harness with coverage artifact |
| `CI / Integration (creative)` | integration shard |
| `CI / Integration (product)` | integration shard |
| `CI / Integration (media-buy)` | integration shard |
| `CI / Integration (infra)` | integration shard |
| `CI / Integration (other)` | integration shard |
| `CI / E2E Tests` | full stack |
| `CI / Admin UI Tests` | admin suite |
| `CI / BDD Tests (Shard 1/2)` | BDD greedy scenario shard |
| `CI / BDD Tests (Shard 2/2)` | BDD greedy scenario shard |
| `CI / BDD Tests` | aggregate status proxy (shard pass/fail) |
| `CI / Migration Roundtrip` | alembic upgrade |
| `CI / Coverage` | `--fail-under` from `.coverage-baseline` using unit + BDD artifacts |
| `CI / Tests Redden On Base` | PR's changed tests on head and base (advisory) |
| `CI / Summary` | aggregation gate |

## Tests redden on base

The `tests-redden-on-base` job (`CI / Tests Redden On Base`) runs each test that a pull
request (PR) adds or changes two times, once on the head and once on the base tree. It
checks that a `fix`, `feat`, or `security` PR brings a test that fails without its
production change. The job runs on `pull_request` only, because a push has no PR base
to compare with. Its verdicts are advisory: see
[What blocks a merge](#what-blocks-a-merge).

### What it runs

The job takes the following steps:

1. Lists the test functions that the PR added, changed, or deleted.
2. Runs the added and changed tests on the head, which is the merge commit of the PR.
3. Resets the production roots (`src`, `templates`, `static`, and `alembic`) to `HEAD^1`
   in place.
4. Runs the same tests again.
5. Grades the two runs and writes a table to the step summary.

**The changed set.** The job reads each `test_*.py` file that the PR touched under
`tests/`. It compares every `test_*` function, and every `test_*` method of a `Test*`
class, with its version on the base. The comparison lives in
[`scripts/ci/changed_functions.py`](../../scripts/ci/changed_functions.py) and uses the
normalized abstract syntax tree (AST) from
[`scripts/ci/ast_normalize.py`](../../scripts/ci/ast_normalize.py). The normalized form
ignores docstrings and the values of string, bytes, and number literals. It also ignores
the names that a function binds, such as parameters, assignment targets, and loop
variables. An edit that changes only those is not a changed test. A change to `None`,
`True`, or `False` still counts. A renamed test function reads as an added test, and its
old name reads as a deleted test.

**The reset.** The job runs `git rm -f -r` on the production roots, then checks them out
from `HEAD^1`. A file that the PR added under a root is absent on the base. The `-f`
flag lets `git rm` remove a tracked file that a head run modified, and the checkout
rebuilds the roots from git. `HEAD^1`, the first parent of that merge commit, is the tip
of the base branch. The job checks out with a depth of two, which carries the merge
commit and both parents. Everything else stays at head: tests, `conftest.py` files,
`scripts/`, and configs.

**Duration.** Replaying three merged PRs on a laptop, migrations included, took 34, 44,
and 162 seconds. The job's `timeout-minutes` is 10.

### How pytest is called

Each run is
`uv run pytest <the changed files> -p scripts.ci.pytest_only_ids --only-ids <ids file>`,
called through the `_pytest` action. The run also passes
`--continue-on-collection-errors` and writes a `pytest-json-report` file for each suite
and side. The plugin in
[`scripts/ci/pytest_only_ids.py`](../../scripts/ci/pytest_only_ids.py) keeps only the
changed node ids.

The job gives pytest the files and lets the plugin select the ids. An explicit node id
that names a test in a module that cannot import makes pytest exit with code 4 and run
nothing. A module that imports a symbol that the PR added cannot import on the base.
With files as arguments, pytest records such a module as a failed collector and runs the
rest. A test in that module reads `error` on the base, which counts as red.

Pytest imports a `-p` plugin before any conftest puts the repository root on `sys.path`,
so the job sets `PYTHONPATH=.` for `scripts` to resolve.

### Hosted and unhosted suites

A suite is hosted when this job runs its tests. The job hosts the following suites:

| Directory | Hosted | Run |
|-----------|--------|-----|
| `tests/unit/` and `tests/harness/` | Yes | One run |
| `tests/integration/` | Yes, except the creative group and `skip_ci` tests | One run on the job's Postgres service, with `-m "not creative and not skip_ci"` |
| `tests/admin/`, `tests/bdd/`, `tests/e2e/`, `tests/quality/`, `tests/smoke/`, `tests/storyboard/`, and `tests/ui/` | No | A `test_` function is listed as `unhosted`, with `-` in both outcome cells. Any other touched file appears under "Touched without a changed test function" |
| Any other directory under `tests/` | No | A `test_` function is listed as `unhosted`, with `-` in both outcome cells. Any other touched file is support, not a test |

The directories in the third row are the unhosted directories: a tox env or a CI job
runs each of them, and this job does not. A BDD scenario is a `.feature` file that a
`scenarios(...)` call binds. The job lists no change for most of the files in the
unhosted directories, such as a scenario, a step module, a known-failures ledger, or a
`conftest.py` file, because they are not `test_*.py` modules. The verdict counts a
touched path in an unhosted directory as a changed test in an unhosted suite. A module
that binds scenarios with `@scenario` on `test_` functions, such as
`tests/bdd/test_uc001_discover_available_inventory.py`, lists `unhosted` rows instead,
and the verdict is `skip` either way.

The creative group, which a filename marker selects, runs in-network, inside the Docker
stack, in the `Integration (creative)` shard, next to the
[reference creative agent](#reference-creative-agent). This job does not host that
group.

A changed test that the head run did not collect shows its suite and `not collected` in
both outcome cells. The verdict treats such a test as unhosted. That covers the creative
group and `skip_ci` tests. It also covers a test in a class that pytest does not
collect, such as a `Test*` class with an `__init__` method.

The storyboard guards under `tests/unit` need the pinned compliance bundle, which the
`_adcp-bundle` action downloads. This job does not run that action, so those guards read
`skipped` on both sides and never count as red on the base.

### Verdict rules

The `verdict` function in
[`scripts/ci/redden_on_base.py`](../../scripts/ci/redden_on_base.py) applies the first
of the following rules that fits:

| Order | Verdict | When |
|-------|---------|------|
| 1 | `error` | A suite with a hosted added or changed test has no readable report on the head, or its head report records an exit code other than 0, 1, or 5. This holds for every title. |
| 2 | `advisory` | The Conventional Commits type of the PR title is not `fix`, `feat`, or `security`. The gate does not grade the PR. |
| 3 | `advisory` | No production root changed. |
| 4 | `error` | A suite with a hosted added or changed test has no readable report on the base, or its base report records an exit code other than 0, 1, or 5. |
| 5 | `fail` | The PR touches no file under `tests/`. |
| 6 | `skip` | The PR has an added or changed test, or a touched path in an unhosted directory, and none of its added or changed tests is hosted and collected on the head. |
| 7 | `pass` | Some hosted changed test is red (`failed` or `error`) on the base and `passed` on the head. |
| 8 | `fail` | None of the earlier rules applies. |

Rule 2 reads the PR title from the event payload. The `pull_request` trigger runs on
`opened`, `synchronize`, and `reopened`. A re-run reuses the event payload, so a
retitled PR keeps the verdict of its last push until the next push.

Rules 1 and 4 check the two runs. Pytest exit codes 2, 3, and 4 mean interrupted,
internal error, and usage error. A report file that exists but does not parse as JSON,
as an empty or a truncated file does, counts as absent. The reason then says
`unreadable report`, and the table still renders.

Rule 1 comes first so that a `refactor` title cannot hide a broken job. Rule 4 comes
after the title rule and the production rule, because the base run of a PR that the
gate does not grade can abort with no defect in the job: see
[Blind spots](#blind-spots). On a PR that the gate grades, an absent base result must
not read as red on base. The gate fails closed: a run that did not complete is an
`error`, and an `error` fails the job.

Rule 6 counts a touched path in an unhosted directory as a changed test there, whether
the PR adds, changes, or deletes it. A deleted test does not count toward rule 6,
because a deleted test cannot fail on the base. A PR that only deletes tests reads
`fail` under rule 8, unless a path that it touches is in an unhosted directory. Rule 8
also covers a PR whose touched files under `tests/`, outside those directories, hold no
test function, such as a change to a `conftest.py` file.

The job exits with code 1 for `fail` and `error`, and with code 0 for the other
verdicts.

### The step summary

Whatever the verdict, the verdict step writes a table to the step summary, under the
heading `Tests redden on base`. Its columns are `test`, `kind`, `suite`, `on base`, and
`on head`, with one row for each changed test. `kind` is `added`, `changed`, or
`deleted`. A deleted test and a test in an unhosted suite show `-` in both outcome
cells. After the table, a list names the touched files under `tests/` that hold no
changed test function.

The base runs of a `fix` PR fail by design. The four pytest steps run with
`continue-on-error: true`, so a failing pytest step does not fail the job. The run page
still shows a red "Process completed with exit code 1" annotation for each failing
pytest step. The verdict step decides the job result, and the step summary table is the
result to read. On a `fail` or an `error`, the verdict step also prints a GitHub `::error`
annotation with the reason, so the run page shows the reason beside the exit code.

### Blind spots

The job has the following blind spots:

- A test that is red on the base for the wrong reason counts as red. Two causes are an
  import error from a renamed helper and a module that imports a symbol that the PR
  added. Both read `error` on the base.
- A base run can abort before it runs a test, and then it writes no report. The usual
  cause is a conftest that imports a symbol which the PR moved or renamed.
  `tests/integration/conftest.py` imports `create_app` from `src.admin.app` at module
  level, for one, so pytest exits with code 4 while it loads that conftest on the base.
  On a PR that the gate grades, the verdict is `error` with the reason
  `base integration: no report`, or `base integration: unreadable report`. Open the
  "Base run (integration, host groups)" step to read the import error. The
  "Base run (unit and harness)" step is the one to open for `base unit`. The same abort
  on a PR whose title the gate does not grade reads `advisory`.
- A migration that the PR adds reaches the base run only through the `adcp_test`
  database, which the `_postgres` step migrates with the head's `alembic`. The
  `integration_db` fixture builds a fresh database with `create_all` from the models of
  the tree under test, so the base run sees the base schema. Only a test that reads
  `adcp_test` directly runs base code on the head schema.
- An edit that changes only literal values, local names, or docstrings is not a changed
  test.
- The comparison reads only the body of a module and of each `Test*` class. It does not
  see a test defined under an `if` or a `try`.
  [`changed_functions.py`](../../scripts/ci/changed_functions.py) states this ceiling.
- A test that the AST lists but pytest never collects reads `not collected`. The verdict
  treats it as unhosted and does not fail it.

### The Summary job

The job is in `summary.needs`. The validate step of `summary` accepts `skipped` for it,
because the job does not run on `push`. Every other job in `needs` must report `success`.

### What blocks a merge

Every verdict is advisory until a maintainer requires `CI / Summary` on the `main`
ruleset. A `fail` or `error` verdict turns the job red on the PR. It blocks the merge
only after that requirement exists. The job needs no change when a maintainer adds it.

## BDD Test Shards

BDD tests (`tests/bdd/test_*.py`, 13 files) run in **2 parallel shards** via
greedy min-load assignment by Gherkin scenario count (`scripts/ci/shard_split.py`).
Each shard uploads coverage; the **Coverage** job combines unit + BDD shard
artifacts and enforces `.coverage-baseline`. The aggregate `BDD Tests` job is
status-only. Shard jobs route pytest through the shared `_pytest` composite.

| Shard | Files | Scenarios (approx.) |
|-------|------:|--------------------:|
| 1/2 | 5 | 479 |
| 2/2 | 8 | 441 |

Reproduce a CI shard locally:

```bash
uv run pytest $(uv run python scripts/ci/shard_paths.py bdd 1)
```

`make test-bdd` (full `tests/bdd/`) runs the same scenarios as both shards combined.

**Load metric note:** greedy assignment balances Gherkin `Scenario` line counts (~920 total). Collected pytest items are much higher (~9×) because each scenario expands by `Examples:` rows and transport parametrization. Wall-clock is dominated by slow DB-heavy scenarios, not test volume — the reason 2 shards was chosen over 3–4.

Structural guard: `tests/unit/test_architecture_ci_bdd_shard_manifest.py`.

## Integration Test Shards

Integration tests are split into 5 parallel shards by entity marker. Shards use a
**strict partition** (priority: creative → product → media-buy → infra → other) so
multi-marker files run in exactly one shard — measured overlap on the pre-fix
markers was 14 duplicate file assignments across shards 1–4.

| Shard | Markers |
|-------|---------|
| creative | `creative` |
| product | `product and not creative` |
| media-buy | `(media_buy or delivery) and not creative and not product` |
| infra | `(transport or auth or … or agent) and not creative and not product and not media_buy and not delivery` |
| other | negation of all 15 markers above |

Each shard runs against a GitHub Actions service container (Postgres 15).

**Admin UI** and **BDD** jobs also require the Postgres service container plus
`_postgres` (wait + migrate) — admin blueprint tests use the `integration_db` fixture.

## E2E Tests

The workflow sets `ADCP_TESTING: true` at the top level for integration/BDD/smoke
jobs. The **E2E job overrides this to empty** so `tests/e2e/conftest.py` starts
`docker-compose.e2e.yml` itself (same as legacy `test.yml`). Do not set
`ADCP_TESTING=true` on the E2E pytest step — that path assumes an already-running
stack on `ADCP_SALES_PORT` and fails with "Server not ready after 60s".

## Reference Creative Agent

The `creative` shard starts a reference creative agent from the upstream
[adcontextprotocol/adcp](https://github.com/adcontextprotocol/adcp) server.
This is the full adcp monolith — the creative agent is one route within it.

### Pinning to a known-good commit

The upstream repo is actively developed and its migrations can break without
warning. We pin to a specific commit SHA via the GitHub archive API:

```yaml
curl -sL https://github.com/adcontextprotocol/adcp/archive/<SHA>.tar.gz \
  | tar xz -C /tmp/adcp-server --strip-components=1
```

**Why archive API instead of `git clone`?** GitHub's smart HTTP protocol does
not allow `git fetch` of arbitrary SHAs on repositories you don't own. A shallow
clone (`--depth 1`) only gets HEAD. The archive endpoint works for any public
commit without authentication.

**When to update the pin:** After verifying that upstream HEAD's migrations run
cleanly. Check the `community_points` / `users` table FK ordering — this was the
failure that prompted pinning (April 2026).

The pin lives only in [`scripts/creative-agent-stack.sh`](../../scripts/creative-agent-stack.sh)
— both CI and `run_all_tests.sh` call that script so local and CI cannot diverge.

### CI image cache (ghcr.io) and retries

On ephemeral GitHub Actions runners, local `/tmp` tarball reuse and `docker image
inspect` guards do not survive between runs. Pin-keyed images in GHCR avoid a
full monolith compile on warm CI runs.

**Publish (trusted `main` context only).** The
[`publish-creative-agent.yml`](../../.github/workflows/publish-creative-agent.yml)
workflow runs on `push` to `main` and `workflow_dispatch`. It logs in to
`ghcr.io` and calls `creative-agent-stack.sh publish`, which builds from the
pinned tarball and pushes `ghcr.io/<repo>/adcp-creative-agent:${IMAGE_TAG}`.
`IMAGE_TAG` is `${ADCP_PIN}-p<checksum>`, where the checksum covers the script's two
patches to the agent source (the Fly size check and the MCP rate limit), so changing
a patch publishes a new tag instead of reusing an image built without it.
If the tag already exists, publish is a no-op. Publish failures fail the
workflow loudly (unlike the test shard, which degrades gracefully).

**CI test shard (pull-only).** The creative matrix leg logs in to `ghcr.io`
(authenticated pulls dodge anonymous rate limits and work for public images
from fork PRs), sets `CREATIVE_AGENT_GHCR_IMAGE`, and calls
`creative-agent-stack.sh up`:

- **Warm run** (public image tag `${IMAGE_TAG}` in ghcr.io): `docker pull` +
  retag to local `adcp-creative-agent` — no compile.
- **Cold / degraded** (package absent, private, or pull blip): fetch tarball and
  `docker build` locally. The shard never pushes.

**Local.** `run_all_tests.sh` calls `up` without `CREATIVE_AGENT_GHCR_IMAGE` —
plain `docker build`, same pin source.

Tarball fetch (`curl -f`), `docker pull`, and `docker build` each retry up to
3 times with exponential backoff to absorb transient `ECONNRESET` flakes.
Publish also retries `docker push`.

The `integration-tests` job grants `packages: read` for GHCR pulls. Publishing
uses `packages: write` only in `publish-creative-agent.yml` on `main`.

**Maintainer prerequisites (org/repo — one-time):**

1. After merge, trigger `Publish creative agent image` via `workflow_dispatch`
   and confirm it creates `adcp-creative-agent` (not `denied: Create
   organization package`). If denied, enable Actions package creation in Org →
   Packages or have an admin pre-create the empty package, then re-run.
2. Set the GHCR package **Public** so fork PRs can pull. Until then, the
   creative shard builds locally everywhere (green, no speedup).

**Fork PR caveat:** warm-cache pull is not verifiable on a fork PR until the
public package exists. Measure the real pull time on `main` before claiming
#1189's <30s warm step — a large image may still exceed 30s; slimming the
image is a sensible follow-up if needed.

### Creative agent infrastructure

The agent runs in its own Docker network (`creative-net`) with a separate
Postgres 16 instance (`adcp-postgres`). It is not connected to the test
database used by our integration tests.

```
creative-net:
  adcp-postgres (Postgres 16, user=adcp, db=adcp_registry)
  creative-agent (port 9999 → 8080)
```

## Security Audit

The `Security Audit` job runs `scripts/security-audit.sh`, which invokes
`uv-secure` against `uv.lock`. Any known vulnerability in a pinned dependency
fails the build unless explicitly ignored with documented rationale in the
script. Fix by bumping the affected package in `pyproject.toml` and running
`uv lock`.

## Postgres Health Check

The service container uses `pg_isready -U adcp_user` for health checks. The
`-U` flag is required — without it, `pg_isready` defaults to the OS user
(`root` on GitHub Actions runners), which produces noisy "role root does not
exist" log entries.

## Branch protection migration

**Do this before merging PR #1372**, or PRs will show green checks that are not
required (or stay blocked on stale `Test Suite / …` names).

### Maintainer checklist

1. Merge PR #1370 (PR2) and rebase PR #1372 (PR3) onto `main`.
2. Run `./scripts/capture-rendered-names.sh` on the rebased PR branch and copy the output.
3. In GitHub → Settings → Rules → `main` branch protection:
   - Remove legacy required checks prefixed with `Test Suite /`.
   - Add all 18 checks prefixed with `CI /` from the script output.
4. Keep non-CI required checks unchanged (`check-pr-title`, CodeQL, `security.yml` jobs, etc.).
5. Merge PR #1372 only after a test PR shows all 18 `CI / …` checks as required and green.
6. After PR #1379 (BDD sharding): add the 2 `CI / BDD Tests (Shard …/2)` required checks and keep `CI / BDD Tests` as the aggregate proxy — **separate** branch-protection update from PR3.

### Local vs CI quality targets

| Target | Runs pytest? | Used by |
|--------|--------------|---------|
| `make quality-ci` | No | CI Quality Gate job |
| `make quality` | Yes (`tests/unit/ -x`) | Local pre-commit habit |
| `make quality-full` | Full suites via `run_all_tests.sh` | Pre-PR local gate |

### Local vs CI Postgres isolation (D9, #1233)

Local `tox -e integration` and `make test-int` reuse a **persistent** Postgres
instance (agent-db or Docker stack on the host). CI integration/admin/BDD jobs
start a **fresh** `postgres:17-alpine` service container per job run.

Cross-test isolation bugs that depend on process-wide factory binding (see
`tests/admin/conftest.py`) can reproduce locally but not in CI, or vice versa.

**Diagnostic:** run `tox -p` or `./run_all_tests.sh quick` locally against a
shared Postgres, then compare with the same slice in CI. If a failure is
isolation-specific, inspect factory session binding and tenant scoping — not
Postgres version drift (guarded by `test_architecture_postgres_image_anchor`).

### Legacy `requires_server` tests removed (D11, #1233)

Integration/admin tests marked ``@pytest.mark.requires_server`` were deselected
by ``-m "not requires_server"`` in tox and CI and never executed (many used the
in-process ``mcp_server`` fixture rather than an external server). Equivalent
coverage lives in ``tests/e2e/`` via ``live_server`` / ``docker_services_e2e``.

**Post-#1234 follow-up — still #1233 scope:**

| Item | Tracking | When |
|------|----------|------|
| `test_sell_readiness_browser.py` admin browser flows | #1233 D11 follow-up | Dedicated admin+e2e-stack CI job |

### Nightly GAM regression (D13, #1477)

~20 tests in `tests/e2e/test_gam_*.py` carry `@pytest.mark.requires_gam`. They
call the live GAM sandbox network and are **excluded from per-PR CI** (quota,
credential blast radius on fork PRs).

| Property | Value |
|----------|-------|
| Workflow | [`.github/workflows/gam-nightly.yml`](../../.github/workflows/gam-nightly.yml) |
| Trigger | Daily cron (`07:00 UTC`) + `workflow_dispatch` |
| Branch | `main` only (`if: github.ref == 'refs/heads/main'`) |
| Environment | `gam-nightly` — create under **Settings → Environments**, restrict deployment branches to `main` |
| Secret | `GAM_SERVICE_ACCOUNT_JSON` on the `gam-nightly` environment (not repo-level; unavailable to fork PRs) |
| Command | `pytest tests/e2e/ -m requires_gam` (GHA Postgres service on :5435 for `gam_lifecycle_db`; tests that request `docker_services_e2e` still start the e2e stack via conftest) |
| `DATABASE_URL` | `postgresql://adcp_user:secure_password_change_me@127.0.0.1:5435/postgres` — GHA `services.postgres` on host port 5435; `gam_lifecycle_db` creates ephemeral databases there |

Failures notify repository watchers via GitHub's default workflow notifications.

**Local equivalent** (requires credentials + Docker):

```bash
export GAM_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export DATABASE_URL=postgresql://adcp_user:secure_password_change_me@127.0.0.1:5435/postgres
uv run pytest tests/e2e/ -m requires_gam -v --timeout=300
```

## Layered pre-commit model (PR 4 of #1234)

| Layer | Trigger | Enforcement |
|-------|---------|-------------|
| Commit (~12 hooks) | `git commit` | ruff, hygiene, gitleaks, repo-invariants — warm target <2s |
| Pre-push (~11 hooks) | `git push` | docs, routes, contracts, mypy — installed via `default_install_hook_types` |
| pytest `arch_guard` | `make quality` | AST guards in `tests/unit/test_architecture_*.py` |
| CI | PR to main | `make quality-ci` in Quality Gate + dedicated jobs (**20** frozen checks after PR #1379) |

Requires pre-commit ≥3.2.0. Run `pre-commit install` once per clone (installs both commit and pre-push hooks). If `pre-commit install` fails with a version-too-old `FatalError`, upgrade with `uv tool install pre-commit`.

Running `make quality` or `make quality-ci` may update the tracked ratchet
baselines (`.duplication-baseline`, `.type-ignore-baseline`,
`.ruff-complexity-baseline`, `.mypy-untyped-defs-baseline`) when counts
decrease. Commit those updates intentionally; CI runs are ephemeral and do
not persist baseline writes.

Checks invoked directly by `make quality-ci` (not via `pre-commit run --all-files` in the Quality Gate):

- **CI-only** (no commit/pre-push stage): `check_code_duplication`, `check-gam-auth-support`,
  `check_response_attribute_access`.
- **Dual-stage** (`pre-push + ci-step` in the coverage map): `check-route-conflicts`,
  `type-ignore-no-regression`, `check-docs-links`, `no-hardcoded-urls`.

See [`.pre-commit-coverage-map.yml`](../../.pre-commit-coverage-map.yml) for hook migration mapping.

## Alembic migrations

`alembic/versions/` is excluded from `ruff format` in `pyproject.toml`. Never
reformat or edit committed migration files in CI PRs — it violates project policy
and creates review noise.

## GitHub Code Quality vs CodeQL scoping (#1422)

Two separate analyzers can comment on Python PRs:

| Analyzer | Configured by | Alembic exclusions |
|----------|---------------|-------------------|
| **CodeQL** (security workflow) | In-repo [`.github/codeql/codeql-config.yml`](../../.github/codeql/codeql-config.yml) | `paths-ignore: alembic/versions/` — honored |
| **Code Quality** (`github-code-quality[bot]`) | GitHub org/repo **Advanced Security → Code Quality** settings | **Not** driven by `codeql-config.yml`; **path exclusions not available yet** (public preview) |

### Problem

Code Quality flags alembic module globals (`revision`, `down_revision`, `branch_labels`, `depends_on`) as "Unused global variable". Those globals are Alembic's public migration API — false positives on every migration touch.

### Current disposition (2026-07)

GitHub Code Quality **does not support path/directory exclusions** today. Org admins cannot mirror `.github/codeql/codeql-config.yml` `paths-ignore` in Code Quality settings — only language selection and runner choice are exposed. GitHub staff have path customization on the roadmap ([community discussion #186446](https://github.com/orgs/community/discussions/186446)).

**Impact:** bot comments are non-gating (COMMENTED, never a failing check) — comment noise only.

**Options until path exclusion ships:**

1. **Wait** (default) — apply `alembic/versions/` exclusion the moment GitHub ships directory customization. Intended scope is already documented here and cross-linked from [`.github/codeql/codeql-config.yml`](../../.github/codeql/codeql-config.yml) via #1491.
2. **Disable Code Quality for Python** — removes alembic false positives but also drops genuine `src/` findings. All-or-nothing; use only if noise becomes intolerable.

Do **not** hunt org settings for a path-exclusion checkbox that does not exist yet.

Track: [#1422](https://github.com/prebid/salesagent/issues/1422).

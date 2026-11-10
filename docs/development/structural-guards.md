# Structural guards

Automated architecture enforcement tests that run on every `make quality`.
Each guard uses AST scanning and introspection to detect violations at the
source level — no runtime execution of business logic needed.

Before you read the inventory, read the decision framework. It governs
whether a guard should exist at all, and most structural concerns are better
served by something that is not a guard. The guard inventory is expected to
shrink as invariants move into types and lint rules.

## Contents

- [Decide whether a guard should exist](#decide-whether-a-guard-should-exist) — the three-question framework; work through it before adding to the inventory
- [Refactoring checks are scaffolding, not guards](#refactoring-checks-are-scaffolding-not-guards) — completion checks get a deletion condition, not a permanent slot
- [What guards catch](#what-guards-catch) — the one defect class that justifies a guard
- [Guard design rules](#guard-design-rules) — shrinking allowlists and the other invariants every guard follows
- [Guard inventory](#guard-inventory) — every active guard, with how it works, its tests, and its known violations:
  - [Transport-boundary guards](#transport-boundary-guards)
  - [Implementation signature](#implementation-signature)
  - [Query type safety guard](#query-type-safety-guard)
  - [internal_detail is an exception](#internal_detail-is-an-exception)
  - [Serialize only at the edges](#serialize-only-at-the-edges)
  - [Repository pattern guard](#repository-pattern-guard)
  - [Self-test and harness guards](#self-test-and-harness-guards)
  - [BDD step quality guards](#bdd-step-quality-guards)
  - [Single migration head guard](#single-migration-head-guard)
  - [No request-supplied session default guard](#no-request-supplied-session-default-guard)
  - [Hook-relocation guards](#hook-relocation-guards)
- [Add a guard](#add-a-guard) — the procedure, and the shared helpers to build on
- [Symbol subjects and shape subjects](#symbol-subjects-and-shape-subjects) — bind a symbol, allowlist a shape
- [Run the guards](#run-the-guards)
- [Relationship to other quality mechanisms](#relationship-to-other-quality-mechanisms) — where guards sit among types, lint, and hooks

## Decide whether a guard should exist

A guard is the last resort, not the first move. Work through these three
questions in order, and stop at the first one that resolves the concern.

### First: can the wrong thing be made unrepresentable?

Correct architecture beats any test, because it removes the ability to
express the mistake instead of detecting it afterwards. There are unbounded
ways to write code wrongly, and a guard can only enumerate the ways someone
thought of. An architecture that makes the wrong call impossible to write is
worth more than a test that reports it.

Concrete substitutions, each backed by a mechanism this repository already
runs:

- **A guard that checks a caller passes certain parameters** → make the
  parameters typed and required. A missing argument is then a mypy error,
  not a test failure. `make quality-ci` runs
  `mypy src/ --config-file=mypy.ini` on every change.
- **A guard that forbids calls to the wrong one of several similar
  functions** → mypy, and ruff's banned-api rule (`TID251`), exist for
  exactly this. `ruff-egress.toml` bans every raw HTTP import across `src/`
  and `scripts/` with a per-import message that names the sanctioned seam,
  and `make quality-ci` runs that check with `--ignore-noqa` so a file
  cannot exempt itself.
- **A guard that watches for growing complexity** → ruff's complexity rules
  already fail the build: `C901` (mccabe, `max-complexity = 10`), `PLR0912`
  (too many branches), and `PLR0915` (too many statements) are
  count-ratcheted against `.ruff-complexity-baseline` by
  `.pre-commit-hooks/check_ruff_complexity_count.py` in `make quality-ci`.
- **A guard that keeps business logic away from raw sessions** → you can
  scan for `.session`, but the better answer is a design where the
  repository and the Unit of Work are the easy path. Make the correct call
  the convenient one, and the wrong call stops being written. The
  repository-pattern guard in the inventory is the backstop while its
  allowlist shrinks, not the primary defense.

### Second: does this need a check at all?

Not every structural concern deserves an artifact. Ask what is actually at
risk if no check exists. A pattern that nothing in future work plausibly
reintroduces, or whose violation is loud on its own — a crash, a type
error, a failing behavioral test — needs no guard on top.

### Last: write a guard

Write a guard only when both earlier answers are no: the wrong thing cannot
be made unrepresentable, and the risk is real. The rest of this document
describes how to write one well and inventories the guards that met that
bar.

## Refactoring checks are scaffolding, not guards

A refactoring check and a permanent invariant are different artifacts.

When the task is "refactor these classes", a check that fails before the
change and passes after it is a legitimate way to know the work is
complete. That is its whole purpose. It does not follow that the check
belongs in the codebase afterwards: it was scaffolding for a finished task.
Delete it when the refactor lands.

A guard earns permanence only if it protects an invariant that future work
could plausibly violate again. "It proved I finished the refactor" is not
that.

## What guards catch

The guards that remain after the framework cover one class of defect:
structural invariants whose violation looks correct in review and surfaces
only as a silent runtime failure. Examples:

- A schema class copies fields from the adcp library instead of inheriting,
  then drifts out of sync when the library changes a field type.
- An MCP wrapper accepts a parameter but doesn't pass it through to the
  shared `_impl` function — callers can set the value, and the wrapper
  silently discards it.
- A database query filters an Integer PK column with string values from
  JSON, returning 0 rows instead of raising an error.

None of these can be made unrepresentable with the types the boundary
offers, and none of them fail loudly on their own. The guards make them
machine-checkable.

## Guard design rules

**Allowlists shrink, never grow.** Every guard has a set of known violations
(existing code that predates the guard). New code that introduces a violation
fails CI immediately. When an existing violation is fixed, the stale-allowlist
test forces you to remove the entry.

**FIXME comments link to a GitHub issue/PR.** Every allowlisted violation has a
`# FIXME(#<gh-issue>)` comment on its allowlist row, or on the comment that
heads its block of rows, linking to a tracked GitHub issue/PR. Use the GitHub
number, never a local beads id — beads ids don't resolve for outside
contributors reading the code.

**AST scanning, not runtime execution.** Guards parse Python source with the
`ast` module. They don't import or execute business logic, so they run fast
and can't be affected by runtime state.

**Introspection for type hierarchies.** Where AST alone is insufficient (for
example, checking a class MRO), guards use `inspect` and `importlib` on the
already-imported modules.

**Shared helpers, not re-implemented traversal.** A guard uses the helpers in
`tests/unit/_architecture_helpers.py` rather than writing its own AST
machinery. See [Add a guard](#add-a-guard).

**Every guard module calls a shared self-test helper.** A detector nobody has
seen fire grades nothing: one that has stopped matching reports "no
violations" over a tree it cannot read, and that pass looks the same as a
clean tree. So every guard module, a `tests/unit/` module whose name starts
with one of `GUARD_MODULE_PREFIXES` (`test_architecture_`, `test_guards_`,
`test_ast_grep_`), calls at least one of the helpers in `SELF_TEST_HELPERS`:

- `assert_detector_catches_ast_snippets`: an AST detector flags each
  known-bad snippet.
- `assert_detector_ignores_ast_snippets`: the detector flags no known-good
  snippet.
- `anchor_consistency_detects_drift`: an anchor-consistency check reports
  sources that disagree.
- `stage_ast_grep_root` and `write_ast_grep_probe`: a disposable root holding
  the real `sgconfig.yml` and `.ast-grep/` rules, and a probe file written
  into it for a rule to match.
- `assert_check_rejects_mutation`: a check that reads files passes on a copy
  of them and rejects the copy once it has been broken.

`tests/unit/test_architecture_guards_have_self_tests.py` holds the rule (see
[Self-test and harness guards](#self-test-and-harness-guards)). It looks for
a call to one of the helpers by name, bare or as an attribute
(`helpers.write_ast_grep_probe(...)`), so an import with no call does not
count, and a hand-rolled self-test, which calls none of them, is not
credited. `KNOWN_WITHOUT_SELF_TEST` lists the guard modules that called no
helper when the rule landed. Give a new guard module a self-test instead of
a row.

## Guard inventory

### Transport-boundary guards

| Test file | What it enforces |
|-----------|-----------------|
| `ruff-boundary.toml` (TID251) | Nothing under `src/` imports `ToolError` except the two edge modules that mint and render it. Replaced an AST scan over a hand-written list of 14 files, which was blind to every module not on it. Proven live by `tests/unit/test_ruff_boundary_bans.py`. |
| `test_transport_agnostic_impl.py` | `_impl` functions have zero transport imports (no fastmcp, a2a, starlette) |
| `ToolImpl` protocol (`src/core/tools/registry.py`, mypy) + `.ast-grep/rules/impl-signature-is-request-and-identity.yml` | Every implementation is exactly `(req: <DTO>, identity: ResolvedIdentity)` (protected) or `(req: <DTO>, identity: PublicIdentity)` (public), the DTO matching its registry row; the annotation is the row's credential policy, derived by `ToolSpec.requires_credential`. Replaced `test_impl_resolved_identity.py` and `test_architecture_boundary_completeness.py`, which read the same fact off `inspect.signature`. |
| `.ast-grep/rules/resolved-identity-constructed-only-by-its-owners.yml` | `ResolvedIdentity(...)` and `PublicIdentity(...)` are constructed only by the resolver and `PrincipalFactory`. Replaced two AST guards (a zero cap over A2A test files and a per-file cap dict over the rest); ruff cannot take it because TID251 bans the import, which forty modules need for annotations. |
| `ruff-boundary.toml` (TID251 on `AdCPAuthRequiredError` / `AdCPAuthenticationError`) | The auth refusals are minted by the resolver alone: a protected tool's `ResolvedIdentity` carries principal and tenant by type, so nothing downstream re-checks; the seller policy that makes `get_products` need a caller is asked by the resolver (`ToolSpec.requires_credential(tenant)`) once it holds the tenant row. Replaced `test_architecture_no_handrolled_identity_guard.py`, which modelled the `if identity is None: raise` shapes and missed the two helper sites the ban found on landing. |
| `ruff-boundary.toml` (TID251 on `src.core.database.repositories.account_lookup`) | The account a request names is resolved by the resolver alone, which builds the identity with it inside (`AccountIdentity` / `ResolvedIdentity.account`); the lookup module can be imported nowhere else under `src/` and `scripts/`. |
| `ruff-ownership.toml` (TID251 on `repositories.principal`, `repositories.principal_lookup`, `auth_utils`, `repositories.account`, `uow.AccountUoW`) + `ruff-boundary.toml` (TID251 on `models.Principal`) | A tool obtains its principal, tenant and account from the identity and nowhere else. A third config rather than more rows in `ruff-boundary.toml` because ruff exempts a whole rule per path: the admin UI and the setup scripts, which manage principals and accounts as data, are exempt from the ownership bans and from nothing in the boundary config. The ORM `Principal` model, whose only exemption is the four repository modules that query it, is banned in the boundary config so the admin tree cannot import it. Proven live by `tests/unit/test_ruff_boundary_bans.py`, which reads both tables. |
| `ruff-boundary.toml` (TID251 on `adcp.types.ContextObject`) + `.ast-grep/rules/context-is-written-by-the-boundary-alone.yml` + `AdcpResponse`'s two refusals | The buyer's `context` object is written by `_boundary._served` alone. The import ban stops business logic naming the type (the schemas and the boundary are exempt), the rule stops a `context=` keyword at any call site outside the boundary, and the response class refuses the field on construction and on assignment, so a dict-splat cannot slip past the rule. Proven by `tests/unit/test_ast_grep_identity_rules.py`, `test_ruff_boundary_bans.py` and `test_response_context_is_boundary_owned.py`. |

These guards enforce Critical Pattern #5: shared `_impl` functions are
transport-agnostic. They don't know whether they're called from MCP, A2A, or
a REST endpoint.

### Implementation signature

**Where:** the `ToolImpl` protocol typing `ToolSpec.impl` in `src/core/tools/registry.py`,
graded by mypy, plus `.ast-grep/rules/impl-signature-is-request-and-identity.yml`.

**What it enforces:** An `_impl` function declares exactly `(req: <DTO>,
identity: ResolvedIdentity)`, and the DTO is the one its registry row names.

**Why it matters:** Every transport reaches an implementation through
`src/core/tools/_boundary.py`, which calls it as `impl(req=..., identity=...)` and nothing
else. A third parameter can never be filled, so it silently takes its default on every call;
an `identity` declared Optional or defaulted describes a state the boundary never produces
and invites a `None` branch that re-derives what the resolver decided.

#### How it works

The generic `ToolSpec[Req]` ties `dto: type[Req]` to `impl: ToolImpl[Req]`, so mypy checks
each row's implementation against that row's DTO and against `ResolvedIdentity`, and rejects
an extra parameter with no default. A protocol accepts a callable that takes MORE than it
asks for, so the ast-grep rule matches the parameter list exactly: no Optional, no default,
no third parameter.

#### What it replaced

`test_impl_resolved_identity.py` and `test_architecture_boundary_completeness.py` read the
same signature off `inspect.signature` at test time. The latter is the cautionary one: it
used to scan each `*_raw` wrapper for the arguments it forwarded, and its wrapper lookup
returned `None` — "nothing to check" — when it found no wrapper, so the day the wrappers were
deleted it went green while grading nothing.

### Query type safety guard

**File:** `tests/unit/test_architecture_query_type_safety.py`

**What it enforces:** Database queries must use Python types matching the
SQLAlchemy column type. Specifically: don't pass string values to Integer PK
columns.

**Why it matters:** When JSON data arrives at the API boundary, IDs are strings
(`"42"`). If these strings are passed directly to `.in_()` or `filter_by()` on
an Integer column, the behavior is database-dependent — PostgreSQL may do an
implicit cast, but some paths return 0 rows silently.

#### How it works

The guard catalogs all models with Integer primary keys:

```python
INTEGER_PK_MODELS = {
    "PricingOption": "id",
    "SyncJob": "sync_id",
    "AuditLog": "log_id",
    # ... 18 total
}
```

It then scans 12 source files for two AST patterns:

1. **`.in_()` on Integer PK columns:** `PricingOption.id.in_(some_list)` — the
   argument type can't be verified statically, so every occurrence is flagged
   for review
2. **String literals in `filter_by()`:** `filter_by(id="42")` — this is always
   a bug

#### Example of what it catches

```python
def _get_pricing_options(pricing_option_ids: list[Any]):
    # pricing_option_ids come from JSON — they're strings like ["42", "99"]
    # PricingOption.id is an Integer column
    stmt = select(PricingOption).where(
        PricingOption.id.in_(pricing_option_ids)  # FLAGGED: strings → Integer column
    )
```

The fix is to cast at the boundary: `[int(x) for x in pricing_option_ids]`.

#### Tests

| Test | What it checks |
|------|---------------|
| `test_no_in_queries_on_integer_pk_with_wrong_type` | No new `.in_()` calls on Integer PK columns without review |
| `test_no_string_literals_in_filter_by_for_integer_pks` | No `filter_by(id="string")` patterns |
| `test_known_violations_still_exist` | Allowlisted violations haven't been fixed (stale entry detection) |

#### Current known violations (1)

| File | Pattern | Tracked by |
|------|---------|------------|
| `media_buy_delivery.py` | `PricingOption.id.in_(string_list)` | salesagent-mq3n |

### internal_detail is an exception

**Files:** `.ast-grep/rules/internal-detail-is-an-exception.yml`

**What it enforces:** `AdCPSalesAgentError.internal_detail` takes the caught exception
and nothing else. The rule matches the keyword argument `internal_detail=` and the
attribute assignment `x.internal_detail =` whose value is an authored string in any
spelling: a string or f-string literal, an implicitly concatenated string, a `+` with a
string on either side, `%` formatting of a string, `.format(...)` on a string, `str(...)`,
a conditional expression with a string arm, or any of those in parentheses, nested to any
depth, under `src/`, `scripts/` and `tests/`. The parameter is typed
`BaseException | None`, so mypy already refuses a string under `src/`; the rule is what
covers the harness and the tests, which mypy does not check.

**Why it matters:** An authored sentence there says nothing the error code, the
exception class and the typed details do not already say, and it reopens the door
ADR-010 closed: the wire fields are functions of the code. A fact (an id, a count, a
status) belongs on the declared details class. The boundary's `record_boundary_error`
writes one record per failure, with the traceback attached when the error has a
`__cause__` or an `internal_detail`; there is no second log record for `internal_detail`
(salesagent-3cs7o.24, proven by `tests/unit/test_tool_error_logging.py`).

### Serialize only at the edges

**Files:** `ruff-serialization.toml` and `.ast-grep/rules/serialize-only-at-the-edges.yml`

**What it enforces:** a model is serialized at a named edge and nowhere else. The
ruff config bans the two bare-call spellings that are importable names,
`pydantic_core.to_jsonable_python` and `pydantic_core.to_json`, everywhere under
`src/` and `scripts/`, with per-file-ignores for exactly the edge modules. The
ast-grep rule matches the method-call spellings, `.model_dump(...)` and
`.model_dump_json(...)`, under `src/` with the same edge list as its `ignores`,
because a method call on an instance imports nothing and ruff cannot see it. The
edge list is the definition of "edge"; it lives in those two files and nowhere else.

**Why it matters:** When business logic serializes, it takes on the serialization
format (JSON mode, aliases, exclude rules) and produces a second representation of
the value that drifts from the model. The model is handed through; the edge that
owns the format serializes it once.

#### What it replaced

An AST guard under `tests/unit/` walked from `*_impl` entrypoints under
`src/core/tools/` and saw only calls named `model_dump`. A call
reached through a helper outside that walk, or spelled `to_jsonable_python`, was a
hole, and `src/core/tools/creatives/_validation.py` escaped it that way. Its
allowlist was already empty. The ruff table is proven live by
`tests/unit/test_ruff_boundary_bans.py`; the ast-grep rule by a manual fire probe,
recorded on salesagent-3cs7o.12.

### Repository pattern guard

**File:** `tests/unit/test_architecture_repository_pattern.py`

**What it enforces:** Three invariants:

1. **No `get_db_session()` in business logic.** No function in the `_impl`
   modules calls `get_db_session()` directly — data access belongs in
   repository classes.
2. **No `session.add()` or `session.add_all()` in test code.** No test,
   fixture or helper function under `tests/` adds a row through a session —
   the factories in `tests/factories/` add it.
3. **No `get_db_session()` in test code.** No test, fixture or helper
   function under `tests/` opens a raw session — it reaches the database
   through factories and the harness UoW
   (`with AccountUoW(tenant_id) as uow: uow.accounts`).

The same file also holds a reverse-layer check (no module under
`src/core/database/repositories/` imports from `adcp.types.domains.protocol`)
and two shape checks on signed outbound delivery
(`TestDeliveryBoundaryTakesNoDonatedSession` and
`TestQueuedWebhookCarriesPrimitivesOnly`); their docstrings describe them.

**Why it matters:** When business logic directly opens database sessions, it
becomes impossible to test without a real database, impossible to swap storage
backends, and impossible to enforce consistent transaction boundaries. Similarly,
when tests scatter `session.add()` calls through test bodies, fixture setup is
duplicated, brittle, and hard to maintain.

This guard is the backstop for the framework's fourth substitution: the
primary defense is a repository and Unit of Work layer that is easier to
call than a raw session. The guard holds the line while the allowlist
shrinks.

#### How it works

The guard parses each scanned file and reports, per function or fixture, the
first call that matches. A row is `(path, function name)`, so a new function
in a file that already has rows is still caught. Calls outside a function
body are not read.

**Invariant 1** reads every tracked module under `src/core/tools/` and
`src/core/helpers/`, found by a glob on each run, plus
`src/core/context_manager.py` and `src/admin/blueprints/creatives.py`. It
flags `get_db_session()` in both the bare and the `module.get_db_session()`
form:

```python
# FLAGGED: business logic opens its own session
async def _create_media_buy_impl(req, identity):
    with get_db_session() as session:   # ← violation
        media_buy = MediaBuy(...)
        session.add(media_buy)

# CORRECT: a repository, reached through the Unit of Work, encapsulates data access
async def _create_media_buy_impl(req, identity):
    with MediaBuyUoW(identity.tenant_id) as uow:
        media_buy = uow.media_buys.create_from_request(req=req, ...)
```

**Invariants 2 and 3** read every `.py` file under `tests/` that git tracks:
test modules, conftest files, BDD step modules, helpers, fixtures, factories
and the harness. A file git does not track is skipped, so the Python that the
storyboard env's `npm ci` leaves under `tests/storyboard/runner/node_modules/`
on the CI box is not read there, and a new file is scanned once it is staged.
The scan stops nowhere because a call that moves out of the scanned files
disappears from the guard: two rows were once removed as fixed when their
calls had only moved into `tests/utils/`, and an enumerated list of roots
missed `tests/bdd/steps/` and `tests/conftest_db.py` the same way.

Invariant 2 matches `add` and `add_all` on a receiver named in
`SESSION_RECEIVERS` (`session`, `db_session`, `mock_session`, `s`,
`_session`, `factory_session`). The receiver is a bare name or the last
attribute of a chain, so `self.session.add(row)` and `env._session.add(row)`
are flagged and `seen.add(x)` on a set is not. Invariant 3 matches
`get_db_session()` the way invariant 1 does:

```python
# FLAGGED: rows added by hand, through a bare or an attribute receiver
def test_something(integration_db):
    with get_db_session() as session:     # ← invariant 3
        session.add(Tenant(name="test"))  # ← invariant 2
        session.add_all(products)         # ← invariant 2

class _Seeder:
    def seed(self, row):
        self.session.add(row)             # ← invariant 2

# CORRECT: a factory adds the row, through the session the harness binds
def test_something(integration_db):
    with DeliveryPollEnv(tenant_id="t1", principal_id="p1") as env:
        tenant = TenantFactory(tenant_id="t1")
```

#### Tests

| Test | What it checks |
|------|---------------|
| `test_no_new_get_db_session_in_impl` | No `get_db_session()` in the scanned `src/` modules (`IMPL_SESSION_ALLOWLIST` is empty) |
| `test_no_new_session_add_in_tests` | No `add` / `add_all` on a session receiver under `tests/` outside `INTEGRATION_SESSION_ADD_ALLOWLIST` |
| `test_no_new_get_db_session_in_tests` | No `get_db_session()` under `tests/` outside `GET_DB_SESSION_IN_TESTS_ALLOWLIST` |
| `test_allowlist_entries_still_exist` (one per invariant) | Stale allowlist detection: a row whose call is gone fails |
| `test_session_add_detector_sees_add_all_and_attribute_receivers` | Self-test: `session.add`, `session.add_all`, `self.session.add`, `env._session.add` and `factory_session.add` are flagged |
| `test_session_add_detector_ignores_sets_and_other_receivers` | Self-test: `seen.add(x)` and `batch.add_all(rows)` are not flagged |
| `test_scan_roots_include_unit_bdd_and_harness` | The scanned files include modules under `tests/unit/`, `tests/bdd/steps/`, `tests/harness/`, `tests/fixtures/` and `tests/factories/` |
| `test_discovery_glob_catches_a_synthetic_new_file` | The invariant 1 glob picks up a file it has never seen, so the scan set is computed on each run |
| `test_discovery_glob_covers_the_files_the_old_list_missed` | The invariant 1 scan includes `src/core/tools/accounts.py` and modules under `src/core/helpers/` |

#### Allowlists

Each is keyed `(path, function name)`.

- `IMPL_SESSION_ALLOWLIST` is empty and stays empty: the `_impl` migration
  finished in [#1094](https://github.com/prebid/salesagent/issues/1094), so a
  row there is a regression.
- `INTEGRATION_SESSION_ADD_ALLOWLIST` holds the existing `session.add()` and
  `add_all()` sites in test code; its header cites
  [#2133](https://github.com/prebid/salesagent/issues/2133).
- `GET_DB_SESSION_IN_TESTS_ALLOWLIST` holds the existing `get_db_session()`
  sites in test code; its header cites
  [#2538](https://github.com/prebid/salesagent/issues/2538).

### Self-test and harness guards

The first of these guards holds every guard module to the self-test rule in
[Guard design rules](#guard-design-rules). The other three keep a test on the
harness: a test takes its env from `tests/harness/`, its app and its client
from the harness, and its rows from a factory in `tests/factories/`. The
[repository pattern guard](#repository-pattern-guard) fails the
`session.add()` that a missing factory forces; the factory guard below fails
the missing factory.

Each of these guards calls both `assert_detector_catches_ast_snippets` and
`assert_detector_ignores_ast_snippets`. Each allowlist lists the sites that
existed when its guard landed, only shrinks, and carries a
`# FIXME(#<issue>)` comment on every row. Rows are keyed by name, never by
line number, so an edit above a site does not stale its row. To leave an
allowlist, fix the site and delete its row in the same change; the
stale-entry check fails until the row is gone.

#### Every guard module has a self-test

**File:** `tests/unit/test_architecture_guards_have_self_tests.py`

**What it enforces:** Every guard module, a `tests/unit/` module named with
one of `GUARD_MODULE_PREFIXES`, calls at least one helper named in
`SELF_TEST_HELPERS`.

**Why it matters:** A guard that has never been seen to fail is not known to
grade anything ([tests/unit/CLAUDE.md](../../tests/unit/CLAUDE.md)). A
self-test keeps that check in the suite, where it runs on every
`make quality`.

**How it works:** `iter_architecture_guard_trees()` yields each guard module,
and `called_function_names()` collects every callee name in it, the bare name
or the last attribute (`helpers.write_ast_grep_probe(...)`). A module passes
when one of those names is in `SELF_TEST_HELPERS`. A call anywhere in the
module counts, including one in a function that no test calls; the
detector's docstring names that ceiling.

```python
# FLAGGED: a hand-rolled self-test calls no shared helper
def test_self():
    assert find(ast.parse("bad()"))

# CORRECT: a shared helper, called bare or as an attribute
def test_detector_catches_known_bad():
    assert_detector_catches_ast_snippets(find, snippets={"call": "bad()\n"})
```

**Tests:**

| Test | What it checks |
|------|---------------|
| `test_every_guard_module_calls_a_shared_self_test_helper` | Every guard module that calls no helper is a row in `KNOWN_WITHOUT_SELF_TEST`, and no row is stale |
| `test_meta_guard_flags_a_module_with_no_helper_call` | A module with only plain asserts, one with a hand-rolled self-test, and one that imports a helper without calling it are flagged |
| `test_meta_guard_accepts_each_helper_by_name_and_as_attribute` | A call to each name in `SELF_TEST_HELPERS` passes, and so does the attribute form |

**Allowlist:** `KNOWN_WITHOUT_SELF_TEST`, keyed `(path,)`; every row carries
`# FIXME(#2534)` ([#2534](https://github.com/prebid/salesagent/issues/2534)).

#### No env subclass outside the harness

**File:** `tests/unit/test_architecture_no_private_env_subclass.py`

**What it enforces:** No class outside `tests/harness/` derives from a
harness env root (`ENV_ROOTS`: `BaseTestEnv`, `IntegrationEnv`,
`BareIntegrationEnv`), directly or through any chain of bases, including a
class defined inside a test function.

**Why it matters:** A test module that subclasses an env defines a private
env: its own `EXTERNAL_PATCHES`, seeding or dispatch. When a test cannot
express the state it needs, the harness is what changes
([tests/harness/CLAUDE.md](../../tests/harness/CLAUDE.md)). A private
subclass leaves that change undone, and the next test that needs the same
state copies the subclass.

**How it works:** `iter_test_module_trees()` parses every tracked module under
`tests/`, harness included, and `class_base_index()` maps each class name to
the base names it is declared with. `derives_from_env()` follows that index
to a root, so a class that reaches one through a local mixin or through a
harness env is found. Only classes outside `tests/harness/` are reported.
The scan reads the AST, so a class written inside a string literal is not a
class.

```python
# FLAGGED in tests/integration/: a private copy of an env the harness has
class _RepoEnv(IntegrationEnv):
    EXTERNAL_PATCHES: dict[str, str] = {}

    def get_session(self):
        self._commit_factory_data()
        return self._session

# CORRECT: the harness env; a method a test needs is added to it in tests/harness/
with BareIntegrationEnv(tenant_id="t1") as env:
    session = env.get_session()
```

**Tests:**

| Test | What it checks |
|------|---------------|
| `test_no_env_subclass_outside_the_harness` | Every env subclass outside `tests/harness/` is a row in `KNOWN_PRIVATE_ENV_SUBCLASSES`, and no row is stale |
| `test_flags_a_subclass_at_module_level_and_inside_a_function` | A subclass at module level, one inside a test function, one with a local mixin beside a root, and one that reaches a root through a harness env (`TaskManagementEnv`) are flagged |
| `test_ignores_classes_that_do_not_derive_from_an_env_root` | A subclass of the e2e `_LiveDBEnv` shim, which has no env base, a plain class, and a class inside a string literal are not flagged |

**Allowlist:** `KNOWN_PRIVATE_ENV_SUBCLASSES`, keyed `(path, class name)`;
every row carries `# FIXME(#2535)`
([#2535](https://github.com/prebid/salesagent/issues/2535)). A row leaves
when its test uses `BareIntegrationEnv` or the domain env, with any method
it needs added to that env.

#### The app and its clients built by the harness

**File:** `tests/unit/test_architecture_app_built_by_harness_only.py`

**What it enforces:** No module under `tests/` outside `tests/harness/` and
`tests/helpers/` calls a name in `APP_CONSTRUCTORS` (`create_app`, `Flask`,
`FastAPI`, `TestClient`), bare or as an attribute, or the `test_client` method
(`CLIENT_METHOD`).

**Why it matters:** A test takes its app and its client from the harness:
the `admin_client` fixture, `env.get_rest_client()`, or
`tests/helpers/admin_session.admin_test_app()`. A module that builds its own
app builds a second one that the harness does not configure, so a patch the
harness applies misses it.

**How it works:** The scan walks every tracked module under `tests/` outside
those two directories with `walk_with_enclosing_function()` and flags each
matching call; a string that mentions `create_app()` is not a call. Rows are
keyed `(path, enclosing function)`, a call at module level keys under
`"<module>"`, and one row covers every construction in a function. The match
is by callee name, so a constructor imported under another name
(`TestClient as Client`) is not seen. The two `admin_client` fixtures, in
`tests/admin/conftest.py` and `tests/integration/conftest.py`, build their
app and client themselves and are rows; a test that takes the fixture adds
none.

```python
# FLAGGED: a second app, built when the module is imported, and its client
from src.admin.app import create_app

app = create_app()

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

# CORRECT: the client comes from the harness
def test_accounts_page(admin_client):
    response = admin_client.get(url)
```

**Tests:**

| Test | What it checks |
|------|---------------|
| `test_tests_build_no_app_or_client_outside_the_harness` | Every construction outside `tests/harness/` and `tests/helpers/` is a row in `KNOWN_APP_CONSTRUCTIONS`, and no row is stale |
| `test_flags_each_construction_form` | `create_app()` at module level, `admin.create_app(...)`, `Flask(...)`, `FastAPI(...)`, `TestClient(...)` and `app.test_client()` are flagged |
| `test_ignores_the_harness_names_and_unrelated_calls` | `admin_test_app()`, `env.get_rest_client()` and `make_users_test_client()` are not flagged |

**Allowlist:** `KNOWN_APP_CONSTRUCTIONS`, keyed `(path, enclosing function)`;
every row carries `# FIXME(#2536)`
([#2536](https://github.com/prebid/salesagent/issues/2536)).

#### Every ORM model has a factory

**File:** `tests/unit/test_architecture_every_model_has_a_factory.py`

**What it enforces:** Every ORM model in `src/core/database/models.py` has a
`SQLAlchemyModelFactory` in a module directly under `tests/factories/`.

**Why it matters:** A test seeds a row through a factory, and the harness
binds a session to each factory registered in `ALL_FACTORIES`. A model with
no factory leaves the test one way to create the row: construct the model
and call `session.add()`, which the
[repository pattern guard](#repository-pattern-guard) bans in test code. The
missing factory is the defect, and the `session.add()` is its symptom.

**How it works:** The scan collects the class name of every ORM model
(`orm_model_class_defs()`) and reads the modules directly under
`tests/factories/`, not its subdirectories. A class is a factory when one of
its bases is `SQLAlchemyModelFactory`, bare or as an attribute
(`factory.alchemy.SQLAlchemyModelFactory`); it credits the model its nested
`Meta` assigns, `model = Tenant` or `model = models.Tenant`. A Pydantic
factory (`factory.Factory`) named after a model builds a schema object, not a
row, and credits nothing. The scan reads class definitions, not
`ALL_FACTORIES`, and does not follow a base chain, so a factory that derives
from another factory class credits no model.

```python
# FLAGGED: Tenant still has no factory, because factory.Factory builds a schema object
class TenantFactory(factory.Factory):
    class Meta:
        model = Tenant

# CORRECT: a SQLAlchemyModelFactory credits Tenant
class TenantFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Tenant
```

**Tests:**

| Test | What it checks |
|------|---------------|
| `test_every_orm_model_has_a_factory` | Every model without an ORM factory is a row in `KNOWN_MODELS_WITHOUT_FACTORY`, and no row is stale |
| `test_flags_a_model_with_no_orm_factory` | A module with only another model's factory, or only a Pydantic factory named like the model, leaves the model missing |
| `test_credits_bare_and_attribute_model_names` | `model = Tenant`, `model = models.Tenant`, and a factory defined inside a function body credit `Tenant` |

**Allowlist:** `KNOWN_MODELS_WITHOUT_FACTORY`, keyed `(model name,)`; every
row carries `# FIXME(#2537)`
([#2537](https://github.com/prebid/salesagent/issues/2537)). It is the one
list of the models without a factory: a document that needs the list names
this constant instead of restating it. A row leaves when the model's factory
is added in `tests/factories/` and registered in `ALL_FACTORIES` in
`tests/factories/__init__.py`.

### BDD step quality guards

Five AST-scanning guards enforce step definition quality in `tests/bdd/steps/`.
They prevent the most common LLM-generated BDD anti-patterns.

#### No-op Then steps

**File:** `tests/unit/test_architecture_bdd_no_pass_steps.py`

Catches three failure modes in `@then` step functions:
1. **Empty body** — `pass`, ellipsis, or docstring-only
2. **No code** — no assert, call, or raise at all
3. **No-op delegation** — body has zero `assert` statements and only delegates to
   non-assertion helpers (like `_pending(ctx, step)`). Catches any LLM-invented
   placeholder by structure, not by name.

A call counts as "meaningful" only if the function name starts with `assert_`,
`_assert_`, `check_`, `_check_`, `verify_`, `_verify_`, or is `pytest.skip/xfail/fail`,
or is `env.*` (harness method).

**Current known violations:** 41 Then steps in `uc004_delivery.py` using `_pending()`.

#### Trivial assertions

**File:** `tests/unit/test_architecture_bdd_no_trivial_assertions.py`

Catches `@then` steps that only use bare truthiness checks (`assert x`) without
comparisons (`==`, `!=`, `in`, `not in`, `is`, `isinstance`).

#### No dict in registry

**File:** `tests/unit/test_architecture_bdd_no_dict_registry.py`

Catches `@given` steps that store raw dict literals in `ctx["registry_formats"]`
instead of `FormatFactory.build()` objects.

#### No duplicate step bodies

**File:** `tests/unit/test_architecture_bdd_no_duplicate_steps.py`

Catches groups of 3+ step functions with identical normalized bodies (after
stripping docstrings). Threshold of 2 is tolerated for partition/boundary pairs.

#### No silent env degradation

**File:** `tests/unit/test_architecture_bdd_no_silent_env.py`

Catches two "No Quiet Failures" violations:
1. **`ctx.get("env")`** — returns `None` instead of `KeyError` when harness is missing.
   Canonical: `ctx["env"]` (guaranteed by autouse fixture).
2. **`hasattr(env, "method")`** — probes harness at runtime instead of using typed
   protocols. If env lacks a method, xfail the scenario rather than silently skip.

**Current known violations:** 17 `ctx.get("env")` + 22 `hasattr(env, ...)` in `uc004_delivery.py`.

### Single migration head guard

**File:** `tests/unit/test_architecture_single_migration_head.py`

**What it enforces:** The Alembic migration graph must have exactly one head
revision at all times.

**Why it matters:** When two PRs each create a migration branching from the
same parent and both merge to main, the migration DAG forks into multiple
heads. This makes `alembic upgrade head` fail, `alembic downgrade -1`
ambiguous, and `alembic revision` error without `--head`. The problem is
invisible to PR authors because neither has the other's migration locally.

#### How it works

The guard parses every migration file's AST to extract `revision` (string)
and `down_revision` (string, tuple, or None). It handles both `ast.Assign`
and `ast.AnnAssign` styles. It then builds the set of all revisions and the
set of all revisions pointed to by a `down_revision`. Heads are revisions
not pointed to by any other migration. The test asserts exactly one head.

#### Tests

| Test | What it checks |
|------|---------------|
| `test_single_migration_head` | Exactly one head exists in the migration graph |

#### No allowlist

Zero tolerance. If multiple heads exist, you must create a merge migration
before your PR merges:

```bash
uv run alembic merge -m "Merge migration heads" heads
```

The smoke test in `tests/smoke/test_database_migrations.py` also checks this,
providing coverage in the CI smoke-tests job before unit tests run.

### No request-supplied session default guard

**File:** `tests/unit/test_architecture_no_request_session_default.py`

**What it enforces:** A Flask session lookup — `session.get`, `session.pop` or
`session.setdefault` with a string key, anywhere under `src/` — never defaults
(positionally or by `default=`) to a value the request supplied: a `request.*`
expression, a parameter of the enclosing function (route arguments arrive that
way), or a name bound from `request.*` in that function. Nor is such a lookup
followed by `or <any of those>`.

**Why it matters:** The default is taken exactly when the request carries no
session, which is the request that must not be trusted.
`session.pop("gam_oauth_tenant_id", state)` in the GAM OAuth callback was the
whole of [#2205](https://github.com/prebid/salesagent/issues/2205): with no
session, the tenant came from the attacker-controlled `state` parameter and
that tenant's ad-server credential was overwritten. The line read as a
harmless fallback in review and failed nothing at runtime.

#### How it works

For every function the guard collects its parameters and every name assigned
from an expression rooted at `request`. It then walks the module with
`walk_with_enclosing_function` and flags two shapes. First, a call to
`.get`/`.pop`/`.setdefault` on `session`, `flask_session` or `<module>.session`
whose first argument is a string constant (which is what separates the Flask
session from SQLAlchemy's `Session.get(Model, pk)`) and whose default — the
second positional argument or the `default=` keyword, which Flask's session
accepts on `pop` and `setdefault` — mentions one of those names or is itself
rooted at `request`. Second, an `or` expression in which such a lookup is
followed by an operand that mentions one of those names or is rooted at
`request`.
A default computed from the session itself — `session.get("user_name",
email.split("@")[0].title())` with `email = session["user"]` — is not flagged.

#### Tests

| Test | What it checks |
|------|---------------|
| `test_no_request_supplied_session_default` | No violation under `src/` beyond `KNOWN_VIOLATIONS` (empty) |
| `test_detector_catches_known_bad` | The detector fires on a route-parameter default, a name bound from `request.args`, a `request.args.get(...)` default, a `default=` keyword, `setdefault`, the `or request...` form, `or` with a request-bound name or a route parameter, and the `flask_session` alias |
| `test_detector_ignores_session_derived_defaults_and_orm_sessions` | Literal and session-derived defaults, `session.pop(...) or session.get(...)`, and `db_session.get(Tenant, pk)` are not flagged |

#### No allowlist

`KNOWN_VIOLATIONS` is empty and stays empty: the one violation was the bug
the guard was written for.

### Hook-relocation guards

These guards run via `pytest -m arch_guard` or as part of `make quality`.
They replaced grep-based pre-commit hooks (issue #1234).

| Test file | Replaces hook | What it enforces |
|-----------|---------------|------------------|
| `test_architecture_no_tenant_config.py` | `no-tenant-config` | No `tenant.config` / `tenant["config"]` in `src/` |
| `test_architecture_jsontype_columns.py` | `enforce-jsontype` | JSON columns use `JSONType`, not plain `JSON` |
| `test_architecture_no_defensive_rootmodel.py` | `check-rootmodel-access` | No `hasattr(x, "root")` without `# noqa: rootmodel` |
| `test_architecture_import_usage.py` | `check-import-usage` | Tree-wide import usage check for `src/` |
| `test_architecture_query_type_safety.py` | `enforce-sqlalchemy-2-0` (partial) | `test_no_legacy_session_query`, `test_models_use_mapped_not_column` |
| `test_architecture_pre_commit_hook_count.py` | — | Commit-stage hook count ≤12 (D27) |
| `test_architecture_pre_commit_no_additional_deps.py` | — | No `additional_dependencies` in pre-commit config |
| `test_architecture_repo_invariants.py` | `repo-invariants` (partial) | Self-tests for `.fn()` detection in consolidated hook |

Guards use the `@pytest.mark.arch_guard` marker (distinct from the
entity-marker `architecture`).

`KNOWN_WITHOUT_SELF_TEST` in
`tests/unit/test_architecture_guards_have_self_tests.py` lists the modules in
this table that call no shared self-test helper yet; the others call one.

CI-only hook enforcement runs in `make quality-ci`: duplication, GAM auth
support, response attribute access, roundtrip tests. See
`.pre-commit-coverage-map.yml`.

## Add a guard

Before step 1, work through
[Decide whether a guard should exist](#decide-whether-a-guard-should-exist).
If the invariant can live in a type signature, a mypy check, or a ruff rule,
put it there and stop. If the check only proves a refactor is finished, write
it, use it, and delete it with the refactor — don't add it here.

1. Create `tests/unit/test_architecture_{name}.py`
2. Use AST scanning (not `inspect.getsource()` — it's banned by lint rules)
3. Build on the shared helpers in `tests/unit/_architecture_helpers.py`
   instead of re-implementing traversal (see the following section)
4. Include an allowlist for pre-existing violations
5. Include a stale-allowlist test that fails when a violation is fixed but the
   entry remains
6. Call a shared self-test helper from a test in the module (see
   [Guard design rules](#guard-design-rules));
   `test_architecture_guards_have_self_tests.py` fails a guard module that
   calls none
7. Put a `# FIXME(#<gh-issue>)` comment on each allowlist row, or on the comment that heads a block of rows (GitHub issue/PR number, never a beads id)
8. Document the guard in this file

### Use the shared helpers

`tests/unit/_architecture_helpers.py` centralizes the machinery guards need,
so a guard states its rule and borrows everything else. The pieces most
guards use:

- `repo_root()` / `rel()` — the repo-root anchor and repo-relative paths for
  stable allowlist keys.
- `parse_module()` — AST parsing with an mtime-keyed cache shared across
  guards; `safe_parse()` is the variant that returns `None` for a missing or
  unparseable file.
- `iter_module_trees()` — yields `(tree, repo_relative_path)` for every
  `.py` file under the given directories, through the shared cache, and
  raises on an unparseable file instead of silently dropping it. It lists
  only files git tracks (`is_untracked_repo_file()`): the storyboard env's
  `npm ci` leaves Python under `tests/storyboard/runner/node_modules/` on the
  CI box, and a walk of the disk would read those files there and not on a
  developer machine. A new file is walked once it is staged, and a path
  outside the repository is never skipped, so a self-test can point the walk
  at a `tmp_path` tree.
- `iter_test_module_trees()` — `(repo_relative_path, tree)`, path first, for
  every tracked `.py` under `tests/`, through `iter_module_trees()`.
- `GUARD_MODULE_PREFIXES` and `iter_architecture_guard_trees()` — the
  file-name prefixes a guard module in `tests/unit/` is spelled with, and a
  walk that yields `(tree, repo_relative_path)` for each such module.
- `ENV_ROOTS`, `class_base_index()` and `derives_from_env()` — the roots of
  the harness env hierarchy, an index from each class name in the given
  modules to its base-class names (classes nested in a function body
  included), and whether a class name reaches a root through that index.
- `src_python_files()` and `iter_call_expressions()` — source-file iteration
  and call-node filtering.
- `walk_with_enclosing_function()` — yields each node with the name of its
  enclosing function, for rules scoped to `_impl` or step functions.
- `assert_violations_match_allowlist()` — the standard
  new-violation/stale-entry comparison.
- `format_failure()` — the standard failure-message formatter.
- `assert_detector_catches_ast_snippets()` — feeds known-bad inline snippets
  to your detector and fails if any go unflagged.
- `assert_detector_ignores_ast_snippets()` — the inverse: feeds known-good
  snippets and fails if the detector flags any. A detector that flags a
  legitimate shape is as wrong as one that misses a violation.
- `assert_check_rejects_mutation()` — for a guard that reads files (a pin, a
  config, a workflow) rather than the AST: copies the named paths into a
  temporary directory, requires the check to pass on the copy, breaks the
  copy with the given mutation, and fails unless the check now rejects it.
  The real tree is never touched.
- `anchor_consistency_detects_drift()` — true when the given sources carry
  conflicting anchors; the mutation probe for a guard built on
  `assert_anchor_consistency()`.
- `stage_ast_grep_root()` and `write_ast_grep_probe()` — a disposable project
  root holding the real `sgconfig.yml` and `.ast-grep/` rules, and a probe
  module written at a unique path under it, in the directory a rule's
  `files:` glob covers. The probe never lands in `src/` or `tests/`, where
  another guard's scan could list it and then fail to read it once it is
  deleted.

`assert_detector_catches_ast_snippets` matters more than it looks: a
detector nobody proved can fire is a guard that passes vacuously. A green
run then reports "no violations" over a tree the detector cannot actually
read, which is indistinguishable from a clean tree. Every guard's detector
gets a known-bad self-test, and every guard module calls at least one of the
self-test helpers (see [Guard design rules](#guard-design-rules)).

### Write a guard with the helpers

A complete guard, with each helper doing the job it exists for. The rule here
is "no `datetime.utcnow()` in `src/`", because it returns a naive datetime;
substitute your own predicate and the rest of the shape holds.

```python
"""Guard: no naive `datetime.utcnow()` in src/."""

import ast

from tests.unit._architecture_helpers import (
    assert_detector_catches_ast_snippets,
    assert_violations_match_allowlist,
    iter_module_trees,
    repo_root,
    walk_with_enclosing_function,
)

# Pre-existing violations, keyed on (path, enclosing function). Never a line
# number: it moves when anything above it is edited, and the entry goes stale
# without the violation being fixed.
KNOWN_VIOLATIONS: set[tuple[str, str]] = set()


def _violations(tree: ast.Module):
    """Yield each `.utcnow()` call with the function that encloses it."""
    for node, enclosing in walk_with_enclosing_function(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "utcnow"
        ):
            yield node, enclosing


def _lineno_violations(tree: ast.Module) -> list[int]:
    """The same detector, as the line-number list the self-test expects."""
    return [node.lineno for node, _ in _violations(tree)]


def test_detector_catches_known_bad() -> None:
    """Prove the detector fires. Without this the scan below proves nothing."""
    assert_detector_catches_ast_snippets(
        _lineno_violations,
        snippets={
            "module level": "import datetime\ndatetime.datetime.utcnow()\n",
            "inside a function": (
                "import datetime\n"
                "def f():\n"
                "    return datetime.datetime.utcnow()\n"
            ),
        },
    )


def test_no_naive_utcnow() -> None:
    found = {
        (path, enclosing)
        for tree, path in iter_module_trees([repo_root() / "src"])
        for _, enclosing in _violations(tree)
    }
    assert_violations_match_allowlist(
        found,
        KNOWN_VIOLATIONS,
        fix_hint="Use datetime.now(UTC); utcnow() returns a naive datetime.",
    )
```

What each helper is doing, and what goes wrong without it:

- **`repo_root()`** anchors the scan. Do not write `Path(__file__).parents[2]`
  or a relative `Path("src")`. The hand-rolled spellings in this repository
  disagree with each other — 55 modules say `parents[2]` and 19 say
  `parents[1]` — so at least one family is anchored somewhere unintended, and
  a relative path resolves against whatever directory pytest was started
  from. A guard pointed at a directory that does not exist finds nothing and
  passes.
- **`iter_module_trees()`** yields `(tree, repo_relative_path)` for every
  `.py` file under the directories you give it, through a shared mtime-keyed
  cache, and raises on a file it cannot parse rather than skipping it. Skipping
  an unparseable file is how a guard silently stops covering it.
- **`walk_with_enclosing_function()`** gives you the enclosing function name
  alongside each node, which is what lets the allowlist key on
  `(path, function)` instead of a line number.
- **`assert_violations_match_allowlist()`** compares both directions: a new
  violation fails, and so does an allowlist entry whose violation is gone. The
  second direction is what stops the allowlist accumulating entries nobody can
  retire.
- **`assert_detector_catches_ast_snippets()`** runs the detector against
  known-bad input. This is the test that matters most, and the one most often
  omitted: a detector that has quietly stopped matching reports "no
  violations" over a tree it cannot read, which is indistinguishable from a
  clean tree. Include a snippet for each spelling the rule must catch — an
  attribute call, an aliased import, a call inside a nested function.

Further helpers cover cases the example does not: `parse_module()` when you
need a single file rather than a tree walk, `iter_call_expressions()` when the
rule is about calls to one named function, and `trailing_name()` when the rule
matches a name written bare or as an attribute: it returns `Foo` for `Foo` and
for `mod.Foo`, and `None` for any other expression. `format_failure()` renders
a failure with a summary, a fix hint, and a documentation link, for guards
that assert directly rather than through the allowlist comparison.

## Symbol subjects and shape subjects

A guard's subject is either a **symbol** — a function, class or constant that
exists in `src/` or the pinned SDK — or a **shape**: a code pattern with no name
to import, like "a bare `except` placed ahead of a specific one".

The rule:

> **If the subject is a symbol, BIND it — import or resolve it in the guard
> module, so a rename fails here. If the subject is a shape, prose is correct;
> there is nothing to import.**

The sorting question is not "does the constant hold an identifier?" It is:

> **If the subject were renamed, does this guard go SILENT or LOUD?**

Bind the silent ones. A string-matching guard whose subject is renamed keeps
passing over a codebase that no longer contains what it scans for — it reports
clean because it finds nothing, which is indistinguishable from finding nothing
wrong. That is the failure mode binding removes: an unresolvable import cannot
be green.

Two things are worth knowing before you write one:

- A **module-level** import buys a collection failure, but it aborts the whole
  unit run and masks every other result. For a heavy module, use
  `importlib.import_module` inside the test — a rename still reddens
  `make quality`, as a failure rather than a collection error.
- Prefer **containment over derivation**. Asserting the guard's vocabulary is a
  subset of production's catches production losing a member. Deriving the
  vocabulary FROM production makes the guard track whatever production says,
  which is the opposite of a guard.

This page does not list which guards are which kind. Such a list is prose about
symbols, which is exactly the artifact that goes stale without anything noticing
— the reason the rule above exists.

## Run the guards

```bash
# All guards (part of make quality)
make quality

# Just the architecture guards
uv run pytest tests/unit/test_architecture_*.py tests/unit/test_guards_*.py tests/unit/test_ast_grep_*.py tests/unit/test_*impl*.py -v

# Single guard
uv run pytest tests/unit/test_architecture_no_raw_select.py -v
```

## Relationship to other quality mechanisms

```
Types + lint (mypy, ruff TID251,   ← make the wrong thing unrepresentable,
complexity ratchet)                  or fail it at the import/signature level
    │
    ▼
Pre-commit hooks                   ← catch formatting, route conflicts, star imports
    │
    ▼
Structural guards                  ← catch architecture violations with allowlists (THIS FILE)
    │
    ▼
Unit tests (~2950)                 ← catch behavior bugs
    │
    ▼
Integration tests (PostgreSQL)     ← catch data layer bugs
    │
    ▼
E2E tests (Docker stack)           ← catch deployment/wiring bugs
```

Guards sit between pre-commit hooks (syntactic) and unit tests (behavioral).
They enforce structural properties that are invisible to both — and only
those. A property expressible at the top of this ladder belongs there, not
here.

**ast-grep scan rules** (`.ast-grep/rules/`) provide fast first-line defense at
commit time for simple BDD patterns (`ctx.get("env")`, `hasattr(env, ...)`,
error fabrication). Python AST guards manage the allowlists for existing
violations and handle complex cross-file analysis.

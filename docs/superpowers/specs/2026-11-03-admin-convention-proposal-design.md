# Admin panel convention and ASGI migration proposal: design

Date: 2026-11-03, revised 2026-11-04 (revision 2)
Status: revision 2, approved by the user on 2026-11-04 ("Approve rev 2").
Revision 1 (route layer on Flask) was approved on 2026-11-03 and superseded
the next day, when the user set the end state to "ASGI everywhere": the route
layer and the test seam moved to FastAPI and the migration became the
strangler pattern in § 5.12. The implementation plan is
`docs/superpowers/plans/2026-11-04-admin-convention-asgi-pilot.md`; code
starts on the user's explicit go after the plan is reviewed.
Measured at: `main` @ c3bf1321 (same commit the architecture report used);
re-checked at 1c202df2, `origin/main` after the 2026-11-03 sync (§ 9): no
count changed. The two-stack numbers in § 1 were measured on 2026-11-04 at
1c202df2.
Related: the admin-plane authorization RFC, GH [#2256](https://github.com/prebid/salesagent/issues/2256)
(touches the same code but decides a different question, see § 2.3); the
admin architecture report (Claude Doc, 13 sections) the counts below come
from; upstream PR [#1066](https://github.com/prebid/salesagent/pull/1066)
("FastAPI migration — unify MCP + A2A + Admin into single process",
2026-03-02), which built the host this migration runs on.

## 1. Intent

The admin panel (`src/admin/`, Flask, 31 blueprints, 227 routes) has no written
convention for where business logic goes, how a route reads the database,
validates input, answers, fails, or is tested. Every blueprint answers those
questions its own way, so a person or an AI agent adding a route copies the
nearest blueprint, and the copy carries that blueprint's habits. The measured
result at c3bf1321:

| What was counted | Count |
|---|---|
| Raw `get_db_session()` calls in `src/admin` (ratchet `.admin-raw-session-baseline`) | 186 |
| Raw `session.add()` in `src/admin` (same ratchet) | 39 |
| Admin rows in the raw-`select()` allowlist (GH [#1119](https://github.com/prebid/salesagent/issues/1119)) | 141 |
| JSON error envelope shapes in use (`{"error"}` / `{"success": false, "error"}` / `{"success": true}`) | 3 (242 / 85 / 35 sites) |
| Bare `except Exception` blocks in `src/admin` | 219 |
| Distinct input-validation styles (inline `request.form.get().strip()`, `validate_form_data`, `sanitize_*`, pydantic `ValidationError`, `AdCPValidationError`) | 5 |
| Routes that audit (`log_admin_action`) before they authorize (`require_tenant_access`) | 54 |
| Private `_auth_session` copies in test modules | 10 |
| Module-level `create_app()` calls in `tests/admin/` modules (one more under `tests/integration/`) | 14 |
| Near-identical blueprint pairs (`creative_agents.py` 296 lines / `signals_agents.py` 332 lines) | 1 pair, 5 routes each |

The user's statement of the problem: "AI generates often duplicates of code
because there is no standard for business logic and tests in the Admin
panel's code."

The second statement, 2026-11-04: "I'd like to have ASGI everywhere." The
admin is the one WSGI component left. Since PR #1066 the whole server is one
FastAPI process (`src/app.py:125`, run by uvicorn from `scripts/run_server.py`)
that serves MCP (FastMCP, Starlette), A2A (a2a-sdk, Starlette), the REST
transport (FastAPI routers) and the Flask admin, the last one bridged in
through `a2wsgi.WSGIMiddleware` and mounted at `/admin` and at the root
(`src/app.py:86-87, 593-594`). The cost of that bridge, measured at 1c202df2:

| What was counted | Count |
|---|---|
| Modules importing `flask` under `src/admin` (plus two adapters: `src/adapters/gam_reporting_api.py:16`, `google_ad_manager.py:25`) | 34 (+2) |
| Modules importing `fastapi` in the whole of `src/` | 4 |
| Flask route rules / blueprints / Jinja templates / `url_for` calls in templates | 229 / 31 / 59 / 138 |
| Flask calls in `src/admin`: `jsonify` / `flash` / `redirect` / `url_for` / `render_template` | 437 / 357 / 308 / 301 / 66 |
| Path models that must agree: FastAPI `root_path` (the mount), Flask `SCRIPT_NAME` (a2wsgi derives it from `root_path`; "they disagree SILENTLY", `src/core/signing/capture.py:333-334`) and the `X-Forwarded-Prefix` header nginx sends, which `CustomProxyFix` (`src/admin/app.py:52-99`) writes over `SCRIPT_NAME`; hence `script_name=` passed into every render | 3 |
| Mount-order code the bridge needs: `_install_admin_mounts()` (`src/app.py:61-87`, re-run at lifespan `:93`) and the `/a2a/` route carved out so the root mount does not swallow it (`:397-401`) | 2 sites |
| Session models (Flask signed cookie for the admin; bearer tokens at the boundary for the protocols) and test clients (Flask `test_client`, httpx `TestClient`) | 2 and 2 |
| Thread-pool hops per admin request (a2wsgi runs the sync WSGI app on a worker thread) | 1 |

The two problems share one fix order. A convention written for a framework
scheduled for removal teaches the team rules twice, so the convention's route
layer is written for FastAPI from the start, and the pilot is the first slice
of the migration. Everything below the route layer (forms, services,
repositories, refusals) is framework-free and is what makes each later slice
a rewrite of one thin layer.

This project produces a written convention, shown on one real blueprint pair
moved to FastAPI so the team can judge it on code rather than on slides, and
gets the team's approval before any of it is enforced.

## 2. Goals, non-goals, anti-goals

### 2.1 Goals

1. A proposal document the team can read in about 15 minutes, presented live
   first (from the user's own server or a GitHub gist) and then reviewed with
   line comments on a draft pull request.
2. One pilot: `creative_agents.py` and `signals_agents.py` moved to the
   convention as FastAPI routers at the same URLs, with their tests, as the
   worked example every rule points at, plus the ASGI admin foundation they
   need (§ 5.12), which every later migration reuses.
3. A migration path for the other 29 blueprints that does not require a big
   bang: the strangler pattern of § 5.12, one blueprint per pull request,
   both URL prefixes kept, Flask deleted in the final pull request. New code
   follows the convention, old code migrates on its scheduled turn, ratchets
   keep the counts falling.
4. Every rule in the proposal names the structural guard that will enforce it
   in Phase 2, so the team approves the enforcement together with the rule.
5. The end state, named so the team approves it as a destination: one ASGI
   process, one web framework, one session model, one test client, no
   `a2wsgi`, no `SCRIPT_NAME` plumbing.

### 2.2 Non-goals (this phase)

- Writing any guard, ast-grep rule, ruff ban, or ratchet. Phase 2, after the
  team's feedback.
- Adding the convention to `CLAUDE.md` or `.claude/rules/`. Phase 2.
- Migrating any blueprint other than the pilot pair. The remaining 29 (and
  the Flask blueprint in `src/adapters/gam_reporting_api.py`) are Phase 3,
  after the Phase 2 guards exist (the user's answer, 2026-11-04: guards are
  what make thirty mechanical migration pull requests reviewable).
- Migrating `auth` (login, Google OAuth, the callback binding from
  [#2296](https://github.com/prebid/salesagent/pull/2296)). It is the last
  blueprint to move; until then FastAPI routes read the login the Flask side
  wrote (§ 5.12.3).
- Changing the session cookie format. Flask's signed cookie stays the one
  format until the final pull request; the switch to Starlette's
  `SessionMiddleware` (one forced re-login) is that pull request's job.
- An async database layer. Repositories and Units of Work stay synchronous;
  FastAPI runs `def` endpoints on its thread pool, the same model a2wsgi
  gives the admin today. "ASGI everywhere" is one framework, not async I/O.
- A CSRF layer. None exists today: `templates/base.html:6` renders
  `csrf_token()` only `if csrf_token`, and nothing under `src/admin` defines
  it. Listed in the proposal as a finding, not fixed here.
- Merging the two pairs of templates (`creative_agent(s)*.html`,
  `signals_agent(s)*.html`) or editing any template. Templates are the front
  end; the problem statement is about business logic and tests, and the
  migration's whole point is that templates do not move.
- Changing any URL. Both prefixes (`/admin/tenant/...` and `/tenant/...`)
  stay; nginx serves the admin at `admin.<domain>/...` through the root mount
  (with `X-Forwarded-Prefix: /admin` on every request,
  `config/nginx/nginx-multi-tenant.conf:132,146`, so Flask links under
  `/admin` there too) and at `<tenant>.<domain>/admin/...` through the
  `/admin` mount (`:168-178`); the tenant host's root catch-all (`:199`)
  sends no prefix. § 5.12.4 keeps all three compositions linking exactly as
  today.
- A pull request to upstream `prebid/salesagent`. The pilot PR stays on the
  fork `v-n7k/salesagent` until the team approves.

### 2.3 Anti-goals (what would make this a failure even if it works)

- A convention that only fits the pilot pair. The rules must read naturally
  for a blueprint with no twin (most of them).
- A pilot that changes what the operator sees without saying so. Every
  behavior change is listed in the PR description (§ 6.4) and is itself a
  rule made visible, never a side effect.
- A big-bang rewrite, a deploy that needs downtime, or a step that logs every
  operator out before the final pull request.
- A migrated route reachable at a different path than today, or a Flask page
  whose link to a migrated page breaks (§ 5.12.4 covers both directions).
- A new Flask blueprint written after this proposal is approved. New admin
  routes are FastAPI routers from the day the pilot merges; the blueprint
  count only shrinks (§ 5.10).
- Deciding the authorization model. Who may call which route, roles,
  `users.role`, super-admin scope: that is GH #2256's RFC. This proposal fixes
  the ORDER of guard and audit (structurally, § 5.2.4) and ports the existing
  decision unchanged; nothing about who passes the guard.
- A rule the codebase's own core layer would contradict. Where the admin
  convention and `CLAUDE.md`'s critical patterns overlap (repositories,
  Unit of Work, DRY, no `model_dump` in business logic, serialization at the
  edges, no `context=` keyword outside the boundary), the admin convention is
  the same rule, not a parallel one.

## 3. Constraints

- Repository rules in `CLAUDE.md` apply in full: repository pattern inside a
  Unit of Work, `JSONType`, DRY as a correctness requirement, no `ToolError`,
  no raw egress, conventional commit prefixes (`docs`, `refactor`; `test` is
  not in the list), never push to `main`.
- The ast-grep rule `context-is-written-by-the-boundary-alone` bans a keyword
  argument named `context` in every file under `src/`. The render helper
  therefore takes `**values`, never `context=`; Starlette's
  `TemplateResponse(request, name, context=...)` spelling is not used.
- The duplication ratchet (`.duplication-baseline`, `src: 25`, `tests: 42`)
  and the admin raw-session ratchet (`186` / `39`) may only go down and the
  committed number must equal the measured one (each has an over-check and a
  slack-check). The pilot is expected to lower both; the builder lowers the
  baseline files the way each ratchet's own test prescribes.
- No local `make quality`, `tox` or full-suite `pytest` runs by the agent;
  file-scoped checks only (`uv run pytest <one file>`, one
  `scripts/run-test.sh --db` slice, `ruff format` on changed files). CI on
  the fork grades the branch (the user's standing rule). The plan therefore
  ends every implementation task with "push, read CI", never with a local run.
- Fork-only: the branch is pushed to `origin` (`git@github.com:v-n7k/salesagent.git`)
  and the draft PR targets the fork's `main`. Nothing goes to the `prebid`
  remote.
- The proposal document must render as a single Markdown file on GitHub, in a
  gist, and in any Markdown viewer with Mermaid support: diagrams are fenced
  ` ```mermaid ` blocks, no image files, no relative links to other repo files
  (full `https://github.com/v-n7k/salesagent/blob/<branch>/...` URLs so the
  gist copy still works).
- The user is not watching in real time; the plan runs without questions
  after approval.
- The current worktree (`salesagent-2256`) is on the #2256 branch. The pilot
  gets its own sibling worktree and branch off fresh `origin/main` (see § 4.2).
- Two existing tests change by design and are the only tests outside the
  pilot's own that do: `tests/unit/test_fastapi_app_regression.py::TestAdminCompatibilityMount`
  (asserts the `/admin` and `""` mounts hold a `WSGIMiddleware`; after the
  pilot they hold the admin sub-application, § 5.12.1; the path assertions
  stay) and the eight agent cases of
  `tests/integration/test_admin_ingest_url_policy.py` (re-pointed at the
  ASGI client, assertions verbatim, § 5.9.9). Every other test in the
  repository passes unchanged.

## 4. Deliverables

### 4.1 The proposal document

- Path: `docs/development/admin-convention-proposal.md` (my call: it sits with
  the other development docs; it is renamed to `admin-conventions.md` and
  linked from `docs/development/README.md` in Phase 2 when it stops being a
  proposal. Phase 1 adds no README row, so the docs-links hook sees one new
  file with absolute links only).
- One file, Markdown with Mermaid, about 1,800 to 2,300 words of text plus
  code blocks and diagrams. Readable in 15 minutes.
- Sections, in this order:
  1. **The problem, measured.** The two tables from § 1, two sentences of
     interpretation each, one Mermaid diagram showing the blueprint pair as
     two copies of the same five routes.
  2. **The convention in one picture.** A Mermaid diagram of the layers
     (router, form model, service, Unit of Work and repository, database)
     and the test seam next to it.
  3. **The rules.** One numbered subsection per rule in § 5, each with:
     the rule in one or two sentences; why (one measured fact); a before and
     after snippet taken from the pilot diff; the Phase 2 guard that will
     enforce it, named but not built.
  4. **The pilot.** What moved where (a file map before and after), the
     before and after measurements (§ 6.5), the list of deliberate behavior
     changes (§ 6.4), and a link to the draft PR.
  5. **Migration.** The strangler mechanism (§ 5.12) in one picture: main
     app, admin sub-application, routers, Flask as the sub-application's
     fallback; the order (§ 5.11); the final pull request; how the three
     ratchets hold the line (blueprint count, raw sessions, duplication).
  6. **Not in this proposal.** § 2.2 and § 2.3 in the team's words, plus the
     three findings the pilot leaves alone: the edit forms echo the stored
     credential into the password input (`templates/creative_agent_form.html:72`,
     `templates/signals_agent_form.html:95`); two adapters import the UI
     framework; no CSRF layer exists.
  7. **Questions for the team.** The decisions the team can still flip
     cheaply (§ 8), each with the proposal's default and why: migration
     order; who migrates (a person or an AI session with the convention as
     its brief); whether the root prefix survives the final pull request or
     only `/admin` does; when to switch the session format; async database
     (the proposal's answer: not part of this).
  8. **How to comment.** The draft PR link, and that line comments on the
     doc file and on the pilot code are both welcome.
- Diagrams (Mermaid, all of them): the layer diagram; a sequence diagram of
  one write request through the session middleware, the guard dependency,
  the audited endpoint, the form model, the service and the UoW; a "before"
  graph of the pair (two blueprints each owning its own copy of everything)
  next to an "after" graph (one router module over one service, one
  repository family, one test module); the strangler picture; a Gantt or
  timeline of the migration order; the test seam (test module, shared
  fixtures, factories, the httpx test client, the one patched external
  dial).

### 4.2 The pilot branch and draft PR

- Worktree: a sibling worktree named `salesagent-admin-convention`, next to
  the existing ticket worktrees (no absolute path here: the repo-invariants
  hook refuses a home-directory path in any tracked text file). Branch:
  `refactor/admin-convention-pilot`, created from freshly fetched
  `origin/main` (1c202df2 after the 2026-11-03 sync, or newer; § 9).
- Commits, in this order, each with a conventional prefix:
  1. `docs(admin): add the admin convention design spec and plan` (this file
     and the implementation plan).
  2. `refactor(admin): add the ASGI admin foundation` (the `src/admin/web/`
     package, the shared guard and audit cores extracted from the Flask
     helpers, the test helpers and fixtures, `tests/admin/test_web.py`).
  3. `refactor(admin): move the agent blueprints to FastAPI routers under the admin convention`
     (forms, service, repositories, `AgentUoW`, the router module, the test
     module, the deletions, the re-pointed tests, the lowered baselines; may
     be split if the diff reads better that way; the builder decides).
  4. `docs(admin): propose the admin convention and ASGI migration` (the
     proposal document, written last so its snippets and counts come from
     the real diff).
- Draft PR on `v-n7k/salesagent`, base `main`, title
  `refactor(admin): admin convention and ASGI migration proposal, with the agent pilot`.
  The description: a two-paragraph summary, the behavior-change list, the
  before/after table, and the reading order (doc first, then `web/`, then the
  pilot).
- CI on the fork must be green before the PR is handed to the team. If a
  guard the pilot did not touch fails, that is a blocker reported to the
  user, never a deselected test. Two things on the fork are not the pilot's
  to fix and are settled in § 9 before the first push: the creative-agent
  image four jobs pull from the fork's own registry, and the IPR Agreement
  check.

### 4.3 This design spec

Committed on the pilot branch as the first commit (§ 4.2), together with the
implementation plan. Whether it travels to upstream later is decided when an
upstream PR is opened; not now.

## 5. The convention (decided content of the proposal)

Each rule below is written as the proposal will state it. "Guard" names the
Phase 2 enforcement; none of it is built in this phase.

### 5.1 Layers and file layout

```
src/admin/routers/<domain>.py             routes only (FastAPI APIRouter): guard, audit, parse, call, answer  [new package]
src/admin/forms/<domain>.py               pydantic form models: the accepted input shape                      [new package]
src/admin/services/<domain>.py            business logic: plain functions, tenant_id first                     [existing package]
src/admin/web/                            the ASGI admin foundation (§ 5.12): app, session, templates,
                                          guards, audit, responses                                             [new package]
src/admin/errors.py                       AdminRefusal and its three subclasses                               [new module]
src/core/database/repositories/<domain>.py  data access (existing place, existing pattern)
src/core/database/repositories/uow.py     one <Domain>UoW row per domain (existing place)
tests/admin/test_<domain>.py              one test module per domain, shared fixtures only
src/admin/blueprints/<legacy>.py          Flask, until its migration PR; no file is ever added here
```

A router is a controller, exactly as an AdCP `_impl` is a controller in
`CLAUDE.md` § 5: it establishes the caller (the guard dependency does),
records the action (the audit decorator does), turns the request into a typed
input (the form model does), calls one service function, and turns the
result into a response. It holds no SQL, no session, no business decision.

My call: services are modules of plain functions, not classes. Two of the
three existing admin services (`DashboardService`, `MediaBuyReadinessService`)
are classes; the third, `business_activity_service.get_business_activities(tenant_id, limit=50)`,
already has the proposed shape, and the core's services (`sync_creatives`) are
functions too. A function that takes `tenant_id` first is what the core's
"service takes an already-resolved caller" rule looks like in the admin.
Existing classes are left alone until touched.

My call: form models get their own package `src/admin/forms/` rather than
living inside the service module, so "where does the input shape go" has one
answer that does not change when a service module grows.

My call: migrated routes live in a new package `src/admin/routers/`, not in
`src/admin/blueprints/`. Two directories make the migration's progress a
number (`ls src/admin/blueprints | wc -l`, 31 today, 29 after the pilot, 0 at
the end) and give the Phase 2 ratchet something to count.

### 5.2 Router (controller) rules

1. A route function body does one of two things with the request: renders a
   template from values a service or repository returned, or parses the
   request into a form model and passes that to one service call.
2. No `get_db_session()`, no `select()`, no ORM model import, no
   `session.add()` in a router module. Guard: ruff TID251 bans on
   `src.core.database.database_session.get_db_session`, `sqlalchemy.select`
   and `src.core.database.models` for `src/admin/routers/**`, the same shape
   as `ruff-boundary.toml`. The package is new, so the baseline is zero and
   the guard needs no allowlist. The admin raw-session ratchet
   (`.admin-raw-session-baseline`) keeps counting the Flask side down.
3. Rendering happens while the Unit of Work is open when the template reads
   ORM rows. Decided: a GET route that only reads and renders opens the
   domain's UoW itself, reads through its repositories, and renders inside
   the block through `render(request, template_name, **values)` from
   `src/admin/web/templates.py` (§ 5.12.5; the response body is produced on
   the call, so the rows are still attached). The tenant row every admin
   template needs (`base.html` reads `tenant.name` and `tenant.favicon_url`)
   comes from the same UoW through `uow.tenant_config.get_tenant()`, so every
   `<Domain>UoW` that serves a page carries `tenant_config`. A row that is
   not there is a refusal the route maps on the spot
   (`return refuse_form(request, AdminNotFound("..."), list_url)`); that is
   mapping, not a decision. Anything that writes, dials, or decides goes
   through a service function.
4. The guard is a dependency on the route decorator,
   `dependencies=[Depends(require_tenant_access(api_mode=...))]`; the audit
   is a decorator on the function, `@audited("<operation>")`. FastAPI resolves
   dependencies before the endpoint body runs, so "guard before audit" is
   structural: an unauthenticated request never reaches the audited body and
   never writes an audit row. Every route that accepts a method other than
   GET carries `@audited` (my call: a delete is the write most worth an audit
   row, and today neither delete route in the pair has one). Guard: an AST
   test over every route in `src/admin/routers/**` that fails when a non-GET
   route has no `audited` decorator or no `require_tenant_access` dependency;
   baseline zero.
5. Endpoints are `def`, never `async def`. Services and repositories are
   synchronous, FastAPI runs a `def` endpoint on its thread pool, and an
   `async def` endpoint that calls synchronous database code blocks the event
   loop for every other request in the process. Guard: an AST test that fails
   on `async def` under `src/admin/routers/**`; baseline zero. The rule is
   lifted only by a separate decision to move the data layer to async, which
   this proposal does not propose.
6. Route names keep today's `blueprint.endpoint` strings
   (`name="creative_agents.list_creative_agents"` on the route decorator),
   paths keep today's rules (`/tenant/{tenant_id}/creative-agents/...`), and
   templates keep calling `url_for('creative_agents.list_creative_agents', ...)`.
   This is what lets a template stay untouched across the migration.
7. Internal links: `url_for()` in templates through the compat global
   (§ 5.12.4); in Python, the same helper from `src/admin/web/templates.py`;
   `scriptRoot` in JavaScript (`CLAUDE.md` § 6, unchanged). A redirect's
   `Location` is always a `url_for` result, never a path written by hand or
   read off the request, because only `url_for` carries the request's prefix
   (§ 5.12.4).
8. No keyword argument named `context` anywhere (the ast-grep rule in § 3);
   the render helper takes `**values`.

### 5.3 Service rules

1. `def <verb>_<noun>(tenant_id: str, ...) -> <typed result>`. The first
   parameter is the tenant the guard already resolved. A service never reads
   a request, a session, or a response object; it imports nothing from
   `flask`, `fastapi` or `starlette`. Guard: TID251 ban on those three for
   `src/admin/services/**` and `src/admin/forms/**`.
2. A service opens exactly one Unit of Work per operation and reaches data
   only through the repositories on it.
3. An expected refusal is raised as an `AdminRefusal` subclass (§ 5.7); an
   unexpected failure is not caught.
4. One service function per operation; two routers that need the same
   operation call the same function with a parameter (the pilot's two agent
   kinds), never a second copy. This is `CLAUDE.md`'s DRY rule, restated.

### 5.4 Data access rules

1. Every read and write goes through a repository class in
   `src/core/database/repositories/`, reached from a `<Domain>UoW` declared
   in `uow.py` with the `_REPOSITORIES` map. `uow.session` is deprecated and
   is not used.
2. A repository that lacks a method gets the method; a caller never reaches
   past it. The pilot adds `list_all`, `get`, `add`, `delete` to the two
   agent repositories.
3. Tenant scoping is the repository's job (every method filters on the
   `tenant_id` the repository was constructed with), never the caller's.

### 5.5 Input validation: one way

1. Every write route has a pydantic form model in `src/admin/forms/<domain>.py`
   and builds it with one call from the submitted form (`request.form()` on
   FastAPI, awaited once by the helper that reads it; the model itself sees a
   plain mapping). Field types, defaults (`priority = 10`, `timeout = 30`),
   required-ness and checkbox-to-bool coercion live on the model, once.
   A form model declares exactly the fields its template submits, and a
   service writes exactly the form's declared fields, so a column the form
   does not carry is never reset to a default by an edit (the creative
   form has no `auth_header` or `timeout` input today, and a creative edit
   must keep leaving those columns alone).
2. A failed validation is a refusal: the router turns the
   `pydantic.ValidationError` into `AdminInvalidInput` through one helper and
   answers the way § 5.6 says. The operator sees today's sentences: each
   field carries `Field(title="Agent URL")`, a `missing` error renders as
   `"<title> is required"` (which is the wording the pair flashes today,
   "Agent URL is required", "Agent name is required"), and any other error
   as `"<title>: <pydantic message>"`. Never a traceback. Validation runs
   before the egress check, so a blank URL says "is required" on both kinds
   (today the creative add route runs the egress check first and flashes
   the egress sentence for a blank URL; § 6.4 lists the change).
3. The URL ingest check (`src/admin/utils/url_policy.py`) stays where it is
   and is called by the service, not the route, because the service is what
   stores the URL. Its two Flask-shaped helpers
   (`redirect_if_url_blocked`, `json_error_if_url_blocked`) get a third,
   framework-free sibling that raises `AdminInvalidInput`; the two existing
   ones are left for their current callers and go when their last Flask
   caller migrates. Guard (Phase 2): none new; the existing egress rules
   cover it.
4. The existing `src/admin/form_validation.py` (`validate_form_data`,
   `sanitize_*`) is the rejected alternative: it checks presence, not type
   or shape, and is one of the five styles. It is not removed in this phase.

My call: pydantic form models are new to the admin (no blueprint has one
today; `settings.py:669` has a one-off `BaseModel` for an LLM reply). The
reason to choose them anyway: the whole core validates at its boundary into a
pydantic DTO, the dependency is installed, FastAPI is built on it, and a typed
model is the only one of the five styles that answers "what does this route
accept" by reading one class.

### 5.6 Responses: one JSON envelope, one HTML path

1. JSON success: `json_ok(**fields)` returns `{"success": true, ...fields}`
   with HTTP 200. JSON failure: `json_error(message, status)` returns
   `{"success": false, "error": message}` with the given 4xx or 5xx. Both
   live in `src/admin/web/responses.py` and return Starlette
   `JSONResponse` objects. Guard: TID251 ban on `fastapi.responses` and
   `starlette.responses` for `src/admin/routers/**` (a router returns what
   `responses.py` and `templates.py` hand it); baseline zero.
2. Why this envelope and not the smaller `{"error"}`: the templates'
   JavaScript already reads `data.success` on success and `data.error` on
   failure (`creative_agents.html:197-200`, `signals_agents.html:179-182`).
   The chosen envelope is a superset of all three shapes in use, so no
   existing reader breaks while every writer converges. Operation-specific
   keys a template contracts on (`format_count`, `sample_formats`,
   `signal_count`) stay as fields next to `success`.
3. HTML path: a write route that succeeds flashes one `success` message and
   redirects to the list or detail page; a refusal flashes one `error`
   message and redirects back to the form (the request's own URL or the edit
   URL). A GET renders. No route returns a rendered template after a POST.
   Redirects carry status 302, as Flask's do today (Starlette's
   `RedirectResponse` defaults to 307, which would replay the POST; the helper
   sets 302 explicitly).

### 5.7 Errors: refusals and failures

1. `src/admin/errors.py` declares `AdminRefusal(Exception)` with
   `message: str` and `status: int`, and three subclasses:
   `AdminNotFound` (404), `AdminInvalidInput` (400), `AdminConflict` (409).
   The message is operator-facing text and is written at the raise site;
   this is the one place in the repo where authored error text is right,
   for the reason `accounts.py:105-109` already gives (an operator surface,
   not the buyer wire). The core's `AdCPSalesAgentError` family is for the
   buyer wire and is not raised by admin services.
2. A router catches `AdminRefusal` and nothing else:
   `except AdminRefusal as exc: return refuse_form(request, exc, back_to)`
   on an HTML route (flash `exc.message` as `error`, mark the audit as failed
   on `request.state` so the audit row says failed, redirect), or
   `return refuse_json(request, exc)` on a JSON route (`json_error`). Both
   helpers live in `src/admin/web/responses.py`.
3. `except Exception` is banned in routers and services. An unexpected
   failure propagates; the audit decorator records it (it re-raises) and
   Starlette's `ServerErrorMiddleware` answers a plain 500 with no exception
   text. Guard: ruff `BLE001` enabled for `src/admin/**` with today's 219
   sites in a per-file ignore list that only shrinks.
4. Phase 2, not the pilot: an exception handler on the admin
   sub-application that answers `json_error("Internal error", 500)` when the
   request is a JSON route and a generic page otherwise, so a JavaScript
   caller never parses an HTML error page. The pilot does not add it because
   it changes every migrated route's 500 at once; it is listed in the
   proposal as the first Phase 2 change.

### 5.8 Guard and audit

1. `src/admin/web/guards.py` declares `require_tenant_access(api_mode=False)`,
   which returns a FastAPI dependency `(request: Request, tenant_id: str)`.
   It decides nothing itself: the decision is the Flask decorator's, extracted
   into one framework-free function in `src/admin/utils/helpers.py`,
   `tenant_access_decision(session_data, tenant_id)`, which both the Flask
   `require_tenant_access` and the dependency call. The function keeps the
   existing order: the setup-mode session check (`_setup_session_reaches`,
   which now takes the session mapping instead of reading Flask's global),
   then "no user in session" (login required), then `is_super_admin(email)`
   (its Flask-session cache is a Flask-context optimisation that simply does
   not apply on the ASGI side; the environment and database checks run),
   then the user's tenant membership (access denied), read through
   `UserRepository.is_active_member(email)` on a new `TenantAccessUoW`
   (`src/core/database/repositories/user.py`; the predicate is the
   decorator's own `select(User).filter_by(email=email.lower(), tenant_id=tenant_id, is_active=True)`,
   `helpers.py:376`, moved into the repository unchanged, because the
   raw-select allowlist is keyed by file and innermost function and may not
   grow, so the same select inside a new function would be a new violation;
   this way the allowlist's `decorated_function` row for `helpers.py` goes
   away instead). The outcome is one of allow (the dependency stores the
   user on `request.state.user`), login required, or denied. The Flask
   decorator keeps its own `try` around the call (`helpers.py:386-394`: an
   unexpected failure logs and answers 500); on the ASGI side an unexpected
   failure propagates (§ 5.7.3).
2. Login required and denied are raised as two exceptions the admin
   sub-application handles (§ 5.12.1): login required answers
   `{"error": "Authentication required"}` 401 when `api_mode` and otherwise a
   302 to `auth.tenant_login` for the tenant, built by `url_for` so it carries
   the request's prefix (§ 5.12.4), with `next=` the request URL, exactly as
   the Flask decorator does (`helpers.py:359-363`); denied answers `{"error": "Access denied"}` 403
   when `api_mode` and a plain 403 otherwise. A third handler maps FastAPI's
   `RequestValidationError` to a plain 404: the only input FastAPI itself
   validates on a migrated route is a path parameter (form bodies go through
   the form helper, § 5.5), and Flask's `<int:agent_id>` converter answers a
   non-integer id with 404 today, where FastAPI alone would answer 422 JSON.
   `api_mode=True` on every JSON route is required so an unauthenticated JSON
   caller gets 401 JSON, not a 302 to the login page. The pair's four JSON routes (delete and test
   connection, both kinds) use the default `api_mode=False` today; the pilot
   switches them (§ 6.4).
3. `src/admin/web/audit.py` declares `audited(operation_name)`, a decorator
   with the same contract as `log_admin_action` (`audit_decorator.py:176`):
   same operation names, same `audit_logger.log_operation(...)` call, same
   fields (principal from the session's `user`, `tenant_id` from the path,
   success or failure, the handled refusal's message). The record composition
   is extracted from `log_admin_action` into one framework-free core in
   `audit_decorator.py` that both decorators call; the FastAPI decorator
   carries no second copy. The handled-failure marker lives on
   `request.state` on the ASGI side (`g` on the Flask side), set by
   `refuse_form` / `refuse_json`. The decorator preserves the endpoint's
   signature (`functools.wraps`; FastAPI reads the wrapped signature for
   dependency injection), so a decorated endpoint declares its parameters
   exactly as an undecorated one.

### 5.9 Tests

1. One module per domain: `tests/admin/test_<domain>.py`, marked
   `pytestmark = [pytest.mark.admin, pytest.mark.requires_db]`.
2. The app and client come from fixtures in `tests/admin/conftest.py`:
   `asgi_admin_app` (the admin sub-application built by
   `build_admin_app(admin_test_app())`, § 5.12.1, with the Flask app from
   `tests/helpers/admin_session.py` as its fallback) and `asgi_admin_client`
   (`fastapi.testclient.TestClient` over it, `raise_server_exceptions=False`
   so a 500 is observed as a 500). The Flask `admin_client` stays for the
   modules that still test Flask blueprints and goes with the last of them.
   No module-level `create_app()`. Guard: an AST test that fails on a
   module-level `create_app(` call under `tests/admin/` with today's 14
   modules allowlisted, shrinking.
3. Authentication is one payload, two carriers: `_session_payload(tenant_id)`
   in `tests/helpers/admin_session.py` is "the session an authenticated super
   admin carries. ONE definition" (its own docstring); `admin_auth_session`
   writes it into the Flask client's session as today, and the new
   `admin_auth_cookie(flask_app, tenant_id) -> str` signs the same payload
   with the Flask app's own serializer for the ASGI client. No private
   `_auth_session`. Guard: an AST test that fails on any `def _auth_session`
   under `tests/`, allowlisting today's 10 and shrinking.
4. Data comes from `factory_session` and the factories in
   `tests/factories/`; no `session.add()`, no `get_db_session()` in a test
   body (`CLAUDE.md` § 8, unchanged). Read-backs after a write go through the
   domain's repository on its UoW, the production read path. The audit row
   is the one named exception: `AuditLogRepository` sits on no production
   UoW and putting it on one for a test is dead weight (`uow.py:452-454`
   says so of an unused repository), so a test constructs
   `AuditLogRepository` on `factory_session` after
   `factory_session.rollback()` (the logger commits in its own session,
   `src/core/audit_logger.py:249-263`).
5. Assertions: HTTP status, redirect `Location`, the exact JSON body for a
   JSON route, the flashed message for an HTML write, and the row's state
   through the repository. On the ASGI client the flash is read from the
   session cookie the redirect set, through
   `session_cookie_payload(flask_app, response)` in
   `tests/helpers/admin_session.py` (decodes with the same serializer);
   that is the ASGI twin of `operator_answer` (`tests/helpers/race_window.py:42`)
   and of the ingest helper's `flashes()` (`_egress_ingest_helpers.py:23`),
   which both pop Flask's `session_transaction()`. A test that only checks
   `status_code == 200` on a write route is not finished.
6. Mocks: only an external dial (`probe_agent`) is patched, at the class
   attribute the route reaches it through, with `AsyncMock` returning a real
   `ProbeResult`. The file stays under the 10-mock ceiling.
7. The admin BDD pattern (`docs/development/admin-bdd-pattern.md`,
   `T-ADMIN-*` features on `admin_integration` and `e2e_admin`) is the second
   layer and is unchanged: it grades operator-visible flows across both
   transports; the module above grades one router's routes in process. The
   proposal says which layer a new test belongs in: a flow an operator would
   describe (create, then see it listed, then test it) is a BDD scenario; a
   route's contract (status, envelope, refusal, audit) is a module test. The
   pilot adds no BDD feature (my call: the pair has no feature today, and no
   BDD scenario drives the agent routes, so none breaks).
8. `tests/admin/test_agent_probe_routes.py` (8 tests) is folded into the
   new module and deleted; its eight assertions survive as parametrised
   cases, so coverage does not drop while the private `_auth_session` count
   goes from 10 to 9 and the module-level `create_app()` count from 14 to 13.
9. Tests follow their routes. `tests/integration/test_admin_ingest_url_policy.py`
   drives the pair's routes through `authenticated_admin_client` (the Flask
   app) in eight cases (lines 161, 182, 201, 227, 253, 818, 830, 843): the
   add and edit forms and the test-connection route, pinning exactly one
   `error` flash with the egress sentence on a refused URL, nothing stored, a
   refused edit leaving the stored URL alone, a refused stored URL not dialed,
   and the refusal reason reaching the log. After the pilot the Flask app has
   no agent routes, so those eight cases take a new
   `authenticated_asgi_admin_client` fixture (`tests/integration/conftest.py`,
   built the same way as § 5.9.2 over `test_admin_app`) and read flashes
   through the cookie helper; every assertion stays verbatim; the file's
   other cases are untouched. The same rule applies to every later migration
   PR: the tests that drive a blueprint move with it, assertions unchanged.
10. `tests/unit/test_fastapi_app_regression.py::TestAdminCompatibilityMount`
    checks the two compatibility mounts by the class name `WSGIMiddleware`
    (`:238-272`). After the pilot the mounts hold the admin sub-application;
    the test's type check changes to that, and its path assertions (`/admin`
    and `""` present; `/tenant`, `/auth`, `/login`, `/logout`, `/signup`,
    `/test` absent; the root login path reachable) stay.
11. The foundation has its own module, `tests/admin/test_web.py` (§ 6.3).

An existing Flask-side helper the pilot keeps and reuses: `admin_test_app()`
in `tests/helpers/admin_session.py`, "the one composition every admin harness
uses". The pilot does not touch `tests/admin/conftest.py:admin_client` or
`tests/integration/conftest.py:646` (`test_admin_app`); the proposal lists the
Flask compositions as a Phase 3 deletion, not a merge.

### 5.10 Phase 2 guards (proposed in the document, not built)

Listed here so the proposal can name each one next to its rule:

| Rule | Guard | Mechanism | Baseline today |
|---|---|---|---|
| No raw DB access in routers (§ 5.2.2) | `ruff-admin.toml` TID251 for `src/admin/routers/**` | ruff | 0 (new package); 186 / 39 (Flask ratchet), 141 (allowlist) keep falling with the migration |
| Guard dependency and `audited` on every non-GET route (§ 5.2.4) | `test_architecture_admin_routers.py` | AST | 0 |
| Sync endpoints only (§ 5.2.5) | same test | AST | 0 |
| No framework in services or forms (§ 5.3.1) | `ruff-admin.toml` TID251 on `flask`, `fastapi`, `starlette` | ruff | 0 (new packages) |
| One JSON envelope (§ 5.6.1) | `ruff-admin.toml` TID251 on `fastapi.responses` / `starlette.responses` outside `src/admin/web/` | ruff | 0 in routers; 362 Flask `jsonify` sites fall with the migration |
| No blind except (§ 5.7.3) | ruff `BLE001` for `src/admin/**` | ruff, per-file ignores | 219 |
| No new Flask blueprint; the count only shrinks (§ 2.3) | `test_architecture_admin_migration_ratchet.py` over `src/admin/blueprints/*.py` and `Blueprint(` constructions (`src/admin/**`, `src/adapters/**`) | count ratchet (`tests/utils/ratchet_counters.py` pattern) | 31 files / 32 constructions; 29 / 30 after the pilot |
| No module-level app in tests (§ 5.9.2) | `test_architecture_admin_tests_use_fixtures.py` | AST | 14 |
| No private auth helper in tests (§ 5.9.3) | same test | AST | 10 |
| Route-conflict hook sees the sub-application's routes (§ 5.12.1) | `.pre-commit-hooks/check_route_conflicts.py` extended | hook | n/a |
| Decorator order documented in the audit decorator's own docstring | already true (`audit_decorator.py:5-10`) | n/a | n/a |

Each guard follows `docs/development/structural-guards.md`: allowlists only
shrink, every allowlisted site carries `# FIXME(#<gh-issue>)`, and a
stale-entry test removes fixed entries. Phase 2 opens one GitHub issue per
guard for those FIXME references.

### 5.11 Migration order (Phase 3)

One blueprint per pull request, each PR carrying the router, its forms and
service, its tests (moved, assertions unchanged), the deletion of the Flask
module and of its `register_blueprint` line, and no template change. Order,
smallest and most self-contained first, measured by routes and raw sessions
at c3bf1321:

1. `signing_keys` (3 routes, already on `SigningKeyUoW`), `schemas` (6
   routes, no DB), `accounts` (5 routes, already on `AccountUoW`): these
   need only the envelope and form-model rules, so they are the cheap
   second wave that proves the convention fits a blueprint with no twin.
2. `workflows` (4 routes, 5 raw sessions), `policy` (4, 4), `adapters`
   (7, 4), `public` (5, 4).
3. `users` (8, 7), then the large ones (`settings`, `products`,
   `principals`, `creatives`, `gam_*` together with the Flask blueprint in
   `src/adapters/gam_reporting_api.py`, which moves under
   `src/admin/routers/` and ends the adapter's dependency on the UI
   framework) one route group at a time; `activity_stream` (server-sent
   events, native in ASGI as a `StreamingResponse`) with its group.
4. `auth` last: Authlib's `flask_client` integration becomes
   `starlette_client`, the OAuth callback keeps the session binding from
   #2296, and the login page moves.
5. The final pull request: Flask's cookie serializer is replaced by
   Starlette's `SessionMiddleware` (every operator logs in once more), the
   Flask fallback mount, `_install_admin_mounts()`, `a2wsgi`, `flask`,
   `flask-caching` (9 call sites, replaced or dropped as each group
   migrates), `waitress` and `src/admin/server.py` are deleted, `/static` is
   served by `StaticFiles`, and the templates' Jinja environment is built
   standalone with the same loader and the two custom filters
   (`from_json`, `markdown`, `app.py:163-164`). The three WSGI proxy
   middlewares go with Flask: `CustomProxyFix`'s prefix job is already the
   resolver of § 5.12.4, its redirect rewrite is unnecessary once every
   `Location` is a `url_for` result, and `WerkzeugProxyFix` /
   `FlyHeadersMiddleware` (`X-Forwarded-For` / `-Proto`, applied at
   `app.py:196-203`) become uvicorn's `--proxy-headers` /
   `--forwarded-allow-ips` plus one small ASGI middleware for the Fly header
   copy if Fly is still a target. nginx is unchanged throughout.

As the migrated set grows, the render helper (§ 5.12.5) gains the request,
`g` and `config` objects the remaining templates read (35, 24 and 19 files
today; none of the pilot's five), each added when the first migrated template
needs it.

The rule in the meantime: a new route is a router; an existing route is
migrated in its scheduled PR or when a change touches its blueprint; a
blueprint is never migrated "while we are here" inside an unrelated fix. The
ratchets make the direction one-way without forcing a date.

### 5.12 The admin sub-application (the ASGI foundation)

This is what the pilot builds once and every later migration reuses. It
lives in `src/admin/web/`.

#### 5.12.1 One sub-application, Flask as its fallback

`build_admin_app(flask_app: Flask) -> FastAPI` (`src/admin/web/app.py`)
returns a FastAPI sub-application (`openapi_url=None`, `docs_url=None`) that:

1. carries the session middleware (§ 5.12.3);
2. includes every admin router (the pilot's two) at their own paths;
3. registers the three exception handlers of § 5.8.2;
4. mounts the Flask app, wrapped in `a2wsgi.WSGIMiddleware`, at `""` as its
   LAST route, so any path no router claims falls through to Flask exactly
   as today;
5. installs the Flask-side `url_build_error_handlers` fallback (§ 5.12.4)
   on the Flask app it was given.

`src/app.py` builds it once from `flask_admin_app` and `_install_admin_mounts()`
mounts it at `/admin` and at `""`, in the same two places and the same last
position the bare `WSGIMiddleware` holds today (`src/app.py:86-87`); the
helper's "remove the prior compatibility mounts" check recognises the
sub-application instead of `WSGIMiddleware`. The `/a2a/` carve-out
(`src/app.py:397`) and the `AuthChallengeResponder` middleware
(`src/core/auth_middleware.py:184`, which upgrades to 401 only a body
carrying an AdCP error code, so an admin 401 passes through it untouched,
exactly as the Flask admin's does today) are unchanged.

Why a sub-application and not routers included on the main app with two
prefixes: a mount sets `scope["root_path"]`, which is what a2wsgi hands Flask
as `SCRIPT_NAME` and strips from `PATH_INFO` (`a2wsgi/wsgi.py:94-97`). So
under `/admin` the Flask side and the routers see the same prefix and the
same relative path from one mechanism, and route names stay unique. The
prefix a page links under is then resolved once, by § 5.12.4, the same way
Flask resolves it today. When Flask is gone, step 4 is removed and nothing
else changes.

#### 5.12.2 The test composition

`tests/admin/conftest.py` builds the same thing over the test Flask app:
`build_admin_app(admin_test_app())`, served by `TestClient`. Paths are
unprefixed (the root-mount case, which is also what the Flask test client
sees). One foundation test mounts the sub-application at `/admin` and `""`
inside a bare `FastAPI()` and asserts the three production compositions of
§ 5.12.4: the `/admin` mount, the root mount with no header, and the root
mount with `X-Forwarded-Prefix: /admin` (the admin host) each serve the list
page, and the links and the redirect `Location` each composition produces
carry that composition's prefix.

#### 5.12.3 One session, two readers

`src/admin/web/session.py` holds `AdminSessionMiddleware`. On the way in it
decodes the Flask session cookie with the Flask app's own serializer
(`flask_app.session_interface.get_signing_serializer(flask_app)`, the
`itsdangerous` serializer Flask signs with, keyed by
`settings.runtime.flask_secret_key`, `src/admin/app.py:119`) into a mutable
mapping on `request.state.session` (an unreadable or missing cookie is an
empty mapping, as in Flask); on the way out, if the mapping was modified, it
writes the cookie back with the attributes the Flask app's config declares
(`SESSION_COOKIE_NAME`, `_PATH`, `_DOMAIN`, `_SECURE`, `_HTTPONLY`,
`_SAMESITE`, `app.py:124-139`). `flash(request, message, category)` and
`get_flashed_messages(request, with_categories)` read and write the same
`_flashes` list of `(category, message)` pairs Flask uses, so a flash set by
a router shows on a Flask page and the other way round. Until the final PR
there is one cookie, one format, one secret, and a login written by the
Flask `auth` blueprint is read by every router.

#### 5.12.4 One prefix, links in both directions

The prefix a page links under is not only the mount. nginx sends
`X-Forwarded-Prefix: /admin` on the admin host for root paths and on the
tenant host for `/admin/` paths, and `CustomProxyFix` (`src/admin/app.py:52-99`)
writes `X-Script-Name`, else `X-Forwarded-Prefix`, over the `SCRIPT_NAME`
a2wsgi derived from the mount, strips it from `PATH_INFO`, and prepends it to
a relative `Location` on every 30x. Flask's `url_for`, `request.script_root`
and the `script_name` the pair passes into every render all read that
`SCRIPT_NAME`. So a migrated page must resolve the prefix the same way, or
on the admin host it would link `/tenant/...` where the Flask page next to
it links `/admin/tenant/...`.

`admin_prefix(request) -> str` in `src/admin/web/templates.py` is that one
resolution: `X-Script-Name`, else `X-Forwarded-Prefix`, else
`request.scope["root_path"]`, the same precedence as `CustomProxyFix`,
honoured only when the value is a plain path (starts with one `/`, no
scheme, the shape nginx sends; `CustomProxyFix` honours any value). No path
is stripped on the ASGI side: a `/admin/...` request always reaches the
`/admin` mount before the root one. Everything on the ASGI side that builds
a path calls it: the template's `script_name`, `url_for`, the guard's login
redirect, every redirect helper. Starlette's own `request.url_for` is not
used, because it knows only `root_path`.

`url_for(endpoint, **values)` resolves a name first against the
sub-application's router (`router.url_path_for`, prefixed with
`admin_prefix`) and then, on no match, against the Flask app's `url_map`
bound to the same prefix (`flask_app.url_map.bind(host, script_name=admin_prefix(request)).build(endpoint, values)`),
which also covers `static`. So a migrated page's `base.html` links to
`auth.logout` or `core.index` keep working while those are Flask routes.
The other direction: Flask's `url_for` raises `BuildError` for an endpoint
that moved; the handler `build_admin_app` installs on
`flask_app.url_build_error_handlers` resolves the name against the
sub-application's router under `request.script_root` and returns the path.
Four pages link to the pilot's endpoints today; none changes. A redirect's
`Location` on the ASGI side is always a `url_for` result (§ 5.2.7), so
`CustomProxyFix`'s rewrite has nothing to do there and is not reproduced.

#### 5.12.5 Templates without a second engine

`render(request, template_name, **values) -> HTMLResponse` renders through
the Flask app's existing Jinja environment (`flask_app.jinja_env`, same
loader, same two custom filters, same `templates/` folder) and supplies
explicitly what Flask's context processors and globals would have supplied:
`url_for` (§ 5.12.4), `get_flashed_messages`, `session` (the mapping of
§ 5.12.3), `script_name` (`admin_prefix(request)`, § 5.12.4), `support_email`
(`get_support_email()`, what `inject_context` injects, `app.py:253-268`), and
whatever the route passes (`tenant`, `tenant_id`, `tenant_name`, the page's
own values). Flask's `request`, `g` and `config` are not supplied: none of
the pilot's five templates reads them (`base.html` and the four agent
templates read `session.role`, `session.username`, `session.email`,
`session.authenticated`, `script_name`, `tenant`, `get_flashed_messages`, and
`csrf_token` behind an `if`). § 5.11 says when they are added. The
environment is Flask's until the final PR builds it standalone; no template
changes at either step.

#### 5.12.6 Guards, audit, responses

§ 5.8 (`guards.py`, `audit.py`) and § 5.6 / § 5.7 (`responses.py`). The
decision and the record composition are shared with the Flask side through
the two extracted cores; the ASGI modules hold only the FastAPI-shaped
wrappers.

## 6. The pilot (decided)

### 6.1 Why this pair

`creative_agents.py` and `signals_agents.py` are the same five routes
(list, add, edit, delete, test connection) written twice: 296 and 332 lines,
7 `get_db_session()` each, 9 raw `select()` each, 15 `flash` each, 5
`except` each, one `session.add` each, and one shared test module
(`test_agent_probe_routes.py`) that already parametrises over the two kinds
by hand. The pair is the problem statement in one diff, and it is small
enough that the whole before and after fits in a review. No BDD scenario and
no other test module drives these routes, so the move is contained (§ 5.9.9
names the one integration file that does).

### 6.2 Target shape

Both kinds of agent are "a remote agent registration for a tenant": a row
(`CreativeAgent`, `SignalsAgent` in `models.py:1887-1960`) with a URL, a
name, an enabled flag, auth fields and a timeout; `CreativeAgent` adds
`priority`, `SignalsAgent` adds `forward_promoted_offering`. Each kind has a
registry with `probe_agent(row) -> ProbeResult`
(`creative_agent_registry.py:508`, `signals_agent_registry.py:294`), and
both probes catch the dial's failures themselves and return a failed
`ProbeResult`. `config_for(db_agent)` and the route's `asyncio.run(...)` sit
outside that `try` (`creative_agent_registry.py:530-534`,
`signals_agent_registry.py:317-321`), so a failure there is an unexpected
failure under § 5.7.3: today it becomes `{"error": "Connection failed: <str(e)>"}`
with 500, after the pilot it is a plain 500 (§ 6.4).

Files after the pilot:

| File | Content |
|---|---|
| `src/admin/web/__init__.py`, `app.py`, `session.py`, `templates.py`, `guards.py`, `audit.py`, `responses.py` | § 5.12 and § 5.6–5.8. Used by the pilot's routers only in this phase. |
| `src/admin/utils/helpers.py`, `src/admin/utils/audit_decorator.py` | The two extracted cores (`tenant_access_decision`, the audit record core); the Flask decorators call them and behave as before. `_setup_session_reaches` takes the session mapping. The decorator's `select(User)` moves to `UserRepository`, so the raw-select allowlist loses its `helpers.py` / `decorated_function` row (the stale-entry test says when). |
| `src/admin/errors.py` | § 5.7. |
| `src/core/database/repositories/agent.py` | `CreativeAgentRepository` and `SignalsAgentRepository` gain `list_all()`, `get(agent_id)`, `add(row)`, `delete(row)`; the shared body lives in one generic base in the same module so the two classes declare only their model and ordering (`priority, name` vs `name`). |
| `src/core/database/repositories/user.py` | `UserRepository.is_active_member(email) -> bool`, the guard's membership predicate moved out of `helpers.py:376` unchanged (§ 5.8.1). |
| `src/core/database/repositories/uow.py` | `AgentUoW(BaseUoW)` with `_REPOSITORIES = {"tenant_config": TenantConfigRepository, "creative_agents": CreativeAgentRepository, "signals_agents": SignalsAgentRepository}` (`tenant_config` for the `tenant` object every page renders, § 5.2.3); `TenantAccessUoW(BaseUoW)` with `{"users": UserRepository}` for the guard decision (§ 5.8.1). |
| `src/admin/forms/_base.py`, `src/admin/forms/agents.py` | `FormModel` and `parse_form` (§ 5.5.2); `AgentFormBase` with the five fields both templates submit (`agent_url`, `name`, `enabled`, `auth_type`, `auth_credentials`); `CreativeAgentForm` adds `priority`; `SignalsAgentForm` adds `auth_header`, `forward_promoted_offering`, `timeout`. Checkbox and blank-string coercion once on the base. The creative columns `auth_header` and `timeout` have no form input today and stay that way (templates untouched); the PR description names the gap. |
| `src/admin/services/agents.py` | `AgentKind` descriptor (my suggestion, builder decides the exact shape): the label used in messages, the UoW attribute name, the form class, the registry's probe, and the projection of a `ProbeResult` onto the template's keys. Functions `create_agent`, `update_agent`, `delete_agent`, `probe_agent`, each `(tenant_id, kind, ...)`. The URL ingest check runs in `create_agent` and `update_agent` on the submitted URL, and in `probe_agent` on the stored URL, for both kinds. |
| `src/admin/routers/__init__.py`, `src/admin/routers/agents.py` | One module registering two `APIRouter`s, `creative_agents` and `signals_agents`, ten explicit routes with today's paths and endpoint names, same template names, same `tenant`, `tenant_id`, `tenant_name`, `script_name` template variables; the ten bodies are five shared private functions parametrised by a small per-router record (templates, endpoint names, the row and form field lists). |
| `src/admin/app.py` | The two `register_blueprint` lines (`:310-311`) and the two imports (`:18`, `:33`) are deleted. |
| `src/app.py` | `build_admin_app(flask_admin_app)` replaces the bare `WSGIMiddleware` in `_install_admin_mounts()`. |
| `tests/admin/conftest.py`, `tests/helpers/admin_session.py`, `tests/integration/conftest.py` | The fixtures and helpers of § 5.9.2, § 5.9.3, § 5.9.5, § 5.9.9. |
| `tests/admin/test_web.py`, `tests/admin/test_agents.py` | § 6.3. |
| `tests/integration/test_admin_ingest_url_policy.py`, `tests/unit/test_fastapi_app_regression.py` | The re-pointed eight cases and the type check (§ 5.9.9, § 5.9.10). |
| `tests/unit/test_architecture_no_raw_select.py`, `tests/unit/test_ssrf_url_validator.py` | The ten allowlist rows naming the deleted blueprints removed, plus the `helpers.py` / `decorated_function` row (§ 5.8.1); the three tests that mock `src.admin.blueprints.signals_agents.get_db_session` and their two helpers removed (the seam test stays). |
| deleted: `src/admin/blueprints/creative_agents.py`, `signals_agents.py`, `tests/admin/test_agent_probe_routes.py` | replaced and folded in. |

Decided: one router module registering two routers, not two modules. Two
modules holding the same ten-line route bodies are what pylint R0801
(`min-similarity-lines = 6`, cross-file) counts, and the `src` duplication
number may not rise. The convention states it as "one module per domain; a
domain may register more than one router". Decided against: a router
factory producing both routers. It would remove the last residual
duplication (two route skeletons) but hides the routes from `grep`, from the
route-conflict hook, and from a reader, and the convention must look right
for the 29 blueprints that have no twin.

### 6.3 Tests for the pilot

`tests/admin/test_agents.py`, parametrised over the two kinds (a small
per-kind record carrying the URL prefix, the factory, the UoW attribute, the
registry class to patch, and the expected template keys), covering for each
kind:

- list page: 200, contains the seeded agent's name;
- add GET: 200; add POST valid: 302 to the list, row present through the
  repository with the typed defaults (`priority` 10 / `timeout` 30), the
  name trimmed, an unknown field ignored, `success` flash; add POST missing
  name: 302 back, `error` flash, no row; add POST blank URL: "Agent URL is
  required"; add POST non-integer `priority` / `timeout`: the field's own
  sentence; add POST with a URL egress policy refuses (a private address):
  302 back, the policy's one wording in the flash, no row, an audit row
  marked failed with that sentence;
- edit POST: row updated, credentials unchanged when the field is blank; a
  creative edit leaves `auth_header` and `timeout` as they were; an absent
  checkbox stores `False`; an unknown id redirects to the list with the
  not-found flash;
- delete: `{"success": true, ...}`, the row is gone, an audit row marked
  success; unknown id: `{"success": false, "error": "<Kind> agent not found"}`
  404 and an audit row marked failed; another tenant's id: 404 and that
  tenant's row untouched;
- test connection: the four existing assertions per kind (success projects
  every field onto the template keys, failure puts the sentence under
  `error`, a success with no count stays `null`, unknown id is 404),
  plus: a stored URL that egress policy refuses answers 400 without dialing;
  a probe that raises outside the registry's `try` answers a plain 500 whose
  body does not carry the exception text.

Unauthenticated access to one HTML route (302 to the login page) and one
JSON route (401 JSON) is asserted once, not per route; the guard is not the
pilot's subject.

`tests/admin/test_web.py`, the foundation:

- the session cookie round trip in both directions: a payload written by
  the Flask client (`admin_auth_session`) is read by a router; a value a
  router writes (a flash) is read back by the Flask side on the next request;
- a flash set by a router shows on a Flask-rendered page, and a flash set by
  a Flask route shows on a router-rendered page;
- `url_for` in a router-rendered template resolves a Flask endpoint
  (`auth.logout` or `core.index`) and a router endpoint, each under the
  request's prefix; Flask's `url_for` resolves a migrated endpoint through
  the fallback handler;
- the three compositions of § 5.12.2 serve the same page and each page's
  links and redirect `Location` carry that composition's prefix; the
  admin-host composition (root mount plus `X-Forwarded-Prefix: /admin`)
  links under `/admin`, as the Flask page does;
- the guard: no session → 302 to `/tenant/<id>/login` with `next=`, or 401
  `{"error": "Authentication required"}` under `api_mode`; a session for
  another tenant without super-admin → 403; the Flask decorator and the
  dependency give the same answer for the same payload (one parametrised
  test over both carriers);
- the session cookie a router writes carries the attributes the Flask app's
  config declares;
- the unexpected-failure path answers 500 without the exception text;
- a non-integer `agent_id` in a path answers 404, not 422 (§ 5.8.2).

### 6.4 Behavior kept and behavior changed

Kept: every URL under both prefixes, every endpoint name, template, template
variable, the audit operation names, the JSON keys the templates read, the
flash wording where it exists today, the login flow, the session cookie.
That the ten routes are now served by the FastAPI sub-application instead of
through a2wsgi is not operator-visible and is not listed as a change.

Changed, each listed in the PR description and in the proposal's pilot
section:

1. All six audited routes in the pair (add, edit, test connection, both
   kinds: `creative_agents.py:66-69, 142-145, 248-251`,
   `signals_agents.py:67-70, 146-149, 261-264`) audit inside the guard
   (the dependency runs first); an unauthenticated request to them no longer
   reaches the audit decorator.
2. JSON 404 bodies gain `"success": false` (the one envelope); the JavaScript
   already reads `data.error`, so nothing visible changes.
3. Unexpected failures in these ten routes answer a plain 500 instead of
   `{"error": "<str(e)>"}` or a flash of `str(e)`; the internal text stops
   reaching the browser.
4. The creative test-connection route re-checks the stored URL against
   egress policy before dialing, as the signals route already does.
5. Form input is validated before any row is read or written (today the
   signals edit route assigns the submitted values to the row first, then
   validates; the commit never happens on refusal, so this is a shape change
   with no observable effect, listed for completeness).
6. A refused write audits as `success=False` (today a refused write that
   returns a redirect audits as a success unless the route calls
   `record_admin_action_failure`, which neither of these does).
7. The four JSON routes (delete, test connection, both kinds) declare
   `api_mode=True`: an unauthenticated JSON caller gets 401 JSON instead of
   a 302 to the login page.
8. The two delete routes gain `@audited("delete_<kind>_agent")` and so write
   an audit row; today they write none.
9. A blank URL on the creative add form flashes "Agent URL is required"
   (as signals does today) instead of the egress-policy sentence, because
   the form is validated before the egress check. A URL the policy refuses
   still flashes exactly one egress sentence, which the ingest test pins.
10. A non-numeric `priority` or `timeout` flashes the field's own sentence
    (`"Priority: Input should be a valid integer, unable to parse string as an integer"`)
    instead of the generic "Error adding creative agent".
11. Submitted text fields are trimmed (`"  Spaced  "` is stored as
    `"Spaced"`) and unknown form fields are ignored, on both kinds.

### 6.5 Measurements to report before and after

Counted on the pilot's files at `main` and at the pilot's head, with the
command used so a reviewer can rerun it:

- lines per route module, lines total for the pair (including the new
  service, forms, repository, foundation and helper code, so the number is
  honest; the foundation is reported on its own line because every later
  migration reuses it);
- `get_db_session(`, `session.add(`, `select(`, `jsonify(`, `flash(`,
  `except Exception` per module;
- pylint R0801 duplicate blocks for `src/` and `tests/` (the
  `.duplication-baseline` numbers) before and after;
- the admin raw-session ratchet numbers before and after (expected
  186 → 172 and 39 → 37; the counter decides);
- modules importing `flask` under `src/admin` (34 → 32) and Flask blueprint
  modules (31 → 29);
- test count for the pair (8 before; after as implemented) and the private
  `_auth_session` / module-level `create_app()` counts.

## 7. Left to the builder

- The exact shape of the kind descriptor in the service (dataclass, enum
  with attributes, or two small adapter classes), as long as there is one
  service function per operation and no per-kind copy; and of the per-router
  record in the router module.
- The generic base for the two repositories (a `Generic[AgentT]` class or a
  mixin), and whether `add` takes a row or keyword fields.
- How the form models coerce checkboxes and blank optional strings.
- The helper that turns a `pydantic.ValidationError` into
  `AdminInvalidInput` and its message format, within § 5.5.2's sentences.
- The session middleware's internals (a pure-ASGI middleware or
  `BaseHTTPMiddleware`; how "modified" is tracked), as long as the cookie it
  writes is one Flask reads.
- The `url_for` compat function's internals and whether it returns a path
  or an absolute URL for `_external=True`.
- The shape of `tenant_access_decision`'s return value and of the audit
  record core, as long as both decorators share them.
- The per-kind test record's shape and whether the modules use a class per
  route group or flat functions.
- The ordering of the commits inside the pilot if the third one is split.
- The proposal document's wording and the Mermaid diagram styling, within
  § 4.1's section list and length.

## 8. Calls I made (check these while reading)

1. Pilot = the two agent blueprints (said in chat; the user did not object).
2. Proposal document lives at `docs/development/admin-convention-proposal.md`,
   single Markdown file with Mermaid, absolute GitHub links.
3. Services are plain functions, `tenant_id` first; existing service classes
   untouched.
4. Form models are pydantic, in a new `src/admin/forms/` package.
5. The JSON envelope is `{"success": bool, ...}` with `error` on failure, the
   superset of today's three shapes.
6. Refusals are a small `AdminRefusal` family with authored operator text;
   failures propagate; the sub-application's 500 handler is Phase 2.
7. One router module registering two routers; no router factory.
8. The pilot adds no BDD feature; templates are untouched.
9. `test_agent_probe_routes.py` is folded into `test_agents.py` and deleted.
10. The Flask-side test fixtures (`admin_client`, `test_admin_app`) are left
    as they are; the pilot adds the ASGI fixtures beside them.
11. Branch `refactor/admin-convention-pilot`, worktree
    `salesagent-admin-convention`, four commits, draft PR on the fork.
12. This spec and the plan are committed as the branch's first commit, not
    on the #2256 branch.
13. `AgentUoW` carries `tenant_config` so a page gets its `tenant` from the
    same UoW; GET routes read and render inside the UoW themselves.
14. Form models declare exactly what their template submits; a creative edit
    keeps `auth_header` and `timeout` untouched.
15. Validation messages keep today's sentences through `Field(title=...)`;
    validation runs before the egress check.
16. Every non-GET route audits; the two delete routes gain the decorator.
17. The four JSON routes switch to `api_mode=True`.
18. The audit read-back in tests uses an `AuditLogRepository` on
    `factory_session`; no production UoW gains a repository for a test.
19. The end state is one ASGI process with FastAPI routers only (the user's
    words, 2026-11-04); the convention's route layer is written for FastAPI
    and the pilot is the migration's first slice.
20. Migration mechanism: a FastAPI sub-application with Flask as its own
    fallback mount, mounted at `/admin` and `""` where the bare WSGI mount is
    today; one blueprint per PR; both prefixes kept.
21. The session cookie keeps Flask's format and secret until the final PR;
    routers read and write it through Flask's own serializer.
22. Endpoints are synchronous `def`; the data layer stays synchronous; async
    I/O is not proposed.
23. Package names: `src/admin/web/` for the foundation, `src/admin/routers/`
    for migrated routes.
24. The guard decision and the audit record composition are extracted from
    the Flask helpers into framework-free cores that both sides call (the
    DRY rule, applied to the migration itself).
25. Templates render through the Flask app's Jinja environment until the
    final PR; no second template engine, no template change.
26. `auth` migrates last; the remaining 29 blueprints are Phase 3, after the
    Phase 2 guards (the user's answer, 2026-11-04).
27. No CSRF layer is added; its absence is a listed finding.
28. The ingest test's eight agent cases are re-pointed at the ASGI client
    with assertions verbatim; the mount regression test's type check is
    updated; nothing else outside the pilot changes.
29. `AuthChallengeResponder`, the `/a2a/` carve-out and nginx are untouched.
30. Dropping FastAPI in favour of plain Starlette was considered and
    rejected: FastMCP and a2a-sdk fix the host as Starlette either way, and
    FastAPI's dependency injection is what makes the guard structural.
31. The prefix a migrated page links under is resolved once, the way
    `CustomProxyFix` resolves it today (`X-Script-Name`, else
    `X-Forwarded-Prefix`, else the mount), narrowed to plain-path values; a
    redirect's `Location` is always a `url_for` result.
32. The guard's membership read becomes `UserRepository.is_active_member`
    on a `TenantAccessUoW`, the predicate unchanged; no `UserRepository`
    exists today and the raw-select allowlist may not grow.
33. The sub-application maps `RequestValidationError` to a plain 404, so a
    non-integer path id answers as Flask's converter does.

## 9. Open questions

Three questions only the user could answer, raised after the builder
checks; each answer is written here once given.

**Which base, and what about the red integration job?** Facts checked on
2026-11-03:

- `origin/main` (fork) is c3bf1321, the measured commit; `prebid/main` is
  four commits ahead (`1c202df2`: #2458 deps, #2356 docker, #2358 "Save
  Account Settings submits nothing (nested favicon forms)" in the admin,
  #2451 deps).
- The Integration job is red at c3bf1321 for everyone: upstream GH
  [#2494](https://github.com/prebid/salesagent/issues/2494) ("Integration
  tests fail on the calendar date"), fix PR
  [#2495](https://github.com/prebid/salesagent/pull/2495) open, head
  `6f2ac1e7`. The ingest test that grades the pilot's routes lives in that
  job.
- The fork has Actions enabled and zero workflow runs so far; the pilot PR
  is the first CI run on the fork.

Options: (a) base on `origin/main` as measured and, when the job is red for
#2494's reason, `git merge --no-ff 6f2ac1e7` into the pilot branch (the
user's standing merge-not-cherry-pick rule), either up front or after the
first red run; (b) sync the fork's `main` to `prebid/main` first and base
there (the "measured at c3bf1321" numbers are then re-measured at the new
base); (c) accept the known-red job and say so in the PR.

**Answer (2026-11-03): (b), sync the fork's `main` first.** Done the same
day: `origin/main` fast-forwarded from c3bf1321 to 1c202df2 (`prebid/main`;
the fork had no commits of its own, so no merge commit). The counts in § 1
were re-checked at 1c202df2 and none changed: the four commits touch the
admin only through `src/admin/blueprints/settings.py` (ten lines removed,
none of them a counted token), its template, and one test that adds a call
to an existing `_auth_session` helper. The ratchet baselines are identical.
The pilot branch is created from `origin/main` at 1c202df2, or newer if
`prebid/main` has moved and the fork is synced again before branching.

The sync does not resolve the red job: #2495 is still open, so the
Integration job is red at 1c202df2 for the same reason. That needs no new
decision, because the user's standing rule covers it (a PR red from a bug an
open upstream PR fixes: offer, then `git merge --no-ff <sha>` of that branch,
which keeps the SHA so a later merge of `main` is clean). So the pilot PR
runs CI first; if its Integration job is red for #2494's reason, the builder
offers `git merge --no-ff 6f2ac1e7` into the pilot branch and merges only on
the user's yes. Nothing is merged up front, and (c) is not taken: a red job
is never reported as accepted.

**Where does the rest of the migration go?** Raised with revision 2 on
2026-11-04: fold the remaining 29 blueprints into Phase 2 next to the guards,
or make them Phase 3 after the guards. **Answer (2026-11-04): Phase 3.**
Phase 2 stays rules and guards; the guards are what make thirty mechanical
migration pull requests reviewable. § 2.2 and § 5.11 say so.

**What does "CI green on the fork" cover?** Raised by the revision-2 builder
check on 2026-11-04. Facts checked the same day:

- The fork has Actions enabled and zero workflow runs; the pilot PR is the
  first. Four CI jobs pull `ghcr.io/<repository>/adcp-creative-agent` from
  the repository's own registry: `Integration (creative)` (`ci.yml:305-311`),
  `E2E Tests` (`:374`), `BDD In-Network (e2e_rest)` (`:437`) and
  `Storyboard Conformance` (`:518`). On the fork that is
  `ghcr.io/v-n7k/salesagent/adcp-creative-agent`, which does not exist
  (checked: package not found). It is published only by
  `publish-creative-agent.yml`, which runs on a push to `main` or on
  `workflow_dispatch` and has never run on the fork. Until it runs once,
  those four jobs are red on every fork PR for a reason no PR can fix.
- Running it is one command,
  `gh workflow run publish-creative-agent.yml --repo v-n7k/salesagent --ref main`,
  and it publishes a container image under the user's GitHub account, which
  is why the builder may not do it on its own.
- `ipr-agreement.yml` (upstream's IPR policy bot) also runs on the fork, on
  `pull_request_target` with `GITHUB_TOKEN`, and clears when the PR author
  comments "I have read the IPR Policy". It is a policy check, not a test.

Options: (a) the user runs the publish workflow once on the fork's `main`
before the pilot's first push (or says yes and the plan's first task runs
it); the four jobs then grade the pilot as upstream would, and "CI green"
means every job. (b) The four jobs are outside the gate and the PR
description says so. The IPR check is outside the gate either way; the user
clears it with the one comment if they want a fully green PR page.
Recommendation: (a), because the handoff gate the user set is "green", and a
proposal whose PR tells reviewers to ignore four red jobs argues against its
own test-integrity stance.

**Answer: open.** The user approved revision 2 on 2026-11-04 without
choosing. The plan carries (a) as its default, and its first task asks in
words before the one command runs, because the command publishes under the
user's account; (b) stays available by saying so at that point.

## Appendix A: facts a builder will want at hand

- The host: `src/app.py:125` builds the one `FastAPI` app; `_install_admin_mounts()`
  (`:61-87`) removes and re-adds the two compatibility mounts at `/admin` and
  `""` so they stay last, and runs at lifespan startup (`:93`);
  `flask_admin_app = create_app(settings=settings)` and the bare
  `WSGIMiddleware` at `:593-594`; the `/a2a/` carve-out at `:397-401`;
  `AuthChallengeResponder` added at `:587`, defined in
  `src/core/auth_middleware.py:184` (upgrades to 401 only a body that carries
  an AdCP error code; strips and re-derives `WWW-Authenticate`).
- a2wsgi sets `SCRIPT_NAME` from `scope["root_path"]` and strips it from
  `PATH_INFO` (`a2wsgi/wsgi.py:94-97`; an environment `SCRIPT_NAME` would
  override it, `:99-101`); Starlette's `Request.url_for` resolves against
  `scope["router"]`, which the OUTERMOST router sets
  (`starlette/routing.py:665-666`, set only when absent), so inside a mounted
  sub-application it resolves against the main app and would always build
  the first mount's prefix; that, and the prefix header, is why the compat
  `url_for` of § 5.12.4 uses the sub-application router's `url_path_for` and
  never `request.url_for`. Starlette routes on `get_route_path(scope)`, the
  path with `root_path` removed (`starlette/_utils.py:96-110`).
- Prefix handling today: `CustomProxyFix` (`src/admin/app.py:52-99`) takes
  `X-Script-Name`, else `X-Forwarded-Prefix`, writes it to `SCRIPT_NAME`,
  strips it from `PATH_INFO` when present, and prepends it to a relative
  `Location` on a 30x; applied in both the production and the development
  branch (`:196-203`; `WerkzeugProxyFix` runs with `x_prefix=0`). nginx
  (`config/nginx/nginx-multi-tenant.conf`) sends `X-Forwarded-Prefix: /admin`
  on the admin host for every path (`:132`, `:146`; root paths go upstream
  unchanged) and on the tenant host under `location /admin/` (`:178`); the
  tenant host's root catch-all (`:199`), the single-tenant conf and the
  development conf send none. `inject_context` reads `script_name` from
  `request.script_root or SCRIPT_NAME` (`app.py:265`); the pair passes
  `script_name=request.environ.get("SCRIPT_NAME", "")` into every render
  (`creative_agents.py:57,84,176`, `signals_agents.py:58,85,182`);
  `core.index` delegates to `admin_index()` when `script_root == "/admin"`
  (`core.py:200-203`). No test sends the header today.
- Versions installed: fastapi 0.136.3, starlette 1.3.1, flask 3.1.3,
  httpx 0.28.1 (`TestClient` is httpx-based), a2wsgi ≥ 1.10, pydantic 2.12.
- Flask session: the default signed cookie (`SecureCookieSessionInterface`,
  `itsdangerous`), `app.secret_key = settings.runtime.flask_secret_key`
  (`src/admin/app.py:119`), cookie attributes at `:124-139`
  (`SESSION_COOKIE_PATH="/"` in both branches; `SAMESITE="None"` and
  `HTTPONLY=False` in production for EventSource). Test stacks pin the
  secret: `TEST_FLASK_SECRET_KEY` in `tests/helpers/admin_session.py:31`;
  `_session_payload(tenant_id, *, auth_method=None)` at `:34` is the one
  authenticated-super-admin payload (eleven keys, including `user`, `role`,
  `tenant_id`, `test_user`, `test_user_role`, `test_tenant_id`,
  `is_super_admin`, `admin_email`).
- Guards: `require_tenant_access(api_mode=False)` in
  `src/admin/utils/helpers.py:321-390`: setup-mode session check through
  `_setup_session_reaches(tenant_id)` (`:298`, reads Flask's `session`
  global), then `"user" not in session` → 401 JSON when `api_mode` else 302
  to `auth.tenant_login` (`:359-363`), then `is_super_admin(email)` (`:141`;
  its session cache is inside a `try` and falls through outside a Flask
  request context, `:152-159`), then the user's tenant membership through
  `get_db_session()` → 403 (`:374-383`). `auth.tenant_login` is
  `/tenant/<tenant_id>/login` (`src/admin/blueprints/auth.py:277`); the
  `auth` blueprint is registered with no prefix (`app.py:293`).
- The guard's membership read: `select(User).filter_by(email=email.lower(), tenant_id=tenant_id, is_active=True)`
  inside `decorated_function` (`helpers.py:376`), in a `try` whose
  `except Exception` re-raises 403/404 and otherwise logs and answers 500
  (`:386-394`). No `UserRepository` exists under
  `src/core/database/repositories/`; `is_tenant_admin` (`:219-241`) is a
  different predicate (`is_admin=True`, no tenant). The raw-select allowlist
  is keyed `(file, innermost function)` (`test_architecture_no_raw_select.py:59`)
  and may not grow; its `helpers.py` rows are at `:247-253`.
- Audit: `log_admin_action(operation_name, extract_details=None)` in
  `src/admin/utils/audit_decorator.py:176`: principal from
  `session.get("user", {})` (`:203`), `tenant_id` from `kwargs` or
  `request.view_args` (`:219`), success/failure around the call with
  re-raise (`:224-233`), `_apply_handled_failure` reading the marker
  `record_admin_action_failure` set on `g` (`:144-176`), then
  `audit_logger.log_operation(...)`, which commits in its own session
  (`src/core/audit_logger.py:249-263`).
- Templates: `templates/` is the Flask app's folder (`app.py:116`); custom
  filters `from_json`, `markdown` (`:163-164`); `inject_context` (`:253`)
  injects `script_name`, `support_email` (`src.core.domain_config.get_support_email`)
  and `tenant` when the session names one. Of the five templates the pilot
  renders, `base.html` reads `session.role` (seven times), `session.username`,
  `session.email`, `session.authenticated`, `script_name` (seven), `tenant`
  (guarded), `get_flashed_messages`, and `csrf_token` behind
  `if csrf_token` (`:6`); the four agent templates read `tenant_id`,
  `tenant_name`, `custom_agents` / `agent`, and `script_name` in their
  JavaScript. Across all 59 templates, 35 read `request.`, 24 read `g.`,
  19 read `config.`, 3 call `url_for('static', ...)`.
- The ast-grep ban on a `context` keyword argument:
  `.ast-grep/rules/context-is-written-by-the-boundary-alone.yml`, files
  `src/**/*.py`, ignoring only `src/core/tools/_boundary.py`.
- Existing tests that name the mounts: `tests/unit/test_fastapi_app_regression.py:238-272`
  (`TestAdminCompatibilityMount`); `tests/helpers/app_state.py:48-66` saves
  and restores `app.router.routes` around tests; the lifespan and signing
  conformance tests mention the catch-all by comment only.
- The ingest test: `tests/integration/test_admin_ingest_url_policy.py`, agent
  cases at lines 161, 182, 201, 227, 253 (signals) and 818, 830, 843
  (creative), all on `authenticated_admin_client` (`tests/integration/conftest.py:646`,
  `test_admin_app` + `admin_auth_session`); `flashes(client)` in
  `tests/integration/_egress_ingest_helpers.py:23` pops the Flask session;
  `operator_answer(client, response)` in `tests/helpers/race_window.py:42`
  does the same for the admin suite.
- URL ingest policy: `src/admin/utils/url_policy.py`,
  `redirect_if_url_blocked(url, label, destination)` and
  `json_error_if_url_blocked(url, label, **payload_extra)` over one
  `_is_allowed(url, label)`; the refusal wording is
  `"{label} is not allowed by outbound egress policy."`.
- Probe: `ProbeResult(ok, message, count=None, samples=())` in
  `src/core/utils/operator_mcp.py:43`; the creative probe fills `count` and
  `samples`, the signals probe fills `count` only; both never raise.
- Unit of Work: `BaseUoW(tenant_id, dry_run=False)` with the
  `_REPOSITORIES: ClassVar[Mapping[str, type]]` map
  (`src/core/database/repositories/uow.py:53,166`); `uow.session` warns;
  `SigningKeyUoW` (`:422-437`) is the declared-style precedent.
- Session: `get_db_session()` needs an explicit `commit()`; a `return`
  inside the block closes without committing
  (`src/core/database/database_session.py:249`).
- Test helpers: `tests/helpers/admin_session.py` (`admin_test_app()`,
  `admin_auth_session(client, tenant_id, *, auth_method=None)`);
  `tests/admin/conftest.py` (`admin_client`, re-exported `integration_db`,
  `factory_session`); factories `tests/factories/core.py:240`
  (`CreativeAgentFactory`), `:266` (`SignalsAgentFactory`), `TenantFactory`;
  `factory_session` in `tests/conftest_db.py:465` (process-wide binding, one
  test at a time per worker); `inject_limits(monkeypatch, **overrides)` in
  `tests/helpers/settings_injection.py`; `UNDIALLED_PUBLIC_HTTPS_ORIGIN` in
  `tests/helpers/egress_hatches.py`.
- Registration today: `src/admin/app.py:310-311` mounts the two blueprints at
  `/tenant/<tenant_id>/creative-agents` and `/tenant/<tenant_id>/signals-agents`;
  imports at `:18` and `:33`.
- CI: `tests/admin` runs in the "Admin UI Tests" job with a per-test Postgres;
  `-m "not slow"` is applied there (`ci.yml:638`, `tox.ini:169`);
  `tests/integration` (the ingest test) runs in the Integration job; the
  Quality Gate runs `make quality-ci`, which prints the duplication and
  raw-session counts.
- Fork CI: `publish-creative-agent.yml` (push to `main`, `workflow_dispatch`,
  no path filter) builds and pushes `ghcr.io/<repository>/adcp-creative-agent`
  through `scripts/creative-agent-stack.sh publish`; `ci.yml` pulls it with
  `packages: read` in `integration-tests` (`creative` group, `:305-311`),
  `e2e-tests` (`:374`), `bdd-in-network` (`:437`) and
  `storyboard-conformance` (`:518`). On 2026-11-04 the fork had zero
  workflow runs and no such package. `ipr-agreement.yml`: `pull_request_target`
  and `issue_comment`, `GITHUB_TOKEN`, signatures in
  `signatures/ipr-signatures.json`, cleared by the comment "I have read the
  IPR Policy".
- Tenant read: `TenantConfigRepository.get_tenant()`
  (`src/core/database/repositories/tenant_config.py:52`); `TenantConfigUoW`
  in `uow.py:276` shows the registration.
- Audit read: `AuditLogRepository` (`src/core/database/repositories/audit_log.py`,
  `find_by_operation`), on no UoW.
- `require_tenant_access` never checks that the tenant row exists, which is
  why every GET route in the pair loads the tenant and redirects "Tenant not
  found"; that redirect is kept.
- The repo-invariants hook (`.pre-commit-hooks/check_repo_invariants.py:98-108`)
  and `tests/unit/test_architecture_repo_invariants.py:94-108` refuse a
  home-directory path in any tracked text file.
- Ratchets: `.admin-raw-session-baseline` is checked by
  `tests/unit/test_architecture_ratchet_enforcement.py` (over and slack) and
  rewritten by `.pre-commit-hooks/check_admin_raw_session_count.py`;
  `.duplication-baseline` by `tests/quality/test_ratchets_slow.py` and
  `.pre-commit-hooks/check_code_duplication.py` (run by `make quality-ci`,
  prints the new count). Neither hook is a pre-commit stage.

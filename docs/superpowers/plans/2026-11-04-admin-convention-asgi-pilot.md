# Admin Convention and ASGI Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ASGI admin foundation (a FastAPI sub-application with the Flask admin as its fallback), move the `creative_agents` and `signals_agents` blueprints onto it as FastAPI routers under the proposed admin convention (router → pydantic form → service → repository inside a Unit of Work, one JSON envelope, one refusal family, guard before audit), with one test module each for the foundation and the pilot, and write the proposal document the team reviews on a fork-only draft PR.

**Architecture:** `build_admin_app(flask_app)` (`src/admin/web/`) returns a FastAPI sub-application that decodes Flask's signed session cookie with Flask's own serializer, renders templates through Flask's Jinja environment, resolves the link prefix the way `CustomProxyFix` does, includes the migrated routers, handles three exceptions (login required, denied, bad path parameter), and mounts the Flask app last as a catch-all. `src/app.py` mounts that sub-application at `/admin` and `""` where the bare `WSGIMiddleware` is today. The guard decision and the audit record are extracted from the Flask decorators into framework-free cores that both sides call. The pilot is one router module registering two `APIRouter`s over one service module (`AgentKind` record), one form package, one repository base and `AgentUoW`. Templates, URLs, endpoint names, template variables and audit operation names do not change.

**Tech Stack:** Python 3.12, FastAPI 0.136 / Starlette 1.3 (`fastapi.testclient.TestClient`, httpx-based), Flask 3.1.3 (kept as the fallback; its `SecureCookieSessionInterface` serializer and `jinja_env` are reused), a2wsgi, pydantic 2.12, SQLAlchemy 2.0 (`BaseUoW` + repositories), pytest + factory-boy (`tests/admin`), Mermaid for the proposal's diagrams, `gh` for the fork's draft PR and CI.

**Spec:** `docs/superpowers/specs/2026-11-03-admin-convention-proposal-design.md` (revision 2, approved 2026-11-04). Section numbers below (§) refer to it. The plan argues from the spec; read both.

## Global Constraints

- **Where the work lives:** a sibling worktree `../salesagent-admin-convention`, branch `refactor/admin-convention-pilot`, created from freshly fetched `origin/main` (1c202df2 or newer). Nothing is committed in `salesagent-2256`. (§ 4.2)
- **Fork only:** push to `origin` (`git@github.com:v-n7k/salesagent.git`); the draft PR targets the fork's `main`; nothing goes to the `prebid` remote; never push to `main`. (§ 3)
- **Local checks are file-scoped only:** `scripts/run-test.sh --db <one test file>`, `uv run pytest <one unit test file>`, `uv run ruff format <changed files>`, `uv run ruff check --fix <changed files>`, `uv run mypy <changed src files> --config-file=mypy.ini`. Never `make quality`, `tox`, `./run_all_tests.sh` or the full unit suite locally; CI on the fork grades every push. (Owner's standing rule; § 3)
- **Four commits, in the spec's order** (§ 4.2): `docs(admin): add the admin convention design spec and plan`; `refactor(admin): add the ASGI admin foundation`; `refactor(admin): move the agent blueprints to FastAPI routers under the admin convention`; `docs(admin): propose the admin convention and ASGI migration`. Tasks stage files; the commit steps are in Tasks 0, 5, 11 and 13. Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; the PR description ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Kept verbatim (§ 6.4 "Kept"):** paths `/tenant/{tenant_id}/creative-agents/`, `/add`, `/{agent_id}/edit`, `/{agent_id}/delete`, `/{agent_id}/test` and the `signals-agents` twins, under both the `/admin` and the root mount; route names `creative_agents.list_creative_agents`, `creative_agents.add_creative_agent`, `creative_agents.edit_creative_agent`, `creative_agents.delete_creative_agent`, `creative_agents.test_creative_agent` and the `signals_agents.*` twins; templates `creative_agents.html`, `creative_agent_form.html`, `signals_agents.html`, `signals_agent_form.html`, untouched; template variables `tenant`, `tenant_id`, `tenant_name`, `custom_agents`, `agent`, `script_name`; audit operation names `add_creative_agent`, `edit_creative_agent`, `test_creative_agent` (+ signals twins) plus the two new `delete_creative_agent` / `delete_signals_agent`; the JSON keys `success`, `message`, `error`, `format_count`, `sample_formats`, `signal_count`; the flash sentences `"Agent URL is required"`, `"Agent name is required"`, `"<Kind> agent '<name>' added successfully"`, `"<Kind> agent '<name>' updated successfully"`, `"<Kind> agent '<name>' deleted successfully"`, `"<Kind> agent not found"`, `"Tenant not found"`, and the egress sentence `"Agent URL is not allowed by outbound egress policy."` (`Kind` is `Creative` or `Signals`); the guard's answers `{"error": "Authentication required"}` 401, `{"error": "Access denied"}` 403, and the 302 to `/tenant/<id>/login?next=<request URL>`.
- **The session cookie stays Flask's:** name `SESSION_COOKIE_NAME` (`session`), signed by `flask_app.session_interface.get_signing_serializer(flask_app)`, loaded with `max_age=int(flask_app.permanent_session_lifetime.total_seconds())`, flashes under the key `_flashes` as a list of `(category, message)` pairs. (§ 5.12.3)
- **Lint ceilings new code must respect** (ratcheted in CI): ruff line length 120, `max-complexity = 10`, `max-branches = 12`, `max-statements = 50`; every new function fully type-annotated (the `mypy --check-untyped-defs` error count may not grow); no `except Exception` in routers, services or forms (§ 5.7.3; the one permitted site is the audit wrapper's record-and-re-raise, as in the Flask decorator).
- **ast-grep and hook traps:** no keyword argument named `context` anywhere under `src/` (the render helper takes `**values`; § 3); never spell `result.message` or `response.message` in `src/` (`scripts/hooks/check_response_attribute_access.py` refuses it; name a probe outcome `probe`); no `/home/<user>/` path in any tracked file; no `FIXME(salesagent-…)` or quoted local beads id; no bare `@pytest.mark.skip`.
- **No `from __future__ import annotations` in a module that defines an `@audited` endpoint** (`src/admin/routers/agents.py`, `tests/admin/test_web.py`): FastAPI resolves string annotations against the endpoint callable's module globals, which after `functools.wraps` are the wrapper's module, not the endpoint's. Real annotations need no resolution.
- **Ratchets only go down, and the committed number must EQUAL the measured one:** `.duplication-baseline` (`src: 25, tests: 42, scripts: 0`; measured only by `make quality-ci` and `tests/quality/test_ratchets_slow.py`) and `.admin-raw-session-baseline` (`admin_get_db_session: 186, admin_session_add: 39`; measured by `.pre-commit-hooks/check_admin_raw_session_count.py` and `tests/unit/test_architecture_ratchet_enforcement.py`). Each has an over-check and a slack-check, so a baseline left above the new count fails too. Guard allowlists shrink, never grow; the raw-select allowlist is keyed `(file, innermost function)`. (§ 3)
- **Two tests outside the pilot change, by design, and no other:** `tests/unit/test_fastapi_app_regression.py::TestAdminCompatibilityMount` (type check) and the eight agent cases of `tests/integration/test_admin_ingest_url_policy.py` (re-pointed, assertions verbatim). (§ 3)
- **Not in scope:** guards, ast-grep/ruff rules, `CLAUDE.md` text, other blueprints, `auth`, a BDD feature, the sub-application's 500 handler, a session-format change, an async data layer, CSRF, an upstream PR. (§ 2.2)

## Review Focus

Inputs the spec implies but names no test for, most likely to bite a person first; each gets its test in the task that owns the code:

1. **A `X-Forwarded-Prefix` that is not a plain path** (`https://attacker.example`, `//attacker.example`): a page must keep linking under the mount, never off-host. → Task 3 (`test_admin_prefix_precedence_and_plain_path_rule` in the unit module; `test_a_prefix_header_that_is_not_a_plain_path_is_ignored` in `test_web.py`).
2. **A tampered or expired session cookie** (`garbage`, or one signed with another secret): expected an anonymous session (login redirect), never a 500. → Task 3 (`test_an_unreadable_cookie_is_an_empty_session`).
3. **A non-numeric `priority` / `timeout`** (`"abc"`): today `int()` raises into the blanket `except` and the operator sees "Error adding creative agent". Expected a 302 back to the form with `"Priority: Input should be a valid integer, unable to parse string as an integer"`. → Task 6 (`test_non_integer_number_names_the_field`) and Task 7 (`test_add_with_a_non_integer_number_is_refused`).
4. **Another tenant's agent id** on delete or probe: expected 404 `{"success": false, "error": "<Kind> agent not found"}` and the other tenant's row untouched. → Task 7 (`test_delete_cannot_reach_another_tenants_agent`).
5. **A probe that raises outside the registry's own `try`** (`config_for` or `asyncio.run`): expected a plain 500 whose body does not carry the exception text. → Task 7 (`test_probe_crash_is_a_plain_500_without_the_exception_text`); the foundation half in Task 3 (`test_an_unexpected_failure_is_a_plain_500_without_the_exception_text`).

---

## File map (after the pilot)

| File | Responsibility |
|---|---|
| `src/admin/errors.py` (new) | `AdminRefusal` + `AdminNotFound` (404) / `AdminInvalidInput` (400) / `AdminConflict` (409) |
| `src/admin/web/__init__.py` (new) | docstring: the ASGI admin foundation, § 5.12 |
| `src/admin/web/responses.py` (new) | `json_ok`, `json_error`, `redirect`, `refuse_json`, `refuse_form` |
| `src/admin/web/session.py` (new) | `AdminSessionMiddleware`, `flash`, `get_flashed_messages` |
| `src/admin/web/templates.py` (new) | `admin_prefix`, `request_url`, `url_for`, `render` |
| `src/admin/web/guards.py` (new) | `require_tenant_access` (dependency factory), `AuthRequired`, `AccessDenied`, their two handlers |
| `src/admin/web/audit.py` (new) | `form_data` (dependency), `record_admin_action_failure`, `audited` |
| `src/admin/web/app.py` (new) | `build_admin_app`, the `RequestValidationError` → 404 handler, the Flask `url_build_error_handlers` fallback |
| `src/admin/routers/__init__.py` (new) | `ADMIN_ROUTERS`, the one registration point |
| `src/admin/routers/agents.py` (new; replaces `blueprints/creative_agents.py` and `blueprints/signals_agents.py`, both deleted) | two `APIRouter`s, ten explicit routes, five shared private bodies |
| `src/admin/forms/__init__.py`, `src/admin/forms/_base.py`, `src/admin/forms/agents.py` (new) | `FormModel`, `parse_form`; `AgentFormBase`, `CreativeAgentForm`, `SignalsAgentForm` |
| `src/admin/services/agents.py` (new) | `AgentKind`, `CREATIVE`, `SIGNALS`, `create_agent`, `update_agent`, `delete_agent`, `probe_agent` |
| `src/admin/utils/helpers.py` (modified) | `TenantAccess`, `tenant_access_decision`; `_setup_session_reaches` takes the mapping; `require_tenant_access` calls the core |
| `src/admin/utils/audit_decorator.py` (modified) | `audit_principal`, `sanitize_request_data`, `fold_handled_failure`, `record_admin_action`; `log_admin_action` calls them |
| `src/admin/utils/url_policy.py` (modified) | `raise_if_url_blocked(url, label)`, the Flask-free third helper |
| `src/admin/app.py` (modified) | the two agent imports and `register_blueprint` lines deleted |
| `src/app.py` (modified) | `admin_app = build_admin_app(flask_admin_app)`; `_install_admin_mounts()` mounts it |
| `src/core/database/repositories/user.py` (new) | `UserRepository.is_active_member` |
| `src/core/database/repositories/agent.py` (modified) | generic `_AgentRepository[AgentRow]` base; the two classes declare model and ordering |
| `src/core/database/repositories/uow.py` (modified) | `TenantAccessUoW`, `AgentUoW` |
| `src/core/database/repositories/__init__.py` (modified) | exports `UserRepository` |
| `tests/helpers/admin_session.py` (modified) | `signed_session_cookie`, `admin_auth_cookie`, `asgi_auth_session`, `session_cookie_payload`, `cookie_flashes` |
| `tests/admin/conftest.py` (modified) | `asgi_admin_app`, `asgi_admin_client` |
| `tests/integration/conftest.py` (modified) | `authenticated_asgi_admin_client` |
| `tests/integration/_egress_ingest_helpers.py` (modified) | `asgi_flashes` |
| `tests/unit/test_admin_web_responses.py`, `tests/unit/test_admin_web_prefix.py`, `tests/unit/test_admin_session_helpers.py`, `tests/unit/test_admin_forms_agents.py` (new) | pure-function tests |
| `tests/admin/test_web.py` (new) | the foundation's tests over probe routes |
| `tests/admin/test_agents.py` (new; `tests/admin/test_agent_probe_routes.py` deleted) | the pilot's route tests, parametrised over the two kinds |
| `tests/unit/test_fastapi_app_regression.py`, `tests/integration/test_admin_ingest_url_policy.py` (modified) | the type check; the eight re-pointed cases |
| `tests/unit/test_architecture_no_raw_select.py`, `tests/unit/test_ssrf_url_validator.py` (modified) | eleven allowlist rows removed; the three DB-mocking blueprint tests and their two helpers removed |
| `.admin-raw-session-baseline`, `.duplication-baseline` (modified) | lowered to the measured counts |
| `docs/development/admin-convention-proposal.md` (new) | the proposal (§ 4.1) |

**One router module, not two.** The duplication ratchet is pylint R0801 with `min-similarity-lines = 6` across files; two modules holding the same ten-line route bodies would raise `src` above 25 on the first CI run. One module cannot trigger a cross-file similarity, and the layout matches `services/agents.py`, `forms/agents.py` and `tests/admin/test_agents.py`. The proposal states it as "one module per domain; a domain may register more than one router" (§ 6.2).

**One foundation test module with probe routes.** `tests/admin/test_web.py` is in the foundation commit, before any pilot router exists, so it grades the foundation over a small `APIRouter` and two Flask routes it registers itself. That is also why `build_admin_app` takes a `routers=` argument: the test passes its probe router, production passes nothing and gets `ADMIN_ROUTERS`.

---

### Task 0: Worktree, branch, the publish-workflow question, first commit, draft PR

**Files:**
- Create (in the new worktree): `docs/superpowers/specs/2026-11-03-admin-convention-proposal-design.md`, `docs/superpowers/plans/2026-11-04-admin-convention-asgi-pilot.md` (copies of the untracked files in `salesagent-2256`)

- [ ] **Step 1: Put the fork-CI question to the user, in words, and do not run the command without a yes**

Four fork CI jobs (`Integration (creative)`, `E2E Tests`, `BDD In-Network (e2e_rest)`, `Storyboard Conformance`) pull `ghcr.io/v-n7k/salesagent/adcp-creative-agent`, which does not exist until `publish-creative-agent.yml` has run once on the fork's `main` (§ 9). Ask: "Run `gh workflow run publish-creative-agent.yml --repo v-n7k/salesagent --ref main` once now? It publishes a container image under your GitHub account. (a) yes, run it; (b) no, those four jobs stay outside the green gate and the PR description says so." Continue with Step 2 and the following tasks while the answer is pending. On (a): run the command, then `gh run list --repo v-n7k/salesagent --workflow publish-creative-agent.yml --limit 1` until it reports `success`, and re-run the failed jobs of the latest pilot run (`gh run rerun <run-id> --repo v-n7k/salesagent --failed`). On (b): record the choice for Task 12's PR body. The IPR Agreement check is outside the gate either way (the user clears it with the comment "I have read the IPR Policy").

- [ ] **Step 2: Create the worktree from fresh `origin/main`**

Run (from `salesagent-2256`):
```bash
git fetch origin main && git worktree add ../salesagent-admin-convention -b refactor/admin-convention-pilot origin/main
```
Expected: `Preparing worktree (new branch 'refactor/admin-convention-pilot')`; `git -C ../salesagent-admin-convention log -1 --format=%h` prints `1c202df2` or a newer `origin/main`.

- [ ] **Step 3: Copy the spec and this plan in, and prepare the environment**

Run (from the new worktree, which is the working directory for every later step):
```bash
mkdir -p docs/superpowers/specs docs/superpowers/plans && cp ../salesagent-2256/docs/superpowers/specs/2026-11-03-admin-convention-proposal-design.md docs/superpowers/specs/ && cp ../salesagent-2256/docs/superpowers/plans/2026-11-04-admin-convention-asgi-pilot.md docs/superpowers/plans/ && uv sync --frozen
```
Expected: both files present under `docs/superpowers/`; `uv sync` ends without error.

- [ ] **Step 4: Commit the two documents**

```bash
git add docs/superpowers/specs/2026-11-03-admin-convention-proposal-design.md docs/superpowers/plans/2026-11-04-admin-convention-asgi-pilot.md
git commit -m "docs(admin): add the admin convention design spec and plan" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
Expected: commit-stage hooks pass (the repo-invariants hook scans tracked text for home-directory paths; neither file has one; the docs-links hook runs at pre-push and only checks relative links, of which these files have none).

- [ ] **Step 5: Push and open the draft PR**

```bash
git push -u origin refactor/admin-convention-pilot
gh pr create --repo v-n7k/salesagent --base main --head refactor/admin-convention-pilot --draft --title "refactor(admin): admin convention and ASGI migration proposal, with the agent pilot" --body "Draft. The description is written once the pilot and its measurements exist."
```
Expected: pre-push hooks pass; `gh` prints the PR URL. Record the PR number for Tasks 11–13. The PR exists now so that every later push is graded by the fork's CI.

---

### Task 1: Refusals and the three plain response helpers

**Files:**
- Create: `src/admin/errors.py`
- Create: `src/admin/web/__init__.py` (docstring only: the ASGI admin foundation of § 5.12; what each module holds)
- Create: `src/admin/web/responses.py`
- Test: `tests/unit/test_admin_web_responses.py`

**Interfaces:**
- Produces:
  - `class AdminRefusal(Exception)`: `status: ClassVar[int] = 400`; `__init__(self, message: str)`; attribute `message: str`; `str(exc) == message`. `AdminNotFound` (`status = 404`), `AdminInvalidInput` (`status = 400`), `AdminConflict` (`status = 409`). Imports nothing from any framework.
  - `json_ok(**fields: Any) -> JSONResponse` → HTTP 200, body `{"success": true, ...fields}`.
  - `json_error(message: str, status: int) -> JSONResponse` → body `{"success": false, "error": message}`, the given status.
  - `redirect(url: str) -> RedirectResponse` → status 302 (never Starlette's 307 default; § 5.6.3).
  - `refuse_json` and `refuse_form` are added to this module in Task 4 (they need the session's `flash` and the audit marker).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_admin_web_responses.py` (no app, no request; `json.loads(response.body)` reads the body):

```python
def test_refusal_statuses_and_message():
    assert (AdminNotFound("x").status, AdminInvalidInput("x").status, AdminConflict("x").status) == (404, 400, 409)
    assert (str(AdminNotFound("gone")), AdminNotFound("gone").message) == ("gone", "gone")

def test_json_ok_carries_success_and_fields():
    response = json_ok(count=3, samples=["a"])
    assert (response.status_code, json.loads(response.body)) == (200, {"success": True, "count": 3, "samples": ["a"]})

def test_json_error_carries_message_and_status():
    response = json_error("nope", 404)
    assert (response.status_code, json.loads(response.body)) == (404, {"success": False, "error": "nope"})

def test_redirect_is_a_302():
    response = redirect("/back")
    assert (response.status_code, response.headers["location"]) == (302, "/back")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_admin_web_responses.py -q`
Expected: FAIL at import (`ModuleNotFoundError: No module named 'src.admin.errors'`).

- [ ] **Step 3: Implement `src/admin/errors.py`, `src/admin/web/__init__.py`, `src/admin/web/responses.py`**

`responses.py` imports `JSONResponse` and `RedirectResponse` from `starlette.responses` and nothing from Flask. Module docstrings state § 5.6 / § 5.7 in one paragraph each (the operator-facing message is authored at the raise site because this is the operator surface, not the buyer wire).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_admin_web_responses.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Format and lint; stage; no commit yet (commit 2 is Task 5)**

Run: `uv run ruff format src/admin/errors.py src/admin/web tests/unit/test_admin_web_responses.py && uv run ruff check src/admin/errors.py src/admin/web tests/unit/test_admin_web_responses.py && git add src/admin/errors.py src/admin/web tests/unit/test_admin_web_responses.py`
Expected: no diagnostics.

---

### Task 2: Test helpers and fixtures for the ASGI client

**Files:**
- Modify: `tests/helpers/admin_session.py` (append five functions; re-express `admin_session_cookie` over the first)
- Modify: `tests/admin/conftest.py` (append two fixtures after `admin_client`)
- Modify: `tests/integration/conftest.py:663` (append one fixture after `authenticated_admin_client`)
- Modify: `tests/integration/_egress_ingest_helpers.py` (append one function after `flashes`)
- Test: `tests/unit/test_admin_session_helpers.py`

**Interfaces:**
- Produces (in `tests/helpers/admin_session.py`):
  - `signed_session_cookie(flask_app: Any, payload: Mapping[str, Any]) -> str`: `flask_app.session_interface.get_signing_serializer(flask_app).dumps(dict(payload))`; asserts the serializer is not `None` with the same message `admin_session_cookie` uses. `admin_session_cookie` becomes: build the bare `Flask` app with the secret as today, then `return signed_session_cookie(app, _session_payload(tenant_id, auth_method=auth_method))`.
  - `admin_auth_cookie(flask_app: Any, tenant_id: str, *, auth_method: str | None = None) -> str` → `signed_session_cookie(flask_app, _session_payload(tenant_id, auth_method=auth_method))` (§ 5.9.3: one payload, two carriers).
  - `asgi_auth_session(client: Any, flask_app: Any, tenant_id: str, *, auth_method: str | None = None) -> None`: `client.cookies.set(flask_app.config["SESSION_COOKIE_NAME"], admin_auth_cookie(...), domain="testserver.local")`. The domain is deliberate and documented in the docstring: `http.cookiejar` turns the dotless test host `testserver` into the effective host `testserver.local`, files a host-only `Set-Cookie` under that domain, and returns a stated cookie only if its domain matches it; stating the cookie under the same domain is what makes the server's later `Set-Cookie` REPLACE it instead of sitting next to it (the `drop_stated_session_cookie` problem, solved at the source for this client).
  - `session_cookie_payload(flask_app: Any, response: Any) -> dict[str, Any]`: the session the response's own `Set-Cookie` carries, decoded with `get_signing_serializer(flask_app).loads(value, max_age=int(flask_app.permanent_session_lifetime.total_seconds()))`; `{}` when the response set no cookie of that name (`response.cookies.get(name)` on an httpx response).
  - `cookie_flashes(flask_app: Any, response: Any) -> list[tuple[str, str]]`: `[tuple(pair) for pair in session_cookie_payload(flask_app, response).get("_flashes", [])]`, the ASGI twin of `operator_answer` (`tests/helpers/race_window.py:42`) and of the ingest helper's `flashes()`.
- Produces (in `tests/admin/conftest.py`):
  - `asgi_admin_app`: `build_admin_app(admin_test_app())` (both imported inside the fixture body; `build_admin_app` from `src.admin.web.app`, Task 3). The Flask app it wraps is reachable as `asgi_admin_app.state.flask_app` (Task 3 sets it).
  - `asgi_admin_client`: `fastapi.testclient.TestClient(asgi_admin_app, raise_server_exceptions=False, follow_redirects=False)` (a 500 is observed as a 500; a 302 is observed as a 302). Docstring: the one client every migrated domain's module uses; the Flask `admin_client` stays for the modules that still test Flask blueprints and goes with the last of them (§ 5.9.2).
- Produces (in `tests/integration/conftest.py`): `authenticated_asgi_admin_client(test_admin_app)` → `build_admin_app(test_admin_app)`, the same `TestClient` arguments, then `asgi_auth_session(client, test_admin_app, "default")`; yields the client. The ASGI twin of `authenticated_admin_client` (§ 5.9.9).
- Produces (in `tests/integration/_egress_ingest_helpers.py`): `asgi_flashes(client, response) -> list[tuple[str, str]]` → `cookie_flashes(client.app.state.flask_app, response)` (a `TestClient` keeps the app it serves on `.app`).

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_admin_session_helpers.py` (a bare `Flask("unit")` with `secret_key = "unit"`; an `httpx.Response(302, headers={"set-cookie": f"session={cookie}; Path=/"}, request=httpx.Request("POST", "http://testserver/x"))` stands in for a response):

```python
def test_admin_auth_cookie_round_trips_through_flasks_own_serializer(app):
    cookie = admin_auth_cookie(app, "t1")
    assert app.session_interface.get_signing_serializer(app).loads(cookie) == _session_payload("t1")

def test_admin_session_cookie_signs_the_same_payload_with_the_given_secret():
    app = Flask("unit"); app.secret_key = "unit"
    assert app.session_interface.get_signing_serializer(app).loads(admin_session_cookie("t1", secret_key="unit")) == _session_payload("t1")

def test_session_cookie_payload_reads_the_cookie_the_response_set(app):
    response = _response_with_cookie(signed_session_cookie(app, {"_flashes": [("error", "bad")]}))
    assert session_cookie_payload(app, response) == {"_flashes": [("error", "bad")]}
    assert cookie_flashes(app, response) == [("error", "bad")]

def test_session_cookie_payload_is_empty_without_a_cookie(app):
    assert session_cookie_payload(app, httpx.Response(200, request=httpx.Request("GET", "http://testserver/x"))) == {}

def test_a_cookie_signed_with_another_secret_reads_as_empty(app):
    other = Flask("other"); other.secret_key = "other"
    assert session_cookie_payload(app, _response_with_cookie(signed_session_cookie(other, {"user": "x"}))) == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_admin_session_helpers.py -q`
Expected: FAIL at import (`ImportError: cannot import name 'admin_auth_cookie'`).

- [ ] **Step 3: Implement the five helpers, the `admin_session_cookie` re-expression, the three fixtures and `asgi_flashes`**

The conftest fixtures import `build_admin_app` inside the fixture body, so the conftest imports cleanly before Task 3 exists. `session_cookie_payload` catches `itsdangerous.BadSignature` (which `SignatureExpired` subclasses) and returns `{}`, the way Flask's `open_session` does.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_admin_session_helpers.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Format and lint; stage**

Run: `uv run ruff format tests/helpers/admin_session.py tests/admin/conftest.py tests/integration/conftest.py tests/integration/_egress_ingest_helpers.py tests/unit/test_admin_session_helpers.py && uv run ruff check --fix <the same files> && git add <the same files>`
Expected: no diagnostics.

---

### Task 3: The sub-application: session, prefix, links, templates, builder

**Files:**
- Create: `src/admin/web/session.py`
- Create: `src/admin/web/templates.py`
- Create: `src/admin/web/app.py`
- Create: `src/admin/routers/__init__.py`
- Test: `tests/unit/test_admin_web_prefix.py`, `tests/admin/test_web.py` (part 1; Task 4 appends part 2)

**Interfaces:**
- Consumes: `json_ok`, `redirect` (Task 1); `admin_test_app`, `admin_auth_session`, `signed_session_cookie`, `session_cookie_payload` (Task 2).
- Produces (in `session.py`):
  - `class AdminSessionMiddleware`: `__init__(self, app: ASGIApp, flask_app: Flask) -> None`; `async def __call__(self, scope, receive, send) -> None`. A pure ASGI middleware (my call, § 7: no `BaseHTTPMiddleware`). For an `http` scope it reads the cookie named `flask_app.config["SESSION_COOKIE_NAME"]`, decodes it with `flask_app.session_interface.get_signing_serializer(flask_app).loads(value, max_age=int(flask_app.permanent_session_lifetime.total_seconds()))` (`BadSignature` or no cookie → `{}`), stores a copy as `scope.setdefault("state", {})["session"]` (that is what `request.state.session` reads: Starlette's `Request.state` wraps `scope["state"]`), and wraps `send` so that on `http.response.start`, if the mapping differs from what was loaded, it appends one `set-cookie` header: the serialized mapping with `path`, `domain`, `secure`, `httponly`, `samesite` from `flask_app.session_interface.get_cookie_path/domain/secure/httponly/samesite(flask_app)`, `expires = now + flask_app.permanent_session_lifetime` only when the mapping has `_permanent` set, and a deleting cookie (`max_age=0`) when the mapping became empty. "Modified" is `session != loaded` (my call: a comparison, not a flag).
  - `flash(request: Request, message: str, category: str = "message") -> None`: appends `(category, message)` to `request.state.session.setdefault("_flashes", [])`.
  - `get_flashed_messages(request: Request, with_categories: bool = False, category_filter: Iterable[str] = ()) -> list[Any]`: pops `_flashes` from the session on first call and keeps the list on `request.state.flashes` so a second call in the same request sees the same messages (Flask's own contract); filters and shapes exactly as `flask.get_flashed_messages`.
- Produces (in `templates.py`):
  - `admin_prefix(request: Request) -> str`: the first of `X-Script-Name`, `X-Forwarded-Prefix`, `request.scope.get("root_path", "")` that is set; a header value is honoured only when it starts with exactly one `/` and contains no `://` (else fall through to the next source); the result is `rstrip("/")`-ed (`"/"` → `""`). (§ 5.12.4, call 31.)
  - `request_url(request: Request) -> str`: the request's own absolute URL with the prefix the operator sees: `str(request.url.replace(path=admin_prefix(request) + route_path))`, where `route_path` is `scope["path"]` with `scope["root_path"]` removed from its front when present. Used for the login redirect's `next=` (Flask sends `request.url`, which carries `SCRIPT_NAME`).
  - `url_for(request: Request, endpoint: str, **values: Any) -> str`: `admin_prefix(request) + str(request.app.url_path_for(endpoint, **values))`; on `starlette.routing.NoMatchFound`, `request.app.state.flask_app.url_map.bind(server_name=request.headers.get("host", "localhost"), script_name=admin_prefix(request), url_scheme=request.url.scheme).build(endpoint, dict(values))` (Werkzeug prefixes `script_name` itself and puts unknown values in the query string, which is how `next=` travels). A Werkzeug `BuildError` propagates: an unknown endpoint is a bug in a template. `request.app` is the sub-application (Starlette sets `scope["app"]` on every nested app it enters).
  - `render(request: Request, template_name: str, **values: Any) -> HTMLResponse`: `request.app.state.flask_app.jinja_env.get_template(template_name).render(...)` with `url_for` (a closure over `request`), `get_flashed_messages` (same), `session=request.state.session`, `script_name=admin_prefix(request)`, `support_email=get_support_email()` (`src.core.domain_config`), then `**values`; a caller's value wins over these five. No `request`, `g` or `config` (§ 5.12.5). The keyword is `**values`, never `context` (§ 3).
- Produces (in `app.py`):
  - `build_admin_app(flask_app: Flask, *, routers: Sequence[APIRouter] | None = None) -> FastAPI`: `FastAPI(openapi_url=None, docs_url=None, redoc_url=None)`; `app.state.flask_app = flask_app`; `app.add_middleware(AdminSessionMiddleware, flask_app=flask_app)`; `app.include_router(r)` for each of `routers if routers is not None else ADMIN_ROUTERS`; `app.add_exception_handler(RequestValidationError, answer_not_found)` (Task 4 adds the two guard handlers here); `app.mount("", WSGIMiddleware(flask_app))` LAST; `flask_app.url_build_error_handlers.append(_migrated_endpoint_resolver(app))`.
  - `answer_not_found(request: Request, exc: Exception) -> PlainTextResponse` → `PlainTextResponse("Not Found", status_code=404)` (§ 5.8.2, call 33).
  - `_migrated_endpoint_resolver(admin_app: FastAPI) -> Callable[[BuildError, str, dict[str, Any]], str | None]`: the Flask-side fallback. Strips `_anchor`, `_method`, `_scheme`, `_external` from `values` (Flask adds them before calling a handler), tries `admin_app.url_path_for(endpoint, **values)`, returns `None` on `NoMatchFound` (Flask then raises the original `BuildError`), else `flask.request.script_root + path`, prefixed with `flask.request.host_url.rstrip("/")` when `_external` was true.
- Produces (in `src/admin/routers/__init__.py`): `ADMIN_ROUTERS: tuple[APIRouter, ...] = ()` with a docstring (migrated routes register here; Task 10 fills it). Package docstring: § 5.1's rules for a router module, in five lines.

Module shape of `tests/admin/test_web.py` (decided):
- `pytestmark = [pytest.mark.admin, pytest.mark.requires_db]`; no `from __future__ import annotations`; no module-level `create_app()`; no private `_auth_session`.
- A module-level `_probe = APIRouter()` with, in part 1 (all unguarded; paths under `/tenant/{tenant_id}/probe/...` to mirror the admin's shape):
  - `GET .../probe/links` name `probe.links` → `json_ok(flask=url_for(request, "auth.tenant_login", tenant_id=tenant_id), router=url_for(request, "probe.links", tenant_id=tenant_id), static=url_for(request, "static", filename="validation.css"))`.
  - `GET .../probe/page` name `probe.page` → `render(request, "base.html", tenant=None, tenant_id=tenant_id)` (every `tenant.` read in `base.html` is behind `{% if tenant ... %}`).
  - `GET .../probe/session` name `probe.session` → `json_ok(email=request.state.session.get("email"))`.
  - `POST .../probe/flash` name `probe.flash` → `flash(request, "from-router", "success")`; `return redirect(url_for(request, "probe.page", tenant_id=tenant_id))`.
  - `GET .../probe/boom` name `probe.boom` → `raise RuntimeError("boom-secret")`.
  - `GET .../probe/item/{item_id}` (`item_id: int`) name `probe.item` → `json_ok(item_id=item_id)`.
- Two Flask routes added to the test's Flask app with `add_url_rule` (endpoint names without dots; Flask reserves the dot for blueprints): `/tenant/<tenant_id>/probe/flashes` (`probe_flashes`) → `jsonify(get_flashed_messages(with_categories=True))`; `/tenant/<tenant_id>/probe/set-flash` (`probe_set_flash`) → `flash("from-flask", "success")` then `redirect(url_for("probe.page", tenant_id=tenant_id))` (this is the Flask-side resolution of a migrated endpoint, § 5.12.4).
- Fixtures: `flask_app` (`admin_test_app()` plus the two routes), `admin_app` (`build_admin_app(flask_app, routers=[_probe])`), `client` (`TestClient(admin_app, raise_server_exceptions=False, follow_redirects=False)`), `flask_client` (`flask_app.test_client()`). The conftest's `asgi_admin_app` is not used here because this module needs its probe router inside the build.
- Cookie hand-over between the two clients, both directions, through two module helpers: `_flask_cookie_to_asgi(flask_client, client)` (`client.cookies.set("session", flask_client.get_cookie("session").value, domain="testserver.local")`) and `_asgi_cookie_to_flask(response, flask_client)` (`flask_client.set_cookie("session", response.cookies["session"])`).

- [ ] **Step 1: Write the failing unit test for the prefix rule**

`tests/unit/test_admin_web_prefix.py` builds a `starlette.requests.Request` from a scope (`{"type": "http", "method": "GET", "path": "/tenant/t1/probe/links", "root_path": root_path, "headers": [(k.encode(), v.encode()) for k, v in headers.items()], "query_string": b"", "scheme": "http", "server": ("testserver", 80)}`):

```python
@pytest.mark.parametrize(("headers", "root_path", "expected"), [
    ({}, "", ""),
    ({}, "/admin", "/admin"),
    ({"x-forwarded-prefix": "/admin"}, "", "/admin"),
    ({"x-forwarded-prefix": "/admin"}, "/admin", "/admin"),
    ({"x-forwarded-prefix": "/admin/"}, "", "/admin"),
    ({"x-script-name": "/x", "x-forwarded-prefix": "/admin"}, "", "/x"),
    ({"x-forwarded-prefix": "https://attacker.example"}, "", ""),
    ({"x-forwarded-prefix": "//attacker.example"}, "/admin", "/admin"),
])
def test_admin_prefix_precedence_and_plain_path_rule(headers, root_path, expected):
    assert admin_prefix(_request(headers, root_path)) == expected

def test_request_url_carries_the_prefix_the_operator_sees():
    assert request_url(_request({"x-forwarded-prefix": "/admin"}, "")) == "http://testserver/admin/tenant/t1/probe/links"
    assert request_url(_request({}, "/admin", path="/admin/tenant/t1/probe/links")) == "http://testserver/admin/tenant/t1/probe/links"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_admin_web_prefix.py -q`
Expected: FAIL at import (`ModuleNotFoundError: No module named 'src.admin.web.templates'`).

- [ ] **Step 3: Write the failing foundation tests (part 1)**

`tests/admin/test_web.py`:

```python
def test_router_reads_the_session_the_flask_client_wrote(client, flask_client):
    admin_auth_session(flask_client, "t1")
    _flask_cookie_to_asgi(flask_client, client)
    assert client.get("/tenant/t1/probe/session").json() == {"success": True, "email": "test@example.com"}

def test_an_unreadable_cookie_is_an_empty_session(client):
    client.cookies.set("session", "garbage", domain="testserver.local")
    response = client.get("/tenant/t1/probe/session")
    assert (response.status_code, response.json()) == (200, {"success": True, "email": None})

def test_flash_set_by_a_router_is_read_by_the_flask_side(client, flask_client):
    response = client.post("/tenant/t1/probe/flash")
    assert (response.status_code, response.headers["location"]) == (302, "/tenant/t1/probe/page")
    _asgi_cookie_to_flask(response, flask_client)
    assert flask_client.get("/tenant/t1/probe/flashes").get_json() == [["success", "from-router"]]

def test_flash_set_by_flask_shows_on_a_router_rendered_page(client, flask_client, flask_app):
    response = flask_client.get("/tenant/t1/probe/set-flash")
    assert (response.status_code, response.headers["Location"]) == (302, "/tenant/t1/probe/page")   # Flask resolved a migrated endpoint
    _flask_cookie_to_asgi(flask_client, client)
    page = client.get("/tenant/t1/probe/page")
    assert page.status_code == 200 and "from-flask" in page.text
    assert session_cookie_payload(flask_app, page).get("_flashes", []) == []   # rendering popped the flash and the cookie was written back

def test_url_for_resolves_both_sides_under_the_request_prefix(client):
    assert client.get("/tenant/t1/probe/links").json() == {"success": True, "flask": "/tenant/t1/login", "router": "/tenant/t1/probe/links", "static": "/static/validation.css"}
    prefixed = client.get("/tenant/t1/probe/links", headers={"X-Forwarded-Prefix": "/admin"}).json()
    assert prefixed == {"success": True, "flask": "/admin/tenant/t1/login", "router": "/admin/tenant/t1/probe/links", "static": "/admin/static/validation.css"}

def test_a_prefix_header_that_is_not_a_plain_path_is_ignored(client):
    links = client.get("/tenant/t1/probe/links", headers={"X-Forwarded-Prefix": "https://attacker.example"}).json()
    assert links["router"] == "/tenant/t1/probe/links"

@pytest.mark.parametrize(("mount", "headers", "prefix"), [("/admin", {}, "/admin"), ("", {}, ""), ("", {"X-Forwarded-Prefix": "/admin"}, "/admin")], ids=["admin-mount", "root-mount", "admin-host"])
def test_the_three_compositions_link_and_redirect_under_their_own_prefix(admin_app, mount, headers, prefix):
    outer = FastAPI(); outer.mount("/admin", admin_app); outer.mount("", admin_app)
    outer_client = TestClient(outer, raise_server_exceptions=False, follow_redirects=False)
    links = outer_client.get(f"{mount}/tenant/t1/probe/links", headers=headers).json()
    assert (links["router"], links["flask"]) == (f"{prefix}/tenant/t1/probe/links", f"{prefix}/tenant/t1/login")
    assert outer_client.post(f"{mount}/tenant/t1/probe/flash", headers=headers).headers["location"] == f"{prefix}/tenant/t1/probe/page"
    assert f'href="{prefix}/static/validation.css"' in outer_client.get(f"{mount}/tenant/t1/probe/page", headers=headers).text   # base.html:18 links through script_name

def test_a_router_written_cookie_carries_the_flask_apps_attributes(client, flask_app):
    morsel = SimpleCookie(client.post("/tenant/t1/probe/flash").headers["set-cookie"])["session"]
    interface = flask_app.session_interface
    assert (morsel["path"], bool(morsel["httponly"]), bool(morsel["secure"]), morsel["samesite"]) == (
        interface.get_cookie_path(flask_app), bool(interface.get_cookie_httponly(flask_app)), bool(interface.get_cookie_secure(flask_app)), interface.get_cookie_samesite(flask_app) or "")

def test_an_unexpected_failure_is_a_plain_500_without_the_exception_text(client):
    response = client.get("/tenant/t1/probe/boom")
    assert response.status_code == 500 and "boom-secret" not in response.text

def test_a_non_integer_path_id_is_404_not_422(client):
    assert client.get("/tenant/t1/probe/item/abc").status_code == 404
    assert client.get("/tenant/t1/probe/item/7").json() == {"success": True, "item_id": 7}
```

- [ ] **Step 4: Run the module to verify it fails for the right reason**

Run: `scripts/run-test.sh --db tests/admin/test_web.py -x -q`
Expected: FAIL at collection (`ModuleNotFoundError: No module named 'src.admin.web.app'`).

- [ ] **Step 5: Implement `session.py`, `templates.py`, `app.py`, `routers/__init__.py`**

Decisions the signatures leave open: the `set-cookie` header value is built with `http.cookies.SimpleCookie` (what Starlette's own `Response.set_cookie` uses); `get_flashed_messages` mirrors Flask's filtering (`category_filter` keeps only listed categories; without `with_categories` it returns the messages alone). `app.py` imports `WSGIMiddleware` from `a2wsgi` (the import leaves `src/app.py` in Task 5).

- [ ] **Step 6: Run both modules to verify they pass**

Run: `uv run pytest tests/unit/test_admin_web_prefix.py -q && scripts/run-test.sh --db tests/admin/test_web.py -q`
Expected: `9 passed` (unit) and `12 passed` (foundation part 1; the compositions case counts three).

- [ ] **Step 7: Format, lint, type-check; stage**

Run: `uv run ruff format src/admin/web src/admin/routers tests/admin/test_web.py tests/unit/test_admin_web_prefix.py && uv run ruff check --fix <the same> && uv run mypy src/admin/web src/admin/routers --config-file=mypy.ini && git add src/admin/web src/admin/routers tests/admin/test_web.py tests/unit/test_admin_web_prefix.py`
Expected: clean.

---

### Task 4: Guard and audit: two cores, two FastAPI wrappers, `UserRepository`

**Files:**
- Modify: `src/admin/utils/helpers.py:291-396` (`_setup_session_reaches`, `require_tenant_access`)
- Modify: `src/admin/utils/audit_decorator.py:93-285` (`_extract_safe_request_data`, `log_admin_action`)
- Create: `src/core/database/repositories/user.py`
- Modify: `src/core/database/repositories/uow.py` (imports; after `SigningKeyUoW`, `:422-437`), `src/core/database/repositories/__init__.py` (import + `__all__` row)
- Create: `src/admin/web/guards.py`, `src/admin/web/audit.py`
- Modify: `src/admin/web/responses.py` (append `refuse_json`, `refuse_form`), `src/admin/web/app.py` (register the two guard handlers)
- Modify: `tests/unit/test_architecture_no_raw_select.py:247` (delete the row `("src/admin/utils/helpers.py", "decorated_function")`)
- Modify: `.admin-raw-session-baseline`
- Test: `tests/admin/test_web.py` (part 2), `tests/integration/test_audit_decorator.py` (9 existing, unchanged), `tests/integration/test_audit_decorator_auth_order.py` (2 existing, unchanged)

**Interfaces:**
- Produces (in `helpers.py`):
  - `@dataclass(frozen=True) class TenantAccess`: `refusal: Literal["login_required", "denied"] | None`; `setup_user: Any = None` (the session's `test_user` when the setup-mode branch granted access, else `None`).
  - `_setup_session_reaches(session_data: Mapping[str, Any], tenant_id: str) -> bool`: the body unchanged except that it reads the mapping it is given, not Flask's `session`.
  - `tenant_access_decision(session_data: Mapping[str, Any], tenant_id: str) -> TenantAccess`: in this order, exactly the decorator's (`helpers.py:355-383`): setup-mode → `TenantAccess(None, session_data["test_user"])`; `"user" not in session_data` → `TenantAccess("login_required")`; `email = _session_email(session_data["user"])`; `is_super_admin(email)` → `TenantAccess(None)`; `with TenantAccessUoW(tenant_id) as uow: member = uow.users.is_active_member(email)` → `TenantAccess(None)` or `TenantAccess("denied")`. No `try`, no logging of the request (the Flask decorator keeps its own debug line and its `try`).
  - `require_tenant_access(api_mode=False)` keeps its signature and answers: the debug log line; `try: access = tenant_access_decision(session, tenant_id) except Exception as e:` → the existing `logger.error` plus `jsonify({"error": "Internal server error"}), 500` / `abort(500)`; then `login_required` → the existing 401 JSON or `redirect(url_for("auth.tenant_login", tenant_id=tenant_id, next=request.url))`; `denied` → the existing 403 JSON or `abort(403)`; `setup_user` not `None` → `g.user = access.setup_user`; `return f(tenant_id, *args, **kwargs)`. The view now runs outside the guard's `try` and outside any guard-held database session; today, for a caller who is not a super admin, it ran inside both (`helpers.py:374-394`), which turned a view's own `abort(400)` into a 500. Listed in Task 12 as Flask-side change 12.
- Produces (in `src/core/database/repositories/user.py`): `class UserRepository`: `__init__(self, session: Session, tenant_id: str)`, `tenant_id` property, `is_active_member(self, email: str) -> bool` → `select(User).filter_by(email=email.lower(), tenant_id=self._tenant_id, is_active=True)` first-or-none, the decorator's predicate moved unchanged (§ 5.8.1, call 32). Exported from `repositories/__init__.py`.
- Produces (in `uow.py`), in the declared style of `SigningKeyUoW`: `class TenantAccessUoW(BaseUoW)` with `users: UserRepository | None` and `_REPOSITORIES = {"users": UserRepository}`; consumers narrow with `assert uow.users is not None`, as `signing_keys.py:58` does.
- Produces (in `audit_decorator.py`):
  - `audit_principal(session_data: Mapping[str, Any]) -> str`: `session_data.get("user", {})` → the dict's `email` or `"unknown"`, a non-dict's `str()` or `"unknown"` (`audit_decorator.py:203-207`, moved).
  - `sanitize_request_data(data: Mapping[str, Any]) -> dict[str, str]`: `_extract_safe_request_data` minus the Flask read: every key that is not `_is_sensitive_field`, value through `_sanitize_value`. `_extract_safe_request_data()` becomes `sanitize_request_data(request.form if request.form else ((request.get_json() or {}) if request.is_json else {}))`.
  - `fold_handled_failure(handled: object | None, success: bool, error_message: str | None) -> tuple[bool, str | None]`: `(False, str(handled))` when `handled is not None`, else unchanged; `_apply_handled_failure` reads `g` and calls it.
  - `record_admin_action(audit_logger: Any, tenant_id: str, operation_name: str, *, user_email: str, method: str, request_data: Mapping[str, str], success: bool, error_message: str | None, extra_details: Mapping[str, Any] | None = None) -> None`: composes `details = {"user": user_email, "action": operation_name, "method": method}`, updates it with `extra_details`, adds `"request_data": dict(request_data)` when `request_data` is non-empty, and calls `audit_logger.log_operation(operation=..., principal_name=user_email, principal_id=user_email, adapter_id="admin_ui", success=..., details=..., error=error_message, tenant_id=tenant_id)` inside the existing `try` / `logger.warning` (a failed audit write never fails the request). `log_admin_action` keeps its signature, its `tenant_id` resolution, its `try`/`except`/`finally`, its `extract_details` call and its `g`-cached logger, and calls `record_admin_action(_get_or_create_audit_logger(tenant_id), tenant_id, operation_name, user_email=audit_principal(session), method=request.method, request_data=_extract_safe_request_data() if request.method == "POST" else {}, success=..., error_message=..., extra_details=...)`.
- Produces (in `src/admin/web/guards.py`):
  - `class AuthRequired(Exception)`: `api_mode: bool`, `tenant_id: str`. `class AccessDenied(Exception)`: `api_mode: bool`.
  - `require_tenant_access(api_mode: bool = False) -> Callable[[Request, str], None]`: returns `def guard(request: Request, tenant_id: str) -> None` (FastAPI injects the path parameter by name): `access = tenant_access_decision(request.state.session, tenant_id)`; `login_required` → `raise AuthRequired(api_mode, tenant_id)`; `denied` → `raise AccessDenied(api_mode)`; else `request.state.user = access.setup_user if access.setup_user is not None else request.state.session.get("user")`. No `try` (§ 5.8.1: an unexpected failure propagates).
  - `answer_auth_required(request: Request, exc: AuthRequired) -> Response`: the guard's JSON bodies keep Flask's shape, `{"error": ...}` with no `success` key (§ 5.8.2, the "Kept" list), so they are not `json_error` calls; return `JSONResponse({"error": "Authentication required"}, status_code=401)` when `exc.api_mode`, else `redirect(url_for(request, "auth.tenant_login", tenant_id=exc.tenant_id, next=request_url(request)))`.
  - `answer_access_denied(request: Request, exc: AccessDenied) -> Response`: `JSONResponse({"error": "Access denied"}, status_code=403)` when `exc.api_mode`, else `PlainTextResponse("Forbidden", status_code=403)`.
  - `build_admin_app` registers both with `add_exception_handler`.
- Produces (in `src/admin/web/audit.py`):
  - `async def form_data(request: Request) -> dict[str, str]`: `{}` unless `request.method == "POST"`; else `{k: v for k, v in (await request.form()).items() if isinstance(v, str)}`; stores the result on `request.state.form_data` before returning it (the audit wrapper reads it there, because a sync wrapper cannot await the body). The one place a migrated route reads a form (§ 5.5.1). JSON bodies are a Phase 3 addition when the first migrated route needs one.
  - `record_admin_action_failure(request: Request, error: object) -> None`: `request.state.admin_action_failure = error` (the `g` marker's twin).
  - `audited(operation_name: str) -> Callable[[F], F]`: `functools.wraps` wrapper that reads `request = kwargs["request"]` and `tenant_id = kwargs["tenant_id"]` (a decorated endpoint declares both; the decorator raises `TypeError` at decoration time when the wrapped signature lacks either, so the mistake is loud at import), runs the endpoint inside the same `try`/`except Exception` (re-raise)/`finally` shape as `log_admin_action`, folds the `request.state` marker through `fold_handled_failure`, and calls `record_admin_action(get_audit_logger("AdminUI", tenant_id), tenant_id, operation_name, user_email=audit_principal(request.state.session), method=request.method, request_data=sanitize_request_data(getattr(request.state, "form_data", {})) if request.method == "POST" else {}, success=..., error_message=...)`. No `extract_details` (nothing in the pilot uses it).
- Produces (in `responses.py`): `refuse_json(request: Request, exc: AdminRefusal) -> JSONResponse` → `record_admin_action_failure(request, exc)`, `json_error(exc.message, exc.status)`; `refuse_form(request: Request, exc: AdminRefusal, back_to: str) -> RedirectResponse` → `flash(request, exc.message, "error")`, `record_admin_action_failure(request, exc)`, `redirect(back_to)`.

Part 2 of `tests/admin/test_web.py` adds to `_probe` (guarded; `tenant` fixture = `TenantFactory()` under `factory_session`; `_audit(factory_session, tenant_id, operation)` → `factory_session.rollback()` then `[(row.success, row.error_message, (row.details or {}).get("request_data")) for row in AuditLogRepository(factory_session, tenant_id).find_by_operation(operation)]`):
  - `GET .../probe/guarded` name `probe.guarded`, `dependencies=[Depends(require_tenant_access())]` → `json_ok()`.
  - `GET .../probe/guarded-json` name `probe.guarded_json`, `api_mode=True` → `json_ok()`.
  - `POST .../probe/audited` name `probe.audited`, guard, `@audited("probe_action")`, `form: dict[str, str] = Depends(form_data)` → `refuse_form(request, AdminInvalidInput("nope"), url_for(request, "probe.page", tenant_id=tenant_id))` when `form.get("name") == "refuse"`, else `json_ok(name=form.get("name"))`.
  - `POST .../probe/audited-json` name `probe.audited_json`, guard `api_mode=True`, `@audited("probe_json_action")` → `refuse_json(request, AdminNotFound("gone"))` when `form.get("name") == "refuse"`, else `json_ok()`.
  - One Flask route `/tenant/<tenant_id>/probe/flask-guarded` (`probe_flask_guarded`), view `require_tenant_access()(lambda tenant_id: "ok")`.

- [ ] **Step 1: Write the failing tests (part 2)**

```python
def test_guard_without_a_session_redirects_to_the_tenant_login_with_next(client):
    response = client.get("/tenant/t1/probe/guarded")
    location = urlsplit(response.headers["location"])
    assert (response.status_code, location.path, parse_qs(location.query)["next"]) == (302, "/tenant/t1/login", ["http://testserver/tenant/t1/probe/guarded"])
    prefixed = urlsplit(client.get("/tenant/t1/probe/guarded", headers={"X-Forwarded-Prefix": "/admin"}).headers["location"])
    assert (prefixed.path, parse_qs(prefixed.query)["next"]) == ("/admin/tenant/t1/login", ["http://testserver/admin/tenant/t1/probe/guarded"])

def test_guard_without_a_session_answers_401_json_under_api_mode(client):
    response = client.get("/tenant/t1/probe/guarded-json")
    assert (response.status_code, response.json()) == (401, {"error": "Authentication required"})

def test_guard_denies_a_user_who_is_not_a_member(client, flask_app, tenant):
    client.cookies.set("session", signed_session_cookie(flask_app, {"user": {"email": "nobody@example.com"}}), domain="testserver.local")
    assert client.get(f"/tenant/{tenant.tenant_id}/probe/guarded").status_code == 403
    response = client.get(f"/tenant/{tenant.tenant_id}/probe/guarded-json")
    assert (response.status_code, response.json()) == (403, {"error": "Access denied"})

def test_guard_allows_an_active_member(client, flask_app, tenant):
    UserFactory(tenant=tenant, email="member@example.com", is_active=True)
    client.cookies.set("session", signed_session_cookie(flask_app, {"user": {"email": "member@example.com"}}), domain="testserver.local")
    assert client.get(f"/tenant/{tenant.tenant_id}/probe/guarded").json() == {"success": True}

@pytest.mark.parametrize("payload_for", [lambda tid: _session_payload(tid), lambda tid: {}, lambda tid: {"user": {"email": "nobody@example.com"}}], ids=["super-admin", "anonymous", "stranger"])
def test_guard_answers_the_same_on_both_carriers(client, flask_client, flask_app, tenant, payload_for):
    payload = payload_for(tenant.tenant_id)
    with flask_client.session_transaction() as sess: sess.update(payload)
    client.cookies.set("session", signed_session_cookie(flask_app, payload), domain="testserver.local")
    flask_answer = flask_client.get(f"/tenant/{tenant.tenant_id}/probe/flask-guarded")
    asgi_answer = client.get(f"/tenant/{tenant.tenant_id}/probe/guarded")
    assert (flask_answer.status_code, urlsplit(flask_answer.headers.get("Location", "")).path) == (asgi_answer.status_code, urlsplit(asgi_answer.headers.get("location", "")).path)

def test_audited_route_writes_one_row_with_the_sanitized_form(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    assert client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "x", "api_key": "secret"}).json() == {"success": True, "name": "x"}
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == [(True, None, {"name": "x"})]

def test_refuse_form_flashes_marks_the_audit_failed_and_redirects(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    response = client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "refuse"})
    assert (response.status_code, response.headers["location"], cookie_flashes(flask_app, response)) == (302, f"/tenant/{tenant.tenant_id}/probe/page", [("error", "nope")])
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == [(False, "nope", {"name": "refuse"})]

def test_refuse_json_answers_the_refusals_status_and_audits_the_failure(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    response = client.post(f"/tenant/{tenant.tenant_id}/probe/audited-json", data={"name": "refuse"})
    assert (response.status_code, response.json()) == (404, {"success": False, "error": "gone"})
    assert _audit(factory_session, tenant.tenant_id, "probe_json_action") == [(False, "gone", {"name": "refuse"})]

def test_an_unauthenticated_request_never_reaches_the_audit(client, tenant, factory_session):
    assert client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "x"}).status_code == 302
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == []
```

- [ ] **Step 2: Run the module to verify the new tests fail for the right reason**

Run: `scripts/run-test.sh --db tests/admin/test_web.py -q`
Expected: part 1 passes; the module fails at import of `src.admin.web.guards` (`ModuleNotFoundError`).

- [ ] **Step 3: Extract the two cores, add `UserRepository` and `TenantAccessUoW`, write `guards.py` and `audit.py`, append the two `refuse_*` helpers, register the two handlers**

Order inside the step: repository and UoW first (`uv run python -c "from src.core.database.repositories.uow import TenantAccessUoW; print('ok')"`), then `helpers.py`, then `audit_decorator.py`, then the two web modules. The module docstring of `helpers.py` gains one paragraph: the decision is one function so the Flask decorator and the FastAPI dependency cannot drift (§ 5.8.1); `audit_decorator.py`'s docstring keeps its DECORATOR ORDER block and adds that the FastAPI side gets the order structurally.

- [ ] **Step 4: Run the foundation module and the two existing decorator modules**

Run: `scripts/run-test.sh --db tests/admin/test_web.py -q && scripts/run-test.sh --db tests/integration/test_audit_decorator.py -q && scripts/run-test.sh --db tests/integration/test_audit_decorator_auth_order.py -q`
Expected: `23 passed` (12 + 11; the both-carriers case counts three); `9 passed`; `2 passed`. The Flask-side modules pass unchanged: that is what "the decorators behave as before" means.

- [ ] **Step 5: Remove the stale raw-select row and lower the raw-session ratchet by the one call the guard no longer makes**

Run: `uv run pytest tests/unit/test_architecture_no_raw_select.py -q`
Expected: before the removal the stale-entry test fails naming `("src/admin/utils/helpers.py", "decorated_function")`; delete that row (line 247) and lower the count in `test_violation_count_matches` by one (the test's own message names the number); after it, all three tests pass.
Run: `uv run pytest tests/unit/test_architecture_ratchet_enforcement.py -q`
Expected: the slack check fails naming the measured counts; set `admin_get_db_session` in `.admin-raw-session-baseline` to the printed value (expected `185`; the counter decides) and re-run until it passes.

- [ ] **Step 6: Format, lint, type-check; stage**

Run: `uv run ruff format src/admin/utils/helpers.py src/admin/utils/audit_decorator.py src/admin/web src/core/database/repositories/user.py src/core/database/repositories/uow.py src/core/database/repositories/__init__.py tests/admin/test_web.py && uv run ruff check --fix <the same> && uv run mypy src/admin/utils/helpers.py src/admin/utils/audit_decorator.py src/admin/web src/core/database/repositories/user.py src/core/database/repositories/uow.py --config-file=mypy.ini && git add <the same> tests/unit/test_architecture_no_raw_select.py .admin-raw-session-baseline`
Expected: clean.

---

### Task 5: Mount the sub-application; commit the foundation; first CI read

**Files:**
- Modify: `src/app.py:61-87` (`_install_admin_mounts`), `:593-594` (`admin_app = build_admin_app(flask_admin_app)` replaces `admin_wsgi = WSGIMiddleware(flask_admin_app)`; the `a2wsgi` import goes)
- Modify: `tests/unit/test_fastapi_app_regression.py:238-272` (`TestAdminCompatibilityMount`)

**Interfaces:**
- Produces: `src.app.admin_app: FastAPI`, built once at import next to `flask_admin_app`. `_install_admin_mounts()` drops every `Mount` whose `.app is admin_app`, then `app.mount("/admin", admin_app)` and `app.mount("/", admin_app)` (Starlette stores the second as path `""`); the two `type: ignore` comments go with the WSGI object. Unchanged: the `/a2a/` carve-out (`:397-401`), `AuthChallengeResponder` (`:587`), the lifespan call (`:93`).

- [ ] **Step 1: Update the regression test first**

In `test_fastapi_app_regression.py::TestAdminCompatibilityMount::test_fastapi_mounts_admin_at_admin_and_root`, import `admin_app` next to `_install_admin_mounts, app` and replace `route.app.__class__.__name__ == "WSGIMiddleware"` with `route.app is admin_app`; every path assertion stays; the two login-path tests stay as they are (the Flask fallback inside the sub-application answers them).

Run: `uv run pytest tests/unit/test_fastapi_app_regression.py -k TestAdminCompatibilityMount -q`
Expected: FAIL (`ImportError: cannot import name 'admin_app' from 'src.app'`).

- [ ] **Step 2: Wire `src/app.py`**

Run: `uv run pytest tests/unit/test_fastapi_app_regression.py -q && uv run python -c "import src.app; print(len(src.app.app.routes))"`
Expected: the whole module passes; the import prints a route count.

- [ ] **Step 3: Format, lint, type-check; commit 2**

```bash
uv run ruff format src/app.py tests/unit/test_fastapi_app_regression.py && uv run ruff check --fix src/app.py tests/unit/test_fastapi_app_regression.py && uv run mypy src/app.py --config-file=mypy.ini
git add src/app.py tests/unit/test_fastapi_app_regression.py
git commit -m "refactor(admin): add the ASGI admin foundation" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
Expected: commit-stage hooks pass (ast-grep, ruff, mypy, route conflicts, response-attribute). The commit holds everything Tasks 1–5 staged.

- [ ] **Step 4: Push and read CI (the procedure Task 11 repeats)**

Run: `git push origin refactor/admin-convention-pilot`, then `gh run list --repo v-n7k/salesagent --branch refactor/admin-convention-pilot --limit 3`, then `gh run view <run-id> --repo v-n7k/salesagent --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'`.
Expected: `Quality Gate`, `Type Check`, `Unit Tests`, `Admin UI Tests`, `Integration (*)` green except as classified below. For a red job: `gh api --allow-escape-sequences repos/v-n7k/salesagent/actions/jobs/<job-id>/logs | grep -nE "FAILED|Error|R0801|baseline|fixed|exceeded|slack" | head -60`.

Classify every red job before touching anything:
- Caused by this branch (a test it wrote or changed, a guard naming its file, a ratchet above baseline): fix in place, commit `fix(admin): ...`, push, re-read. If the Quality Gate prints lower duplication counts (`fixed` lines), set `.duplication-baseline` to the printed values in that fix commit (the slack check in `tests/quality/test_ratchets_slow.py` needs an exact match); if `src` or `tests` rose, a new duplicate block was introduced: fold it, never raise the number.
- `Integration (<group>)` red on `tests/integration/test_media_buy_*` with a calendar date in the traceback: upstream [#2494](https://github.com/prebid/salesagent/issues/2494); **stop and ask the user** whether to `git merge --no-ff 6f2ac1e76da7b5bff36d316d9869235e2a211b02` (the open fix PR [#2495](https://github.com/prebid/salesagent/pull/2495)); merge only on their yes (§ 9).
- The four image-pulling jobs red with an image-pull error: Task 0 Step 1's answer decides (re-run after the publish, or outside the gate).
- A job that needs a secret the fork does not hold, or an unrelated guard: **report to the user as a blocker**; never deselect or skip a test (§ 4.2).

---

### Task 6: Form models

**Files:**
- Create: `src/admin/forms/__init__.py` (docstring only: the package holds the accepted input shape of every admin write route)
- Create: `src/admin/forms/_base.py`
- Create: `src/admin/forms/agents.py`
- Test: `tests/unit/test_admin_forms_agents.py`

**Interfaces:**
- Consumes: `AdminInvalidInput` (Task 1).
- Produces:
  - `class FormModel(BaseModel)` with `model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)`.
  - `parse_form(model: type[FormT], data: Mapping[str, Any]) -> FormT`: drops every key whose value is a string that is blank after stripping (so blank == absent), then `model.model_validate(...)`; on `pydantic.ValidationError` raises `AdminInvalidInput(message)` built from the FIRST error only: type `missing` → `f"{title} is required"`, anything else → `f"{title}: {error['msg']}"`, where `title` is `model.model_fields[name].title` (`name` is `error["loc"][0]`).
  - `class AgentFormBase(FormModel)`: `agent_url: str = Field(title="Agent URL")`, `name: str = Field(title="Agent name")`, `enabled: bool = Field(default=False, title="Enabled")`, `auth_type: str | None = Field(default=None, title="Auth type")`, `auth_credentials: str | None = Field(default=None, title="Auth credentials")`.
  - `class CreativeAgentForm(AgentFormBase)`: `priority: int = Field(default=10, title="Priority")`.
  - `class SignalsAgentForm(AgentFormBase)`: `auth_header: str | None = Field(default=None, title="Auth header")`, `forward_promoted_offering: bool = Field(default=False, title="Forward promoted offering")`, `timeout: int = Field(default=30, title="Timeout")`.
  - Field order matters: `agent_url` first, `name` second, so a form missing both reports the URL (today's order). pydantic's lax mode parses `"on"` → `True` and `"10"` → `10`; no custom validator.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_admin_forms_agents.py`:

```python
URL = "https://1.1.1.1/mcp"

def test_blank_url_is_required():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(CreativeAgentForm, {"agent_url": "   ", "name": "n"})
    assert refused.value.message == "Agent URL is required"

def test_missing_name_is_required():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(SignalsAgentForm, {"agent_url": URL})
    assert refused.value.message == "Agent name is required"

def test_first_error_wins_in_declaration_order():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(CreativeAgentForm, {})
    assert refused.value.message == "Agent URL is required"

def test_checkbox_defaults_trimming_and_unknown_fields():
    form = parse_form(CreativeAgentForm, {"agent_url": f" {URL} ", "name": "  Spaced  ", "enabled": "on", "csrf_token": "x"})
    assert (form.agent_url, form.name, form.enabled, form.priority, form.auth_type, form.auth_credentials) == (URL, "Spaced", True, 10, None, None)

def test_signals_defaults_when_only_the_required_fields_are_posted():
    form = parse_form(SignalsAgentForm, {"agent_url": URL, "name": "n"})
    assert (form.enabled, form.forward_promoted_offering, form.timeout, form.auth_header) == (False, False, 30, None)

def test_non_integer_number_names_the_field():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(SignalsAgentForm, {"agent_url": URL, "name": "n", "timeout": "abc"})
    assert refused.value.message == "Timeout: Input should be a valid integer, unable to parse string as an integer"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_admin_forms_agents.py -q`
Expected: FAIL at import (`ModuleNotFoundError: No module named 'src.admin.forms'`).

- [ ] **Step 3: Implement the three modules**

`_base.py` imports `BaseModel`, `ConfigDict`, `Field`, `ValidationError` from `pydantic` and `AdminInvalidInput` from `src.admin.errors`; nothing from `flask`, `fastapi` or `starlette` (§ 5.3.1). `agents.py` holds the three models and nothing else.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_admin_forms_agents.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Format, lint; stage (commit 3 is Task 11)**

Run: `uv run ruff format src/admin/forms tests/unit/test_admin_forms_agents.py && uv run ruff check src/admin/forms tests/unit/test_admin_forms_agents.py && git add src/admin/forms tests/unit/test_admin_forms_agents.py`
Expected: no diagnostics.

---

### Task 7: The pilot's route test module (RED)

**Files:**
- Create: `tests/admin/test_agents.py`

**Interfaces:**
- Consumes: `asgi_admin_app`, `asgi_admin_client`, `factory_session` (conftest; Task 2), `asgi_auth_session`, `cookie_flashes` (Task 2), `AgentUoW` and the repositories' `list_all()` (Task 8, so the module does not import until then), `ProbeResult` (`src/core/utils/operator_mcp.py`), `inject_limits(monkeypatch, adcp_outbound_allow_private=...)` from `tests/helpers/settings_injection.py`, `UNDIALLED_PUBLIC_HTTPS_ORIGIN` from `tests/helpers/egress_hatches.py`, `AuditLogRepository(session, tenant_id).find_by_operation(name)`, factories `TenantFactory`, `CreativeAgentFactory`, `SignalsAgentFactory`.
- Produces: the pilot's acceptance tests; nothing else imports this module.

Module shape (decided):
- `pytestmark = [pytest.mark.admin, pytest.mark.requires_db]`; no module-level `create_app()`; no private `_auth_session`; no `from __future__ import annotations` needed (no endpoint is defined here).
- Constants: `AGENT_URL = f"{UNDIALLED_PUBLIC_HTTPS_ORIGIN}/mcp"`, `BLOCKED_URL = "https://169.254.169.254/agent"`, `EGRESS_SENTENCE = "Agent URL is not allowed by outbound egress policy."`, `SUCCESS_MESSAGE = "Connected to Optable, 42 formats available"`, `FAILURE_MESSAGE = "Connection failed: handshake rejected by the endpoint"`, `SAMPLE_FORMATS = ("display_300x250_image", "video_16x9_15s", "audio_30s")`.
- A frozen dataclass `_Case` with: `label` (`"Creative"`/`"Signals"`), `key` (`"creative"`/`"signals"`), `prefix` (`"creative-agents"`/`"signals-agents"`), `factory`, `repository` (`"creative_agents"`/`"signals_agents"`, the `AgentUoW` attribute), `probe_target` (`"src.core.creative_agent_registry.CreativeAgentRegistry.probe_agent"` / `"src.core.signals_agent_registry.SignalsAgentRegistry.probe_agent"`), `number_field` (`"priority"`/`"timeout"`), `kind_fields` (`(("priority", 10),)` / `(("forward_promoted_offering", False),)`: the column only this kind has, holding the value the form stores when the field is not posted), `probe_success_body` (creative `{"success": True, "message": SUCCESS_MESSAGE, "format_count": 42, "sample_formats": list(SAMPLE_FORMATS)}`; signals `{"success": True, "message": SUCCESS_MESSAGE, "signal_count": 37}`), `probe_no_count_body` (creative `{..., "format_count": None, "sample_formats": []}`; signals `{..., "signal_count": None}`), `probe_success_result` / `probe_no_count_result` (creative `ProbeResult(ok=True, message=SUCCESS_MESSAGE, count=42, samples=SAMPLE_FORMATS)`; signals `count=37`, no samples).
- Fixtures: `case` (`params=[CREATIVE_CASE, SIGNALS_CASE], ids=["creative", "signals"]`), `tenant` (`TenantFactory()` under `factory_session`), `flask_app` (`asgi_admin_app.state.flask_app`), `client` (`asgi_auth_session(asgi_admin_client, flask_app, tenant.tenant_id)`; returns `asgi_admin_client`), `agent` (`case.factory(tenant=tenant, agent_url=AGENT_URL, auth_credentials="secret-1", auth_header="x-api-key", timeout=45)`).
- Helpers: `_answer(flask_app, response)` → `(response.status_code, response.headers.get("location", ""), cookie_flashes(flask_app, response))`; `_rows(case, tenant_id)` → `with AgentUoW(tenant_id) as uow:` read `getattr(uow, case.repository).list_all()` inside the block into plain tuples `(name, enabled, auth_type, auth_credentials, auth_header, timeout, tuple((k, getattr(row, k)) for k, _ in case.kind_fields))` (the last element equals `case.kind_fields` whenever the kind-specific column holds its form default); `_audit(factory_session, tenant_id, operation)` → `factory_session.rollback()` then `[(row.success, row.error_message) for row in AuditLogRepository(factory_session, tenant_id).find_by_operation(operation)]`; `_probe(case, result_or_exc)` → one `patch(case.probe_target, new=AsyncMock(return_value=... | side_effect=...))` context manager (the module's only `patch(` call site; under the 10-mock ceiling).

- [ ] **Step 1: Write the tests**

Parametrised over `case` unless noted; `P = f"/tenant/{tenant.tenant_id}/{case.prefix}"` is written out in each test:

```python
def test_list_page_shows_the_seeded_agent(client, case, tenant, agent):
    response = client.get(f"/tenant/{tenant.tenant_id}/{case.prefix}/")
    assert response.status_code == 200 and agent.name in response.text

def test_add_form_renders(client, case, tenant):
    assert client.get(f"/tenant/{tenant.tenant_id}/{case.prefix}/add").status_code == 200

def test_add_stores_the_row_with_typed_defaults(client, flask_app, case, tenant, factory_session):
    response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
                           data={"agent_url": AGENT_URL, "name": "  Spaced  ", "enabled": "on", "csrf_token": "x"})
    status, location, flashed = _answer(flask_app, response)
    assert (status, location, flashed) == (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/", [("success", f"{case.label} agent 'Spaced' added successfully")])
    assert _rows(case, tenant.tenant_id) == [("Spaced", True, None, None, None, 30, case.kind_fields)]
    assert _audit(factory_session, tenant.tenant_id, f"add_{case.key}_agent") == [(True, None)]

def test_add_without_a_name_is_refused(client, flask_app, case, tenant):
    status, location, flashed = _answer(flask_app, client.post(f".../{case.prefix}/add", data={"agent_url": AGENT_URL}))
    assert (status, location, flashed) == (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/add", [("error", "Agent name is required")])
    assert _rows(case, tenant.tenant_id) == []

def test_add_with_a_blank_url_is_refused(client, flask_app, case, tenant):          # behavior change 9 for creative
    ... data={"agent_url": "  ", "name": "x"} → flashed == [("error", "Agent URL is required")], no row

def test_add_with_a_non_integer_number_is_refused(client, flask_app, case, tenant):
    ... data={"agent_url": AGENT_URL, "name": "x", case.number_field: "abc"}
    → flashed == [("error", f"{case.number_field.capitalize()}: Input should be a valid integer, unable to parse string as an integer")], no row

def test_add_refuses_a_url_egress_policy_blocks_and_audits_the_refusal(client, flask_app, case, tenant, monkeypatch, factory_session):
    inject_limits(monkeypatch, adcp_outbound_allow_private=False)
    status, location, flashed = _answer(flask_app, client.post(f".../{case.prefix}/add", data={"agent_url": BLOCKED_URL, "name": "x"}))
    assert (status, location, flashed) == (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/add", [("error", EGRESS_SENTENCE)])
    assert _rows(case, tenant.tenant_id) == []
    assert _audit(factory_session, tenant.tenant_id, f"add_{case.key}_agent") == [(False, EGRESS_SENTENCE)]

def test_edit_updates_the_row_and_keeps_blank_credentials(client, flask_app, case, tenant, agent):
    data = {"agent_url": AGENT_URL, "name": "Renamed", "enabled": "on", "auth_type": "bearer", "auth_credentials": ""}
    if case.key == "signals": data |= {"auth_header": "x-api-key", "timeout": "45"}
    status, location, flashed = _answer(flask_app, client.post(f".../{case.prefix}/{agent.id}/edit", data=data))
    assert (status, location, flashed) == (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/", [("success", f"{case.label} agent 'Renamed' updated successfully")])
    assert _rows(case, tenant.tenant_id) == [("Renamed", True, "bearer", "secret-1", "x-api-key", 45, case.kind_fields)]
    # creative: auth_header "x-api-key" and timeout 45 come from the fixture and survive an edit whose form has no
    # such fields (§ 5.5.1); priority stays at the form default 10. signals: both values come from the form.

def test_edit_unchecks_a_checkbox_when_the_field_is_absent(client, flask_app, case, tenant, agent):
    ... data={"agent_url": AGENT_URL, "name": agent.name}
    → [(row[1], row[6]) for row in _rows(case, tenant.tenant_id)] == [(False, case.kind_fields)]   # enabled False; signals also stores forward_promoted_offering False

def test_edit_of_an_unknown_id_redirects_to_the_list(client, flask_app, case, tenant, agent):
    ... POST f".../{case.prefix}/{agent.id + 9999}/edit" → (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/", [("error", f"{case.label} agent not found")])

def test_delete_removes_the_row_and_audits(client, case, tenant, agent, factory_session):
    response = client.delete(f".../{case.prefix}/{agent.id}/delete")
    assert (response.status_code, response.json()) == (200, {"success": True, "message": f"{case.label} agent '{agent.name}' deleted successfully"})
    assert _rows(case, tenant.tenant_id) == []
    assert _audit(factory_session, tenant.tenant_id, f"delete_{case.key}_agent") == [(True, None)]

def test_delete_of_an_unknown_id_is_404_and_audits_as_a_failure(client, case, tenant, agent, factory_session):
    response = client.delete(f".../{case.prefix}/{agent.id + 9999}/delete")
    assert (response.status_code, response.json()) == (404, {"success": False, "error": f"{case.label} agent not found"})
    assert _audit(factory_session, tenant.tenant_id, f"delete_{case.key}_agent") == [(False, f"{case.label} agent not found")]

def test_delete_cannot_reach_another_tenants_agent(client, case, tenant):
    other = case.factory(tenant=TenantFactory(), agent_url=AGENT_URL)
    response = client.delete(f"/tenant/{tenant.tenant_id}/{case.prefix}/{other.id}/delete")
    assert (response.status_code, response.json()) == (404, {"success": False, "error": f"{case.label} agent not found"})
    assert [row[0] for row in _rows(case, other.tenant_id)] == [other.name]

def test_probe_success_projects_every_field_onto_the_template_keys(client, case, tenant, agent):
    with _probe(case, case.probe_success_result):
        response = client.post(f".../{case.prefix}/{agent.id}/test")
    assert (response.status_code, response.json()) == (200, case.probe_success_body)

def test_probe_failure_puts_the_sentence_under_error(client, case, tenant, agent):
    with _probe(case, ProbeResult(ok=False, message=FAILURE_MESSAGE)): ...
    assert (response.status_code, response.json()) == (400, {"success": False, "error": FAILURE_MESSAGE})

def test_probe_success_without_a_count_stays_null_on_the_wire(client, case, tenant, agent):
    with _probe(case, case.probe_no_count_result): ...
    assert (response.status_code, response.json()) == (200, case.probe_no_count_body)

def test_probe_of_an_unknown_id_is_404(client, case, tenant, agent):       # behavior change 2
    ... → (404, {"success": False, "error": f"{case.label} agent not found"})

def test_probe_refuses_a_stored_url_egress_policy_blocks_without_dialing(client, case, tenant, monkeypatch):
    blocked = case.factory(tenant=tenant, agent_url=BLOCKED_URL)
    inject_limits(monkeypatch, adcp_outbound_allow_private=False)
    with _probe(case, case.probe_success_result) as probe:
        response = client.post(f".../{case.prefix}/{blocked.id}/test")
    assert (response.status_code, response.json(), probe.await_count) == (400, {"success": False, "error": EGRESS_SENTENCE}, 0)

def test_probe_crash_is_a_plain_500_without_the_exception_text(client, case, tenant, agent):   # behavior change 3
    with _probe(case, RuntimeError("boom-secret")):            # AsyncMock(side_effect=...)
        response = client.post(f".../{case.prefix}/{agent.id}/test")
    assert response.status_code == 500 and "boom-secret" not in response.text

def test_a_non_integer_agent_id_is_404(client, case, tenant):                # § 5.8.2, call 33
    assert client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/abc/test").status_code == 404

# Not parametrised: the guard is not the pilot's subject, so once each (creative prefix), on the anonymous client.
def test_unauthenticated_html_request_redirects_to_login(asgi_admin_client, tenant):
    response = asgi_admin_client.get(f"/tenant/{tenant.tenant_id}/creative-agents/")
    assert (response.status_code, urlsplit(response.headers["location"]).path) == (302, f"/tenant/{tenant.tenant_id}/login")

def test_unauthenticated_json_request_gets_401_json(asgi_admin_client, tenant):    # behavior change 7; the guard answers before any row lookup
    response = asgi_admin_client.delete(f"/tenant/{tenant.tenant_id}/creative-agents/1/delete")
    assert (response.status_code, response.json()) == (401, {"error": "Authentication required"})
```

The eight assertions of `tests/admin/test_agent_probe_routes.py` are the four `test_probe_*` cases above × two kinds (§ 5.9.8); the 404 body gains `"success": false` (§ 6.4 item 2).

- [ ] **Step 2: Run the module to verify it fails for the right reason**

Run: `scripts/run-test.sh --db tests/admin/test_agents.py -x -q`
Expected: FAIL at collection with `ImportError: cannot import name 'AgentUoW' from 'src.core.database.repositories.uow'` (the module's only import that does not exist yet). Stage the file; it is committed with Task 11.

---

### Task 8: Repository base and `AgentUoW`

**Files:**
- Modify: `src/core/database/repositories/agent.py` (whole file)
- Modify: `src/core/database/repositories/uow.py` (imports; after `TenantAccessUoW` from Task 4)

**Interfaces:**
- Produces (in `agent.py`):
  - `AgentRow = TypeVar("AgentRow", CreativeAgent, SignalsAgent)`
  - `class _AgentRepository(Generic[AgentRow])`: `__init__(self, session: Session, tenant_id: str)`, `tenant_id` property, class attributes each subclass sets: `_model: ClassVar[type]` and `_ordering: ClassVar[tuple[Any, ...]]`; methods `get_enabled(self) -> list[AgentRow]` (the two existing bodies become one: `enabled.is_(True)`, ordered by `_ordering`), `list_all(self) -> list[AgentRow]` (the tenant's rows, ordered by `_ordering`), `get(self, agent_id: int) -> AgentRow | None` (`filter_by(id=agent_id, tenant_id=...)`), `add(self, row: AgentRow) -> AgentRow` (`session.add(row)`, `session.flush()`, return the row with its id), `delete(self, row: AgentRow) -> None` (`session.delete(row)`).
  - `class CreativeAgentRepository(_AgentRepository[CreativeAgent])`: `_model = CreativeAgent`, `_ordering = (CreativeAgent.priority, CreativeAgent.name)`.
  - `class SignalsAgentRepository(_AgentRepository[SignalsAgent])`: `_model = SignalsAgent`, `_ordering = (SignalsAgent.name,)`.
  - Every query keeps `tenant_id == self._tenant_id` in the WHERE clause (§ 5.4.3). `select()` stays inside this module (the raw-select guard permits repositories).
- Produces (in `uow.py`), in the declared style of `SigningKeyUoW`:
  ```python
  class AgentUoW(BaseUoW):
      tenant_config: TenantConfigRepository | None
      creative_agents: CreativeAgentRepository | None
      signals_agents: SignalsAgentRepository | None
      _REPOSITORIES: ClassVar[Mapping[str, type]] = {
          "tenant_config": TenantConfigRepository,
          "creative_agents": CreativeAgentRepository,
          "signals_agents": SignalsAgentRepository,
      }
  ```
  with a docstring saying `tenant_config` is there because every admin page renders `tenant` (§ 5.2.3). Consumers narrow with `assert uow.<repo> is not None`, as `signing_keys.py:58` does.

- [ ] **Step 1: Implement the repository base and the UoW**

The module docstring of `agent.py` keeps its history paragraph and adds one sentence: the admin surface reaches these rows through the same repositories, so the ten raw selects the two blueprints carried are gone. The existing callers of `get_enabled()` (the two registries and the admin format search) are untouched: the method's name, signature and ordering are unchanged.

- [ ] **Step 2: Verify the existing callers still import and the RED module advances**

Run: `uv run python -c "from src.core.database.repositories.uow import AgentUoW; from src.core.creative_agent_registry import CreativeAgentRegistry; from src.core.signals_agent_registry import SignalsAgentRegistry; print('ok')"`
Expected: `ok`.
Run: `scripts/run-test.sh --db tests/admin/test_agents.py -q`
Expected: the module now collects. The sub-application has no agent routers yet, so every request falls through to the OLD Flask routes, which are still registered. What the § 6.4 "Kept" list covers passes against them (list page, add form, missing name, edit of a known and an unknown id, delete success body, probe success / failure / null count, the HTML login redirect); the failures are the behavior changes, at least: `test_add_with_a_blank_url_is_refused[creative]`, `test_add_with_a_non_integer_number_is_refused`, `test_add_refuses_a_url_egress_policy_blocks_and_audits_the_refusal` (no audit row today), `test_delete_removes_the_row_and_audits`, `test_delete_of_an_unknown_id_is_404_and_audits_as_a_failure` and `test_delete_cannot_reach_another_tenants_agent` (today's 404 body has no `success` key), `test_probe_of_an_unknown_id_is_404`, `test_probe_refuses_a_stored_url_egress_policy_blocks_without_dialing[creative]`, `test_probe_crash_is_a_plain_500_without_the_exception_text`, `test_unauthenticated_json_request_gets_401_json`. A failure on kept behavior is a defect in the test module; fix it now.

- [ ] **Step 3: Format, lint, type-check; stage**

Run: `uv run ruff format src/core/database/repositories/agent.py src/core/database/repositories/uow.py && uv run ruff check src/core/database/repositories/agent.py src/core/database/repositories/uow.py && uv run mypy src/core/database/repositories/agent.py src/core/database/repositories/uow.py --config-file=mypy.ini && git add src/core/database/repositories/agent.py src/core/database/repositories/uow.py`
Expected: clean.

---

### Task 9: The agent service and the Flask-free egress helper

**Files:**
- Modify: `src/admin/utils/url_policy.py` (append one function after `_is_allowed`)
- Create: `src/admin/services/agents.py`

**Interfaces:**
- Consumes: `AgentUoW`, the repositories (Task 8); `AgentFormBase`, `CreativeAgentForm`, `SignalsAgentForm` (Task 6); `AdminNotFound`, `AdminInvalidInput` (Task 1); `ProbeResult`; `CreativeAgentRegistry` / `SignalsAgentRegistry` (imported at module level; `format_search.py` already imports the creative registry at module level, so there is no cycle).
- Produces:
  - `url_policy.raise_if_url_blocked(url: Any, label: str) -> None`: `if not _is_allowed(url, label): raise AdminInvalidInput(_REJECTION_MESSAGE.format(label=label))`. The two existing helpers are untouched (§ 5.5.3).
  - ```python
    @dataclass(frozen=True)
    class AgentKind:
        key: str                      # "creative" | "signals"
        label: str                    # "Creative" | "Signals"
        repository: str               # AgentUoW attribute name
        model: type[CreativeAgent] | type[SignalsAgent]
        form: type[AgentFormBase]
        registry: Callable[[], Any]   # the registry CLASS; instantiated per probe so a test can patch probe_agent on it
        probe_fields: Callable[[ProbeResult], dict[str, Any]]
    CREATIVE: AgentKind   # probe_fields → {"message": p.message, "format_count": p.count, "sample_formats": list(p.samples)}
    SIGNALS: AgentKind    # probe_fields → {"message": p.message, "signal_count": p.count}
    def create_agent(tenant_id: str, kind: AgentKind, form: AgentFormBase) -> str   # returns the stored name
    def update_agent(tenant_id: str, kind: AgentKind, agent_id: int, form: AgentFormBase) -> str
    def delete_agent(tenant_id: str, kind: AgentKind, agent_id: int) -> str
    def probe_agent(tenant_id: str, kind: AgentKind, agent_id: int) -> ProbeResult
    ```
  - Rules every function follows (§ 5.3): first parameter `tenant_id`; exactly one `with AgentUoW(tenant_id) as uow:` per call; the repository is `getattr(uow, kind.repository)`; a missing row raises `AdminNotFound(f"{kind.label} agent not found")`; no `flask`, `fastapi` or `starlette` import; no `except`.
  - `create_agent`: `raise_if_url_blocked(form.agent_url, "Agent URL")`, then `repo.add(kind.model(tenant_id=tenant_id, **_fields(form)))`, where `_fields(form)` is `{name: getattr(form, name) for name in type(form).model_fields}` (attribute reads, not `model_dump`, which the serialization guard bans outside the edge modules).
  - `update_agent`: `row = repo.get(agent_id)` (404 first), `raise_if_url_blocked(...)`, then `setattr` every form field onto the row except `auth_credentials` when the form's value is `None` (a blank credential keeps the stored one; § 6.3). A creative form carries no `auth_header` / `timeout`, so those columns are never touched (§ 5.5.1).
  - `delete_agent`: `row = repo.get(agent_id)`, `repo.delete(row)`, return `row.name`.
  - `probe_agent`: `row = repo.get(agent_id)`, `raise_if_url_blocked(row.agent_url, "Agent URL")` (both kinds; § 6.4 item 4), then `return asyncio.run(kind.registry().probe_agent(row))` inside the block. Name the local `probe`, never `result`.

- [ ] **Step 1: Implement `raise_if_url_blocked` and the service module**

The service's module docstring states § 5.3 in three sentences and that the kind record is "data, not code": two routers, one function per operation.

- [ ] **Step 2: Verify the service imports and the kind records resolve**

Run: `uv run python -c "from src.admin.services.agents import CREATIVE, SIGNALS, create_agent, update_agent, delete_agent, probe_agent; from src.admin.utils.url_policy import raise_if_url_blocked; print(CREATIVE.label, SIGNALS.label)"`
Expected: `Creative Signals`. Leave `src/admin/services/__init__.py` untouched (it exports `DashboardService` only); the router imports the service by module path.

- [ ] **Step 3: Format, lint, type-check; stage**

Run: `uv run ruff format src/admin/services/agents.py src/admin/utils/url_policy.py && uv run ruff check src/admin/services/agents.py src/admin/utils/url_policy.py && uv run mypy src/admin/services/agents.py src/admin/utils/url_policy.py --config-file=mypy.ini && git add src/admin/services/agents.py src/admin/utils/url_policy.py`
Expected: clean.

---

### Task 10: The router module (GREEN), the deletions, the re-pointed ingest cases

**Files:**
- Create: `src/admin/routers/agents.py`
- Modify: `src/admin/routers/__init__.py` (`ADMIN_ROUTERS = (creative_agents, signals_agents)`)
- Delete: `src/admin/blueprints/creative_agents.py`, `src/admin/blueprints/signals_agents.py`, `tests/admin/test_agent_probe_routes.py`
- Modify: `src/admin/app.py:18`, `:33` (the two imports) and `:310-311` (the two `register_blueprint` lines): deleted
- Modify: `tests/integration/test_admin_ingest_url_policy.py` (the eight agent cases at lines 161, 182, 201, 227, 253, 818, 830, 843; the module docstring's "These cases drive the actual Flask routes" sentence)
- Test: `tests/admin/test_agents.py` (Task 7)

**Interfaces:**
- Consumes: everything Tasks 1, 3, 4, 6, 8, 9 produce: `require_tenant_access` (`src.admin.web.guards`), `audited`, `form_data` (`src.admin.web.audit`), `render`, `url_for` (`src.admin.web.templates`), `flash` (`src.admin.web.session`), `json_ok`, `json_error`, `redirect`, `refuse_form`, `refuse_json` (`src.admin.web.responses`), `parse_form`, the service functions and kinds.
- Produces: `creative_agents = APIRouter(prefix="/tenant/{tenant_id}/creative-agents")` and `signals_agents = APIRouter(prefix="/tenant/{tenant_id}/signals-agents")`; the ten endpoint functions keep today's names (`list_creative_agents`, `add_creative_agent`, `edit_creative_agent`, `delete_creative_agent`, `test_creative_agent`, and the signals five) and each route decorator carries `name="<blueprint>.<function>"`, so every route name is unchanged (§ 5.2.6).
- The templates' JavaScript is the JSON contract: `templates/creative_agents.html:197-223` reads `data.success`, `data.format_count`, `data.sample_formats.join(...)` (so `sample_formats` is always a list, `[]` when the probe returns none) and `data.error`; `templates/signals_agents.html:179-205` reads `data.success`, `data.signal_count`, `data.message`, `data.error`; both delete handlers branch on `response.ok` and read `err.error` otherwise. The fetch URLs are built from `{{ script_name }}`, which `render` supplies.

Module shape (decided):
- No `from __future__ import annotations` (Global Constraints).
- A frozen dataclass `_Pages`: `kind: AgentKind`, `list_template: str`, `form_template: str`, `list_endpoint: str`, `add_endpoint: str`, `edit_endpoint: str`, `row_fields: tuple[str, ...]` (the list page's per-row keys besides `id`, `has_auth`, `created_at`: creative `("agent_url", "name", "enabled", "priority", "auth_type")`, signals `("agent_url", "name", "enabled", "auth_type", "forward_promoted_offering", "timeout")`), `form_fields: tuple[str, ...]` (the edit form's `agent` dict keys besides `id`: creative `("agent_url", "name", "enabled", "priority", "auth_type", "auth_credentials")`, signals `("agent_url", "name", "enabled", "auth_type", "auth_header", "auth_credentials", "forward_promoted_offering", "timeout")`). Two module constants `_CREATIVE = _Pages(CREATIVE, "creative_agents.html", "creative_agent_form.html", "creative_agents.list_creative_agents", "creative_agents.add_creative_agent", "creative_agents.edit_creative_agent", ...)` and `_SIGNALS`.
- Private bodies, one per operation, each `(request: Request, pages: _Pages, tenant_id: str, ...) -> Response`:
  - `_list_page(request, pages, tenant_id)`: `with AgentUoW(tenant_id) as uow:` → `tenant = uow.tenant_config.get_tenant()`; `None` → `return refuse_form(request, AdminNotFound("Tenant not found"), url_for(request, "core.index"))`; rows → `custom_agents=[_row_dict(pages, row) ...]` (`id`, every `row_fields` attribute, `has_auth=bool(row.auth_credentials)`, `created_at`); `render(request, pages.list_template, tenant=tenant, tenant_id=tenant_id, tenant_name=tenant.name, custom_agents=...)` inside the block (§ 5.2.3; `script_name` comes from `render`).
  - `_add(request, pages, tenant_id, form)`: GET → the same tenant lookup, `render(request, pages.form_template, ..., agent=None)`; POST → `parsed = parse_form(pages.kind.form, form)`; `name = create_agent(tenant_id, pages.kind, parsed)`; `flash(request, f"{pages.kind.label} agent '{name}' added successfully", "success")`; `return redirect(url_for(request, pages.list_endpoint, tenant_id=tenant_id))`; `except AdminRefusal as exc: return refuse_form(request, exc, url_for(request, pages.add_endpoint, tenant_id=tenant_id))`.
  - `_edit(request, pages, tenant_id, agent_id, form)`: GET → tenant + `row = repo.get(agent_id)`; missing → `refuse_form(request, AdminNotFound(f"{label} agent not found"), list_url)`; renders `agent={"id": row.id, **{f: getattr(row, f) for f in pages.form_fields}}`; POST → `parse_form`, `update_agent`, flash `"... updated successfully"`, redirect to the list; `except AdminRefusal as exc: return refuse_form(request, exc, list_url if isinstance(exc, AdminNotFound) else url_for(request, pages.edit_endpoint, tenant_id=tenant_id, agent_id=agent_id))` (a missing row goes to the list, as today; a bad form goes back to the form). Every `Location` is a `url_for` result (§ 5.2.7).
  - `_delete(request, pages, tenant_id, agent_id)`: `name = delete_agent(...)` → `json_ok(message=f"{label} agent '{name}' deleted successfully")`; `except AdminRefusal as exc: return refuse_json(request, exc)`.
  - `_test(request, pages, tenant_id, agent_id)`: `probe = probe_agent(...)` under the same `except`; `if probe.ok: return json_ok(**pages.kind.probe_fields(probe))`; else `return json_error(probe.message, 400)`.
- Routes, decorator order outermost first: the route decorator, then `@audited(...)`; the guard rides on the route decorator as `dependencies=[Depends(require_tenant_access(api_mode=...))]` (§ 5.2.4); every body is one `return _<op>(request, _CREATIVE|_SIGNALS, ...)`:
  - `@router.get("/", name=...)` → `def list_<kind>_agents(request: Request, tenant_id: str) -> Response`; no audit (GET only).
  - `@router.api_route("/add", methods=["GET", "POST"], name=...)` + `@audited("add_<kind>_agent")` → `def add_<kind>_agent(request: Request, tenant_id: str, form: dict[str, str] = Depends(form_data)) -> Response` (one function for both methods keeps the one route name, and the GET of the form is audited exactly as it is today).
  - `@router.api_route("/{agent_id}/edit", methods=["GET", "POST"], name=...)` + `@audited("edit_<kind>_agent")` → `(request, tenant_id, agent_id: int, form=Depends(form_data))`.
  - `@router.delete("/{agent_id}/delete", name=...)` with `api_mode=True` + `@audited("delete_<kind>_agent")` (new audit; § 6.4 items 7, 8).
  - `@router.post("/{agent_id}/test", name=...)` with `api_mode=True` + `@audited("test_<kind>_agent")`.
- The module imports nothing from `src.core.database.database_session`, `sqlalchemy`, `src.core.database.models`, `flask`, `fastapi.responses` or `starlette.responses` (§ 5.2.2, § 5.6.1) and has no `try`/`except` other than `except AdminRefusal` (§ 5.7.2). The slashless list path (`/tenant/<id>/creative-agents`) is not served: Flask answered it with a 308 to the slashed path, the Flask fallback now answers 404, and every link in the app carries the slash. Listed in Task 12 as change 13.

- [ ] **Step 1: Write `src/admin/routers/agents.py`, register the routers, delete the two blueprints and the probe test module, unwire `src/admin/app.py`**

Delete lines 18 and 33 and lines 310–311 of `src/admin/app.py`. Then `git rm src/admin/blueprints/creative_agents.py src/admin/blueprints/signals_agents.py tests/admin/test_agent_probe_routes.py`.

- [ ] **Step 2: Run the route module to verify it passes**

Run: `scripts/run-test.sh --db tests/admin/test_agents.py -q`
Expected: every test passes (20 parametrised × 2 kinds + 2 = 42 passed).

- [ ] **Step 3: Re-point the eight ingest cases and run that slice**

In `tests/integration/test_admin_ingest_url_policy.py`: in the eight functions (and only those), replace the fixture `authenticated_admin_client` with `authenticated_asgi_admin_client`; replace the two `flashes(authenticated_admin_client)` reads (lines 173 and 826) with `asgi_flashes(authenticated_asgi_admin_client, response)`; replace the one `response.get_json()` (line 243) with `response.json()`; import `asgi_flashes` next to `flashes`. Every assertion stays verbatim (§ 5.9.9). The helpers `post_signals_agent`, `create_agent_through_the_add_form`, `post_creative_agent_add`, `create_creative_agent_through_the_add_form` work unchanged with either client (`client.post(path, data=..., follow_redirects=False)` is the same call on both). The module docstring's second sentence now reads "These cases drive the actual admin routes (the agent routers on the ASGI sub-application, the tenant-management JSON API on Flask)".

Run: `scripts/run-test.sh --db tests/integration/test_admin_ingest_url_policy.py -k "agent" -q`
Expected: all `*_agent_*` cases pass (the exact single egress flash, nothing stored, the refused edit leaves the URL alone, the stored URL is not dialed, the reason reaches the log).

- [ ] **Step 4: Format, lint, type-check; the route-conflict hook; stage**

```bash
uv run ruff format src/admin/routers src/admin/app.py tests/admin/test_agents.py tests/integration/test_admin_ingest_url_policy.py && uv run ruff check --fix src/admin/routers src/admin/app.py tests/admin/test_agents.py tests/integration/test_admin_ingest_url_policy.py && uv run mypy src/admin/routers src/admin/app.py --config-file=mypy.ini && uv run python .pre-commit-hooks/check_route_conflicts.py
git add -A src/admin/routers src/admin/blueprints src/admin/app.py tests/admin tests/integration/test_admin_ingest_url_policy.py
```
Expected: clean; the route-conflict hook prints no conflict (it inspects the Flask `url_map`, which no longer has the pair; the FastAPI routes are a Phase 2 extension of the hook, § 5.10).

---

### Task 11: Allowlists, baselines, the retired SSRF tests; commit the pilot; read CI

**Files:**
- Modify: `tests/unit/test_architecture_no_raw_select.py:119-123` and `:195-199` (delete the ten rows naming `src/admin/blueprints/creative_agents.py` and `src/admin/blueprints/signals_agents.py`; lower the count in `test_violation_count_matches` by ten)
- Modify: `tests/unit/test_ssrf_url_validator.py:124-145` (delete `_make_signals_agent_client` and `_mock_db_for_signals_add`), `:190-294` (delete `test_add_endpoint_rejects_docker_internal_url`, `test_add_endpoint_accepts_safe_public_url`, `test_edit_endpoint_rejects_unsafe_url_on_update`), keep `test_the_seam_raises_on_the_url_the_endpoints_reject` and the two URL constants; drop the now-unused `os`, `MagicMock`, `patch` imports; rewrite the class docstring and the module docstring's last "Covers" bullet to say the endpoint wiring is graded against a real database by `tests/integration/test_admin_ingest_url_policy.py` and `tests/admin/test_agents.py` (`test_add_refuses_a_url_egress_policy_blocks_and_audits_the_refusal`, `test_edit_*`), because a test that mocks the session to watch the handler is a test of the mock (tests/CLAUDE.md § Which kind of test).
- Modify: `.admin-raw-session-baseline`

- [ ] **Step 1: Remove the ten raw-select allowlist rows and run the guard**

Run: `uv run pytest tests/unit/test_architecture_no_raw_select.py -q`
Expected: before the removal the stale-entry test fails naming the ten rows; after it, all three tests pass.

- [ ] **Step 2: Prune the SSRF unit module and run it**

Run: `uv run pytest tests/unit/test_ssrf_url_validator.py -q`
Expected: PASS; every test above the wiring class is untouched and `test_the_seam_raises_on_the_url_the_endpoints_reject` still passes.

- [ ] **Step 3: Lower the admin raw-session ratchet**

Run: `uv run pytest tests/unit/test_architecture_ratchet_enforcement.py -q`
Expected: the slack check fails naming the measured counts (`.admin-raw-session-baseline is slack (committed above actual) — lower it to match:`). Set `admin_get_db_session` and `admin_session_add` to the printed values (expected `185 - 14 = 171`, seven `get_db_session()` calls per deleted module on top of Task 4's one, and `39 - 2 = 37`; trust the counter, not this arithmetic) and re-run until it passes. Running `.pre-commit-hooks/check_admin_raw_session_count.py` directly rewrites the file to the same values.

- [ ] **Step 4: Commit the pilot (commit 3)**

```bash
git add tests/unit/test_architecture_no_raw_select.py tests/unit/test_ssrf_url_validator.py .admin-raw-session-baseline
git commit -m "refactor(admin): move the agent blueprints to FastAPI routers under the admin convention" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
Expected: commit-stage hooks pass. The commit holds everything Tasks 6–11 staged. Split it only if the diff reads better in two (forms + service + repositories, then routers + tests + deletions); the builder decides (§ 4.2).

- [ ] **Step 5: Push and read CI**

Task 5 Step 4's procedure, verbatim: push, list the run, classify every red job, fix or ask or report, never deselect.

---

### Task 12: Measurements and the PR description

**Files:**
- Create (scratch, not committed): the measurement table pasted into the PR body

- [ ] **Step 1: Measure before and after on the pilot's files**

Run (each number goes into the table with its command):
```bash
git show origin/main:src/admin/blueprints/creative_agents.py | wc -l; git show origin/main:src/admin/blueprints/signals_agents.py | wc -l
wc -l src/admin/routers/agents.py src/admin/services/agents.py src/admin/forms/_base.py src/admin/forms/agents.py src/admin/errors.py
wc -l src/admin/web/*.py src/core/database/repositories/user.py        # the foundation, on its own line (§ 6.5)
for t in 'get_db_session(' 'session.add(' 'select(' 'jsonify(' 'flash(' 'except Exception'; do printf '%s before=%s after=%s\n' "$t" "$(git show origin/main:src/admin/blueprints/creative_agents.py origin/main:src/admin/blueprints/signals_agents.py | grep -cF "$t")" "$(cat src/admin/routers/agents.py src/admin/services/agents.py | grep -cF "$t")"; done
git show origin/main:.duplication-baseline; cat .duplication-baseline; git show origin/main:.admin-raw-session-baseline; cat .admin-raw-session-baseline
git grep -l 'def _auth_session' -- tests/admin | wc -l; grep -lE '^(app|_app) ?= ?create_app\(' tests/admin/*.py | wc -l
grep -rl '^from flask\|^import flask' src/admin --include=*.py | wc -l; ls src/admin/blueprints/*.py | wc -l
```
Expected: `_auth_session` copies 10 → 9, module-level `create_app()` 14 → 13, test count 8 → 42 (+ the foundation's 23), both ratchets lower (raw sessions 186 → 171 and 39 → 37 as measured), `flask`-importing modules under `src/admin` 34 → 32, blueprint modules 31 → 29; the duplication numbers come from the Quality Gate log of Task 11's run.

- [ ] **Step 2: Write the PR body and apply it**

Body sections, in this order: two paragraphs (what the convention is; what the pilot and the foundation show), "Read in this order" (the proposal doc, then `src/admin/web/`, then `src/admin/routers/agents.py`, services, forms, tests), "Behavior changes" (§ 6.4 items 1–11 verbatim, plus 12: the Flask `require_tenant_access` no longer runs the view inside its own `try` and database session, so a view's own HTTP error reaches the browser with its status for tenant users as it already did for super admins; plus 13: the slashless list URL answers 404 where Flask answered a 308 to the slashed one), "Before / after" (Step 1's table), "CI" (one line: green; or the #2494 note; or, under Task 0's option (b), which four jobs are outside the gate and why), and the footer line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Links are full `https://github.com/v-n7k/salesagent/blob/refactor/admin-convention-pilot/...` URLs.

Run: `gh pr edit <n> --repo v-n7k/salesagent --body-file <scratch file>`
Expected: `gh pr view <n> --repo v-n7k/salesagent --json body --jq .body | head -5` shows the new body.

---

### Task 13: The proposal document (commit 4)

**Files:**
- Create: `docs/development/admin-convention-proposal.md`

**Interfaces:**
- Consumes: the real diff (`git diff origin/main -- src/admin src/app.py tests/admin src/core/database/repositories`) for every before/after snippet; the Task 12 table; the PR URL.

- [ ] **Step 1: Write the document (§ 4.1, exactly these eight sections, in this order)**

1. **The problem, measured** — the two tables from § 1 (with the Task 12 "before" numbers for the pair), two sentences of interpretation each, a Mermaid `graph LR` showing the pair as two copies of the same five routes.
2. **The convention in one picture** — Mermaid `flowchart TB`: router → form model → service → UoW + repository → database, with the test seam (test module, shared fixtures, factories, the httpx test client, the one patched probe) drawn beside it.
3. **The rules** — one numbered subsection per rule of § 5.2–5.9: the rule in one or two sentences; why (one measured fact); a before/after snippet from the diff (≤ 12 lines each side); the Phase 2 guard that will enforce it (§ 5.10 table), named, not built.
4. **The pilot** — file map before/after (the table at the top of this plan), the Task 12 measurements, the thirteen behavior changes, the draft PR link; a Mermaid "before" graph (two blueprints each owning its copy of everything) beside an "after" graph (one router module over one service, one repository family, one test module).
5. **Migration** — the strangler mechanism of § 5.12 in one picture (main app, admin sub-application, routers, Flask as the sub-application's fallback; a sequence diagram of one write request through the session middleware, the guard dependency, the audited endpoint, the form model, the service and the UoW); the order of § 5.11 as a Mermaid `gantt` or `timeline`; the final pull request; how the three ratchets hold the line (blueprint count, raw sessions, duplication).
6. **Not in this proposal** — § 2.2 and § 2.3 in the team's words, plus the three findings the pilot leaves alone: both edit forms echo the stored credential into the password input (`templates/creative_agent_form.html:72`, `templates/signals_agent_form.html:95`); two adapters import the UI framework (`src/adapters/gam_reporting_api.py:16`, `src/adapters/google_ad_manager.py:25`); no CSRF layer exists (`templates/base.html:6`).
7. **Questions for the team** — the decisions the team can still flip cheaply (§ 4.1 item 7), each with the proposal's default and why: migration order; who migrates (a person or an AI session with the convention as its brief); whether the root prefix survives the final pull request or only `/admin` does; when to switch the session format; async database (the proposal's answer: not part of this).
8. **How to comment** — the draft PR link; line comments on this file and on the pilot code are both welcome.

Rules for the file: Markdown + fenced ` ```mermaid ` blocks only, no images, no relative links (every link is `https://github.com/v-n7k/salesagent/blob/refactor/admin-convention-pilot/<path>` or an upstream issue/PR URL such as `https://github.com/prebid/salesagent/pull/1066`), 1,800–2,300 words of text excluding code and diagrams, readable in 15 minutes (§ 4.1).

- [ ] **Step 2: Check it renders and links resolve**

Run: `uv run python -c "import re,sys;t=open('docs/development/admin-convention-proposal.md').read();print(len(re.findall(r'\w+',re.sub(r'\x60\x60\x60.*?\x60\x60\x60','',t,flags=re.S))),'words;',t.count('\x60\x60\x60mermaid'),'diagrams;',len(re.findall(r'\]\((?!https://)',t)),'relative links')"`
Expected: `1800–2300 words; 7 diagrams; 0 relative links`. Open the file in the GitHub PR "Files" view after pushing and confirm each Mermaid block renders.

- [ ] **Step 3: Commit, push, read CI, undraft nothing**

```bash
git add docs/development/admin-convention-proposal.md
git commit -m "docs(admin): propose the admin convention and ASGI migration" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin refactor/admin-convention-pilot
```
Then Task 5 Step 4's procedure again. The PR stays a draft on the fork; the user presents it and decides when the team sees it (§ 2.2).

---

## Self-review (done while writing; re-run after execution)

- **Spec coverage:** § 4.1 → Task 13; § 4.2 → Tasks 0, 5, 11, 12; § 4.3 → Task 0; § 5.1 → file map; § 5.2 → Task 10; § 5.3 → Task 9; § 5.4 → Tasks 4, 8; § 5.5 → Task 6 (+ `raise_if_url_blocked` in Task 9); § 5.6 and § 5.7 → Tasks 1, 4; § 5.8 → Task 4; § 5.9 → Tasks 2, 3, 4, 7, 10 (fixtures, cookie helpers, probe test folded, `_auth_session` and `create_app()` counts down by one each, the ingest cases re-pointed, the mount test re-typed); § 5.10, § 5.11 → Task 13; § 5.12.1 → Tasks 3, 5; § 5.12.2 → Tasks 2, 3; § 5.12.3 → Task 3; § 5.12.4 → Task 3; § 5.12.5 → Task 3; § 5.12.6 → Task 4; § 6.2 → Tasks 8–10; § 6.3 → Tasks 3, 4, 7; § 6.4 → Tasks 7, 10, 12; § 6.5 → Task 12; § 9 → Task 0 Step 1, Task 5 Step 4. Not implemented by design: § 5.7.4 (the Phase 2 500 handler).
- **Calls recorded here beyond § 7's latitude:** the decision core returns a frozen `TenantAccess(refusal, setup_user)`; the audit core takes the already-built logger; the session middleware is pure ASGI and tracks "modified" by comparison; `url_for` returns a path (`_external` is honoured only on the Flask-side fallback); the form body is read by a dependency that leaves it on `request.state.form_data`; `build_admin_app` takes `routers=` so the foundation test can grade it before any pilot router exists; one Flask-side effect of the extraction (change 12) and the slashless list path (change 13) are listed, not silent.
- **Type consistency:** `AgentKind.repository` is the `AgentUoW` attribute name used by the service and by the tests' `_Case.repository`; `parse_form` raises `AdminInvalidInput`, which `refuse_form` answers; `probe_agent` returns `ProbeResult`, which `_test` projects through `AgentKind.probe_fields`; `_Case.kind_fields` is the shape `_rows` puts in its last tuple element; `require_tenant_access` (the FastAPI one) raises `AuthRequired` / `AccessDenied`, which `answer_auth_required` / `answer_access_denied` handle; `record_admin_action_failure(request, error)` is what `refuse_form` / `refuse_json` call and what `audited` folds through `fold_handled_failure`; `cookie_flashes(flask_app, response)` is what `_answer` and `asgi_flashes` call; `asgi_auth_session(client, flask_app, tenant_id)` is what the `client` fixture and `authenticated_asgi_admin_client` call.
- **Facts checked against the tree on 2026-11-04:** `src/app.py:61-87` and `:593-594` hold the only `WSGIMiddleware` use; the regression test is the only test naming it (`:251`); `g.user` is written at `helpers.py:269,356` and read by nothing under `src/` or `templates/`; `base.html` reads `tenant` only behind `{% if tenant ... %}` and links through `script_name` at lines 12, 18, 173–176, 231; the four agent templates call `url_for(` four times each, `base.html` never; four Flask pages link to the pilot's endpoints (`tenant_settings.html:2570,2593`, `add_product_gam.html:64,116`), which the Flask-side fallback serves; `flask_wtf` is not installed, so no `csrf_token` global exists; `UserFactory` exists (`tests/factories/user.py`); `AuditLog` has `success`, `error_message`, `details`; Starlette's `Request.state` wraps `scope["state"]`; `TestClient` takes `raise_server_exceptions` and `follow_redirects`; the raw-select allowlist's `helpers.py` / `decorated_function` row is at `:247` and the pair's ten rows at `:119-123,195-199`; seven `get_db_session()` calls and one `session.add` per old module; the `auth` blueprint's login views validate `next` through `_safe_redirect` (`auth.py:283-286`), so an absolute `next=` keeps working.

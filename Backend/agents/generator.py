"""Agent B — The Generator / RAG Specialist (Strict Contract Architecture).

Turns each ValidatedRequirement into concrete, executable functional TestCases,
grounded in a VERTICAL SLICE of the real source tree (Router + Pydantic Schema
+ SQLAlchemy Model) retrieved via multi-query expansion against ChromaDB.

Design points:
- `query_source_context()` is called ONCE per requirement but performs three
  targeted ChromaDB queries internally (Router / Schema / Model), deduplicated.
- Snippets are injected with their `path:start-end` header so the model can
  cite real locations in `source_refs`. Retrieved paths are also used as a
  fallback when the model omits `source_refs`.
- Unverifiable or un-retrievable ACs land in `coverage_gaps` — never fabricated.
- Every TestCase now declares `setup_fixtures` — tests cannot rely on "magic"
  users existing in the database.
- Test IDs are stamped by the node to guarantee uniqueness across requirements.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.prompts import ChatPromptTemplate

from database import (
    RagMode,
    RouteIntent,
    VerticalSliceContext,
    query_source_context,
    resolve_rag_mode,
)
from state import (
    CoverageGap,
    DesignContract,
    ProjectState,
    SurfaceBinding,
    TestCase,
    ValidatedRequirement,
)
from ._paths import _paths_match_any
from .attestation import stamp_attestation_mode
from utils import (
    LLMInvocationError,
    get_local_llm,
    inflate_placeholders,
    invoke_with_retry,
    parse_llm_json,
    stringify_response,
)

logger = logging.getLogger(__name__)


GENERATOR_SYSTEM_PROMPT = """You are Agent B — The Generator, a senior SDET for HPE's
Sentinel-QA pipeline. You write concrete, executable, TECHNICALLY PRECISE tests
for a React front-end backed by a FastAPI service.

Every test you emit will be executed against real code. Hallucinated fields,
invented routes, and contract-mismatched payloads will fail at runtime and
pollute the heal-loop. You WILL be judged on grounded accuracy, not coverage.

============================================================
STRICT CONTRACT ENFORCEMENT — NON-NEGOTIABLE
============================================================

## RULE 1 — GROUNDED FIELDS ONLY (multi-source grounding)
You may ONLY reference fields, routes, status codes, response keys, and
rendered text that are GROUNDED in the retrieved SOURCE CONTEXT. The context
is organized into FIVE sections:

  (A) ROUTER & API ENDPOINT
  (B) PYDANTIC REQUEST / RESPONSE SCHEMAS
  (C) DATABASE / SQLALCHEMY MODELS
  (D) FRONTEND RENDERING (React JSX/TSX)
  (E) FRONTEND API CLIENT CONFIG (axios / fetch / baseURL)

A field is "grounded" if it appears in ANY of these five sections. Use the
section that matches the assertion layer:

  • Pydantic schema → assert it in the API request or JSON response.
  • SQLAlchemy model → assert its persistence behavior (what the DB stores).
  • Frontend JSX → assert it in rendered UI via a DOM / E2E test.
  • API client config → assert the outbound request URL / scheme sent by
    the browser (e.g. `baseURL: 'http://...'` grounds an http:// transport
    test).

Critical pattern — frontend grounding covers backend gaps:
  Suppose an AC says "the dashboard shows the user's email after login."
  • If the login response schema returns only `access_token` / `token_type`
    (no `email` key), the API-level assertion is NOT grounded.
  • BUT if a JSX file in section (D) renders `{{user?.email}}` in the
    dashboard header, or persists email via `localStorage.setItem('auth_user',
    ...)`, that IS grounded — emit a UI test that asserts the rendered DOM
    contains the email after a successful login.
  • This is NOT a coverage gap. The AC is testable on the frontend even
    though the backend response is silent on it.

Rules:
- NEVER invent a field. If `full_name`, `phone_number`, `bio`, etc. appear
  in NONE of the five sections, that field does not exist — do NOT put it in
  `input_data`, `expected_json_keys`, or a DOM selector.
- Emit a `coverage_gaps` entry ONLY when the field / behavior is absent from
  ALL FIVE sections. Do not abstain when the frontend grounds what the
  backend doesn't, or vice versa.
- `expected_json_keys` must be grounded in the retrieved `response_model` /
  Pydantic schema specifically. Frontend rendering does not justify a JSON-
  response assertion — use a DOM assertion instead.
- Every test's `coverage_rationale` must name the grounding layer you used
  (e.g. "grounded in Pydantic UserCreate at schemas.py:12-28" or "grounded
  in Dashboard.jsx:247 which renders {{user?.email}}").

### ABSOLUTE TEXTUAL GROUNDING — NO LIBRARY / PLATFORM TRIVIA
Your rationale MUST quote TEXT THAT APPEARS in the retrieved source context.
You are FORBIDDEN from citing undocumented library internals, "typical"
platform behaviors, or constraints you learned during training that are not
visible in the snippets:

  ❌ BANNED rationale examples:
    • "bcrypt silently truncates passwords at 72 bytes, so passwords longer
       than 72 characters produce the same hash." — BANNED unless the byte
       limit appears literally in the retrieved code.
    • "Typical database VARCHAR(255) column limits will reject this." —
       BANNED unless a `String(N)` / `VARCHAR(N)` declaration appears
       literally in section (C).
    • "PostgreSQL B-tree indexes cap key size at 2712 bytes." — BANNED
       unless that number appears in a migration / DDL snippet.
    • "FastAPI's default body-size limit is 10MB." — BANNED unless a
       `MAX_CONTENT_LENGTH` / middleware / server config literal appears.
    • "JavaScript numbers lose precision above 2^53." — BANNED unless the
       app actually does arithmetic near that limit.

  ✅ ACCEPTED rationale examples:
    • "The retrieved `schemas.py:12` declares `password: constr(min_length=8)` —
       a 7-char password fails this validator and yields 422."
    • "The retrieved `models.py:60` declares `email = Column(String(255))`
       and `auth_router.py:86` INSERTs into this column on registration, so
       a 256-char email triggers an SQLAlchemy DataError on the write path."

Rule: if the exact limit / behavior is not written in the retrieved Python,
JSX, JSON, YAML, or config text, you are FORBIDDEN from using it as a
rationale. Emit a `coverage_gaps` entry naming what would need to be
retrieved ("requires bcrypt config or password-hashing module to verify
byte-limit behavior") rather than fabricating the rationale from training
data.

### Protocol / deployment boundary (anti-fabrication)
Application source code does NOT control URL protocol, CORS policy, proxy
rewriting, cookie flags, TLS termination, or deployment-time redirects.
Those are controlled by deployment & tooling configs:
  - `vite.config.js/ts` / `webpack.config.js` — dev server protocol, proxy
  - `nginx.conf` / `Caddyfile` / `httpd.conf` — TLS, redirect, headers
  - `docker-compose.yml` / `Dockerfile` — port mapping, env
  - FastAPI `CORSMiddleware`, `HTTPSRedirectMiddleware`,
    `TrustedHostMiddleware`, `SessionMiddleware` (look for `app.add_middleware`)
  - `.env.example` / `settings.py` — protocol/host configuration keys

Do NOT emit a test that asserts any of the following UNLESS the SOURCE CONTEXT
contains a snippet from one of the config/middleware sources above:
  • URL protocol (`http://` vs `https://`, `ws://` vs `wss://`)
  • HTTP→HTTPS redirect behavior
  • CORS allow-origin / allow-credentials behavior
  • Cookie `Secure` / `HttpOnly` / `SameSite` flags
  • `Strict-Transport-Security` / `Content-Security-Policy` headers
  • Proxy path rewriting (`/api` → backend)
  • Trusted-host / host-header validation

If the AC requires such an assertion and the retrieved context does NOT
include the controlling config, emit a `coverage_gaps` entry naming the
SPECIFIC config file you would need (e.g. "requires vite.config.js to
verify dev-server protocol" or "requires FastAPI CORSMiddleware
configuration at app startup"). Do NOT infer protocol from application
routing code (e.g. `App.jsx` defining `<Route path="/dashboard">` does NOT
ground an `http://` vs `https://` assertion — it only grounds that the
`/dashboard` path exists).

### API-transport carve-out (groundable frontend clients)
A frontend HTTP client config IS sufficient grounding for an API-TRANSPORT
assertion (i.e. "the REQUEST URL the browser sends starts with http://").
This carve-out applies ONLY when the retrieved context contains one of:
  - `axios.create({{ baseURL: "http://..." }})` or `axios.defaults.baseURL`
  - a `fetch(...)` call with a hard-coded `http://` URL
  - `new URL("http://...")` in an api client module
  - Apollo `HttpLink({{ uri: "http://..." }})` / `ky.create({{ prefixUrl: ... }})`
  - a `VITE_API_URL` / `REACT_APP_API_URL` / `API_BASE_URL` value read at
    build time that is explicitly `http://` in the retrieved file

When any of the above IS retrieved:
  ✅ ACCEPTED — emit a test asserting the API request URL uses `http://`.
    title: "Login POST is sent over http:// (no TLS)"
    coverage_rationale must quote the exact file and line (e.g.
      "grounded in frontend/src/api/axios.js:18 which declares
       `baseURL: 'http://localhost:8000'` — any request built from this
       client inherits the http:// scheme").
    assertion targets the request initiator (axios / fetch call site),
    NOT the browser's URL bar.

When the above is NOT retrieved, or the AC is about the BROWSER PAGE URL
(e.g. "/dashboard page URL starts with http://"), keep treating it as a
coverage gap — frontend routing (`<Route>`, `useNavigate`) does not
control page protocol; only nginx/Caddy/vite config does.

Boundary (important): the API-transport carve-out NEVER grounds claims
about:
  - page URL (address bar) protocol
  - HSTS / HTTPSRedirectMiddleware behavior
  - whether the server ALSO accepts https://
  - network-level packet inspection / Wireshark visibility
Those remain deployment/infra concerns and stay in `coverage_gaps`.

### DOM SELECTOR GROUNDING — NO INVENTED ATTRIBUTES
Whenever a TestCase targets the UI (any `ui_action`, `element_selector`,
Playwright / Cypress-style locator, or assertion about rendered DOM),
EVERY selector string you emit MUST appear VERBATIM in a retrieved JSX /
TSX / HTML snippet in section (D). No exceptions.

This applies to, and is NOT limited to:
  - `data-testid="..."` / `data-cy="..."` / `data-qa="..."` / any `data-*` hook
  - CSS class selectors (`.overdue-btn`)
  - id selectors (`#filter-date`)
  - `role="..."` / `aria-label="..."` values
  - visible text used in `getByText(...)` / `:has-text(...)` matchers

Rules:
  - If the retrieved JSX renders `<select id="filter-date">` with
    `<option value="Overdue">`, the correct test targets `#filter-date`
    and sets its value to `"Overdue"`. Do NOT invent
    `[data-testid='filter-date-overdue']` just because it matches industry
    convention — if the attribute is not in the snippet, it does not exist.
  - If the AC requires interacting with a control and section (D) does
    NOT expose a stable selector (id, role, or accessible text), emit a
    `coverage_gaps` entry naming the missing hook, e.g. "FilterBar.jsx
    renders an `<option>` for 'Overdue' inside an unnamed `<select>` —
    a data-testid or id on the option would be needed to target it
    reliably in E2E; no stable selector retrieved."
  - `coverage_rationale` for any UI test MUST quote the exact JSX line
    that grounds the selector, e.g. "grounded in FilterBar.jsx:138 which
    renders `<select id='filter-date'>` — test sets its value to
    'Overdue' (FilterBar.jsx:146) and fires a change event."
  - The SAME rule applies to `expected_result` text assertions: if the
    test asserts "page shows 'Task deleted successfully'", that literal
    string MUST appear in the retrieved JSX or in a response schema
    (section B). If it appears NOWHERE, that is a hallucinated assertion.

Breaching this rule — citing any DOM attribute, selector, or visible
string that does not appear verbatim in the retrieved context — is
treated as hallucinated grounding and the test will be rejected
downstream. Prefer rejecting the test (coverage_gap) over inventing
a selector.

## RULE 2 — FASTAPI AUTHENTICATION CONTRACT (Form vs JSON)
FastAPI's `OAuth2PasswordRequestForm` is a FORM dependency, not a JSON body.
It consumes `application/x-www-form-urlencoded` with the EXACT keys `username`
and `password`. It does NOT accept a JSON body. It does NOT accept an `email`
key. This is true EVEN IF the user model stores the login identifier as
`email` — the form layer normalizes it into `username`.

Detection — the ROUTER section uses this form contract when you see ANY of:
  - `OAuth2PasswordRequestForm`
  - `form_data: OAuth2PasswordRequestForm = Depends()`
  - one or more `= Form(...)` parameters on the endpoint

When the router uses the form contract, EVERY test for that endpoint MUST:
  - set `input_data` to a dict that begins with the sentinel key
    `"_content_type": "application/x-www-form-urlencoded"`
  - use the keys `username` and `password` EXACTLY (case-sensitive)
  - NEVER include a `email` key for the credential itself
  - NEVER send a JSON body — no other top-level keys beyond the sentinel,
    `username`, `password`, and (if the form declares them) `grant_type`,
    `scope`, `client_id`, `client_secret`

Example (login endpoint using OAuth2PasswordRequestForm):
  ✅ CORRECT:
     "input_data": {{
       "_content_type": "application/x-www-form-urlencoded",
       "username": "test@example.com",
       "password": "Correct!123"
     }}
  ❌ WRONG (JSON body instead of form):
     "input_data": {{ "email": "test@example.com", "password": "Correct!123" }}
  ❌ WRONG (wrong key name even though the DB stores email):
     "input_data": {{ "_content_type": "application/x-www-form-urlencoded",
                      "email": "test@example.com", "password": "x" }}

For all other endpoints (registration, CRUD, profile updates) use a plain
JSON dict for `input_data` UNLESS the retrieved router explicitly declares
`Form(...)` parameters.

## RULE 3 — VALIDATION BOUNDARY DISCIPLINE (storage ≠ route)
Each route is validated by the schema IT declares — nothing else. Do NOT
carry validation rules across routes, AND do NOT conflate storage constraints
with route constraints.

### Storage vs Route
A SQLAlchemy column (e.g. `email = Column(String(255), ...)`) is a STORAGE
constraint. It is enforced ONLY when the ORM actually INSERTs or UPDATEs
that column. It is NOT automatically a route-layer validation.

A Pydantic constraint (e.g. `constr(max_length=255)`,
`Field(..., max_length=255)`, a `field_validator`) is a ROUTE constraint.
It is enforced on EVERY request that uses the schema.

Boundary rules:
  • WRITE routes (POST /register, PUT /users/{{id}}) may be bounded by BOTH
    the Pydantic schema AND the storage column width. Test both.
  • LOOKUP routes (POST /login, GET /users/{{id}}) are bounded by the REQUEST
    schema only. A 256-char login identifier is NOT rejected for "exceeding
    column width" — it simply fails the lookup and returns `401 Unauthorized`.
    Do NOT emit a boundary test framed as "256 chars fails due to String(255)
    column" on a route that never writes.
  • If a WRITE route's Pydantic schema does NOT declare a max_length but the
    storage column does, the bound may surface as a database integrity error
    (typically `500` unless middleware catches it, NOT `422`).
  • `boundary_value_used` MUST name the layer being bounded:
    "route-layer Pydantic constr(max_length=255) at schemas.py:14"
    vs. "storage-layer String(255) at models.py:60 via INSERT".

### ANTI-PATTERN — do NOT cite storage columns as the cause of lookup outcomes
On ANY route that does not INSERT or UPDATE the column in question, a
SQLAlchemy `String(N)` declaration is IRRELEVANT to the HTTP outcome. The
LLM is often tempted to write:

  ❌ BANNED rationale on a login test:
    "The input username exceeds the database's String(255) column limit for
     email (models.py:60), meaning such a user cannot exist. The system
     correctly returns 401 Unauthorized."

This is wrong reasoning dressed up as grounded. The correct chain is:
  ✅ ACCEPTED rationale on a login test:
    "A 1000-char username has no matching row in the users table — the
     `db.query(User).filter(User.email == ...).first()` call in
     authenticate_user returns None, so the route returns 401. The
     String(255) column width is irrelevant: login never writes, and
     SQLAlchemy does not enforce column widths on SELECT / filter
     comparisons."

### TITLE DISCIPLINE — ban column framing in test titles, not just rationale
The `title` field is the primary human-readable label and it MUST NOT
imply the column caused the HTTP outcome on a read/lookup route. Apply
the same rule as rationale: cite the LOOKUP MISS, not the storage bound.

  ❌ BANNED titles on a login test:
    • "Login with username exceeding DB column length returns 401"
    • "Login with email longer than String(255) limit fails"
    • "Login rejects 256-char email due to column width"
    • "Login with oversized username triggers DB constraint"

  ✅ ACCEPTED titles on a login test:
    • "Login with nonexistent 256-char username returns 401"
    • "Login with 1000-char username yields lookup miss (401)"
    • "Oversized username has no matching user → 401 Unauthorized"

Rule: on lookup / auth / read routes, BOTH your `title` AND
`coverage_rationale` MUST frame the outcome as a lookup miss (or the
failed predicate), NOT a column / storage / DB-length constraint. Do
NOT use the phrases "DB column", "column limit", "column length",
"String(N)", "database constraint", "storage bound", or "exceeds the
database" on any route that does not write the column in question. You
may cite the column ONLY if the route actually writes that column.
Breaching this in EITHER the title OR the rationale is treated as
hallucinated grounding and the test will be rejected downstream.

### Route-specific rules
- Registration routes apply password-complexity / length rules ONLY if the
  retrieved UserCreate-style schema actually declares them. Do not invent
  complexity rules. Quote the validator line in `coverage_rationale`.
- Login routes backed by `OAuth2PasswordRequestForm` have NO password-
  complexity validation — the form accepts any non-empty string. Do NOT
  assert `422 "password must contain an uppercase letter"` on login.
  Login negative paths target AUTHENTICATION failures:
    • wrong password → `401 Unauthorized`
    • nonexistent user → `401 Unauthorized` (never `404` — auth endpoints
      must not leak user existence)
    • overlong username → `401 Unauthorized` (lookup miss, NOT a length error)
    • missing `username` or `password` field → `422`
- If the retrieved login router wraps the form identifier in a custom
  validator (e.g., calls `EmailStr(form_data.username)`), you MAY assert
  `422` — but `coverage_rationale` MUST quote the exact router line.

If you cannot tell which schema applies to which route because the context
is thin, emit a `coverage_gaps` entry rather than guessing.

## RULE 4 — MISSING SECURITY CONTROLS ARE TESTABLE VULNERABILITIES
When an AC describes a security CONTROL (rate limit, account lockout, CAPTCHA,
CSRF token check, idempotency key, brute-force delay, per-request audit log)
and the retrieved code shows NO implementation of that control, do NOT emit
a coverage_gaps entry. A missing control IS testable as a negative-control
security assertion.

Emit a SECURITY test that demonstrates the missing control:
  • `test_category = "security"`, `is_adversarial = true`
  • `action` describes the attack loop — e.g. "send 100 login attempts with
    wrong password against the same username in rapid succession"
  • `input_data` MUST be a single dict annotated with the sentinel
    `"_repeat": <int>` (runtime loops the call). See RULE 6 — list inputs
    are forbidden.
  • `expected_result` describes the OBSERVED vulnerability:
    "All 100 attempts receive 401; no 429 Too Many Requests seen; account
    is NOT locked; next valid credential still succeeds immediately after."
  • `resilience_signature` = what a PATCHED app would do, e.g.
    "429 Too Many Requests after N failed attempts" or
    "account locked for T minutes after N failures"
  • `vulnerability_signature` = what the CURRENT app does, e.g.
    "accepts unlimited attempts at full server rate; no throttling headers"
  • `forbidden_response_content` = strings that would FALSELY imply
    enforcement, e.g. ["Too Many Requests", "account locked", "try again",
    "rate limit", "Retry-After"]
  • `expected_status_code` = the status the unprotected endpoint actually
    returns on each attempt (usually `401` for auth, `200/201` for CSRF-less
    state-changing endpoints)

Example (brute-force AC against an endpoint with no rate limiter):
  title: "No lockout after 1000 failed login attempts"
  action: "send 1000 wrong-password POSTs to /login for the same username"
  input_data: {{
    "_content_type": "application/x-www-form-urlencoded",
    "_repeat": 1000,
    "username": "test@example.com",
    "password": "Wrong!000"
  }}
  expected_status_code: 401
  forbidden_response_content: ["Too Many Requests", "locked", "Retry-After"]
  resilience_signature: "429 after 10 consecutive failures or account lock"
  vulnerability_signature: "all 1000 attempts return 401 at full rate; no
    throttling observed; successful login immediately after still works"
  coverage_rationale: "Satisfies AC 'system should prevent brute-force
    attempts'. Grounded in auth_router.py:85-111 (no rate-limit decorator)
    and auth.py:178-193 (no attempt counter). The absence IS the finding."

This test PASSES (as a vulnerability report) when the app fails to throttle.
A missing control is evidence, not a gap.

## RULE 5 — EXECUTOR REPEAT CAP (HARD 2000)
The test runner has a HARDCODED safety limit of 2000 iterations per test
(`SENTINEL_REPEAT_CAP`, default 2000). Requests beyond this cap are silently
clamped by the executor.

If an AC asks for a loop count GREATER than 2000 (e.g. "1000000 attempts",
"10000 failed logins", "unlimited retries"):
  • Set `"_repeat": 2000` in `input_data` — NEVER emit a larger integer,
    even if the AC demands it. The runtime will truncate anyway and you
    will look like you did not read the docs.
  • EXPLICITLY state the clamp in `coverage_rationale`:
    "AC requests 10000 attempts; clamped to executor safety cap of 2000
     iterations. At 2000 attempts with no throttling / 429 / lockout
     observed, the vulnerability signature is already satisfied — a
     rate-limited implementation would have fired by this point."
  • Adjust `expected_result` / `vulnerability_signature` to describe what
    is observable in 2000 iterations, not the AC's aspirational count.

Never emit `"_repeat": 10000` and hope the runner does the right thing —
the run log will show `_repeat=2000` regardless and your rationale will
look wrong.

## RULE 6 — INPUT_DATA IS A DICT, NEVER A LIST
The `input_data` field MUST be a single JSON object (dict). The runtime
contract expects `dict` for single-shot and `dict + "_repeat"` for loops.
NEVER emit a JSON array of request dicts.

  ❌ BANNED — list of dicts:
     "input_data": [
       {{"username": "a", "password": "wrong"}},
       {{"username": "a", "password": "wrong"}},
       {{"username": "a", "password": "Correct!123"}}
     ]

  ✅ CORRECT — single dict with `_repeat` for the loop part:
     "input_data": {{
       "_content_type": "application/x-www-form-urlencoded",
       "_repeat": 1000,
       "username": "test@example.com",
       "password": "Wrong!000"
     }}

If the scenario legitimately requires "N failures THEN 1 success" (e.g.
"verify lockout does NOT happen — valid credentials still work after
1000 failures"), split it into TWO separate TestCases linked via
`parent_test_id`:
  • Test A: 1000 failing attempts (`_repeat: 1000`, wrong password).
  • Test B: 1 successful login with correct credentials,
    `parent_test_id` = Test A's `test_id`, `coverage_rationale` explains
    the ordering dependency ("must run after <Test A> to verify the
    endpoint did not lock the account").
Alternatively, collapse the post-loop verification into Test A's
`expected_result` prose and skip the second test. Either is acceptable;
a list input is NOT.

Same rule for sequences like "create → read → delete": emit a test per
step with `parent_test_id` chaining. Never encode the sequence as a list
under `input_data`.

## RULE 7 — EXHAUSTIVE AC PROCESSING (NO AC LEFT BEHIND)
For EVERY acceptance criterion in the requirement under test you MUST
output AT LEAST ONE of:
  (a) a TestCase whose `covered_acceptance_criterion` quotes that AC, or
  (b) a `coverage_gaps` entry whose `acceptance_criterion` quotes that AC.

Dropping an AC silently — emitting neither a test nor a gap for it — is
the single worst failure mode of this agent. Before you close the JSON,
mentally walk each AC in the prompt's `Acceptance Criteria` block and
confirm it appears somewhere in your output.

Per-AC processing rules (apply each separately, do NOT group ACs):
  • If the AC is grounded in ANY of the FIVE sections (A-E), emit a
    TestCase. Multi-clause ACs ("display user's full_name AND email")
    must be DECOMPOSED: evaluate each noun/field independently.
      - `email` grounded in Dashboard.jsx?    → TestCase for email.
      - `full_name` grounded anywhere?        → TestCase for full_name.
      - `full_name` missing from all sections → CoverageGap naming
        "full_name field not present in Pydantic schema (B), DB model (C),
         or frontend render (D); cannot ground a visibility assertion."
  • If the AC is unverifiable ("intuitive", "fast", "secure" with no
    measurable threshold), emit a CoverageGap quoting the AC and naming
    the unverifiable term.
  • If the AC requires an infrastructure file not in the context
    (nginx.conf, vite.config.js), emit a CoverageGap naming the specific
    file per RULE 1's protocol-boundary guidance.

Example — REQ-005 with the AC "display the user's full_name and email on
the dashboard":
  • Decompose into {{full_name, email}}.
  • Inspect section (D) for each field's render.
  • If `{{user?.email}}` appears in Dashboard.jsx → TestCase for email.
  • If `full_name` appears NOWHERE → CoverageGap for full_name with
    reason "full_name is not declared on the User model (C), not returned
    by /login response schema (B), and not rendered in Dashboard.jsx (D);
    no layer grounds a visibility assertion."
  Outputting ONLY the email test and silently dropping full_name is a
  VIOLATION — you must emit the full_name gap explicitly.

## RULE 8 — CLIENT-SIDE VULNERABILITY PIVOT
If the retrieved context reveals that a feature (like Search or Filtering) is
handled entirely on the client-side (e.g., local React filtering) and does
not hit a backend database query, you MUST NOT abandon security testing.
Instead of Backend SQLi, you MUST pivot to generating Client-Side Security
tests (e.g., DOM-based XSS, Prototype Pollution) using Playwright assertions
against the rendered JSX.

## RULE 9 — OWASP A03 DEFENSE-PATH COVERAGE (authenticated payload test)
This rule applies ONLY when the requirement's `OWASP mapping` (supplied in
the user prompt) contains `A03:2021`, or when the Critic flagged an
injection-class SecurityRisk on this REQ. For all other REQs, ignore this
rule entirely.

Common failure mode: emitting only a PREVENTION-layer test (e.g. an
unauthenticated request that returns 401) and calling the injection risk
covered. That test proves the gate works; it does NOT prove the payload
would be neutralized if a legitimate user sent it. The Critic's flagged
risk lives on the defense layer, not the gate.

When A03:2021 is present, the test_suite MUST contain AT LEAST ONE test
that exercises the DEFENSE layer (not just the auth gate) with all of:

  - `setup_fixtures` includes an entry that issues a valid JWT / session
    for a seeded user and attaches it as a Bearer token (or the
    session-cookie equivalent if the retrieved auth layer uses cookies).
  - `input_data` places the injection payload in the EXACT field the
    Critic flagged (read `OWASP mapping` context or the AC — typical
    targets: `date_filter`, `search`, `sort_by`, `id`, `q`, `order`).
  - `expected_status_code` is the status the endpoint returns when the
    payload is treated as a harmless LITERAL string — usually `200`
    (query ran, zero or normal rows returned) or `400`/`422` if the
    field has enum / regex validation that the payload fails. It is
    NOT `401` (that is the prevention gate, not the defense).
  - `forbidden_response_content` includes strings that would indicate
    the payload was INTERPRETED rather than neutralized, for example:
    ["syntax error", "SQLSTATE", "ProgrammingError", "OperationalError",
     "unterminated", "near \"--\"", "Traceback", "psycopg2", "sqlite3.",
     "column does not exist"].
  - `coverage_rationale` MUST quote the router / ORM line where the
    flagged field flows into the parameterized call, demonstrating the
    field is compared as a value — never concatenated into SQL. Example:
    "grounded in task_router.py:277-280 — `Task.due_date < today_start`
    and `Task.status != 'Completed'` are SQLAlchemy expressions;
    `date_filter` at task_router.py:257 is `.strip().lower()`-compared
    against string literals ('today' / 'upcoming' / 'overdue') and never
    concatenated into SQL, so a payload falls through the if/elif ladder
    without reaching the query."
  - `title` frames the test as verifying the defense, e.g.
    "Authenticated SQLi payload in date_filter is neutralized (200, no
    DB error, no rows)".
  - `test_category = "security"`, `is_adversarial = true`.

An auth-gate-only test (unauthenticated + 401) remains acceptable as a
SUPPLEMENTARY test. It does NOT on its own satisfy RULE 9. If you emit
only the prevention-layer test when A03:2021 is flagged, the suite is
incomplete and the Critic's risk is unmet.

Grounding fallback: if the retrieved context does NOT include the router
/ ORM line where the flagged field flows into a query, do NOT guess the
defense path. Emit a `coverage_gaps` entry naming the specific router
or handler file that would be required (e.g. "requires the handler for
GET /tasks where `date_filter` is consumed; retrieved snippets do not
include the query-construction line").

## RULE 10 — STORY SCOPE DISCIPLINE (no off-story proxy tests)
This rule fences the test suite to the routes / surfaces the STORY actually
touches. It exists because prior runs emitted off-story adversarial tests as
a "free coverage" hedge, which both inflated the suite size and produced
verdicts about routes the story didn't own.

### 10a — No auth-scaffolding proxy tests
If the requirement under test does NOT mention authentication, registration,
login, or session management, you are FORBIDDEN from emitting tests against
`/register`, `/login`, `/logout`, `/refresh`, `/password-reset`, or any
similar auth-scaffolding route — even as a "proxy" for testing the OWASP
control the AC names.

  Trigger conditions (any one disqualifies an auth-route test):
    • Neither `action` nor any AC mentions auth, register, login, logout,
      session, JWT, token, or password.
    • The OWASP mapping is one of A01 (Broken Access Control) on a
      NON-auth resource (e.g. tasks, projects, files), A03 in a
      NON-credential input field, A04, A05, A08, A09.
    • The retrieved source context does not include an auth router file
      (no `auth_router.py`, no `login`/`register` endpoint definitions).

  Allowed when:
    • The requirement's `action` literally contains "login", "register",
      "logout", "reset password", "refresh token", or
    • At least one AC text describes credential, session, or token behavior.

  Why: a story about "task sharing IDOR" producing tests for SQLi-on-
  /register is non-grounded — the test exercises a different feature, and
  any verdict (vulnerable / resilient) attaches to the wrong AC. Emit a
  `coverage_gaps` entry naming the in-scope route you would need instead.

### 10b — No backend-query tests when the feature is client-side only
Reinforces RULE 8 with a structural test: if ALL of the following hold,
you MUST NOT emit a backend SQLi / NoSQLi / command-injection test:

  • The retrieved source context contains NO backend router that consumes
    the user-supplied query field (no `@router.get` / `@app.get` /
    `@router.post` handler for the path the AC names).
  • The retrieved frontend context shows the query field is handled by
    client-side filtering (e.g. `.filter(...)`, `useMemo` over a local
    array, Array methods on data already fetched).
  • No SQLAlchemy / ORM call in the retrieved context references the
    field by name.

  When all three hold:
    • Pivot to a CLIENT-SIDE test per Rule 8 (DOM-based XSS, stored-XSS
      via localStorage, prototype pollution) using Playwright assertions.
    • Emit a `coverage_gaps` entry stating the absence of a backend
      query path so the reviewer knows backend SQLi was deliberately not
      tested ("no backend route consumes `search` per retrieved context;
      filtering occurs client-side at TasksList.jsx:142 via .filter()").

  Why: a `GET /tasks/?search=<SQLi>` test against an endpoint that does
  not parse the field server-side returns 200 with normal results and the
  prior classifier flagged it as exploited. The fix at the test layer
  (Stage 2 per-route exploit semantics) handles the false positive but
  the test itself was still wasted budget. Suppress it at the source.

## RULE 11 — SURFACE MAP BINDING (HARD CONSTRAINT, SUPERSEDES RULE 10)

The Surface Resolver (Agent 1.5) has already mapped this requirement to
its testable surface in the codebase. The binding is BINDING STATE —
not a hint, not a default. You cannot override it.

The user prompt below carries a SURFACE BINDING block with:
  - state: BACKEND_API | FRONTEND_ONLY | CLIENT_SIDE_ONLY |
           NOT_IMPLEMENTED | NEEDS_CLARIFICATION
  - backend_endpoints: list of (method, path) you MAY target
  - frontend_surfaces: list of components (future Playwright track)
  - rationale: WHY this binding was chosen — quote it in coverage_gaps
  - grounding_refs: file:line evidence the Resolver relied on

You receive this block ONLY when state == BACKEND_API. For all other
states the Generator skips invoking you entirely; the upstream agent
emits a coverage_gap with the Resolver's rationale. So if you are
reading a SURFACE BINDING block, state IS BACKEND_API by construction.

Hard rules when SURFACE BINDING is present:

  • Every test's `action` MUST start with one of the bound endpoints in
    the form "METHOD /path ...". E.g. if backend_endpoints lists
    `{{"method": "GET", "path": "/tasks/"}}`, valid actions begin with
    "GET /tasks/" or "GET /tasks". Tests against any other path are
    INVALID OUTPUT and will be DROPPED by post-validation.

  • Adversarial tests target the SAME bound endpoints. You may NOT
    emit a SQLi-on-/register test as a "proxy" for testing a search
    requirement bound to /tasks/. The Resolver already considered
    cross-cutting paths and declined to bind them.

  • If you genuinely believe the binding is wrong, emit a coverage_gap
    with reason "RULE 11: binding disagreement — <evidence>" and the
    operator can patch the binding via surface_overrides/<story>.json.
    Do NOT silently emit off-binding tests.

This rule is the typed contract version of Rule 10. Rule 10 was a
prompt heuristic; Rule 11 is enforced by post-LLM validation. Off-
binding tests are not passed through to the Compiler.

## RULE 11b — ANTI-PATTERN TRANSLATION (when DEFENSIVE_INVERTED is set)

The Surface Resolver's threat-class classifier may mark a requirement
as DEFENSIVE_INVERTED. The story's narrator wrote anti-pattern language
— the Critic flagged it as a security risk because the INVERSE
(rejection / hiding / filtering) is the real defense. The Resolver
located the defense and emitted a `defense_kind` telling you which
test shape to emit.

When the SURFACE BINDING block includes `defense_kind` and
`defense_assertion`, your tests MUST verify the DEFENSE. The right
test shape DEPENDS ON THE KIND. Do NOT force 4xx on every kind — kinds
3/4/5 below succeed with 200 / 5xx by design.

Universal rules for any DEFENSIVE_INVERTED test:
  • test_category MUST be "security"
  • is_adversarial MUST be true
  • input_data exercises the anti-pattern (1000-char input, sqli
    payload, peer-user id, error-inducing payload, etc.)
  • coverage_rationale QUOTES the defense_assertion AND names the
    defense mechanism found in the retrieved code
  • Title frames the test as verifying the defense, NOT confirming the
    anti-pattern

Per-kind rules:

### defense_kind = INPUT_REJECTION
  Anti-pattern: "accept any length", "allow malformed input",
                "unlimited retries", "no rate limit"
  Defense: Pydantic validator, length cap, auth gate, rate-limiter
  → expected_status_code in {{400, 401, 403, 422, 429}}
  → forbidden_response_content includes leakage indicators:
      ["Traceback", "psycopg2", "sqlite3.", "SQLSTATE",
       "OperationalError"]
  Example (login REQ-001):
      title: "Reject 1000-char email at /register"
      action: "POST /register with 1000-char email"
      input_data: {{{{"email": "<STRING:len=1000>@x.com", "password": "Sentinel1!"}}}}
      expected_status_code: 422

### defense_kind = TRANSPORT
  Anti-pattern: "transmit session token over HTTP", "no TLS required"
  Defense: HTTPSRedirectMiddleware, HSTS header, Secure cookie flag
  → expected_status_code in {{301, 302, 307, 308}}
  → response_match_regex includes "Strict-Transport-Security" header
    presence OR "Location: https://" pattern
  Example (login REQ-004):
      title: "GET /tasks/ over http:// redirects to https://"
      expected_status_code: 301

### defense_kind = OUTPUT_REDACTION
  Anti-pattern: "show internal IDs / system fields / password hashes
                in response", "display PII", "expose secrets"
  Defense: response_model excludes field, by_alias, exclude_none,
           serializer hides field
  → expected_status_code = 200 (the request SUCCEEDS; defense is
    that sensitive content is REDACTED)
  → forbidden_response_content REQUIRED: list the specific keys
    that the defense must strip
      ["password_hash", "_password", "salt", "raw_password",
       "deleted_at" if soft-delete is the defense]
  Example (search REQ-002 "show internal IDs"):
      title: "GET /tasks/ response does not leak password_hash"
      action: "GET /tasks/ as authenticated user"
      expected_status_code: 200
      forbidden_response_content: ["password_hash", "hashed_password",
                                    "salt"]

### defense_kind = IMPLICIT_FILTER
  Anti-pattern: "show records across all users", "see private items",
                "list deleted entries"
  Defense: ORM filter (Task.user_id == current_user.id),
           soft-delete (deleted_at IS NULL), tenant scoping
  → expected_status_code = 200 (request SUCCEEDS; defense is that
    unauthorized rows are FILTERED OUT)
  → forbidden_response_content includes IDs/titles of seed rows
    belonging to OTHER users — those must NOT appear
  → setup_fixtures MUST seed at least: (a) the test user, (b) a
    DIFFERENT user's row, then assert the response does not contain
    that other row
  Example (search REQ-003 "show all users' records"):
      title: "GET /tasks/ as user A does not return user B's tasks"
      action: "GET /tasks/ as user A"
      setup_fixtures: ["Seed user A and user B; seed task 'B-secret'
                        owned by user B"]
      expected_status_code: 200
      forbidden_response_content: ["B-secret"]

### defense_kind = ERROR_SANITIZATION
  Anti-pattern: "display SQL query / database error / stack trace
                to users", "verbose 500 messages"
  Defense: global exception handler, generic 500 message, no DEBUG
           in production
  → expected_status_code in {{500, 503}}
  → forbidden_response_content REQUIRED — list the SQL/stack tokens
    that must NOT appear in the body:
      ["Traceback", "psycopg2", "sqlite3.", "SQLSTATE",
       "OperationalError", "ProgrammingError",
       "near \\"--\\"", "unterminated", "psycopg2.errors"]
  Example (search REQ-005 "leak SQL errors"):
      title: "Invalid input does not leak SQL fragments in 500 body"
      action: "POST /register with input that triggers DB error"
      expected_status_code: 500
      forbidden_response_content: ["Traceback", "psycopg2",
                                    "sqlite3.", "SQLSTATE"]

VIOLATION HANDLING:
  • A test asserting `expected_status_code: 200` for an
    INPUT_REJECTION binding (i.e. confirming the insecure behavior
    works) will be DROPPED by post-validation.
  • A test asserting `expected_status_code: 4xx` for an
    OUTPUT_REDACTION or IMPLICIT_FILTER binding (i.e. mis-applying
    rejection-kind logic to redaction-kind defenses) will be DROPPED.
  • A test for ERROR_SANITIZATION asserting 200 (i.e. expecting the
    error to be hidden) will be DROPPED — the error MUST surface;
    only its details are scrubbed.

============================================================
TEST GENERATION DISCIPLINE
============================================================

Required ratio per requirement (enforce approximately):
  - ~20% Positive   (happy path, success cases)
  - ~35% Negative   (input validation, type mismatch, empty/null)
  - ~20% Boundary   (max length, min value, overflow, off-by-one)
  - ~25% Security   (OWASP: injection, bypass, XSS, auth)
  - When the AC describes a multi-step API lifecycle (create → read → update →
    delete), emit at least one `state_transition` test instead of four unrelated
    single-shot tests.

============================================================
STATE_TRANSITION TESTS (5th category — workflow / API lifecycle)
============================================================

Use `test_category = "state_transition"` when ONE test must prove an ordered
sequence against the SAME resource (e.g. POST create → GET by id → PATCH →
DELETE → GET 404). This is NOT security/adversarial — set `is_adversarial` false.

Rules:
  • Emit `workflow_steps`: an ordered array (minimum 2 steps).
  • Each step: method, path, input_data (object, may be {{}}), expected_status_code.
  • Use FastAPI path templates in `path` (e.g. `/tasks/{{task_id}}`). After a step
    that creates a resource, set `capture_json_key` to the response field holding
    the id (usually `"id"`). The runner substitutes `{{task_id}}` from that capture.
  • `action` MUST summarize the full chain (e.g. "POST /tasks/ then GET /tasks/{{task_id}}").
  • `expected_status_code` on the TestCase = the LAST step's expected code.
  • `setup_fixtures` must include JWT seeding when routes require auth.
  • Do NOT use `_repeat` in workflow tests.

Example workflow_steps for soft-delete lifecycle:
  [
    {{"method": "POST", "path": "/tasks/", "input_data": {{"title": "Probe", "priority": "High", "status": "Active"}}, "expected_status_code": 201, "capture_json_key": "id"}},
    {{"method": "GET", "path": "/tasks/{{task_id}}", "expected_status_code": 200, "expected_json_keys": ["id", "title"]}},
    {{"method": "PATCH", "path": "/tasks/{{task_id}}", "input_data": {{"priority": "Low"}}, "expected_status_code": 200}},
    {{"method": "DELETE", "path": "/tasks/{{task_id}}", "expected_status_code": 200}},
    {{"method": "GET", "path": "/tasks/{{task_id}}", "expected_status_code": 404}}
  ]

For every TestCase:
1. `covered_requirement_id` + `covered_acceptance_criterion` trace to exactly
   one AC. Set `test_category` (positive / negative / boundary / security /
   state_transition).
2. `source_refs` lists the `path:start-end` headers from the SOURCE CONTEXT
   that you actually relied on. Empty list is allowed. Fabricated paths are NOT.
3. `setup_fixtures` (REQUIRED) — declare the pre-state the runner must seed
   before executing. Each entry is a single imperative sentence. Examples:
     - "Seed DB with user test@example.com (password hash for 'Correct!123')"
     - "Ensure no user exists with email duplicate@example.com"
     - "Seed DB with project id=42 owned by user test@example.com"
     - "Issue a valid JWT for user test@example.com and attach as Bearer token"
   If a test truly has no precondition (e.g. anonymous health check), emit
   `["none"]`. An EMPTY LIST is not allowed — tests must declare their state
   dependencies explicitly.
4. Technical assertions (populate ALL applicable fields):
     - `expected_status_code`: a SINGLE integer (emit separate tests for
       multiple possible statuses; no arrays)
     - For POST /login use OAuth2 form fields: `username` (email) and
       `password` — not `email` alone (the harness maps email→username).
     - `expected_json_keys`: list, grounded in the retrieved response schema
     - `forbidden_response_content`: strings that MUST NOT appear in the
       response (e.g. "SQL", "stack trace", "bcrypt", "hashed_password",
       "Traceback")
     - `response_match_regex`: optional
     - `boundary_value_used`: MANDATORY for boundary tests, cite the exact
       value tested (e.g. "256 chars (max+1 for VARCHAR(255))")
5. `coverage_rationale` must state (a) which AC is satisfied, (b) WHY the
   chosen `input_data` exercises that AC, and (c) for boundary tests, the
   exact numeric/length boundary being probed.
6. When a string of a SPECIFIC character length is required, emit the
   placeholder `<STRING:len=N>` as the value — the runtime will expand it
   to exactly N alphanumeric characters. For dates/datetimes (especially
   `due_date`), NEVER emit literal calendar dates — they go stale. Use
   `<DATETIME:future:Nd>` (N days ahead, UTC) or `<TODAY_ISO_UTC>` (alias
   for tomorrow UTC). Use literal strings only when the exact content
   matters (a specific email, a named duplicate, etc.).
7. If an AC is UNVERIFIABLE ("fast", "intuitive", "secure" with no measurable
   threshold) OR the retrieved context is insufficient to ground a test, do
   NOT invent one — emit a `coverage_gaps` entry instead.
8. TEST-DESIGN TECHNIQUE (ISTQB / ISO 29119-4). For each test, set
   `test_technique` to the design discipline it embodies:
     - equivalence_partition : one representative test per INPUT CLASS
     - boundary_value        : a value at/adjacent to a limit (min, max, ±1)
     - decision_table        : one row of a condition→action table
     - state_transition      : an ordered multi-step workflow (workflow_steps)
     - requirements_based     : a direct AC restatement with no sharper technique
     - security_adversarial   : an attack/abuse case (adversarial)
   EQUIVALENCE PARTITIONING — for each input field a requirement validates,
   enumerate its CLASSES and emit at least one test per MEANINGFUL class
   (do NOT emit two tests for the same class):
     valid              — a representative in-range value
     invalid-empty      — missing/empty/null
     invalid-type       — wrong type / malformed
     invalid-boundary   — just outside the accepted range (pairs with boundary_value)
     auth-missing       — required auth absent (where applicable)
   Tag each such test with `equivalence_class` naming its class. One test per
   class is the goal — breadth of classes over depth of duplicates.
9. Output STRICT JSON. No prose, no markdown fences, no trailing commentary.

============================================================
OUTPUT SCHEMA
============================================================
{{
  "test_cases": [
    {{
      "title": "<short imperative>",
      "action": "<single verb phrase>",
      "input_data": {{"<field>": "<value>"}},
      "setup_fixtures": ["Seed DB with ..."],
      "expected_result": "<observable, assertable outcome>",
      "expected_status_code": <single integer>,
      "expected_json_keys": ["key1", "key2"],
      "forbidden_response_content": ["error_keyword1"],
      "response_match_regex": "<optional regex>",
      "boundary_value_used": "<exact value used for boundary tests>",
      "test_category": "positive|negative|boundary|security|state_transition",
      "test_technique": "equivalence_partition|boundary_value|decision_table|state_transition|requirements_based|security_adversarial",
      "equivalence_class": "<class name when test_technique=equivalence_partition, e.g. invalid-empty; else null>",
      "workflow_steps": [
        {{
          "method": "POST|GET|PATCH|DELETE|PUT",
          "path": "/tasks/ or /tasks/{{task_id}}",
          "input_data": {{}},
          "expected_status_code": 201,
          "capture_json_key": "id",
          "expected_json_keys": []
        }}
      ],
      "coverage_rationale": "Satisfies AC '<criterion>' of <REQ-ID>. ...",
      "covered_requirement_id": "<REQ-ID>",
      "covered_acceptance_criterion": "<criterion text>",
      "source_refs": ["<path:start-end from source context>"],
      "is_adversarial": false,
      "attestation_mode": null,
      "vulnerability_signature": null,
      "resilience_signature": null
    }}
  ],
  "coverage_gaps": [
    {{
      "acceptance_criterion": "<criterion text or null>",
      "reason": "<why this AC cannot be objectively tested OR why the "
                "retrieved context was insufficient>"
    }}
  ]
}}

============================================================
ADVERSARIAL FIELD CONTRACT (HARD CONSTRAINT)
============================================================

These four fields drive the security posture the dashboard reports. If
you get them wrong, the verdict UI lies. Treat them as authoritative
metadata.

  is_adversarial
    true  when test_category is "security" AND the test exercises an
          attacker action (XSS payload, brute-force loop, SQLi probe,
          IDOR, missing-control demonstration, etc.).
    false otherwise (positive / negative / boundary functional tests).

  attestation_mode  — REQUIRED when is_adversarial is true.
                      MUST be null otherwise.

    "missing_control"
        The required defense is ABSENT in the retrieved code; this test
        documents the gap. Pytest pass = gap reproduced = vulnerable.
        Use whenever:
          - the SURFACE BINDING block declares
            attestation_mode: missing_control, OR
          - the Critic flagged a security risk for this REQ AND retrieval
            does not show a corresponding defense (validator, rate-limit,
            sanitizer, header, anti-enumeration response shape).

    "defense_confirming"
        The defense IS present in the retrieved code; this test verifies
        it holds. Pytest pass = defense held = resilient.
        Use whenever:
          - the SURFACE BINDING block declares
            attestation_mode: defense_confirming, OR
          - the binding's threat_class is DEFENSIVE_INVERTED with a
            defense_kind set (Rule 11b).

    INHERITANCE: when the SURFACE BINDING block explicitly states an
    attestation_mode, every adversarial test you emit for this REQ
    MUST carry that same value. The binding is the single source of
    truth — do not flip it based on your own reading of the test.

  vulnerability_signature
    Required when attestation_mode is "missing_control". One sentence
    describing what an exploited / unprotected response looks like
    (e.g. "16 sequential POST /register all return 201; no Retry-After"
    or "title field round-trips '<script>' verbatim in response body").

  resilience_signature
    Required when attestation_mode is "missing_control". One sentence
    describing what a patched/resilient response would look like
    (e.g. "16th POST /register returns 429 with Retry-After header"
    or "title field stored with HTML escaped").

VIOLATION HANDLING:
  - Adversarial tests with attestation_mode = null will be flagged
    UNCLASSIFIED. They are NOT counted as resilient or vulnerable —
    they appear in a separate "unclassified" bucket and the dashboard
    surfaces them as a coverage problem.
  - Setting attestation_mode = "defense_confirming" on a test that
    actually documents a gap (e.g. titled "User Enumeration") will
    return the wrong verdict. If you see a gap, emit "missing_control"
    even when your test title sounds defensive.
"""


GENERATOR_USER_PROMPT = """Requirement under test:
  ID: {requirement_id}
  Statement: {statement}
  OWASP mapping: {owasp_mapping}
  Acceptance Criteria:
{acceptance_criteria_block}

{surface_binding_block}

REQUIRED TEST GENERATION RATIO: ~20% Positive · ~35% Negative · ~20% Boundary · ~25% Security.

The SOURCE CONTEXT below is a VERTICAL SLICE for the action "{action}". It was
retrieved with FIVE targeted queries against the indexed source tree:
  (1) Router / API endpoint definition
  (2) Pydantic request & response schemas
  (3) Database / SQLAlchemy models
  (4) Frontend rendering (React JSX / TSX)
  (5) Frontend API client config (axios / fetch / baseURL / VITE_API_URL)

Treat these five sections together as the COMPLETE authoritative contract
for this feature. A field is grounded if it appears in ANY section — use the
layer that matches the assertion (JSON for schema, DOM for frontend, row
shape for models, request scheme for api-client). Fields absent from ALL
FIVE sections DO NOT EXIST.
Validation rules absent from these snippets DO NOT APPLY. If the router uses
OAuth2PasswordRequestForm, obey Rule 2. If the AC describes a control the
code does NOT implement (rate limit, lockout, CSRF, audit), obey Rule 4 —
emit a security test that demonstrates the missing control, not a coverage gap.

----- BEGIN SOURCE CONTEXT (VERTICAL SLICE) -----
{source_context}
----- END SOURCE CONTEXT -----

Emit STRICT JSON only, following the schema exactly. Every test_case MUST set
`test_category` AND `setup_fixtures` (use ["none"] for stateless tests)."""

# ------------------------------------------------------------------ #
# PRE_CODE prompts — no codebase, output DesignContracts
# ------------------------------------------------------------------ #

DESIGN_CONTRACT_SYSTEM_PROMPT = """You are Agent B in PRE_CODE mode — a senior API
designer for HPE's Sentinel-QA pipeline. No codebase exists yet. Your job is to
output a precise API contract for each Acceptance Criterion so developers know
exactly what to build before writing a line of code.

Output STRICT JSON only, no prose, no markdown fences.

OUTPUT SCHEMA:
{{
  "design_contracts": [
    {{
      "requirement_id": "<REQ-ID>",
      "endpoint": "<e.g. POST /auth/login>",
      "method": "<GET|POST|PUT|PATCH|DELETE>",
      "request_fields": {{"<field_name>": "<type e.g. string|int|bool>"}},
      "response_fields": {{"<field_name>": "<type>"}},
      "error_codes": {{"<status_code>": "<meaning>"}},
      "validation_rules": ["<rule e.g. 'email must be valid format'>"],
      "notes": "<optional clarifications>"
    }}
  ]
}}
Rules:
- One DesignContract per distinct endpoint implied by the ACs.
- Infer only what the ACs explicitly state — do NOT invent fields.
- If an AC implies a field but its type is ambiguous, use "string".
- error_codes keys must be strings e.g. "401", "422" — not integers.
- validation_rules must be direct quotes or close paraphrases of the AC text.
- notes should flag any AC ambiguity the developer must resolve.
"""

DESIGN_CONTRACT_USER_PROMPT = """Requirement:
  ID: {requirement_id}
  Statement: {statement}
  Acceptance Criteria:
{acceptance_criteria_block}

Output STRICT JSON only."""


# --------------------------------------------------------------------------- #
# Retrieval helpers
# --------------------------------------------------------------------------- #

def _build_action_descriptor(req: ValidatedRequirement) -> str:
    """Extract a short, targeted action phrase for multi-query expansion.

    The action descriptor drives three ChromaDB queries — it wants to be
    concrete enough to match real router / schema / model text, but short
    enough that the embedding stays focused. We combine the requirement
    statement with the first AC (if present) and clamp the length.
    """
    base = (req.statement or "").strip()
    if req.acceptance_criteria:
        first_ac = req.acceptance_criteria[0].strip()
        if first_ac and first_ac.lower() not in base.lower():
            base = f"{base} — {first_ac}"
    return (base or "the requested feature")[:240]


def _extract_ac_keywords(req: ValidatedRequirement) -> str:
    """Extract distinct keywords from Acceptance Criteria to guide RAG retrieval."""
    if not req.acceptance_criteria:
        return ""
    text = " ".join(req.acceptance_criteria)
    # Simple heuristic: grab words longer than 3 chars, ignoring common stop words
    words = re.findall(r'\b[A-Za-z_]{4,}\b', text)
    stop_words = {
        "this", "that", "with", "from", "when", "then", "given", "must", 
        "should", "will", "user", "system", "does", "have", "been", "only"
    }
    keywords = list(set(w for w in words if w.lower() not in stop_words))
    return " ".join(keywords)


# Word-boundary patterns for route-intent classification. Kept deliberately
# small and conservative: when in doubt we fall through to UNKNOWN and let
# the union query run (legacy behavior).
_AUTH_INTENT_RE = re.compile(
    r"\b(log\s*in|login|sign\s*in|sign-?in|signin|authenticate|authentication|"
    r"log\s*out|logout|sign\s*out|signout|session|jwt|token)\b",
    re.IGNORECASE,
)
_WRITE_INTENT_RE = re.compile(
    r"\b(register|registration|sign\s*up|signup|create|creates|creating|insert|"
    r"add|adds|adding|submit|submits|save|saves|post|posts|posting|"
    r"update|updates|updating|edit|edits|editing|modify|modifies|patch|"
    r"delete|deletes|deleting|remove|removes|removing|destroy|destroys|"
    r"upload|uploads|uploading)\b",
    re.IGNORECASE,
)
_LOOKUP_INTENT_RE = re.compile(
    r"\b(read|reads|reading|fetch|fetches|fetching|retrieve|retrieves|"
    r"retrieving|list|lists|listing|get|gets|getting|view|views|viewing|"
    r"display|displays|displaying|show|shows|showing|load|loads|loading|"
    r"search|searches|searching|query|queries|querying|lookup|look\s*up|"
    r"find|finds|finding|browse|browses|browsing|dashboard|render|rendered|"
    r"rendering)\b",
    re.IGNORECASE,
)


def _classify_route_intent(req: ValidatedRequirement) -> RouteIntent:
    """Classify a requirement as LOOKUP vs WRITE from its natural-language text.

    Priority:
      1. AUTH keywords (login/logout/session/jwt) → LOOKUP. Auth wins even
         when 'submit' / 'post' / 'send' appear — login endpoints are
         SELECT-driven even though they accept POST bodies.
      2. Explicit WRITE verbs (register/create/update/delete/…) → WRITE.
      3. Explicit LOOKUP verbs (read/fetch/display/…) → LOOKUP.
      4. Otherwise UNKNOWN (retrieval falls back to union query).

    The classifier reads both the requirement statement and the acceptance
    criteria so a statement like "the login form must accept any password"
    is still classified as LOOKUP when the ACs are the more descriptive
    "Given a login form, When a password with 1000+ characters is entered".
    """
    text_parts: List[str] = [req.statement or ""]
    text_parts.extend(req.acceptance_criteria or [])
    text = " \n ".join(text_parts)

    if _AUTH_INTENT_RE.search(text):
        return RouteIntent.LOOKUP
    if _WRITE_INTENT_RE.search(text):
        return RouteIntent.WRITE
    if _LOOKUP_INTENT_RE.search(text):
        return RouteIntent.LOOKUP
    return RouteIntent.UNKNOWN


# --------------------------------------------------------------------------- #
# Payload normalization
# --------------------------------------------------------------------------- #

def _format_acceptance_criteria(criteria: List[str]) -> str:
    if not criteria:
        return "  (none supplied — treat entire statement as the implicit AC)"
    return "\n".join(f"  - {c}" for c in criteria)


def _to_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def _coerce_status_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        return int(match.group(0)) if match else None
    if isinstance(value, list):
        for item in value:
            coerced = _coerce_status_code(item)
            if coerced is not None:
                return coerced
    return None


_WORKFLOW_PATH_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
_WORKFLOW_PROBE_UUID = "00000000-0000-4000-8000-000000000001"


def _probe_workflow_path(path: str) -> str:
    """Replace ``{task_id}``-style segments so Rule 11 can match templates."""
    return _WORKFLOW_PATH_PLACEHOLDER_RE.sub(_WORKFLOW_PROBE_UUID, path)


def _canonical_task_crud_workflow(
    req: ValidatedRequirement,
    idx: int,
    retrieved_refs: List[str],
) -> Dict[str, Any]:
    """Deterministic state_transition test for LIFE-001 when the LLM omits workflow_steps."""
    return {
        "title": "Full task CRUD lifecycle via API (state_transition)",
        "action": (
            "POST /tasks/ then GET /tasks/{task_id} then PATCH /tasks/{task_id} "
            "then DELETE /tasks/{task_id} then GET /tasks/{task_id}"
        ),
        "test_category": "state_transition",
        "workflow_steps": [
            {
                "method": "POST",
                "path": "/tasks/",
                "input_data": {
                    "title": "Sentinel lifecycle probe",
                    "priority": "High",
                    "status": "Active",
                },
                "expected_status_code": 201,
                "capture_json_key": "id",
                "expected_json_keys": ["id", "title"],
            },
            {
                "method": "GET",
                "path": "/tasks/{task_id}",
                "expected_status_code": 200,
                "expected_json_keys": ["id", "title", "priority"],
            },
            {
                "method": "PATCH",
                "path": "/tasks/{task_id}",
                "input_data": {"priority": "Low"},
                "expected_status_code": 200,
            },
            {
                "method": "DELETE",
                "path": "/tasks/{task_id}",
                "input_data": {},
                "expected_status_code": 200,
            },
            {
                "method": "GET",
                "path": "/tasks/{task_id}",
                "expected_status_code": 404,
            },
        ],
        "setup_fixtures": [
            "Issue a valid JWT for the test user and attach as Bearer token",
        ],
        "expected_result": (
            "Task is created, read, updated, soft-deleted, then absent on final GET"
        ),
        "expected_status_code": 404,
        "coverage_rationale": (
            f"Satisfies CRUD lifecycle ACs for {req.requirement_id} in one ordered "
            "state_transition test (ISTQB state-transition technique)."
        ),
        "covered_requirement_id": req.requirement_id,
        "covered_acceptance_criterion": (req.acceptance_criteria or [""])[0],
        "source_refs": retrieved_refs[:3],
        "is_adversarial": False,
    }


_VALID_TECHNIQUES = {
    "equivalence_partition", "boundary_value", "decision_table",
    "state_transition", "requirements_based", "security_adversarial",
}


def _infer_test_technique(normalized: Dict[str, Any]) -> str:
    """Map a test case to its ISTQB/ISO-29119-4 design technique.

    Honors an explicit `test_technique` from the LLM if it's a known value;
    otherwise infers from shape + category. Inference order (most specific
    first):
      workflow_steps present        -> state_transition
      adversarial / security        -> security_adversarial
      explicit equivalence_class    -> equivalence_partition
      boundary category / value     -> boundary_value
      positive|negative category    -> equivalence_partition
      everything else               -> requirements_based
    """
    explicit = (normalized.get("test_technique") or "").strip().lower()
    if explicit in _VALID_TECHNIQUES:
        return explicit

    if normalized.get("workflow_steps"):
        return "state_transition"
    cat = (normalized.get("test_category") or "").strip().lower()
    if normalized.get("is_adversarial") or cat == "security":
        return "security_adversarial"
    if normalized.get("equivalence_class"):
        return "equivalence_partition"
    if cat == "boundary" or (normalized.get("boundary_value_used") or "").strip():
        return "boundary_value"
    if cat in ("positive", "negative"):
        return "equivalence_partition"
    return "requirements_based"


def _normalize_workflow_steps(value: Any) -> List[Dict[str, Any]]:
    """Normalize LLM-emitted workflow_steps for state_transition tests."""
    if not value or not isinstance(value, list):
        return []
    steps: List[Dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        method = str(raw.get("method") or "GET").strip().upper()
        path = str(raw.get("path") or "/").strip()
        if not path.startswith("/"):
            path = "/" + path
        inp = raw.get("input_data") or {}
        if not isinstance(inp, dict):
            inp = {}
        code = _coerce_status_code(raw.get("expected_status_code"))
        if code is None:
            continue
        step: Dict[str, Any] = {
            "method": method,
            "path": path,
            "input_data": inflate_placeholders(inp),
            "expected_status_code": code,
        }
        cap = raw.get("capture_json_key")
        if cap:
            step["capture_json_key"] = str(cap).strip()
        ej = _to_str_list(raw.get("expected_json_keys"))
        if ej:
            step["expected_json_keys"] = ej
        steps.append(step)
    return steps


# Framework error-envelope keys that legitimately appear in EVERY FastAPI /
# Pydantic error body. Forbidding them is always a test defect — a 422/4xx
# response is literally `{"detail":[{"loc":[...],"msg":"...","type":"..."}]}`.
_ENVELOPE_KEYS = {
    "detail", "loc", "msg", "type", "ctx", "input", "url", "errors",
}

# High-signal leakage tokens that ARE legitimate forbidden content even on a
# validation response — these indicate the app spilled internals. Never
# stripped. Substring match, lowercased.
_LEAKAGE_ALLOWLIST = (
    "traceback", "psycopg2", "sqlite3", "sqlstate", "operationalerror",
    "programmingerror", "integrityerror", "stack trace", "stacktrace",
    "password_hash", "hashed_password", "passwordhash", "salt", "secret",
    "private_key", "bearer ", "authorization:", 'near "--"', "syntax error",
    "unterminated", "/users/", "/home/", "c:\\\\", "file \"",
)

# Validation status codes whose bodies STRUCTURALLY echo the offending field
# name (Pydantic loc/msg). A negative test that posts a missing/short `title`
# and forbids "title" contradicts itself — the 422 body names the field.
_VALIDATION_STATUSES = {400, 422}
_SUCCESS_STATUSES = frozenset(range(200, 300))


def _collect_input_strings(value: Any) -> List[str]:
    """Gather all string leaf values from nested input_data."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: List[str] = []
        for v in value.values():
            out.extend(_collect_input_strings(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_collect_input_strings(v))
        return out
    return []


def _sanitize_forbidden_content(
    forbidden: List[str],
    *,
    input_data: Any,
    expected_json_keys: List[str],
    expected_status_code: Optional[int],
) -> Tuple[List[str], List[str]]:
    """Strip self-contradictory tokens from forbidden_response_content.

    Returns (kept, dropped). The Generator routinely poisons this field with
    legitimate response/field names, producing FALSE functional failures
    (lifecycle TC-REQ-001-03/04/06 forbade "title" on a 422 that names the
    title field; 003-02 forbade "detail", the error envelope key). None of
    those are app bugs — they are test defects the pipeline then counted as
    red and chased with patches.

    Removal rules (a token is dropped if ANY fires):
      1. It is a framework envelope key (detail/loc/msg/...).
      2. It equals a request input field name (you can't forbid what you sent).
      3. It equals an expected_json_key (contradictory: expect AND forbid).
      4. The response is a validation error (400/422) AND the token is not a
         high-signal leakage indicator — on these structured bodies, only
         genuine internals-leakage (Traceback, SQL tokens, password_hash)
         is a valid forbidden assertion; field-name echoes are not.
      5. The expected status is a success (2xx) AND the token appears inside
         a request input value — a 201/200 body often echoes submitted fields
         (SQLi payloads in description, etc.); forbidding the literal attack
         string on success is self-contradictory unless it is a leakage token.

    Legitimate OUTPUT_REDACTION / IMPLICIT_FILTER / ERROR_SANITIZATION
    forbidden lists (password_hash on 200, peer ids on 200, Traceback on 500)
    are preserved because they are 2xx/5xx and/or on the leakage allowlist.
    """
    if not forbidden:
        return [], []

    input_keys = set()
    if isinstance(input_data, dict):
        input_keys = {str(k).strip().lower() for k in input_data.keys()}
    expected_keys = {str(k).strip().lower() for k in (expected_json_keys or [])}
    is_validation = expected_status_code in _VALIDATION_STATUSES
    is_success = expected_status_code in _SUCCESS_STATUSES
    input_strings = _collect_input_strings(input_data)

    def _is_leakage(tok: str) -> bool:
        t = tok.lower()
        return any(sig in t for sig in _LEAKAGE_ALLOWLIST)

    kept: List[str] = []
    dropped: List[str] = []
    for raw in forbidden:
        tok = (raw or "").strip()
        if not tok:
            continue
        low = tok.lower()
        if low in _ENVELOPE_KEYS:
            dropped.append(tok); continue
        if low in input_keys:
            dropped.append(tok); continue
        if low in expected_keys:
            dropped.append(tok); continue
        if is_validation and not _is_leakage(tok):
            dropped.append(tok); continue
        if is_success and not _is_leakage(tok):
            if any(tok.lower() in s.lower() for s in input_strings):
                dropped.append(tok); continue
        kept.append(tok)
    return kept, dropped


def _normalize_setup_fixtures(value: Any) -> List[str]:
    fixtures = _to_str_list(value)
    fixtures = [f.strip() for f in fixtures if f and f.strip()]
    if not fixtures:
        # Never let a test go out with undeclared state — force an explicit
        # "none" marker so reviewers can see the Generator considered it.
        return ["none"]
    return fixtures


def _normalize_test_case_payload(
    tc: Dict[str, Any],
    req: ValidatedRequirement,
    idx: int,
    retrieved_refs: List[str],
) -> Dict[str, Any]:
    normalized = dict(tc)

    normalized.setdefault("covered_requirement_id", req.requirement_id)
    normalized["test_id"] = f"TC-{req.requirement_id}-{idx:02d}"

    source_refs = normalized.get("source_refs")
    if not source_refs and retrieved_refs:
        source_refs = retrieved_refs[:3]
    normalized["source_refs"] = _to_str_list(source_refs)

    input_data = normalized.get("input_data", {})
    if not isinstance(input_data, (dict, list)):
        input_data = {"value": str(input_data)}
    normalized["input_data"] = inflate_placeholders(input_data)

    normalized["setup_fixtures"] = _normalize_setup_fixtures(
        normalized.get("setup_fixtures")
    )

    workflow_steps = _normalize_workflow_steps(normalized.get("workflow_steps"))
    normalized["workflow_steps"] = workflow_steps

    # P1 — infer the formal test-design technique when the LLM omits it.
    normalized["test_technique"] = _infer_test_technique(normalized)
    if normalized.get("equivalence_class") is not None:
        normalized["equivalence_class"] = str(normalized["equivalence_class"]).strip() or None

    expected_result = normalized.get("expected_result")
    if expected_result is None:
        expected_result = "Expected outcome matches acceptance criterion"
    normalized["expected_result"] = inflate_placeholders(str(expected_result))

    normalized["expected_status_code"] = _coerce_status_code(
        normalized.get("expected_status_code")
    )

    normalized["expected_json_keys"] = _to_str_list(normalized.get("expected_json_keys"))
    # Fix #1 — sanitize forbidden_response_content before it can drive a false
    # functional failure. See _sanitize_forbidden_content for the rules.
    _forbidden_kept, _forbidden_dropped = _sanitize_forbidden_content(
        _to_str_list(normalized.get("forbidden_response_content")),
        input_data=normalized.get("input_data"),
        expected_json_keys=normalized["expected_json_keys"],
        expected_status_code=normalized.get("expected_status_code"),
    )
    normalized["forbidden_response_content"] = _forbidden_kept
    if _forbidden_dropped:
        normalized["_forbidden_dropped"] = _forbidden_dropped
    normalized["mutated_fields"] = _to_str_list(normalized.get("mutated_fields"))

    if normalized.get("response_match_regex") is not None:
        normalized["response_match_regex"] = str(normalized["response_match_regex"])

    string_fields = [
        "title",
        "action",
        "coverage_rationale",
        "boundary_value_used",
        "test_category",
        "covered_acceptance_criterion",
        "resilience_signature",
        "vulnerability_signature",
        "owasp_category",
        "payload",
        "exploit_target",
        "parent_test_id",
    ]
    for field in string_fields:
        if normalized.get(field) is not None:
            normalized[field] = str(normalized[field])

    if "is_adversarial" in normalized:
        normalized["is_adversarial"] = bool(normalized["is_adversarial"])

    # ------------------------------------------------------------------ #
    # P0-4 (Cursor) — enforce contracts for security-category tests.     #
    # ------------------------------------------------------------------ #
    # The system prompt instructs the LLM that security tests must have
    # is_adversarial=True with owasp_category set. The LLM doesn't reliably
    # follow this — observed in exec-demo-login-post_code-20260528_170306
    # where TC-REQ-002-01 ("100 failed login attempts") came back with
    # is_adversarial=False and no owasp_category, so:
    #   1. pytest_runner classified it as a functional test (vs adversarial),
    #      meaning a passing "no rate limit" outcome logs as success rather
    #      than confirming the story's stated weakness.
    #   2. _acceptable_status_codes_for_adversarial fell through to single-int
    #      semantics, producing `_accept = [200]` for tests that should accept
    #      the full A07/A04 resilience list.
    # This block re-asserts both contracts. It does NOT invent owasp_category
    # — it inherits from the requirement's owasp_mapping (Critic's call).
    # When the requirement has no OWASP mapping, we leave owasp_category None
    # rather than fabricate one.
    test_cat = (normalized.get("test_category") or "").strip().lower()
    if test_cat not in ("positive", "negative", "boundary", "security", "state_transition"):
        if normalized.get("is_adversarial"):
            test_cat = "security"
        elif len(workflow_steps) >= 2:
            test_cat = "state_transition"
        elif (normalized.get("boundary_value_used") or "").strip():
            test_cat = "boundary"
        else:
            esc = normalized.get("expected_status_code")
            if esc is not None and int(esc) >= 400:
                test_cat = "negative"
            elif esc is not None and int(esc) < 400:
                test_cat = "positive"
            else:
                test_cat = "uncategorized"
        normalized["test_category"] = test_cat
    if test_cat == "state_transition":
        normalized["is_adversarial"] = False
        if len(workflow_steps) >= 2 and normalized.get("expected_status_code") is None:
            normalized["expected_status_code"] = workflow_steps[-1]["expected_status_code"]
        if workflow_steps:
            summary = " then ".join(
                f"{s['method']} {s['path']}" for s in workflow_steps[:4]
            )
            if not (normalized.get("action") or "").strip():
                normalized["action"] = summary
    if test_cat == "security":
        if not normalized.get("is_adversarial"):
            normalized["is_adversarial"] = True
        if not normalized.get("owasp_category"):
            req_owasp = list(req.owasp_mapping or [])
            if req_owasp:
                normalized["owasp_category"] = req_owasp[0]
        # Inherit exploit_target from owasp_category when absent — gives the
        # security_posture's by_exploit_target bucket a meaningful key
        # instead of the "unknown" leak.
        if (
            normalized.get("is_adversarial")
            and normalized.get("owasp_category")
            and not normalized.get("exploit_target")
        ):
            normalized["exploit_target"] = normalized["owasp_category"]

    return normalized


# --------------------------------------------------------------------------- #
# Layer A — SurfaceMap binding helpers (Rule 11)                              #
# --------------------------------------------------------------------------- #


# Method extraction regex used to read the LLM's emitted `action` and stamp
# bound_method on the TestCase. Tolerant of casing.
_ACTION_METHOD_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE)
_ACTION_PATH_RE = re.compile(r"(/[A-Za-z0-9_\-./{}]*)")


def _escape_template_braces(text: str) -> str:
    """Escape `{` / `}` so ChatPromptTemplate does NOT interpret them as
    variable placeholders.

    Why: the Resolver's bound paths frequently contain FastAPI path-param
    templates like `/tasks/{task_id}`. The Generator's ChatPromptTemplate
    treats single `{name}` as a substitution slot; finding `{task_id}` in
    the binding block causes a `KeyError: 'task_id'` at prompt-render
    time and aborts test generation for that requirement (observed in
    exec-demo-search-post_code-20260529_064454, where REQ-002 — the only
    BACKEND_API binding — failed before any test was emitted, producing
    a 0-test suite).

    Same trick the Resolver's own prompt already uses for its example
    schema (`{{task_id}}` instead of `{task_id}`). Apply at the boundary
    where dynamic, LLM-derived text meets the f-string prompt template.
    """
    return text.replace("{", "{{").replace("}", "}}")


def _render_surface_binding_block(binding: Optional[SurfaceBinding]) -> str:
    """Render the BINDING block included in the user prompt for BACKEND_API.

    Empty string for non-BACKEND_API states because the Generator does not
    invoke the LLM for those — they emit coverage_gap deterministically.
    Including this block is what Rule 11 references in-prompt; the
    post-LLM validator below enforces it.

    NOTE: the returned string passes through `_escape_template_braces`
    before being substituted into the Generator's ChatPromptTemplate.
    See `_escape_template_braces` for why.
    """
    if binding is None or binding.state != "BACKEND_API":
        return ""
    eps_lines = "\n".join(
        f"    - {ep.method} {ep.path}"
        + (f"  (handler: {ep.handler_file}"
           + (f":{ep.handler_line}" if ep.handler_line else "")
           + ")"
           if ep.handler_file else "")
        for ep in binding.backend_endpoints
    ) or "    (none — bug; should not invoke generator)"
    grounding = ", ".join(binding.grounding_refs) or "(none)"

    # Refinement 1.1 — anti-pattern block carries defense_kind so the
    # Generator picks the right test shape. Status-code rules differ per
    # kind (INPUT_REJECTION → 4xx, TRANSPORT → 3xx, OUTPUT_REDACTION → 200
    # + redaction list, IMPLICIT_FILTER → 200 + filtered list,
    # ERROR_SANITIZATION → 5xx + scrubbed body). See Rule 11b in the
    # system prompt for the full table.
    anti_pattern_block = ""
    if (
        binding.threat_class == "DEFENSIVE_INVERTED"
        and binding.defense_assertion
        and binding.defense_kind
    ):
        kind_hint = {
            "INPUT_REJECTION":    "expected_status_code in {400, 401, 403, 422, 429}; clean body",
            "TRANSPORT":          "expected_status_code in {301, 302, 307, 308}; assert HTTPS/HSTS",
            "OUTPUT_REDACTION":   "expected_status_code = 200; forbidden_response_content lists the keys defense must strip",
            "IMPLICIT_FILTER":    "expected_status_code = 200; setup_fixtures seeds a peer row; forbidden_response_content asserts peer's data is absent",
            "ERROR_SANITIZATION": "expected_status_code in {500, 503}; forbidden_response_content lists SQL/stack tokens that must NOT appear",
        }.get(binding.defense_kind, "see Rule 11b for kind-specific rules")
        anti_pattern_block = (
            "\n"
            "ANTI-PATTERN TRANSLATION (Rule 11b — HARD CONSTRAINT):\n"
            f"  threat_class:      DEFENSIVE_INVERTED\n"
            f"  defense_kind:      {binding.defense_kind}\n"
            f"  anti_pattern:      {binding.anti_pattern_summary or '(not specified)'}\n"
            f"  defense_assertion: {binding.defense_assertion}\n"
            f"  test shape:        {kind_hint}\n"
            "Your tests MUST verify the defense for this kind. Mismatched\n"
            "status codes (e.g. 200 for INPUT_REJECTION, or 4xx for\n"
            "OUTPUT_REDACTION) will be DROPPED by post-validation."
        )

    missing_control_block = ""
    if binding.attestation_mode == "missing_control":
        missing_control_block = (
            "\n"
            "MISSING CONTROL ATTESTATION (Rule 4 — HARD CONSTRAINT):\n"
            "  attestation_mode:  missing_control\n"
            "  The required security control is ABSENT from retrieved code.\n"
            "  Emit at least one `security` / `is_adversarial: true` test per AC\n"
            "  that demonstrates the gap on the bound endpoint (e.g. repeated\n"
            "  failed logins all return 401 with no 429 / Retry-After / lockout).\n"
            "  Do NOT emit a coverage_gap for the missing control — absence IS\n"
            "  the finding. Use `_repeat` in input_data for brute-force loops.\n"
            "  `expected_status_code` is what the unprotected app returns today\n"
            "  (usually 401 on /login); `vulnerability_signature` describes the\n"
            "  observed weakness; `resilience_signature` describes the patched app.\n"
            "  EVERY adversarial test you emit for this REQ MUST carry\n"
            "  `attestation_mode: \"missing_control\"` — do not override.\n"
        )
    elif binding.attestation_mode == "defense_confirming":
        missing_control_block = (
            "\n"
            "DEFENSE-CONFIRMING ATTESTATION (HARD CONSTRAINT):\n"
            "  attestation_mode:  defense_confirming\n"
            "  The required defense IS present in retrieved code; verify it holds.\n"
            "  EVERY adversarial test you emit for this REQ MUST carry\n"
            "  `attestation_mode: \"defense_confirming\"` — do not override.\n"
        )

    return (
        "SURFACE BINDING (Rule 11 — HARD CONSTRAINT):\n"
        f"  state: BACKEND_API\n"
        f"  confidence: {binding.confidence}\n"
        f"  rationale: {binding.rationale}\n"
        f"  grounding: {grounding}\n"
        f"  bound endpoints (you MAY emit tests against ONLY these):\n"
        f"{eps_lines}\n"
        + anti_pattern_block
        + missing_control_block + "\n"
        "All tests' `action` field MUST begin with one of the bound\n"
        "endpoints in the form 'METHOD /path ...'. Any test against\n"
        "another path will be DROPPED by post-validation."
    )


def _coverage_gap_for_non_backend(
    req: ValidatedRequirement,
    binding: SurfaceBinding,
) -> CoverageGap:
    """Build the deterministic coverage_gap emitted when state is not
    BACKEND_API. The LLM is NOT invoked — Resolver's rationale is the
    authoritative reason."""
    state_msg = {
        "FRONTEND_ONLY": "Surface is frontend-only (no logic to verify at the API layer)",
        "CLIENT_SIDE_ONLY": "Surface is client-side only (logic in browser; no backend route to test)",
        "NOT_IMPLEMENTED": "No surface for this requirement found in the codebase",
        "NEEDS_CLARIFICATION": "Surface mapping needs stakeholder clarification",
    }.get(binding.state, f"Surface state {binding.state} does not permit API tests")
    grounding = ", ".join(binding.grounding_refs) or "(no grounding)"
    return CoverageGap(
        requirement_id=req.requirement_id,
        acceptance_criterion=None,
        reason=(
            f"[Rule 11 / SurfaceMap] {state_msg}. "
            f"Resolver rationale: {binding.rationale} "
            f"Grounding: {grounding}"
        ),
    )


_DEFENSE_KIND_STATUS_RULES = {
    "INPUT_REJECTION":    ({400, 401, 403, 422, 429},   "INPUT_REJECTION requires 4xx (400/401/403/422/429)"),
    "TRANSPORT":          ({301, 302, 307, 308},        "TRANSPORT requires 3xx redirect (301/302/307/308)"),
    "OUTPUT_REDACTION":   ({200, 201},                  "OUTPUT_REDACTION requires 2xx — defense is body-level"),
    "IMPLICIT_FILTER":    ({200, 201},                  "IMPLICIT_FILTER requires 2xx — defense scopes results"),
    "ERROR_SANITIZATION": ({500, 502, 503, 504},        "ERROR_SANITIZATION requires 5xx — error surfaces, details scrubbed"),
}

# App-wide defenses don't bind to a specific URL path — the defense
# (global exception handler, HTTPSRedirectMiddleware, CORS, HSTS) applies
# across every route. For these the Resolver emits `path: "/"` as a
# sentinel; the Generator may pick any concrete URL the defense will fire
# against, and Rule 11 path-match becomes a no-op.
_APP_WIDE_DEFENSE_KINDS = ("TRANSPORT", "ERROR_SANITIZATION")


def _binding_is_app_wide(binding: SurfaceBinding) -> bool:
    if binding.defense_kind not in _APP_WIDE_DEFENSE_KINDS:
        return False
    paths = {(ep.path or "").strip() for ep in binding.backend_endpoints}
    # Sentinel: every bound endpoint is "/" (or empty) → app-wide.
    return paths.issubset({"/", ""})


def _workflow_allowed_paths(
    binding: SurfaceBinding,
    surface_map: Optional[Dict[str, SurfaceBinding]] = None,
) -> List[str]:
    """Paths a state_transition test may target.

    Single-endpoint bindings (per-REQ Resolver output) cannot satisfy a CRUD
    workflow alone. For lifecycle stories, union all BACKEND_API /tasks*
    endpoints across the surface map.
    """
    paths = [ep.path for ep in binding.backend_endpoints]
    if surface_map:
        for other in surface_map.values():
            if other.state != "BACKEND_API":
                continue
            for ep in other.backend_endpoints:
                if ep.path.startswith("/tasks") and ep.path not in paths:
                    paths.append(ep.path)
    return paths


def _workflow_stamp_for_binding(
    tc: TestCase,
    binding: SurfaceBinding,
) -> Tuple[str, str]:
    """Pick bound_method/bound_path for a workflow test.

    Stamp the first step whose path matches *this requirement's* endpoints
    (e.g. PATCH /tasks/{task_id} for REQ-003), not the first step of the
    workflow (often POST /tasks/ setup). Tier-0 and Compiler use bound_path.
    """
    req_paths = [ep.path for ep in binding.backend_endpoints]
    fallback_method: Optional[str] = None
    fallback_path: Optional[str] = None
    for step in tc.workflow_steps:
        method = step.method.upper()
        path = step.path
        if fallback_method is None:
            fallback_method, fallback_path = method, path
        probe = _probe_workflow_path(path)
        if req_paths and _paths_match_any(probe, req_paths):
            return method, path
    return fallback_method or "POST", fallback_path or "/"


def _validate_workflow_test_against_binding(
    tc: TestCase,
    binding: SurfaceBinding,
    surface_map: Optional[Dict[str, SurfaceBinding]] = None,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Rule 11 for state_transition tests — every workflow step must hit the binding."""
    if len(tc.workflow_steps) < 2:
        return (
            False, None, None,
            "state_transition requires at least 2 workflow_steps",
        )
    if binding.state != "BACKEND_API":
        return (False, None, None, "workflow test requires BACKEND_API binding")
    allowed_paths = _workflow_allowed_paths(binding, surface_map)
    for step in tc.workflow_steps:
        probe = _probe_workflow_path(step.path)
        if not _binding_is_app_wide(binding) and not _paths_match_any(probe, allowed_paths):
            return (
                False, step.method, probe,
                f"workflow step {step.method} {step.path} not allowed by surface binding "
                f"{[(ep.method, ep.path) for ep in binding.backend_endpoints]}",
            )
    stamp_method, stamp_path = _workflow_stamp_for_binding(tc, binding)
    return (True, stamp_method, stamp_path, None)


def _validate_test_against_binding(
    tc: TestCase,
    binding: SurfaceBinding,
    surface_map: Optional[Dict[str, SurfaceBinding]] = None,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Return (ok, bound_method, bound_path, reason).

    Inspects the emitted test's action/title/input_data via the same
    _method_path_from_action 4-tier inference the Compiler will use. If the
    inferred (method, path) hits one of the bound endpoints (via
    path-template matching), the test is valid and bound_method/bound_path
    can be stamped on the TestCase.

    Rule 11b: for DEFENSIVE_INVERTED bindings, also enforce that the
    emitted expected_status_code matches the allowed set for the
    binding's defense_kind. A test asserting 200 for INPUT_REJECTION
    (i.e. confirming the insecure path) or 422 for OUTPUT_REDACTION
    (i.e. mis-applying rejection logic to a redaction defense) is
    structurally wrong and gets dropped.
    """
    if tc.workflow_steps:
        return _validate_workflow_test_against_binding(tc, binding, surface_map)

    # Import here to avoid the circular import — security_compiler imports
    # from this module's siblings.
    from .security_compiler import _method_path_from_action

    inferred_method, inferred_path, _err = _method_path_from_action(
        tc.action or "",
        title=tc.title or "",
        input_data=tc.input_data,
    )
    if not inferred_path:
        return (False, None, None,
                "could not infer (method, path) from emitted test — Rule 11 cannot verify")
    # App-wide defenses (ERROR_SANITIZATION, TRANSPORT) skip path-match —
    # the defense applies to every route.
    if not _binding_is_app_wide(binding):
        bound_paths = [ep.path for ep in binding.backend_endpoints]
        if not _paths_match_any(inferred_path, bound_paths):
            return (False, inferred_method, inferred_path,
                    f"test targets {inferred_method} {inferred_path} but binding allows "
                    f"{[(ep.method, ep.path) for ep in binding.backend_endpoints]}")
    method = (inferred_method or "POST").upper()

    # Rule 11b — per-kind status code check.
    if (
        binding.threat_class == "DEFENSIVE_INVERTED"
        and binding.defense_kind
        and tc.expected_status_code is not None
    ):
        rule = _DEFENSE_KIND_STATUS_RULES.get(binding.defense_kind)
        if rule is not None:
            allowed, message = rule
            if tc.expected_status_code not in allowed:
                return (
                    False, method, inferred_path,
                    f"Rule 11b: defense_kind={binding.defense_kind} requires "
                    f"expected_status_code in {sorted(allowed)}, got "
                    f"{tc.expected_status_code}. {message}",
                )

    return (True, method, inferred_path, None)


# --------------------------------------------------------------------------- #
# Core generation
# --------------------------------------------------------------------------- #

def _generate_for_requirement(
    req: ValidatedRequirement,
    llm,
    n_per_category: int = 15,
    pipeline_mode: str = "POST_CODE",
    surface_binding_block: str = "",
) -> Tuple[Dict[str, Any], VerticalSliceContext | None, RouteIntent | None]:

    if pipeline_mode == "PRE_CODE":
        prompt = ChatPromptTemplate.from_messages(
            [("system", DESIGN_CONTRACT_SYSTEM_PROMPT),
             ("user", DESIGN_CONTRACT_USER_PROMPT)]
        )
        chain = prompt | llm
        response = invoke_with_retry(
            chain.invoke,
            {
                "requirement_id": req.requirement_id,
                "statement": req.statement,
                "acceptance_criteria_block": _format_acceptance_criteria(
                    req.acceptance_criteria
                ),
            },
        )
        payload = parse_llm_json(response.content)
        payload["_raw"] = stringify_response(response.content)
        return payload, None, None

    action = _build_action_descriptor(req)
    intent = _classify_route_intent(req)
    context_keywords = _extract_ac_keywords(req)
    vertical_slice = query_source_context(
        action, n_results=n_per_category, intent=intent, context_keywords=context_keywords
    )
    source_context = vertical_slice.as_mega_context()

    prompt = ChatPromptTemplate.from_messages(
        [("system", GENERATOR_SYSTEM_PROMPT), ("user", GENERATOR_USER_PROMPT)]
    )
    chain = prompt | llm
    # `invoke_with_retry` handles Vertex 429 / 503 / 504 / 500 / 409 with
    # exponential backoff + jitter. Non-transient errors (auth, schema,
    # invalid prompt) surface immediately and remain caught upstream.
    response = invoke_with_retry(
        chain.invoke,
        {
            "requirement_id": req.requirement_id,
            "statement": req.statement,
            "owasp_mapping": ", ".join(req.owasp_mapping) or "none",
            "acceptance_criteria_block": _format_acceptance_criteria(req.acceptance_criteria),
            "action": action,
            "source_context": source_context,
            # Brace-escape: bound paths like /tasks/{task_id} contain literal
            # braces that ChatPromptTemplate would otherwise interpret as
            # substitution slots. See _escape_template_braces docstring.
            "surface_binding_block": (
                _escape_template_braces(surface_binding_block)
                if surface_binding_block
                else "(no surface binding — pre-Layer-A back-compat path)"
            ),
        },
    )
    parsed = parse_llm_json(response.content)
    # LLMs intermittently return a BARE top-level array of test cases instead
    # of the documented {"test_cases": [...]} object. Calling parsed["_raw"]
    # on a list raised `TypeError: list indices must be integers` and lost the
    # whole requirement (observed: REQ-006b on the validation story). Normalize
    # to the dict shape — same top-level-array tolerance the Surface Resolver's
    # _extract_raw_bindings already has.
    if isinstance(parsed, list):
        payload: Dict[str, Any] = {"test_cases": parsed, "_bindings_shape": "top_level_array"}
    elif isinstance(parsed, dict):
        payload = parsed
    else:
        payload = {
            "test_cases": [],
            "_parse_warning": f"unexpected LLM root type: {type(parsed).__name__}",
        }
    payload["_raw"] = stringify_response(response.content)
    return payload, vertical_slice, intent


def generator_node(state: ProjectState) -> ProjectState:
    """LangGraph node: validated_requirements → functional test_suite + coverage_gaps.

    Per requirement the node performs:
      1. action = statement + first AC (trimmed)
      2. VerticalSliceContext = multi-query RAG (Router + Schema + Model)
      3. LLM call with strict-contract system prompt + sectioned mega-context
      4. Normalize & validate every TestCase (including `setup_fixtures`)
      5. Route unverifiable or un-retrievable ACs into `coverage_gaps`
    """
    if not state.validated_requirements:
        state.metadata["generator_skipped"] = "no validated_requirements in state"
        return state
    # ── PRE_CODE: produce DesignContracts, skip RAG entirely ──────────────
    if state.pipeline_mode == "PRE_CODE":
        precode_llm = get_local_llm(temperature=0.0, json_mode=True, seed=42)
        new_contracts: List[DesignContract] = []
        raw_outputs: List[str] = []

        for req in state.validated_requirements:
            try:
                payload, _, _ = _generate_for_requirement(
                    req, precode_llm, pipeline_mode="PRE_CODE"
                )
            except LLMInvocationError as exc:
                state.metadata.setdefault("generator_provider_failures", []).append(
                    req.requirement_id
                )
                continue
            except (json.JSONDecodeError, ValueError):
              continue
            except Exception as exc:
                continue

            raw_outputs.append(payload.pop("_raw", ""))
            for dc in payload.get("design_contracts", []):
                dc.setdefault("requirement_id", req.requirement_id)
                try:
                    new_contracts.append(DesignContract(**dc))
                except Exception:
                    continue

        state.design_contracts.extend(new_contracts)
        # Populate surface_map from the contracts we just produced. The Surface
        # Resolver runs BEFORE the Generator in the graph, so in PRE_CODE its
        # branch saw an empty design_contracts list and produced an empty map.
        # Derive it HERE, where the contracts now exist, so the PRE_CODE
        # artifact carries a real surface_map (uniform with POST_CODE).
        if state.design_contracts and not state.surface_map:
            try:
                from .surface_resolver import _surface_map_from_design_contracts
                state.surface_map = _surface_map_from_design_contracts(
                    state.design_contracts
                )
            except Exception:  # noqa: BLE001 — never let this abort PRE_CODE
                pass
        state.metadata["generator_raw"] = raw_outputs
        state.metadata["generator_mode"] = "PRE_CODE"
        return state


    # Heal re-entry: executor routed back here — replace the prior functional suite
    # so we do not accumulate duplicate TC-* rows across heal iterations.
    if state.heal_attempts > 0:
        state.test_suite.clear()
        state.coverage_gaps.clear()

    import time as _t

    logger.info(
        "[generator] processing %d validated requirements …",
        len(state.validated_requirements),
    )

    llm = get_local_llm(temperature=0.0, json_mode=True, seed=42)

    new_tests: List[TestCase] = []
    new_gaps: List[CoverageGap] = []
    raw_outputs: List[str] = []
    slice_summaries: List[Dict[str, Any]] = []

    provider_failures: List[str] = []

    rule11_dropped: List[Dict[str, Any]] = []
    surface_map_skips: List[Dict[str, Any]] = []

    for _i, req in enumerate(state.validated_requirements, start=1):
        _tr = _t.perf_counter()

        # ── Rule 11: SurfaceMap gate. Skip LLM for non-BACKEND_API states. ──
        binding = state.surface_map.get(req.requirement_id) if state.surface_map else None
        if binding is not None and binding.state != "BACKEND_API":
            new_gaps.append(_coverage_gap_for_non_backend(req, binding))
            surface_map_skips.append({
                "requirement_id": req.requirement_id,
                "state": binding.state,
                "reason": binding.rationale,
            })
            logger.info(
                "[generator] req %d/%d [%s] SKIPPED LLM (binding=%s)",
                _i, len(state.validated_requirements), req.requirement_id, binding.state,
            )
            continue

        binding_block = _render_surface_binding_block(binding)

        logger.info(
            "[generator] req %d/%d [%s] retrieving + invoking Vertex …",
            _i,
            len(state.validated_requirements),
            req.requirement_id,
        )
        try:
            payload, vertical_slice, intent = _generate_for_requirement(
                req, llm, surface_binding_block=binding_block,
            )
        except LLMInvocationError as exc:
            # All retries exhausted on a transient provider error (429, 503,
            # 504, 500, 409). Convert to a coverage_gap for THIS requirement
            # so the pipeline continues with whatever else is still healthy.
            provider_failures.append(req.requirement_id)
            new_gaps.append(
                CoverageGap(
                    requirement_id=req.requirement_id,
                    acceptance_criterion=None,
                    reason=(
                        "Generator aborted for this requirement after exhausting "
                        f"LLM retries: {type(exc.cause).__name__}: {exc.cause}. "
                        "Retry the run when provider quota or availability recovers."
                    ),
                )
            )
            continue
        except (json.JSONDecodeError, ValueError) as exc:
            new_gaps.append(
                CoverageGap(
                    requirement_id=req.requirement_id,
                    acceptance_criterion=None,
                    reason=f"Generator produced unparseable output: {exc}",
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 — keep pipeline alive on unexpected LLM/RAG failures
            logger.exception("[generator] unexpected failure for %s", req.requirement_id)
            new_gaps.append(
                CoverageGap(
                    requirement_id=req.requirement_id,
                    acceptance_criterion=None,
                    reason=f"Generator raised unexpected error: {type(exc).__name__}: {exc}",
                )
            )
            continue

        raw_outputs.append(payload.pop("_raw", ""))
        slice_summaries.append(
            {
                "requirement_id": req.requirement_id,
                "action": vertical_slice.action,
                "route_intent": intent.value,
                "router_chunks": len(vertical_slice.router_snippets),
                "schema_chunks": len(vertical_slice.schema_snippets),
                "model_chunks": len(vertical_slice.model_snippets),
                "frontend_chunks": len(vertical_slice.frontend_snippets),
                "api_client_chunks": len(vertical_slice.api_client_snippets),
            }
        )

        retrieved_refs = vertical_slice.source_refs

        # Auto-gap ONLY when all THREE frontend-capable layers (Pydantic schema,
        # JSX render, API-client config) came back empty. A field absent from
        # the Pydantic schema may still be grounded via JSX (e.g. {user?.email}
        # on the dashboard) or via the api-client config (for HTTP transport
        # assertions), so we do not force-skip on schema-empty alone.
        #
        # This heuristic assumes multi-query retrieval actually ran; in NAIVE
        # mode we collapse to a single `router_snippets` bucket by design and
        # the other three are empty-by-contract, not empty-by-miss. Suppress
        # the false positive in that case — if naive retrieval genuinely got
        # nothing, `router_snippets` would also be empty and the LLM will
        # surface real gaps via its own `coverage_gaps` payload.
        _mode = resolve_rag_mode()
        if (_mode is not RagMode.NAIVE
                and not vertical_slice.schema_snippets
                and not vertical_slice.frontend_snippets
                and not vertical_slice.api_client_snippets):
            new_gaps.append(
                CoverageGap(
                    requirement_id=req.requirement_id,
                    acceptance_criterion=None,
                    reason=(
                        "Multi-query retrieval returned no Pydantic schema, "
                        "no frontend rendering, and no api-client config for "
                        f"action '{vertical_slice.action}'. No layer is "
                        "available to ground request fields, UI assertions, or "
                        "HTTP-transport claims; any emitted tests are "
                        "router/model-grounded only."
                    ),
                )
            )

        test_cases_raw = list(payload.get("test_cases", []))
        if state.story_id == "LIFE-001" and req.requirement_id == "REQ-001":
            has_workflow = any(
                (t.get("test_category") or "").strip().lower() == "state_transition"
                and len(t.get("workflow_steps") or []) >= 2
                for t in test_cases_raw
            )
            if not has_workflow:
                test_cases_raw.append(
                    _canonical_task_crud_workflow(req, 99, retrieved_refs)
                )
                state.metadata.setdefault(
                    "generator_state_transition_injected", []
                ).append(req.requirement_id)

        for idx, tc in enumerate(test_cases_raw, start=1):
            try:
                normalized_tc = _normalize_test_case_payload(tc, req, idx, retrieved_refs)
                if (
                    (normalized_tc.get("test_category") or "").strip().lower()
                    == "state_transition"
                    and len(normalized_tc.get("workflow_steps") or []) < 2
                ):
                    new_gaps.append(
                        CoverageGap(
                            requirement_id=req.requirement_id,
                            acceptance_criterion=normalized_tc.get(
                                "covered_acceptance_criterion"
                            ),
                            reason=(
                                "state_transition test requires at least 2 "
                                "workflow_steps"
                            ),
                        )
                    )
                    continue
                tc_obj = TestCase(**normalized_tc)
            except Exception as exc:
                new_gaps.append(
                    CoverageGap(
                        requirement_id=req.requirement_id,
                        acceptance_criterion=tc.get("covered_acceptance_criterion"),
                        reason=(
                            "Generator emitted invalid test case after normalization: "
                            f"{exc}"
                        ),
                    )
                )
                continue

            # Rule 11 post-LLM validation: confirm the emitted test targets
            # one of the bound endpoints. Stamp bound_method/bound_path so
            # the Compiler can use them as source-of-truth (no inference)
            # and the Classifier tier 0 can detect off-target at run time.
            if binding is not None and binding.state == "BACKEND_API":
                ok, bound_method, bound_path, reason = _validate_test_against_binding(
                    tc_obj, binding, state.surface_map,
                )
                if not ok:
                    new_gaps.append(
                        CoverageGap(
                            requirement_id=req.requirement_id,
                            acceptance_criterion=tc_obj.covered_acceptance_criterion,
                            reason=f"[Rule 11 violation — test dropped] {reason}",
                        )
                    )
                    rule11_dropped.append({
                        "requirement_id": req.requirement_id,
                        "test_title": tc_obj.title,
                        "test_action": tc_obj.action,
                        "reason": reason,
                    })
                    continue
                tc_obj.bound_method = bound_method
                tc_obj.bound_path = bound_path
                tc_obj.bound_surface_state = "BACKEND_API"
                stamp_attestation_mode(tc_obj, binding)

            elif tc_obj.is_adversarial:
                stamp_attestation_mode(tc_obj, binding)

            new_tests.append(tc_obj)

        for gap in payload.get("coverage_gaps", []):
            gap.setdefault("requirement_id", req.requirement_id)
            new_gaps.append(CoverageGap(**gap))

        logger.info(
            "[generator] req %d/%d done in %.1fs",
            _i,
            len(state.validated_requirements),
            _t.perf_counter() - _tr,
        )

    # LIFE-001: ensure at least one executable state_transition test survives Rule 11.
    if state.story_id == "LIFE-001":
        has_workflow = any(
            (t.test_category or "").lower() == "state_transition"
            and len(t.workflow_steps) >= 2
            for t in new_tests
        )
        if not has_workflow and state.validated_requirements:
            req0 = state.validated_requirements[0]
            binding0 = (state.surface_map or {}).get(req0.requirement_id)
            if binding0 and binding0.state == "BACKEND_API":
                try:
                    raw = _canonical_task_crud_workflow(req0, 1, [])
                    norm = _normalize_test_case_payload(raw, req0, 1, [])
                    tc_w = TestCase(**norm)
                    ok, bm, bp, reason = _validate_test_against_binding(
                        tc_w, binding0, state.surface_map,
                    )
                    if ok:
                        tc_w.bound_method = bm
                        tc_w.bound_path = bp
                        tc_w.bound_surface_state = binding0.state
                        new_tests.append(tc_w)
                        state.metadata.setdefault(
                            "generator_state_transition_injected", []
                        ).append("REQ-001_fallback")
                except Exception as exc:
                    logger.warning(
                        "[generator] LIFE-001 workflow inject failed: %s", exc
                    )

    state.test_suite.extend(new_tests)
    state.coverage_gaps.extend(new_gaps)
    state.metadata["generator_raw"] = raw_outputs
    state.metadata["generator_retrieval"] = slice_summaries
    if provider_failures:
        state.metadata["generator_provider_failures"] = provider_failures
    if rule11_dropped:
        state.metadata["generator_rule11_dropped"] = rule11_dropped
    if surface_map_skips:
        state.metadata["generator_surface_map_skips"] = surface_map_skips
    st_count = sum(
        1 for t in state.test_suite
        if (t.test_category or "").lower() == "state_transition"
        and len(t.workflow_steps) >= 2
    )
    if st_count:
        state.metadata["generator_state_transition_count"] = st_count
    return state

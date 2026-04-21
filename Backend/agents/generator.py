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
import re
from typing import Any, Dict, List, Tuple

from langchain_core.prompts import ChatPromptTemplate

from database import RouteIntent, VerticalSliceContext, query_source_context
from state import (
    CoverageGap,
    ProjectState,
    TestCase,
    ValidatedRequirement,
)
from utils import (
    LLMInvocationError,
    get_local_llm,
    inflate_placeholders,
    invoke_with_retry,
    parse_llm_json,
    stringify_response,
)


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

## RULE 11 — CLIENT-SIDE VULNERABILITY PIVOT
If the retrieved context reveals that a feature (like Search or Filtering) is
handled entirely on the client-side (e.g., local React filtering) and does
not hit a backend database query, you MUST NOT abandon security testing.
Instead of Backend SQLi, you MUST pivot to generating Client-Side Security
tests (e.g., DOM-based XSS, Prototype Pollution) using Playwright assertions
against the rendered JSX.

============================================================
TEST GENERATION DISCIPLINE
============================================================

Required ratio per requirement (enforce approximately):
  - ~20% Positive   (happy path, success cases)
  - ~35% Negative   (input validation, type mismatch, empty/null)
  - ~20% Boundary   (max length, min value, overflow, off-by-one)
  - ~25% Security   (OWASP: injection, bypass, XSS, auth)

For every TestCase:
1. `covered_requirement_id` + `covered_acceptance_criterion` trace to exactly
   one AC. Set `test_category` (positive / negative / boundary / security).
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
   to exactly N alphanumeric characters. Use literal strings only when the
   exact content matters (a specific email, a named duplicate, etc.).
7. If an AC is UNVERIFIABLE ("fast", "intuitive", "secure" with no measurable
   threshold) OR the retrieved context is insufficient to ground a test, do
   NOT invent one — emit a `coverage_gaps` entry instead.
8. Output STRICT JSON. No prose, no markdown fences, no trailing commentary.

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
      "test_category": "positive|negative|boundary|security",
      "coverage_rationale": "Satisfies AC '<criterion>' of <REQ-ID>. ...",
      "covered_requirement_id": "<REQ-ID>",
      "covered_acceptance_criterion": "<criterion text>",
      "source_refs": ["<path:start-end from source context>"]
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
"""


GENERATOR_USER_PROMPT = """Requirement under test:
  ID: {requirement_id}
  Statement: {statement}
  OWASP mapping: {owasp_mapping}
  Acceptance Criteria:
{acceptance_criteria_block}

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

    expected_result = normalized.get("expected_result")
    if expected_result is None:
        expected_result = "Expected outcome matches acceptance criterion"
    normalized["expected_result"] = inflate_placeholders(str(expected_result))

    normalized["expected_status_code"] = _coerce_status_code(
        normalized.get("expected_status_code")
    )

    normalized["expected_json_keys"] = _to_str_list(normalized.get("expected_json_keys"))
    normalized["forbidden_response_content"] = _to_str_list(
        normalized.get("forbidden_response_content")
    )
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

    return normalized


# --------------------------------------------------------------------------- #
# Core generation
# --------------------------------------------------------------------------- #

def _generate_for_requirement(
    req: ValidatedRequirement,
    llm,
    n_per_category: int = 15,
) -> Tuple[Dict[str, Any], VerticalSliceContext, RouteIntent]:
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
        },
    )
    payload = parse_llm_json(response.content)
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

    llm = get_local_llm(temperature=0.0, json_mode=True, seed=42)

    new_tests: List[TestCase] = []
    new_gaps: List[CoverageGap] = []
    raw_outputs: List[str] = []
    slice_summaries: List[Dict[str, Any]] = []

    provider_failures: List[str] = []

    for req in state.validated_requirements:
        try:
            payload, vertical_slice, intent = _generate_for_requirement(req, llm)
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
        if (not vertical_slice.schema_snippets
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

        for idx, tc in enumerate(payload.get("test_cases", []), start=1):
            try:
                normalized_tc = _normalize_test_case_payload(tc, req, idx, retrieved_refs)
                new_tests.append(TestCase(**normalized_tc))
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

        for gap in payload.get("coverage_gaps", []):
            gap.setdefault("requirement_id", req.requirement_id)
            new_gaps.append(CoverageGap(**gap))

    state.test_suite.extend(new_tests)
    state.coverage_gaps.extend(new_gaps)
    state.metadata["generator_raw"] = raw_outputs
    state.metadata["generator_retrieval"] = slice_summaries
    if provider_failures:
        state.metadata["generator_provider_failures"] = provider_failures
    return state

# Design Note: IDOR tests require bound path templates + seeded peer task ids

**Status:** Open — deferred (do NOT quick-fix the matcher alone; see Risk).
**Surfaced by:** P1.8 cross-story smoke matrix (2026-05-30), `perms` story (AUTHZ-001).
**Severity:** Medium — caps coverage on access-control / IDOR stories; not a correctness regression.

## Symptom

`perms` (AUTHZ-001) bound all 6 requirements to `BACKEND_API` (good grounding),
but produced only **2 tests** (`INSUFFICIENT`). Four tests were dropped at the
Generator's Rule 11 path-match step:

```
REQ-002  action='GET /tasks/{task_id_b}'   reason=test targets GET /tasks/ but binding allows [('GET', '/tasks/{task_id}')]
REQ-003  action='PATCH /tasks/{task_id}'   reason=test targets PATCH /tasks/ but binding allows [('PATCH', '/tasks/{task_id}')]
REQ-004  action='PATCH /tasks/{task_id}'   reason=test targets PATCH /tasks/ but binding allows [('PATCH', '/tasks/{task_id}')]
REQ-005b action='GET /tasks/{task_id}'     reason=test targets GET /tasks/ but binding allows [('GET', '/tasks/{task_id}')]
```

These are exactly the IDOR tests the perms story exists to exercise
("User A cannot read/modify User B's task → 404").

## Root cause (two layers)

1. **Path-param truncation in inference.**
   [`security_compiler.py:231-260`](../../Backend/agents/security_compiler.py#L231-L260)
   - `_METHOD_PATH_RE` path group is `(/[A-Za-z0-9_\-./]+)` — the `{` character
     is not in the class, so `GET /tasks/{task_id}` matches only `/tasks/`.
   - `_try_method_path_regex` *additionally* rejects any path containing `{`/`}`
     (a deliberate guard from the pre-SurfaceMap era when path params could not
     be substituted).
   - Net: inferred path `= /tasks/`, which fails `_paths_match_any('/tasks/',
     ['/tasks/{task_id}'])` on segment-count mismatch → test dropped.

2. **No path-param substitution or peer-row seeding in the harness.**
   The pytest template ([`templates/pytest_api.jinja2`](../../Backend/agents/templates/pytest_api.jinja2))
   fires `client.request(method, path, ...)` with `path` verbatim. There is no
   mechanism to (a) seed a *second user's* task, (b) capture its real id, and
   (c) substitute it into `/tasks/{task_id}` at request time.

## Risk — why the matcher fix ALONE is wrong

Loosening the regex to capture `{task_id}` makes the 4 tests survive Rule 11,
but they would then execute against the **literal** URL `/tasks/{task_id}`.
FastAPI matches the `/tasks/{task_id}` route with `task_id == "{task_id}"`,
`_get_owned_task` finds no such row → returns **404**. The IDOR test
`expected_status_code = 404` then **passes for the wrong reason** (route ran
with a garbage id, not "User A was denied User B's real task"). That is a
false-pass — strictly worse than the current honest drop.

## Required scope (when prioritized)

A correct fix is a small *feature*, not a one-liner:

1. **Preserve path templates through inference + binding.**
   Add `{`/`}` to `_METHOD_PATH_RE`'s path class and drop the `{...}` rejection
   in `_try_method_path_regex`. Stamp `bound_path = "/tasks/{task_id}"` on the
   TestCase. (~3 lines, but inert without steps 2-3.)

2. **Typed path-params on TestCase + fixture protocol.**
   Let the Generator declare `path_params` and a `setup_fixtures` entry that
   seeds a peer-owned row, e.g.:
   ```
   setup_fixtures: ["Seed user B; seed task 'B-secret' owned by user B; expose its id as {task_id}"]
   path_params: {"task_id": "$.seeded.B_secret.id"}
   ```

3. **Template substitution + multi-user fixtures.**
   Extend `pytest_api.jinja2` to (a) register/login a *second* bearer (user B),
   (b) create user B's task, capture its id, (c) substitute into `bound_path`,
   (d) fire the request as user A. Assert 404 (ownership) — now for the *right*
   reason.

4. **Classifier awareness.**
   `IMPLICIT_FILTER` / IDOR verdicts should confirm the peer row was actually
   seeded (else the 404 is inconclusive, not resilient).

## Interim posture (demo narrative)

`perms` honestly reports `INSUFFICIENT` with 2 attested tests + 4 coverage_gaps
naming the dropped IDOR checks. This is defensible: "Sentinel binds the IDOR
requirements to the correct `/tasks/{task_id}` routes but abstains from
executing them until multi-user path-param fixtures land, rather than emitting
false-passing tests." That is the Layer-A principle (honest abstention over
proxy noise) applied at the harness layer.

## Related

- Same path-template machinery would also benefit `taskshare` *if* a share
  endpoint is ever added to repo_cache.
- Pairs with P1.3 (deterministic fallback) only loosely — this is a coverage
  feature, not a parse-robustness fix.

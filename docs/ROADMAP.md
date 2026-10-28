# Roadmap

The project is built one milestone at a time. A milestone is only marked
done after its features are implemented **and verified by actually running
them**.

1. **Milestone 1 — Foundation:** project structure, FastAPI backend,
   environment config, health endpoint, basic tests, Git initialized.
   **Status: DONE** — verified by a real test run (3 passed) and a live
   `GET /health` check against a running uvicorn server.
2. **Milestone 2 — Workspace:** confined file operations, path validation,
   file-size limits, workspace security tests.
   **Status: DONE** — verified by a real test run (30 passed, including 27
   workspace tests covering traversal, symlink escapes, and size limits).
3. **Milestone 3 — Docker Sandbox:** execution image, output/exit capture,
   timeouts, resource limits, cleanup, isolation tests.
   **Status: CODE COMPLETE — live verification pending Docker host.**
   The hardened image (`sandbox/Dockerfile`, non-root uid 10001), the
   fixed-policy runner (`backend/app/sandbox/runner.py`), sandbox
   settings, and 17 daemon-free policy tests are implemented and passing
   (full suite: 47 passed). Live container execution is **not** verified:
   the build environment has no Docker daemon, and the runner honestly
   raises `SandboxUnavailableError` there. Remaining verification — run
   a harmless program in a real container and confirm output capture,
   non-zero exit codes, timeout kill, and network isolation — must
   happen on a Docker host (the user's laptop with Docker Desktop).
4. **Milestone 4 — Groq Integration:** OpenAI-compatible client, model
   availability check, tool-calling loop, rate-limit and error handling,
   max-iteration enforcement.
   **Status: CODE COMPLETE — live model call pending a valid
   GROQ_API_KEY in .env.** The Groq client factory
   (`backend/app/agent/llm_client.py`, refuses to build without a key
   and model), the six workspace-tool schemas and validating dispatcher
   (`backend/app/tools/definitions.py`), and the controlled agent loop
   (`backend/app/agent/loop.py` — bounded iterations, cancellation,
   rate-limit retries with backoff, fail-fast on authentication errors,
   real tool failures fed back to the model) are implemented and
   verified entirely against a scripted fake client: 15 new tests, full
   suite 62 passed, including a real file created in a temporary
   workspace via a model-requested tool call and a path-traversal
   attempt refused and reported. NOT verified: any live Groq call — no
   valid API key is available in the build environment (previous keys
   returned 401), so the first live verification must happen with a
   valid `GROQ_API_KEY` and `GROQ_MODEL` (recommended:
   `llama-3.3-70b-versatile`) in `backend/.env` on the user's machine.
5. **Milestone 5 — Autonomous Coding:** agent connected to workspace,
   execution and test tools; one complete small coding task verified end
   to end.
   **Status: DONE (agent + execution-tool wiring verified with fake
   model and local executor stand-in; live Docker execution + live Groq
   still pending their hosts).** The dispatcher gained four tools —
   `run_python_file` and `run_tests` delegating to the sandbox runner's
   new fixed command allowlist (`validate_command`/`run_command` in
   `backend/app/sandbox/runner.py`: only `python <file.py>` and
   `python -m pytest <path>` survive server-side validation; flags and
   escaping paths are refused), plus read-only `git_status`/`git_diff`
   (fixed argv, no shell, no git write operations exist). The task
   service (`backend/app/services/task_service.py`) runs tasks on
   background threads with per-task cancellation and persists records
   in SQLite; the API (`backend/app/api/tasks.py`) exposes
   create/get/list/cancel and returns an honest 503 when the model
   client is not configured. Verification (28 new tests, full suite 90
   passed): a scripted fake model wrote a calculator with a deliberate
   bug, ran the tests through an injected local executor (a test-only
   stand-in for Docker — real pytest, real failure output), fixed the
   bug from that feedback, and re-ran to a real pass; the same flow
   against the real sandbox runner in this Docker-less environment
   surfaces "execution unavailable" to the model and claims nothing.
   NOT verified: execution inside a real container and a live Groq
   model call — both still pending their hosts, as in Milestones 3–4.
6. **Milestone 6 — Web Search:** separately configured search provider,
   real cited results, honest failure handling.
   **Status: DONE — verified live.** The `web_search` tool delegates to
   a provider selected by `SEARCH_PROVIDER` (`backend/app/search/
   provider.py`): DuckDuckGo via the `ddgs` package by default (no API
   key), Tavily optionally (a real `api.tavily.com` call; selected
   without `TAVILY_API_KEY` it raises an honest not-configured error).
   Every provider failure is wrapped in `SearchUnavailableError` with
   the real reason and surfaces to the model as a tool error — never
   as a fake or empty success; an actually-empty result set is reported
   as "no results". Results are framed with an explicit header marking
   them as untrusted external data (information, never instructions).
   Verification: 16 new tests (fake-provider dispatcher behaviour,
   ddgs dict mapping via a stubbed `DDGS`, Tavily request/response
   mapping via a mocked httpx transport, missing-key and
   unknown-provider errors, config defaults), full suite 106 passed —
   plus a **live smoke check**: the real `DuckDuckGoProvider` searched
   "Groq API tool calling" and returned 5 real results (first: "Tool
   Use Overview - GroqDocs", console.groq.com). Note: a first live
   attempt timed out when ddgs routed to a slow backend; the immediate
   retry succeeded — DuckDuckGo's public endpoints are best-effort and
   can rate-limit or time out, which is exactly what the honest-error
   path exists for. Tavily's live path is unit-tested with a mocked
   transport only — no Tavily key is available in this environment.
7. **Milestone 7 — Frontend:** React dashboard with real task progress,
   logs, files, test results, cancellation and approval controls.
   **Status: DONE — build verified in this environment.** The backend
   gained CORS for the Vite dev origins (`FRONTEND_ORIGINS` setting,
   default `http://localhost:5173` + `http://127.0.0.1:5173`; 3 new
   tests, full backend suite 109 passed, and the allow-origin header
   confirmed against a live uvicorn server). The frontend
   (`frontend/`, Vite 6 + React 18 + TypeScript, no UI kit or state
   library) talks to the exact task API shipped in Milestone 5:
   submit form (the backend's real error — e.g. the 503 "LLM not
   configured" detail — is shown verbatim), task list, detail panel
   with status pill, result summary, error box, and an ordered
   tool-call timeline, plus a Cancel button while a task is
   queued/running. Live updates are honest polling — `GET
   /tasks/{id}` every 2 seconds while non-terminal, stopping at
   terminal states; an unreachable backend shows a plain banner, never
   invented state. `npm install` + `npm run build` verified for real
   (tsc clean; dist JS 150.14 kB / 48.49 kB gzip), and `vite preview`
   served the built page (title + bundle confirmed over HTTP) while a
   live backend answered `/health`, `GET /tasks` and the CORS check.
   One honest scoping note: the API records `tool_calls` as tool
   **names only**, so the dashboard shows the timeline of names and
   has no "files changed" view — deriving one would fabricate data
   the API never returned (see `frontend/README.md`).
8. **Milestone 8 — Reliability and Security:** full test suite, permission
   and Docker review, malformed-input and malicious-path testing,
   documented residual limitations.
   **Status: DONE.** Structured logging was added across the backend
   (`backend/app/logging_config.py`, the `asa` logger tree, `LOG_LEVEL`
   setting): the task service logs created/started/finished with the
   task id, the agent loop logs tool call *names* and real failure
   reasons — and a test with sentinel values proves neither the API
   key nor file contents ever reach the logs. The task service gained
   a concurrency limit (`MAX_CONCURRENT_TASKS`, default 2): excess
   tasks wait `queued` in creation order, and cancelling a queued
   task finalizes it as `cancelled` without it ever running (verified
   with an event-gated fake client). The system prompt now states
   that tool outputs are data, never instructions — documented in
   `docs/SECURITY.md` as a prompt-level defense-in-depth layer, not a
   behavioural guarantee. Failure paths hardened: an unusable SQLite
   store raises a clear `TaskStoreError` at startup, and a workspace
   deleted mid-task still leaves a terminal, honest record.
   Dependency audits were really run: pip-audit found 14 findings in
   2 packages (venv `pip 24.0` tooling + `pytest 8.4.2`); both were
   fixed (pip → 26.2.2 in the venv, pytest → 9.0.3 with the
   requirements range updated after a green suite) and the re-audit
   is clean. `npm audit` could **not** be run — this environment's
   registry proxy refuses the audit endpoint (HTTP 403
   `policy_denied`) — so the frontend audit remains an open item,
   recorded as unmeasured rather than clean. 8 new tests; full
   backend suite 117 passed.
9. **Milestone 9 — Local Deployment:** repeatable local startup,
   environment setup docs, troubleshooting guide, final verification
   checklist. Not exposed publicly by default.

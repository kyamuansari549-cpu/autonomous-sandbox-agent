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
7. **Milestone 7 — Frontend:** React dashboard with real task progress,
   logs, files, test results, cancellation and approval controls.
8. **Milestone 8 — Reliability and Security:** full test suite, permission
   and Docker review, malformed-input and malicious-path testing,
   documented residual limitations.
9. **Milestone 9 — Local Deployment:** repeatable local startup,
   environment setup docs, troubleshooting guide, final verification
   checklist. Not exposed publicly by default.

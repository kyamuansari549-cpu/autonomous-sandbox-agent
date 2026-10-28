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
5. **Milestone 5 — Autonomous Coding:** agent connected to workspace,
   execution and test tools; one complete small coding task verified end
   to end.
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

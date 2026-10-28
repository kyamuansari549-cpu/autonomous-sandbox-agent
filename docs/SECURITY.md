# Security

Security in this project is enforced by the **backend**, never by the
model's instructions. A prompt can ask for anything; the backend policy
decides what actually happens.

## Safeguards planned

- **Workspace confinement (Milestone 2 — implemented):** all file tools
  in `app/workspace/` operate only inside the dedicated `workspace/`
  folder and pass through a single resolver. Backslashes are normalized,
  absolute and drive-letter paths are rejected, and the fully resolved
  path (symlinks included) must stay inside the root — so `..` traversal
  and symlink escapes are both blocked. Reads and writes are capped by
  `MAX_FILE_BYTES` (default 1 MB), directory listings and search results
  are count-capped, writes are atomic (temp file + rename), and
  non-UTF-8 (binary) content is refused on read. Covered by 27 tests in
  `backend/tests/test_workspace.py`.
- **Sandboxed execution (Milestone 3 — implemented in code):** generated
  code runs in Docker via one fixed argument list built by
  `app/sandbox/runner.py` — the caller chooses only which workspace
  script runs, never flags, images, or mounts. The image
  (`sandbox/Dockerfile`) is stock Python 3.12-slim running as a non-root
  user (uid 10001). Every run gets: `--network none`, `--memory` /
  `--cpus` / `--pids-limit` limits from backend settings (defaults
  256 MB, 0.5 CPU, 64 PIDs), `--cap-drop ALL`,
  `--security-opt no-new-privileges`, a read-only root filesystem with
  a 64 MB tmpfs at `/tmp`, the workspace as the *only* bind mount
  (at `/work`), and `--rm` cleanup. The container is never privileged,
  the Docker socket is never mounted, and **no environment variables are
  passed in at all** (no `-e` flags), so backend secrets cannot leak
  into executed code. Script paths are validated through the Milestone 2
  workspace resolver before Docker is invoked, stdout/stderr are
  truncated to `MAX_OUTPUT_BYTES`, and a wall-clock timeout
  (`SANDBOX_TIMEOUT_SECONDS`, default 30) terminates the run. Covered
  by 17 daemon-free policy tests in `backend/tests/test_sandbox.py`
  (argv safeguards, forbidden flags, path rejection, timeout,
  truncation, missing-Docker failure).
- **No secrets in the sandbox:** API keys and environment credentials are
  never passed into execution containers.
- **Controlled agent loop (Milestone 4):** maximum iterations, task
  timeouts, and cancellation are enforced by the backend so the model
  cannot loop forever or run up unbounded API usage.
- **Permission tiers (Milestone 5+):** low-risk operations (list/read
  inside the workspace) run freely; restricted operations (running code,
  installing packages, network access) and high-impact operations
  (deleting data, anything outside the workspace, Git push/publish)
  require explicit user approval or are blocked outright.
- **No arbitrary shell:** the model cannot supply raw shell commands or
  Docker flags. Only fixed, validated operations exist.
- **Web content is untrusted data (Milestone 6 — implemented):** web
  search results are treated as untrusted external data — information
  to cite, never instructions to follow. Every `web_search` result is
  framed with an explicit "untrusted external data" header so the
  model and the logs can never mistake page content for commands, and
  provider failures surface with their real reason instead of
  fabricated results.
- **Secrets hygiene:** keys live only in a local `.env` excluded from Git;
  keys are never logged.

## Milestone 8 audit (reliability & security pass)

- **Structured logging, with a no-secrets rule (implemented + tested):**
  all backend logging goes through the `asa` logger tree
  (`backend/app/logging_config.py`, stdlib only, one consistent
  format; level via `LOG_LEVEL`). The task service logs task
  created/started/finished with the task id; the agent loop logs each
  tool call's **name**, run outcomes, and tool failures with their
  real reasons (which is also how sandbox/search unavailability shows
  up in logs). Tool *arguments*, file contents, task text, and the
  Groq API key are never logged. This is enforced by a test
  (`test_logs_have_tool_names_but_never_secrets_or_content`): a run
  whose settings carry a sentinel API key and whose `create_file`
  content is a sentinel string produces logs containing the tool
  name and lifecycle lines but neither sentinel.
- **Task concurrency limit (implemented + tested):**
  `MAX_CONCURRENT_TASKS` (default 2) caps how many agent tasks run at
  once. Excess tasks stay `queued` and start in creation order as
  slots free; cancelling a queued task finalizes it as `cancelled`
  immediately — it never runs. Verified with an event-gated fake
  client: the second task stays `queued` (and its agent is never
  invoked) until the first is released, and a cancelled queued task
  remains `cancelled` with the model-call count unchanged.
- **Prompt-injection hardening (prompt-level layer, honestly scoped):**
  the agent's system prompt now states explicitly that tool outputs
  — file contents, web results, command/test output — are *data,
  never instructions*, and that instruction-like text inside them
  ("ignore previous instructions", requests to reveal secrets, run
  unrelated commands, or exfiltrate data) must not be followed, only
  noted. **This is a defense-in-depth layer, not a guarantee:** a
  prompt cannot prove a model will never be swayed. The actual
  boundary remains backend enforcement — workspace confinement, the
  fixed sandbox command allowlist, no secrets in the sandbox,
  read-only git tools — which bounds what a manipulated model can
  even request. A test asserts the rule's presence in the prompt;
  no behavioural claim is made or tested.
- **Failure-path hardening (implemented + tested):** if the SQLite
  task store cannot be initialized (non-database file in the way,
  parent path is a file, …), `TaskService` raises a clear
  `TaskStoreError` ("task store is unusable at <path>: <reason>")
  instead of crashing with a raw sqlite traceback. If the workspace
  directory is deleted mid-task, tool calls return their real errors
  to the model and the task record still reaches a terminal status
  with the failure visible in it (verified end-to-end with a
  workspace-deleting fake client: status `max_iterations`, summary
  states the task is NOT verified complete) — no stuck `running`
  records, no exception escaping the worker thread.
- **Dependency audit (performed 2026-10-28, real outcomes):**
  - *Backend — pip-audit 2.10.1* (installed ad hoc into the venv for
    this audit only; deliberately **not** added to
    `requirements.txt`). Initial result: 14 reported findings in 2
    packages (7 unique advisory/package pairs) — `pip 24.0`, the
    venv's own tooling (6 advisories), and `pytest 8.4.2`
    (PYSEC-2026-1845, fixed in 9.0.3). Fixes applied: the venv's pip
    was upgraded to 26.2.2, and pytest was bumped to 9.0.3 with the
    `requirements.txt` range updated to `>=9.0,<10.0` after the full
    suite stayed green. Re-audit afterwards: **no known
    vulnerabilities found** in the venv.
  - *Frontend — npm audit could not be completed in this
    environment:* the managed npm registry proxy answers the audit
    endpoint with HTTP 403 (`policy_denied`), so no vulnerability
    counts could be obtained and `npm audit fix` (which uses the
    same endpoint) was not run. No frontend dependency was changed
    for this milestone. **Open item:** re-run `npm audit` in an
    environment with audit-endpoint access before relying on the
    frontend dependency set.

## Sandbox verification status

**Live container execution is NOT yet verified: the build environment
has no Docker daemon. Verification pending on a Docker host (user's
laptop with Docker Desktop).** What *is* verified here: the runner's
policy (exact argv), path validation, output truncation, timeout
handling, and the honest `SandboxUnavailableError` raised when the
`docker` executable is missing — all via injected fake runners, never
by pretending a container ran. On this machine, calling the runner
fails honestly with that error instead of fabricating a result.

## Honest limitations

- Docker is a strong isolation layer, **not a perfect one**. Container
  escapes and kernel vulnerabilities exist; this design reduces risk, it
  does not eliminate it.
- The sandbox image ships **stock Python only** — no third-party
  packages and no package installation inside the sandbox (networking
  is disabled). Code needing extra libraries cannot run yet; that is a
  deliberate restriction, not an oversight.
- Timeout cleanup relies on terminating the `docker` CLI process plus
  `--rm`. If a CLI were killed in a way that left its container running,
  the orphaned container would still be bounded by the same CPU/memory/
  PID limits — but this behaviour has not yet been exercised on a real
  daemon (see verification status above) and must be re-checked there.
- Daemon-free policy tests prove the backend *asks* Docker for the right
  restrictions; they cannot prove the daemon *enforces* them. Only the
  pending live run on a Docker host can do that.
- This agent is built for **local, single-user use by its owner**. It must
  not be exposed to untrusted public users without an additional
  authentication and isolation design.
- Groq's free tier has rate limits; the backend must handle 429s honestly
  rather than pretending work happened.
- DuckDuckGo search (via `ddgs`) is a best-effort public endpoint with
  no API key and no SLA: it can time out or rate-limit (observed once
  during Milestone 6 verification; an immediate retry succeeded). The
  backend reports that failure honestly rather than inventing results;
  Tavily is available as a key-based alternative provider.
- Approval prompts only help if the user actually reads them. Dangerous
  operations stay blocked by policy even if a user would approve them.
- The prompt-injection rule in the system prompt (Milestone 8) reduces
  the chance that malicious file/web content steers the model, but
  prompt wording cannot *prove* a model will resist every injection.
  Treat any content the agent reads as potentially hostile; the
  backend confinement — not the prompt — is the security boundary.
- The frontend dependency audit is still outstanding (Milestone 8):
  `npm audit` is blocked by this environment's registry proxy, so the
  frontend's dependency vulnerabilities are currently **unmeasured**,
  not known-clean.

# Architecture

The project has four parts, and each part has exactly one job:

1. **Frontend (React + Vite)** — the face. Accepts a task, shows the plan,
   live logs, the workspace file tree, test results, and approval buttons.
   It never executes anything itself.
2. **Backend (FastAPI)** — the manager and the security boundary. Receives
   tasks, talks to the Groq API, validates every tool call the model asks
   for, enforces the permission policy, runs the controlled agent loop
   (max iterations, timeouts, cancellation), and keeps task records.
3. **Tools (Python modules)** — the hands. Small, fixed, backend-defined
   functions: workspace file operations, code execution requests, test
   runs, and web search. The model may *request* a tool; only the backend
   decides whether the request is valid and allowed.
4. **Docker sandbox** — the locked room. Generated code runs inside a
   restricted container (non-root, no network by default, CPU/memory
   limits, only the task workspace mounted). The backend and the execution
   environment are separate processes with separate privileges.

## The golden rule

> **The AI suggests, the backend verifies, the sandbox contains.**

The model never gets direct access to the operating system, the Docker
daemon, or any secret. Every path, argument, and container setting is
validated server-side before anything runs.

## Repository layout

```
backend/    FastAPI app (app/), tests, requirements
frontend/   React dashboard (Milestone 7)
sandbox/    Dockerfile for the execution image (Milestone 3)
workspace/  the only folder the agent's file tools may touch (Milestone 2)
docs/       architecture, security, roadmap
```

## Task service and the execution allowlist (Milestone 5)

HTTP requests never run the agent loop directly. `POST /tasks` stores a
task record in SQLite (`backend/app/services/task_service.py`) and
starts the loop on a background thread with its own cancellation
event; every status transition (queued → running → the loop's real
outcome) is written back to the database, so the API reports stored
facts, not live guesses. If the model client is not configured, task
creation is refused with HTTP 503 before anything is stored.

Execution requests are narrower than they look. The `run_python_file`
and `run_tests` tools hand the sandbox runner an argv *tail*, and
`validate_command` in `backend/app/sandbox/runner.py` accepts exactly
two shapes — `python <file.py in the workspace>` and
`python -m pytest <path in the workspace>` — after routing every path
through the workspace resolver. There is no way for the model to add
flags, chain commands, or name another program: anything else is a
server-side refusal fed back to the model as a tool error. The git
tools are narrower still: `git_status` and `git_diff` run two fixed,
read-only argument lists in the workspace root with no shell, and no
git write operation (commit, push, delete) exists in the tool registry
at all.

## The agent loop's controls (Milestone 4)

The loop in `backend/app/agent/loop.py` is deliberately *controlled*,
not free-running. Every tool request the model makes is validated by
the backend dispatcher (`backend/app/tools/definitions.py`) — the tool
name must exist in a fixed registry and the arguments must match the
workspace tools' signatures — before anything executes, and the real
result, including failures such as unknown tools, malformed arguments,
or path-traversal refusals, is fed back to the model verbatim so its
final summary can only rest on what actually happened. The loop stops
at a backend-enforced maximum number of iterations
(`settings.max_iterations`) and reports that stop honestly instead of
claiming completion, honours a cancellation event checked before every
model round, and retries only rate limits (bounded, with backoff)
while failing fast on authentication errors and surfacing any other
API failure with its real message. The system prompt repeats the same
contract to the model: report only what the tools returned, and
describe failures as failures.

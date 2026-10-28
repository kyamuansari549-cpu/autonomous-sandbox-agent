# Local deployment

This project is built for **local, single-user use by its owner**. It
is not exposed publicly by default, has no authentication, and must
not be put on a public network without an additional design (see
`docs/SECURITY.md`). There are two ways to run it locally: manually
(simplest, and the way every milestone was verified) or with Docker
Compose.

## Option A — Manual run (verified path)

Prerequisites: Python 3.12, Node 20+, and — only for sandboxed code
execution — Docker running on the same machine.

Backend:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # fill in GROQ_API_KEY + GROQ_MODEL
uvicorn app.main:app --port 8000
```

Check: `curl http://127.0.0.1:8000/health` returns
`{"status":"ok","service":"autonomous-sandbox-agent"}`.

Tests: `pytest` (from `backend/`, with the venv active).

Frontend (backend running first):

```bash
cd frontend
npm ci
npm run dev                      # http://localhost:5173
```

For a production-style local serve, `npm run build` then
`npm run preview`.

## Option B — Docker Compose

Prerequisites: Docker with the Compose plugin.

```bash
cp backend/.env.example .env     # NOTE: at the REPOSITORY ROOT —
                                 # compose reads this file, and it is
                                 # a different file from backend/.env
# fill in GROQ_API_KEY and GROQ_MODEL in ./.env
docker compose --profile tools build sandbox-image   # sandbox image
docker compose up --build
```

- Frontend: http://localhost:5173 — Backend: http://localhost:8000
- Runtime state (task database + agent workspace) lives in the
  `app-data` named volume (`/data` in the backend container), wired
  via the `TASKS_DB_PATH` and `WORKSPACE_ROOT` settings.
- `VITE_API_BASE_URL` is baked into the frontend bundle at build
  time, so compose passes it as a build argument; the default
  (`http://localhost:8000`) is correct because the *browser* calls
  the backend through the host's published port 8000.
- Stop with `docker compose down` (add `-v` to also drop the state
  volume).

> **Status:** this compose file was validated structurally (YAML
> parse + service/volume assertions) in the Milestone 9 build
> environment, which has **no Docker daemon** — it has not been run
> with `docker compose up` yet. Its first live run is part of the
> pending Docker-host verification below.

### The Docker-socket tradeoff

The backend container mounts `/var/run/docker.sock` so it can start
sandbox containers. Socket access is effectively host-root access;
this is accepted only for the owner's local machine. Full discussion:
`docs/SECURITY.md` → "Deployment: the Docker-socket tradeoff".

### Sandbox execution under Compose — path caveat

The sandbox runner asks the **host** daemon to bind-mount the task
workspace into each sandbox container, passing the path as the
backend sees it. Under compose the workspace sits in a named volume
at `/data/workspace` *inside* the backend container; the host has no
such directory with the task files, so `run_python_file`/`run_tests`
cannot find them. The API, task service, workspace tools, and web
search all work under compose; only in-container execution is
affected. To make execution work on a Docker host, give the backend
a **host bind mount at an identical path** instead of the named
volume, e.g.:

```yaml
    environment:
      WORKSPACE_ROOT: /data/workspace
    volumes:
      - /home/you/asa-data:/data        # host dir == container path
```

and keep `TASKS_DB_PATH` under the same mount. (Running the backend
manually on the host — Option A — has no such issue: the workspace
path is a real host path.)

## Pending live verifications

Everything that could be verified without a Docker daemon or a real
Groq key has been (see `docs/ROADMAP.md`). Exactly two verifications
remain, both needing the owner's machine:

### 1. Live sandbox execution (needs a Docker host)

```bash
docker build -t autonomous-sandbox-agent:latest sandbox/

# output capture:
docker run --rm --network none autonomous-sandbox-agent:latest \
  python -c "print('sandbox ok')"            # expect: sandbox ok

# non-zero exit propagates:
docker run --rm autonomous-sandbox-agent:latest \
  python -c "import sys; sys.exit(3)"; echo "exit=$?"   # expect: 3

# network isolation (the runner always passes --network none):
docker run --rm --network none autonomous-sandbox-agent:latest \
  python -c "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)"
# expect: an exception (no network), not a successful fetch
```

Then, with the backend running on that host (Option A), submit a
task through the API that creates and runs a Python file, and
confirm the task record shows the real `run_python_file` tool call
and the program's real output in the summary.

### 2. Live Groq model call (needs a valid GROQ_API_KEY)

```bash
# in backend/.env:
#   GROQ_API_KEY=<your key>
#   GROQ_MODEL=llama-3.3-70b-versatile   (or another tool-calling model)
cd backend && uvicorn app.main:app --port 8000
curl -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task": "Create hello.py that prints hello from the agent, then run it and tell me the output"}'
curl http://127.0.0.1:8000/tasks/<task_id>   # poll until terminal
```

Expect: a `completed` record whose tool calls and summary reflect
real model/tool behaviour. A `failed` record with a real API error
(e.g. 401 for a bad key) is also a passing honesty check — a fake
success is the only failure mode that matters.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `POST /tasks` → 503 "LLM not configured" | `GROQ_API_KEY`/`GROQ_MODEL` empty in the env the backend loaded. |
| Task summary says execution unavailable | Docker is not running, or the sandbox image is not built (`docker build -t autonomous-sandbox-agent:latest sandbox/`). |
| Task fails with a 401 from the model API | The Groq key is invalid/revoked — issue a fresh key; the backend fails fast on auth errors by design. |
| Task fails with 429s after retries | Groq rate limit; wait, or lower task frequency. |
| Frontend shows "Backend unreachable" | Backend is not running on port 8000, or the frontend was built with a different `VITE_API_BASE_URL`. |
| Frontend loads but API calls are blocked (CORS) | The page's origin is not in `FRONTEND_ORIGINS` (default covers `localhost:5173`). |
| Under compose, sandbox can't see task files | The path caveat above — use the bind-mount arrangement. |
| `npm audit` findings unknown | The Milestone 8 audit could not run in the build environment (registry proxy 403); run `npm audit` locally. |

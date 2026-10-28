# Autonomous Sandbox Agent

An autonomous AI software-development agent: it accepts a task in natural
language, plans the work, creates and edits files, executes code inside a
restricted Docker sandbox, observes the real output, fixes errors, runs
tests, and reports what was actually verified.

**Golden rule:** the AI suggests, the backend verifies, the sandbox
contains. The agent never fabricates terminal output, test results, or
file contents.

## Architecture

- **Backend** (FastAPI, `backend/`): a controlled agent loop calls a
  Groq model (OpenAI-compatible API) and validates every tool call
  server-side before dispatch.
- **Tools**: confined workspace file operations, sandboxed execution
  (`python` file / `pytest` only, fixed allowlist), read-only git,
  and web search framed as untrusted data.
- **Sandbox** (`sandbox/`): a minimal non-root Python image; the
  backend runs it with no network, dropped capabilities, and fixed
  CPU/memory/PID limits the model cannot change.
- **Task service**: SQLite-backed task records, bounded concurrency,
  cancellation, honest status — served over a small REST API.
- **Frontend** (`frontend/`): a Vite + React dashboard that submits
  tasks and polls the real API for status, summaries, and tool-call
  timelines.

## Status

**All nine milestones are built.** Backend test suite: **118 passed**;
frontend production build verified. A fresh checkout was cloned and
re-verified end to end (tests, `/health`, frontend build) for
Milestone 9. Two verifications remain pending their hosts, honestly:

| Component | Verified | Pending |
|---|---|---|
| Backend API, task service, agent loop logic | This build env (118 tests, live `/health`) | — |
| Workspace confinement & tool policy | This build env (traversal/symlink/allowlist tests) | — |
| Web search (DuckDuckGo) | **Live** in this build env (real results) | Tavily live (no key here) |
| Frontend build + serving | This build env (`npm run build`, preview smoke) | `npm audit` (registry proxy blocked it) |
| Docker sandbox execution | Policy/argv tests only (fake runners) | **Live run on a Docker host** |
| Groq model call | Fake-client tests only (full loop behaviour) | **Live call with a valid `GROQ_API_KEY`** |
| Docker Compose stack | YAML structure validated | First `docker compose up` on a Docker host |

Per-milestone detail and evidence: [docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Then check the health endpoint:

```powershell
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"autonomous-sandbox-agent"}
```

Run the tests:

```powershell
cd backend
pytest -v
```

Frontend (backend must be running on port 8000 first):

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173 — see frontend/README.md
```

Or run the whole stack with Docker Compose (see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) first — it explains the
root `.env` file and the Docker-socket tradeoff):

```bash
cp backend/.env.example .env    # repository root; fill in your key
docker compose --profile tools build sandbox-image
docker compose up --build
```

## Configuration

Copy `backend/.env.example` to `backend/.env` and fill in your own values.
`.env` is excluded from Git. You will need a Groq API key from
<https://console.groq.com> starting at Milestone 4 — never commit it and
never paste it into chat.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the four parts fit together
- [docs/SECURITY.md](docs/SECURITY.md) — safeguards and honest limitations
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — local run (manual + compose), troubleshooting, pending live verifications
- [docs/ROADMAP.md](docs/ROADMAP.md) — the nine milestones

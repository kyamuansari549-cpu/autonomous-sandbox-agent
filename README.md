# Autonomous Sandbox Agent

An autonomous AI software-development agent: it accepts a task in natural
language, plans the work, creates and edits files, executes code inside a
restricted Docker sandbox, observes the real output, fixes errors, runs
tests, and reports what was actually verified.

**Golden rule:** the AI suggests, the backend verifies, the sandbox
contains. The agent never fabricates terminal output, test results, or
file contents.

## Status

**Milestones 1–7 are built** — FastAPI backend with confined
workspace tools, a hardened Docker sandbox runner, the Groq agent
loop, a SQLite-backed task service with a task API, a live web-search
tool, and the React frontend. Backend test suite: **109 passed**.
Two verifications remain pending their hosts, honestly: executing
code inside a real Docker container (needs a Docker host) and a live
Groq model call (needs a valid `GROQ_API_KEY`). Per-milestone detail
and evidence: [docs/ROADMAP.md](docs/ROADMAP.md).

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

## Configuration

Copy `backend/.env.example` to `backend/.env` and fill in your own values.
`.env` is excluded from Git. You will need a Groq API key from
<https://console.groq.com> starting at Milestone 4 — never commit it and
never paste it into chat.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the four parts fit together
- [docs/SECURITY.md](docs/SECURITY.md) — safeguards and honest limitations
- [docs/ROADMAP.md](docs/ROADMAP.md) — the nine milestones

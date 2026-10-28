# Autonomous Sandbox Agent

An autonomous AI software-development agent: it accepts a task in natural
language, plans the work, creates and edits files, executes code inside a
restricted Docker sandbox, observes the real output, fixes errors, runs
tests, and reports what was actually verified.

**Golden rule:** the AI suggests, the backend verifies, the sandbox
contains. The agent never fabricates terminal output, test results, or
file contents.

## Status

**Milestone 1 (Foundation) is complete** — project structure, FastAPI
backend with a health endpoint, environment-based configuration, and a
passing automated test suite. Everything else (workspace tools, Docker
sandbox, Groq agent loop, web search, React frontend) is planned work;
see [docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start (Milestone 1)

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

## Configuration

Copy `backend/.env.example` to `backend/.env` and fill in your own values.
`.env` is excluded from Git. You will need a Groq API key from
<https://console.groq.com> starting at Milestone 4 — never commit it and
never paste it into chat.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the four parts fit together
- [docs/SECURITY.md](docs/SECURITY.md) — safeguards and honest limitations
- [docs/ROADMAP.md](docs/ROADMAP.md) — the nine milestones

# Frontend — Autonomous Sandbox Agent

A small React + TypeScript dashboard for the backend task API: submit
a task, watch its real status and tool calls, read its result or
error, and cancel it while it runs. React + Vite only — no UI kit, no
state library, no router.

## Prerequisites

- Node.js (developed against Node 24 / npm 10)
- The backend running first (see below)

## Run it

Start the backend on port 8000 (from the project root):

```powershell
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Then start the frontend dev server:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The backend's CORS settings
(`FRONTEND_ORIGINS`, default `http://localhost:5173` and
`http://127.0.0.1:5173`) already allow this origin.

Production build: `npm run build` (type-checks with `tsc`, then
bundles into `dist/`); `npm run preview` serves that build locally.

## Configuration

| Variable            | Default                 | Meaning                     |
| ------------------- | ----------------------- | --------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the backend API |

Set it in `frontend/.env` (see `.env.example`) when the backend runs
somewhere else, and restart the dev server — Vite reads it at startup.

## How it stays honest

- **Polling, not fake streaming.** While the selected task is
  `queued`/`running`, the detail panel re-fetches `GET /tasks/{id}`
  every 2 seconds and renders exactly what the API returned. Polling
  stops at a terminal status (`completed`, `max_iterations`,
  `failed`, `cancelled`). There is no simulated progress anywhere.
- **Real errors, shown plainly.** If the backend is not running, a
  "Backend unreachable" banner appears with a Retry button. If the
  backend refuses a task — e.g. HTTP 503 because `GROQ_API_KEY` is not
  configured — the backend's own `detail` message is displayed in the
  form, unchanged.
- **Cancellation is a request, not a lie.** The Cancel button calls
  `POST /tasks/{id}/cancel`; the task stops at its next step and the
  panel keeps polling until the stored record reaches `cancelled`.

## Known API limitation

The backend records `tool_calls` as an ordered list of tool **names
only** (`backend/app/services/task_service.py`) — no arguments, no
per-call results. The timeline therefore shows exactly those names,
and this UI deliberately has **no "files changed" view**: deriving one
would mean inventing data the API never returned. Adding such a view
requires a backend change to persist tool-call arguments first.

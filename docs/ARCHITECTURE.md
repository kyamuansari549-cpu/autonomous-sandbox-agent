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

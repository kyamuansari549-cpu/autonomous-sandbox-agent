# Backend image for the autonomous sandbox agent (Milestone 9).
#
# Layout note: the app package is copied to /app/app and uvicorn runs
# from /app, mirroring how it runs from backend/ in a manual checkout.
# Runtime state does NOT live in the image: the task database and the
# agent workspace are redirected onto a volume via TASKS_DB_PATH and
# WORKSPACE_ROOT (see docker-compose.yml and docs/DEPLOYMENT.md).
FROM python:3.12-slim

# Run as an unprivileged user, never root.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies first so this layer is cached unless requirements change.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code only (tests and local state are .dockerignore'd).
COPY app ./app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

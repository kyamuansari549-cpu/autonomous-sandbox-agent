# Execution image for the autonomous sandbox agent (Milestone 3).
#
# Generated code runs ONLY inside containers built from this image, via
# the fixed argument list built by backend/app/sandbox/runner.py. The
# image itself is deliberately minimal:
#
#   * a stock CPython on a slim Debian base — nothing else installed;
#   * execution happens as the unprivileged "sandbox" user (uid 10001),
#     never as root;
#   * the task workspace is bind-mounted at /work by the runner; the
#     image ships no code and no credentials of its own.
#
# Build it (on a machine with Docker) from the repository root:
#
#   docker build -t autonomous-sandbox-agent:latest sandbox/
#
# Runtime hardening (network isolation, resource limits, dropped
# capabilities, read-only root filesystem, ...) is NOT baked in here —
# it is applied per-run by the backend runner so the model can never
# control it. See docs/SECURITY.md.
FROM python:3.12-slim

# Dedicated non-root user with a fixed uid/gid. The runner also passes
# --user 10001:10001 so the uid is pinned even if the image is rebuilt.
RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

# The task workspace is mounted here at runtime (and only there).
WORKDIR /work

# No .pyc files written into the (read-only) filesystem; unbuffered
# stdout/stderr so captured output is complete and in order.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

USER sandbox

CMD ["python"]

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
- **Sandboxed execution (Milestone 3):** generated code runs in Docker as
  a non-root user — never privileged, no Docker socket mounted, no host
  filesystem beyond the single task workspace, networking disabled by
  default, CPU/memory/process/time limits, dropped capabilities,
  `no-new-privileges`, output-size caps, and guaranteed container cleanup
  after timeouts.
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
- **Web content is untrusted data:** search results are information, never
  instructions (Milestone 6).
- **Secrets hygiene:** keys live only in a local `.env` excluded from Git;
  keys are never logged.

## Honest limitations

- Docker is a strong isolation layer, **not a perfect one**. Container
  escapes and kernel vulnerabilities exist; this design reduces risk, it
  does not eliminate it.
- This agent is built for **local, single-user use by its owner**. It must
  not be exposed to untrusted public users without an additional
  authentication and isolation design.
- Groq's free tier has rate limits; the backend must handle 429s honestly
  rather than pretending work happened.
- Approval prompts only help if the user actually reads them. Dangerous
  operations stay blocked by policy even if a user would approve them.

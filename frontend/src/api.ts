// Typed client for the backend task API.
//
// The shapes below mirror backend/app/schemas.py exactly:
//   POST /tasks            {task} -> {task_id, status}
//   GET  /tasks            -> TaskRecord[] (newest first)
//   GET  /tasks/{id}       -> TaskRecord
//   POST /tasks/{id}/cancel -> TaskRecord
//
// Note: `tool_calls` is a list of tool NAMES only — the backend does
// not record arguments, so this UI never pretends to know which files
// a tool call touched.
//
// Errors are surfaced, never hidden: a non-2xx response throws an
// ApiError carrying FastAPI's `detail` text (e.g. the 503 "LLM not
// configured" message), and a failed fetch throws
// BackendUnreachableError so the UI can say so plainly.

export interface TaskRecord {
  task_id: string;
  task: string;
  status: string;
  created_at: string;
  updated_at: string;
  result_summary: string | null;
  tool_calls: string[];
  error: string | null;
}

export interface TaskCreated {
  task_id: string;
  status: string;
}

export const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/$/, '');

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
  }
}

export class BackendUnreachableError extends Error {
  constructor() {
    super(
      `Backend unreachable at ${apiBaseUrl}. ` +
        'Start the backend first, then reload this page.',
    );
    this.name = 'BackendUnreachableError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new BackendUnreachableError();
  }
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (
        body !== null &&
        typeof body === 'object' &&
        'detail' in body &&
        typeof (body as { detail: unknown }).detail === 'string'
      ) {
        detail = (body as { detail: string }).detail;
      }
    } catch {
      // Keep the generic message when the body is not JSON.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function listTasks(): Promise<TaskRecord[]> {
  return request<TaskRecord[]>('/tasks');
}

export function getTask(taskId: string): Promise<TaskRecord> {
  return request<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}`);
}

export function createTask(task: string): Promise<TaskCreated> {
  return request<TaskCreated>('/tasks', {
    method: 'POST',
    body: JSON.stringify({ task }),
  });
}

export function cancelTask(taskId: string): Promise<TaskRecord> {
  return request<TaskRecord>(
    `/tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: 'POST' },
  );
}

/** Statuses after which a task never changes again (backend truth). */
const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'max_iterations',
  'failed',
  'cancelled',
]);

export function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

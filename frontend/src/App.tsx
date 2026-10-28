import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  BackendUnreachableError,
  apiBaseUrl,
  cancelTask,
  createTask,
  getTask,
  isTerminal,
  listTasks,
  type TaskRecord,
} from './api';

const POLL_INTERVAL_MS = 2000;

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function StatusPill({ status }: { status: string }) {
  const className = `pill pill--${status.replace(/_/g, '-')}`;
  return <span className={className}>{status.replace(/_/g, ' ')}</span>;
}

function TaskDetail({
  record,
  loadError,
  cancelling,
  cancelRequested,
  onCancel,
}: {
  record: TaskRecord | null;
  loadError: string | null;
  cancelling: boolean;
  cancelRequested: boolean;
  onCancel: () => void;
}) {
  if (loadError) {
    return (
      <div className="detail">
        <div className="error-box">{loadError}</div>
      </div>
    );
  }
  if (!record) {
    return (
      <div className="detail">
        <p className="placeholder">
          Select a task from the list, or submit a new one, to see its
          real status, tool calls and result here.
        </p>
      </div>
    );
  }
  const active = !isTerminal(record.status);
  return (
    <div className="detail">
      <div className="detail-header">
        <StatusPill status={record.status} />
        {active && (
          <button
            type="button"
            className="cancel-button"
            onClick={onCancel}
            disabled={cancelling}
          >
            {cancelling ? 'Requesting…' : 'Cancel task'}
          </button>
        )}
      </div>
      {active && cancelRequested && (
        <p className="hint">
          Cancellation requested. The task stops at its next step; this
          panel keeps updating until it reaches a final state.
        </p>
      )}
      <h2 className="detail-task">{record.task}</h2>
      <dl className="meta">
        <div>
          <dt>Task ID</dt>
          <dd className="mono">{record.task_id}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatTime(record.created_at)}</dd>
        </div>
        <div>
          <dt>Last updated</dt>
          <dd>{formatTime(record.updated_at)}</dd>
        </div>
      </dl>
      {active && (
        <p className="hint">
          Auto-refreshing every 2 seconds while the task is active.
        </p>
      )}
      {record.error && (
        <section>
          <h3>Error</h3>
          <div className="error-box">{record.error}</div>
        </section>
      )}
      {record.result_summary && (
        <section>
          <h3>Result summary</h3>
          <div className="result-box">{record.result_summary}</div>
        </section>
      )}
      <section>
        <h3>Tool calls</h3>
        {record.tool_calls.length > 0 ? (
          <ol className="timeline">
            {record.tool_calls.map((name, index) => (
              <li key={`${index}-${name}`} className="mono">
                {name}
              </li>
            ))}
          </ol>
        ) : (
          <p className="placeholder">
            {isTerminal(record.status)
              ? 'No tool calls were recorded for this task.'
              : 'No tool calls yet.'}
          </p>
        )}
      </section>
    </div>
  );
}

export default function App() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskRecord | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelRequestedFor, setCancelRequestedFor] = useState<
    string | null
  >(null);

  const refreshList = useCallback(async () => {
    try {
      const data = await listTasks();
      setTasks(data);
      setUnreachable(false);
      setListError(null);
    } catch (err) {
      if (err instanceof BackendUnreachableError) {
        setUnreachable(true);
      } else {
        setListError(errorMessage(err));
      }
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  // Fetch a fresh copy of the selected task whenever the selection
  // changes (the list copy is shown immediately in the meantime).
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let stale = false;
    getTask(selectedId)
      .then((record) => {
        if (!stale) {
          setDetail(record);
          setDetailError(null);
        }
      })
      .catch((err: unknown) => {
        if (!stale) setDetailError(errorMessage(err));
      });
    return () => {
      stale = true;
    };
  }, [selectedId]);

  // Poll the selected task every 2s while it is non-terminal; the
  // effect tears the interval down as soon as a terminal status (or a
  // different selection) is observed. Nothing here invents progress —
  // the panel only ever renders what GET /tasks/{id} returned.
  const detailIsTerminal = detail ? isTerminal(detail.status) : true;
  useEffect(() => {
    if (!selectedId || detailIsTerminal) return;
    const timer = window.setInterval(() => {
      getTask(selectedId)
        .then((record) => {
          setDetail(record);
          setTasks((prev) =>
            prev.map((t) => (t.task_id === record.task_id ? record : t)),
          );
        })
        .catch(() => {
          // Transient poll failure: keep showing the last record the
          // API actually returned instead of guessing a state.
        });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [selectedId, detailIsTerminal]);

  function selectTask(record: TaskRecord) {
    setSelectedId(record.task_id);
    setDetail(record);
    setDetailError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const created = await createTask(text);
      setDraft('');
      setCancelRequestedFor(null);
      await refreshList();
      setSelectedId(created.task_id);
    } catch (err) {
      if (err instanceof BackendUnreachableError) setUnreachable(true);
      setFormError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!detail || cancelling) return;
    setCancelling(true);
    try {
      const record = await cancelTask(detail.task_id);
      setDetail(record);
      setTasks((prev) =>
        prev.map((t) => (t.task_id === record.task_id ? record : t)),
      );
      setCancelRequestedFor(record.task_id);
    } catch (err) {
      setDetailError(errorMessage(err));
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Autonomous Sandbox Agent</h1>
        <p className="api-base">Backend API: {apiBaseUrl}</p>
      </header>

      {unreachable && (
        <div className="banner" role="alert">
          <span>
            Backend unreachable at {apiBaseUrl}. Start the backend
            first, then retry.
          </span>
          <button type="button" onClick={() => void refreshList()}>
            Retry
          </button>
        </div>
      )}

      <main className="layout">
        <aside className="sidebar">
          <form className="task-form" onSubmit={handleSubmit}>
            <label htmlFor="task-text">New task</label>
            <textarea
              id="task-text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Describe the task for the agent…"
              rows={4}
              disabled={submitting}
            />
            <button type="submit" disabled={submitting || !draft.trim()}>
              {submitting ? 'Submitting…' : 'Run task'}
            </button>
            {formError && <div className="error-box">{formError}</div>}
          </form>

          <h2 className="list-heading">Tasks</h2>
          {listError && <div className="error-box">{listError}</div>}
          {tasks.length === 0 && !listError && (
            <p className="placeholder">No tasks yet.</p>
          )}
          <ul className="task-list">
            {tasks.map((record) => (
              <li key={record.task_id}>
                <button
                  type="button"
                  className={
                    record.task_id === selectedId
                      ? 'task-item selected'
                      : 'task-item'
                  }
                  onClick={() => selectTask(record)}
                >
                  <span className="task-item-text">{record.task}</span>
                  <span className="task-item-meta">
                    <StatusPill status={record.status} />
                    <span className="task-item-time">
                      {formatTime(record.created_at)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <TaskDetail
          record={detail}
          loadError={detailError}
          cancelling={cancelling}
          cancelRequested={
            detail !== null && cancelRequestedFor === detail.task_id
          }
          onCancel={() => void handleCancel()}
        />
      </main>
    </div>
  );
}

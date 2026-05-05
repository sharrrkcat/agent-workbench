import { useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Run } from '../types';

export function RunPanel() {
  const { runs, runEvents, runEventLoading, loadRunEvents } = useWorkbenchStore();
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  async function toggleRun(run: Run) {
    const next = expandedRunId === run.run_id ? null : run.run_id;
    setExpandedRunId(next);
    if (next && !runEvents[run.run_id]) {
      await loadRunEvents(run.run_id);
    }
  }

  return (
    <aside className="run-panel">
      <div className="panel-title">
        <Activity size={16} />
        Runs
      </div>
      <div className="run-list">
        {runs.length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          runs
            .slice()
            .reverse()
            .map((run) => {
              const expanded = expandedRunId === run.run_id;
              const events = runEvents[run.run_id] || [];
              return (
                <div className={`run-row ${run.status.toLowerCase()}`} key={run.run_id}>
                  <button className="run-summary" type="button" onClick={() => void toggleRun(run)}>
                    {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <strong>{run.target_id}</strong>
                    <span>{run.status}</span>
                  </button>
                  {run.action_id ? <small>{run.action_id}</small> : null}
                  {run.current_step ? <em>{run.current_step}</em> : null}
                  {run.error ? <p>{run.error}</p> : null}
                  {expanded ? (
                    <div className="run-timeline">
                      {runEventLoading === run.run_id ? (
                        <div className="timeline-loading">
                          <Loader2 size={13} className="spin" />
                          Loading timeline
                        </div>
                      ) : events.length === 0 ? (
                        <p className="muted">No timeline events.</p>
                      ) : (
                        events.map((event) => (
                          <div className="timeline-event" key={event.event_id}>
                            <time>{new Date(event.created_at).toLocaleTimeString()}</time>
                            <strong>{event.type}</strong>
                            {event.message ? <span>{event.message}</span> : null}
                          </div>
                        ))
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })
        )}
      </div>
    </aside>
  );
}

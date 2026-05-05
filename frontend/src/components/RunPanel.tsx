import { Activity } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function RunPanel() {
  const runs = useWorkbenchStore((state) => state.runs);

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
            .map((run) => (
              <div className={`run-row ${run.status.toLowerCase()}`} key={run.run_id}>
                <div>
                  <strong>{run.target_id}</strong>
                  {run.action_id ? <small>{run.action_id}</small> : null}
                </div>
                <span>{run.status}</span>
                {run.current_step ? <em>{run.current_step}</em> : null}
                {run.error ? <p>{run.error}</p> : null}
              </div>
            ))
        )}
      </div>
    </aside>
  );
}

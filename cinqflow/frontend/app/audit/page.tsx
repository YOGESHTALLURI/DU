'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';

interface AuditItem {
  id: string;
  action: string;
  actor_id: string;
  actor_email?: string;
  object_type: string;
  object_id?: string;
  description?: string;
  created_at: string;
  before_state?: any;
  after_state?: any;
}

export default function AuditPage() {
  const [events, setEvents] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAction, setFilterAction] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('cinqflow_token');
    const url = filterAction
      ? `/api/v1/audit/events?action=${filterAction}`
      : '/api/v1/audit/events?limit=50';

    fetch(url, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setEvents(data))
      .finally(() => setLoading(false));
  }, [filterAction]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Immutable Audit Trail</h1>
            <p className="text-sm text-slate-400 mt-1">
              Append-only historical ledger of all configuration changes, batch lifecycles, and operational decisions.
            </p>
          </div>
          <div>
            <select
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
              className="bg-slate-900 border border-slate-700 text-xs text-slate-200 px-3 py-2 rounded-lg"
            >
              <option value="">All Actions</option>
              <option value="feed.created">feed.created</option>
              <option value="feed_version.published">feed_version.published</option>
              <option value="input.registered">input.registered</option>
              <option value="input.duplicate_detected">input.duplicate_detected</option>
              <option value="batch.started">batch.started</option>
              <option value="stage.completed">stage.completed</option>
              <option value="quarantine.record_added">quarantine.record_added</option>
              <option value="reconciliation.computed">reconciliation.computed</option>
            </select>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Recorded Audit Events ({events.length})
          </h2>

          {loading ? (
            <p className="text-xs text-slate-400">Loading audit trail...</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-slate-500 py-4">No audit events found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-medium">
                    <th className="pb-3">Timestamp</th>
                    <th className="pb-3">Action</th>
                    <th className="pb-3">Actor</th>
                    <th className="pb-3">Object Type</th>
                    <th className="pb-3">Description</th>
                    <th className="pb-3">State Diff</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {events.map((e) => (
                    <tr key={e.id} className="hover:bg-slate-800/40">
                      <td className="py-3 text-slate-400 text-[10px]">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                      <td className="py-3">
                        <span className="bg-blue-950 text-blue-400 border border-blue-800 px-2 py-0.5 rounded text-[10px] font-semibold">
                          {e.action}
                        </span>
                      </td>
                      <td className="py-3 text-slate-300 text-xs font-sans">{e.actor_email || e.actor_id}</td>
                      <td className="py-3 text-slate-400">{e.object_type}</td>
                      <td className="py-3 text-slate-300 font-sans text-xs">{e.description}</td>
                      <td className="py-3">
                        {e.after_state && (
                          <pre className="text-[10px] text-emerald-400 bg-slate-950 p-1.5 rounded max-w-xs truncate border border-slate-800">
                            {JSON.stringify(e.after_state)}
                          </pre>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

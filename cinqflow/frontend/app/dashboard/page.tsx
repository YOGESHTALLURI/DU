'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface BatchSummary {
  id: string;
  feed_id: string;
  status: string;
  created_at: string;
  restart_count: number;
}

export default function DashboardPage() {
  const [stats, setStats] = useState({
    totalFeeds: 0,
    totalContracts: 0,
    openUnknowns: 0,
    totalBatches: 0,
    successfulBatches: 0,
    recentBatches: [] as BatchSummary[],
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('cinqflow_token');
    const headers = { Authorization: `Bearer ${token || ''}` };

    Promise.all([
      fetch('/api/v1/feeds', { headers }).then((r) => (r.ok ? r.json() : [])),
      fetch('/api/v1/contracts', { headers }).then((r) => (r.ok ? r.json() : [])),
      fetch('/api/v1/contracts/risk-view', { headers }).then((r) => (r.ok ? r.json() : { open_unknowns: 0 })),
      fetch('/api/v1/pipeline/batches?limit=10', { headers }).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([feeds, contracts, risk, batches]) => {
        setStats({
          totalFeeds: feeds.length,
          totalContracts: contracts.length,
          openUnknowns: risk.open_unknowns || 0,
          totalBatches: batches.length,
          successfulBatches: batches.filter((b: BatchSummary) => b.status === 'SUCCESS').length,
          recentBatches: batches,
        });
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Wave 0 Control Plane & Pipeline Monitor</h1>
            <p className="text-sm text-slate-400 mt-1">
              Live operational metrics derived directly from metadata & database state.
            </p>
          </div>
          <Link
            href="/landing"
            className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition"
          >
            + Ingest New File
          </Link>
        </div>

        {/* Real Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Configured Feeds</p>
            <p className="text-3xl font-bold text-blue-400 mt-2">{loading ? '...' : stats.totalFeeds}</p>
            <p className="text-xs text-slate-500 mt-1">Generic metadata-driven</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Contract Register</p>
            <p className="text-3xl font-bold text-emerald-400 mt-2">{loading ? '...' : stats.totalContracts}</p>
            <p className="text-xs text-slate-500 mt-1">Execution-plane domains</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Unconfirmed Assumptions</p>
            <p className="text-3xl font-bold text-amber-400 mt-2">{loading ? '...' : stats.openUnknowns}</p>
            <p className="text-xs text-slate-500 mt-1">Open unknown risks</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Pipeline Batches</p>
            <p className="text-3xl font-bold text-indigo-400 mt-2">
              {loading ? '...' : `${stats.successfulBatches}/${stats.totalBatches}`}
            </p>
            <p className="text-xs text-slate-500 mt-1">Successful / Total runs</p>
          </div>
        </div>

        {/* Recent Batches Execution Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Recent Batch Executions</h2>
            <Link href="/landing" className="text-xs text-blue-400 hover:underline">
              View All Inputs &rarr;
            </Link>
          </div>
          {stats.recentBatches.length === 0 ? (
            <p className="text-sm text-slate-500 py-4">No pipeline runs executed yet. Ingest a file to start.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-3 font-medium">Batch ID</th>
                    <th className="pb-3 font-medium">Status</th>
                    <th className="pb-3 font-medium">Restarts</th>
                    <th className="pb-3 font-medium">Started At</th>
                    <th className="pb-3 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {stats.recentBatches.map((b) => (
                    <tr key={b.id} className="hover:bg-slate-800/40">
                      <td className="py-3 font-mono text-xs text-blue-300">{b.id}</td>
                      <td className="py-3">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-semibold ${
                            b.status === 'SUCCESS'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : b.status === 'FAILED'
                              ? 'bg-rose-950 text-rose-400 border border-rose-800'
                              : 'bg-amber-950 text-amber-400 border border-amber-800'
                          }`}
                        >
                          {b.status}
                        </span>
                      </td>
                      <td className="py-3 font-mono text-xs">{b.restart_count}</td>
                      <td className="py-3 text-xs text-slate-400">{new Date(b.created_at).toLocaleString()}</td>
                      <td className="py-3">
                        <Link
                          href={`/batches/${b.id}`}
                          className="text-xs text-blue-400 hover:text-blue-300 font-medium"
                        >
                          View Details &rarr;
                        </Link>
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

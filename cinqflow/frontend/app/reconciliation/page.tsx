'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface BatchSummary {
  id: string;
  feed_id: string;
  status: string;
  created_at: string;
}

export default function ReconciliationPage() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [reconciliations, setReconciliations] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('cinqflow_token');
    const headers = { Authorization: `Bearer ${token || ''}` };

    fetch('/api/v1/pipeline/batches', { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then(async (batchList) => {
        setBatches(batchList);
        const reconMap: Record<string, any> = {};
        for (const b of batchList) {
          try {
            const res = await fetch(`/api/v1/reconciliation/batches/${b.id}`, { headers });
            if (res.ok) {
              reconMap[b.id] = await res.json();
            }
          } catch {}
        }
        setReconciliations(reconMap);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white">Reconciliation Ledger & Balance Engine</h1>
          <p className="text-sm text-slate-400 mt-1">
            Mathematical proof of zero unexplained row loss:{' '}
            <span className="font-mono text-emerald-400 font-semibold">
              Input Rows = Silver Raw Rows + Quarantined Rows + Dropped Rows
            </span>
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Batch Reconciliation Ledger History
          </h2>

          {loading ? (
            <p className="text-xs text-slate-400">Loading reconciliation ledger...</p>
          ) : batches.length === 0 ? (
            <p className="text-xs text-slate-500 py-4">No batch reconciliations available.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-medium">
                    <th className="pb-3">Batch ID</th>
                    <th className="pb-3 text-center">Input Rows</th>
                    <th className="pb-3 text-center">=</th>
                    <th className="pb-3 text-center">Silver Raw</th>
                    <th className="pb-3 text-center">+</th>
                    <th className="pb-3 text-center">Quarantined</th>
                    <th className="pb-3 text-center">+</th>
                    <th className="pb-3 text-center">Dropped</th>
                    <th className="pb-3 text-center">Discrepancy</th>
                    <th className="pb-3 text-center">Balance Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-mono">
                  {batches.map((b) => {
                    const recon = reconciliations[b.id];
                    return (
                      <tr key={b.id} className="hover:bg-slate-800/40">
                        <td className="py-3 text-blue-400 font-bold">
                          <Link href={`/batches/${b.id}`} className="hover:underline">
                            {b.id.slice(0, 8)}...
                          </Link>
                        </td>
                        <td className="py-3 text-center text-white font-bold">{recon ? recon.rows_in : '—'}</td>
                        <td className="py-3 text-center text-slate-600">=</td>
                        <td className="py-3 text-center text-blue-400">{recon ? recon.rows_silver_raw : '—'}</td>
                        <td className="py-3 text-center text-slate-600">+</td>
                        <td className="py-3 text-center text-amber-400">{recon ? recon.rows_quarantined : '—'}</td>
                        <td className="py-3 text-center text-slate-600">+</td>
                        <td className="py-3 text-center text-slate-400">{recon ? recon.rows_dropped : '—'}</td>
                        <td className="py-3 text-center text-emerald-400">{recon ? recon.discrepancy : '—'}</td>
                        <td className="py-3 text-center">
                          {recon ? (
                            <span
                              className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${
                                recon.status === 'PASS'
                                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                  : 'bg-rose-950 text-rose-400 border border-rose-800'
                              }`}
                            >
                              {recon.status}
                            </span>
                          ) : (
                            <span className="text-slate-500 text-[10px]">PENDING</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

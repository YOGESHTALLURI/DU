'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';
import DriftAlertBanner from '@/components/drift/DriftAlertBanner';
import ProductionDQSummary from '@/components/rules/ProductionDQSummary';

interface Stage {
  id: string;
  stage_name: string;
  stage_order: number;
  status: string;
  rows_in: number;
  rows_out: number;
  rows_quarantined: number;
  rows_dropped: number;
  output_path: string;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
}

interface BatchDetail {
  id: string;
  feed_id: string;
  status: string;
  restart_count: number;
  triggered_by: string;
  error_message?: string;
  created_at: string;
  stages: Stage[];
}

export default function BatchDetailPage() {
  const params = useParams();
  const batchId = params?.id as string;
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [reconciliation, setReconciliation] = useState<any>(null);

  const fetchBatch = () => {
    if (!batchId) return;
    const token = localStorage.getItem('cinqflow_token');
    const headers = { Authorization: `Bearer ${token || ''}` };

    fetch(`/api/v1/pipeline/batches/${batchId}`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setBatch(data))
      .finally(() => setLoading(false));

    fetch(`/api/v1/reconciliation/batches/${batchId}`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setReconciliation(data))
      .catch(() => setReconciliation(null));
  };

  useEffect(() => {
    fetchBatch();
  }, [batchId]);

  const handleExecute = async () => {
    setExecuting(true);
    const token = localStorage.getItem('cinqflow_token');
    await fetch(`/api/v1/pipeline/batches/${batchId}/execute`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token || ''}` },
    });
    fetchBatch();
    setExecuting(false);
  };

  const handleRestart = async () => {
    setExecuting(true);
    const token = localStorage.getItem('cinqflow_token');
    await fetch(`/api/v1/pipeline/batches/${batchId}/restart`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token || ''}` },
    });
    fetchBatch();
    setExecuting(false);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8">Loading batch execution details...</div>
      </div>
    );
  }

  if (!batch) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8">Batch not found.</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href="/dashboard" className="text-xs text-blue-400 hover:underline">
              &larr; Back to Dashboard
            </Link>
            <h1 className="text-2xl font-bold text-white font-mono mt-1">Batch: {batch.id}</h1>
          </div>
          <div className="flex items-center space-x-3">
            <span
              className={`px-3 py-1 rounded-full text-xs font-semibold ${
                batch.status === 'SUCCESS'
                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                  : batch.status === 'FAILED'
                  ? 'bg-rose-950 text-rose-400 border border-rose-800'
                  : 'bg-amber-950 text-amber-400 border border-amber-800'
              }`}
            >
              Status: {batch.status} (Restarts: {batch.restart_count})
            </span>
            {batch.status === 'PENDING' && (
              <button
                onClick={handleExecute}
                disabled={executing}
                className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-1.5 rounded-lg text-xs font-medium transition"
              >
                {executing ? 'Executing...' : 'Run Pipeline'}
              </button>
            )}
            {batch.status === 'FAILED' && (
              <button
                onClick={handleRestart}
                disabled={executing}
                className="bg-amber-600 hover:bg-amber-500 text-white px-4 py-1.5 rounded-lg text-xs font-medium transition"
              >
                {executing ? 'Restarting...' : 'Restart From Failed Stage'}
              </button>
            )}
          </div>
        </div>

        {/* Pre-Ingestion Schema Drift Alert Banner */}
        <DriftAlertBanner batchId={batch.id} feedId={batch.feed_id} onAcknowledged={fetchBatch} />

        {/* Stage Execution Progress Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {batch.stages.map((stage) => (
            <div key={stage.id} className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-400 font-mono">
                  STAGE {stage.stage_order}: {stage.stage_name}
                </span>
                <span
                  className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                    stage.status === 'SUCCESS'
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                      : stage.status === 'FAILED'
                      ? 'bg-rose-950 text-rose-400 border border-rose-800'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {stage.status}
                </span>
              </div>
              <div className="mt-4 space-y-1 text-xs font-mono text-slate-300">
                <p>Rows In: <span className="text-white font-bold">{stage.rows_in ?? '—'}</span></p>
                <p>Rows Out: <span className="text-white font-bold">{stage.rows_out ?? '—'}</span></p>
                <p>Quarantined: <span className="text-amber-400 font-bold">{stage.rows_quarantined ?? '—'}</span></p>
                <p className="truncate text-[10px] text-slate-500 mt-2">Output: {stage.output_path || 'None'}</p>
              </div>
              {stage.error_message && (
                <p className="text-xs text-rose-400 mt-2 bg-rose-950/40 p-2 rounded border border-rose-800">
                  {stage.error_message}
                </p>
              )}
            </div>
          ))}
        </div>

        {/* Production DQ Execution Summary */}
        <ProductionDQSummary batchId={batch.id} />

        {/* Reconciliation Result Card */}
        {reconciliation && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                Measurable Reconciliation Balance
              </h2>
              <span
                className={`px-3 py-1 rounded text-xs font-bold ${
                  reconciliation.status === 'PASS'
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : 'bg-rose-950 text-rose-400 border border-rose-800'
                }`}
              >
                Reconciliation: {reconciliation.status}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-4 text-center font-mono text-sm bg-slate-950 p-4 rounded-lg border border-slate-800">
              <div>
                <p className="text-slate-500 text-xs">Total In</p>
                <p className="text-2xl font-bold text-white mt-1">{reconciliation.rows_in}</p>
              </div>
              <div>
                <p className="text-slate-500 text-xs">Silver Raw</p>
                <p className="text-2xl font-bold text-blue-400 mt-1">{reconciliation.rows_silver_raw}</p>
              </div>
              <div>
                <p className="text-slate-500 text-xs">Quarantined</p>
                <p className="text-2xl font-bold text-amber-400 mt-1">{reconciliation.rows_quarantined}</p>
              </div>
              <div>
                <p className="text-slate-500 text-xs">Discrepancy</p>
                <p className="text-2xl font-bold text-emerald-400 mt-1">{reconciliation.discrepancy}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

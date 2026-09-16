'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface ColumnStat {
  id: string;
  column_name: string;
  ordinal_position: number;
  inferred_type: string;
  null_count: number;
  null_percentage: number;
  distinct_count: number;
  distinct_percentage: number;
  min_value: string | null;
  max_value: string | null;
  sample_values: string[] | null;
  detected_date_patterns: { pattern: string; count: number }[] | null;
}

interface ProfilingDetails {
  id: string;
  feed_id: string;
  sample_file_id: string;
  status: string;
  started_at: string;
  completed_at: string;
  row_count: number;
  column_count: number;
  profiling_summary: any;
  error_message: string | null;
  column_stats: ColumnStat[];
}

export default function ProfilingResultsPage() {
  const params = useParams();
  const runId = params?.id as string;
  const [details, setDetails] = useState<ProfilingDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [creatingSchema, setCreatingSchema] = useState(false);
  const [schemaName, setSchemaName] = useState('');
  const [schemaDesc, setSchemaDesc] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!runId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/profiling-runs/${runId}`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setDetails(data);
        if (data) {
          setSchemaName(`Schema from Profiling Run ${data.id.slice(0, 8)}`);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [runId]);

  const handleCreateSchema = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!details) return;
    setCreatingSchema(true);
    setError('');

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/schemas', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({
          feed_id: details.feed_id,
          name: schemaName,
          description: schemaDesc,
          source_profiling_run_id: details.id,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to create schema' }));
        setError(err.detail || 'Failed to create schema');
        return;
      }

      const newSchema = await res.json();
      window.location.href = `/schemas/${newSchema.id}`;
    } catch {
      setError('Connection error while creating schema contract');
    } finally {
      setCreatingSchema(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-xs text-slate-400">Loading profiling results...</div>
      </div>
    );
  }

  if (!details) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-xs text-rose-400">Profiling run not found.</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href={`/feeds/${details.feed_id}/samples`} className="text-xs text-blue-400 hover:underline">
              &larr; Back to Feed Samples
            </Link>
            <div className="flex items-center space-x-3 mt-1">
              <h1 className="text-2xl font-bold text-white">Deterministic Profiling Evidence</h1>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
                {details.status}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 font-mono">
              Run ID: {details.id} &bull; Sample File ID: {details.sample_file_id}
            </p>
          </div>

          <button
            onClick={() => setShowModal(true)}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition flex items-center space-x-2"
          >
            <span>Create Schema Contract Draft &rarr;</span>
          </button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-rose-950/60 border border-rose-800 rounded-xl text-rose-300 text-xs">
            {error}
          </div>
        )}

        {/* Fact Summary Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <span className="text-slate-400 text-xs uppercase tracking-wider font-semibold">Total Rows</span>
            <p className="text-2xl font-bold text-white mt-1 font-mono">{details.row_count.toLocaleString()}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <span className="text-slate-400 text-xs uppercase tracking-wider font-semibold">Total Columns</span>
            <p className="text-2xl font-bold text-white mt-1 font-mono">{details.column_count}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <span className="text-slate-400 text-xs uppercase tracking-wider font-semibold">Columns with Nulls</span>
            <p className="text-2xl font-bold text-amber-400 mt-1 font-mono">
              {details.profiling_summary?.columns_with_nulls ?? '—'}
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <span className="text-slate-400 text-xs uppercase tracking-wider font-semibold">Inference Engine</span>
            <p className="text-xs font-mono text-indigo-400 mt-2">Deterministic Rule Engine</p>
          </div>
        </div>

        {/* Column Observational Facts Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
              Column Observational Facts ({details.column_stats.length})
            </h2>
            <span className="text-xs text-slate-400 italic">
              Observational facts derived directly from sample bytes
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-medium">
                  <th className="pb-3">#</th>
                  <th className="pb-3">Column Name</th>
                  <th className="pb-3">Inferred Type (Fact)</th>
                  <th className="pb-3">Null Count (%)</th>
                  <th className="pb-3">Distinct Count (%)</th>
                  <th className="pb-3">Min / Max Range</th>
                  <th className="pb-3">Detected Date Patterns</th>
                  <th className="pb-3">Sample Values</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {details.column_stats.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-800/40">
                    <td className="py-3 font-mono text-slate-500">{c.ordinal_position}</td>
                    <td className="py-3 font-mono font-bold text-white">{c.column_name}</td>
                    <td className="py-3">
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-blue-950 text-blue-300 border border-blue-800">
                        {c.inferred_type}
                      </span>
                    </td>
                    <td className="py-3 font-mono">
                      <span className={c.null_count > 0 ? 'text-amber-400' : 'text-slate-400'}>
                        {c.null_count} ({c.null_percentage}%)
                      </span>
                    </td>
                    <td className="py-3 font-mono text-slate-300">
                      {c.distinct_count} ({c.distinct_percentage}%)
                    </td>
                    <td className="py-3 font-mono text-slate-400 text-[11px]">
                      {c.min_value || '—'} &rarr; {c.max_value || '—'}
                    </td>
                    <td className="py-3 font-mono">
                      {c.detected_date_patterns && c.detected_date_patterns.length > 0 ? (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-indigo-950 text-indigo-300 border border-indigo-800">
                          {c.detected_date_patterns[0].pattern} ({c.detected_date_patterns[0].count})
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="py-3 font-mono text-slate-400 text-[10px] max-w-xs truncate">
                      {c.sample_values ? c.sample_values.join(', ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Modal: Create Schema Contract Draft */}
        {showModal && (
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-md shadow-2xl">
              <h2 className="text-lg font-bold text-white mb-2">Create Schema Contract Draft</h2>
              <p className="text-xs text-slate-400 mb-6">
                This will create a governed draft schema contract for this feed. Profiling facts will seed the initial field definitions, retaining full lineage to this run.
              </p>
              <form onSubmit={handleCreateSchema} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Contract Name</label>
                  <input
                    type="text"
                    value={schemaName}
                    onChange={(e) => setSchemaName(e.target.value)}
                    required
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Description</label>
                  <textarea
                    value={schemaDesc}
                    onChange={(e) => setSchemaDesc(e.target.value)}
                    rows={3}
                    placeholder="Optional purpose or notes..."
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-xs text-white"
                  />
                </div>

                <div className="p-3 bg-slate-950 rounded-lg text-[11px] font-mono text-indigo-300 border border-slate-800">
                  <p>Feed ID: {details.feed_id}</p>
                  <p>Lineage: Run {details.id.slice(0, 8)}</p>
                  <p>Fields to seed: {details.column_stats.length}</p>
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-slate-800">
                  <button
                    type="button"
                    onClick={() => setShowModal(false)}
                    className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creatingSchema}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium"
                  >
                    {creatingSchema ? 'Creating Draft...' : 'Create Draft'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

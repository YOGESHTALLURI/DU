'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';
import { AlertCircle, CheckCircle2, ShieldCheck, Copy } from 'lucide-react';
import DriftAlertBanner from '@/components/drift/DriftAlertBanner';

interface VersionItem {
  id: string;
  version_number: number;
  status: string;
  config_snapshot: any;
  change_notes: string;
  published_by: string;
  created_at: string;
}

interface FeedDetail {
  id: string;
  name: string;
  domain: string;
  description: string;
  format: string;
  landing_folder: string;
  filename_pattern: string;
  schedule_expression: string;
  source_system?: string;
  data_owner?: string;
  sla_expectation?: string;
  cloned_from_feed_id?: string;
  status: string;
  versions: VersionItem[];
}

export default function FeedDetailPage() {
  const params = useParams();
  const feedId = params?.id as string;
  const [feed, setFeed] = useState<FeedDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [testFilename, setTestFilename] = useState('');
  const [matchResult, setMatchResult] = useState<boolean | null>(null);

  // Status transition state
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [statusSuccess, setStatusSuccess] = useState('');

  // Clone state
  const [showCloneModal, setShowCloneModal] = useState(false);
  const [cloneForm, setCloneForm] = useState({
    new_name: '',
    new_filename_pattern: '',
    description: '',
  });
  const [cloneError, setCloneError] = useState('');

  const fetchFeed = () => {
    if (!feedId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/feeds/${feedId}`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setFeed(data);
        if (data) {
          setCloneForm({
            new_name: `${data.name}_CLONE`,
            new_filename_pattern: data.filename_pattern,
            description: `Cloned from ${data.name}`,
          });
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchFeed();
  }, [feedId]);

  const handleStatusChange = async (targetStatus: string, reason?: string) => {
    setStatusLoading(true);
    setStatusError('');
    setStatusSuccess('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/feeds/${feedId}/status`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ status: targetStatus, reason: reason || `Changed via UI to ${targetStatus}` }),
      });
      if (!res.ok) {
        const err = await res.json();
        setStatusError(err.detail || `Failed to transition feed to ${targetStatus}`);
        return;
      }
      setStatusSuccess(`Feed status transitioned to ${targetStatus} successfully.`);
      fetchFeed();
    } catch {
      setStatusError('Connection error occurred while updating status.');
    } finally {
      setStatusLoading(false);
    }
  };

  const handleCloneSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCloneError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/feeds/${feedId}/clone`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify(cloneForm),
      });
      if (!res.ok) {
        const err = await res.json();
        setCloneError(err.detail || 'Failed to clone feed');
        return;
      }
      const cloned = await res.json();
      setShowCloneModal(false);
      setStatusSuccess(`Feed successfully cloned as ${cloned.name}.`);
    } catch {
      setCloneError('Connection error');
    }
  };

  const handleTestPattern = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!feedId || !testFilename) return;
    const token = localStorage.getItem('cinqflow_token');
    const res = await fetch(`/api/v1/feeds/${feedId}/validate-pattern`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token || ''}`,
      },
      body: JSON.stringify({ sample_filename: testFilename }),
    });
    if (res.ok) {
      const data = await res.json();
      setMatchResult(data.matches);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-slate-400">Loading feed details...</div>
      </div>
    );
  }

  if (!feed) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-slate-400">Feed not found.</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-16">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Navigation & Header */}
        <div className="mb-6">
          <Link href="/feeds" className="text-xs text-blue-400 hover:underline">
            &larr; Back to Feed Registry
          </Link>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mt-2">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white font-mono">{feed.name}</h1>
              {feed.cloned_from_feed_id && (
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-purple-950 text-purple-300 border border-purple-800">
                  CLONED FEED
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Link
                href={`/onboarding/${feed.id}`}
                className="bg-blue-600 hover:bg-blue-500 text-white px-3.5 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
              >
                Onboarding Wizard &rarr;
              </Link>
              <button
                onClick={() => setShowCloneModal(true)}
                className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1"
              >
                <Copy className="w-3.5 h-3.5" /> Clone
              </button>
              <span
                className={`px-3 py-1 rounded-full text-xs font-semibold ${
                  feed.status === 'ACTIVE'
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : feed.status === 'INACTIVE'
                    ? 'bg-slate-800 text-slate-400 border border-slate-700'
                    : feed.status === 'RETIRED'
                    ? 'bg-rose-950 text-rose-400 border border-rose-800'
                    : 'bg-amber-950 text-amber-400 border border-amber-800'
                }`}
              >
                {feed.status}
              </span>
            </div>
          </div>
        </div>

        {/* Notifications */}
        {statusError && (
          <div className="mb-6 p-4 bg-rose-950/80 border border-rose-800 rounded-xl text-xs text-rose-300 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <strong>Activation / Status Error:</strong> {statusError}
            </div>
          </div>
        )}
        {statusSuccess && (
          <div className="mb-6 p-4 bg-emerald-950/80 border border-emerald-800 rounded-xl text-xs text-emerald-300 flex items-start gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            <div>{statusSuccess}</div>
          </div>
        )}

        {/* Pre-Ingestion Schema Drift Banner */}
        <DriftAlertBanner feedId={feed.id} onAcknowledged={fetchFeed} />

        {/* Feed Metadata Card */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 md:col-span-2 space-y-4">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Feed Properties</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-xs font-mono">
              <div>
                <span className="text-slate-500">Domain:</span>
                <p className="text-white mt-0.5">{feed.domain}</p>
              </div>
              <div>
                <span className="text-slate-500">File Format:</span>
                <p className="text-white mt-0.5">{feed.format}</p>
              </div>
              <div>
                <span className="text-slate-500">Landing Folder:</span>
                <p className="text-white mt-0.5 truncate">{feed.landing_folder}</p>
              </div>
              <div>
                <span className="text-slate-500">Schedule:</span>
                <p className="text-white mt-0.5">{feed.schedule_expression}</p>
              </div>
              <div>
                <span className="text-slate-500">Source System:</span>
                <p className="text-white mt-0.5">{feed.source_system || '—'}</p>
              </div>
              <div>
                <span className="text-slate-500">Data Owner:</span>
                <p className="text-white mt-0.5">{feed.data_owner || '—'}</p>
              </div>
              {feed.sla_expectation && (
                <div className="col-span-2 sm:col-span-3">
                  <span className="text-slate-500">SLA Expectation:</span>
                  <p className="text-white mt-0.5">{feed.sla_expectation}</p>
                </div>
              )}
            </div>

            {/* Lifecycle Status Action Bar */}
            <div className="mt-6 pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="text-xs font-semibold text-slate-400">Lifecycle Controls:</span>
                <p className="text-[11px] text-slate-500">
                  {feed.status === 'DRAFT' && 'Feed requires a PUBLISHED schema contract to activate.'}
                  {feed.status === 'ACTIVE' && 'Feed is active and ingesting files.'}
                  {feed.status === 'INACTIVE' && 'Feed ingestion is paused.'}
                  {feed.status === 'RETIRED' && 'Feed is permanently retired (immutable).'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {feed.status === 'DRAFT' && (
                  <button
                    onClick={() => handleStatusChange('ACTIVE', 'Activated via Feed Details page')}
                    disabled={statusLoading}
                    className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-3.5 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                  >
                    <ShieldCheck className="w-4 h-4" />
                    {statusLoading ? 'Validating...' : 'Activate Feed'}
                  </button>
                )}
                {feed.status === 'ACTIVE' && (
                  <>
                    <button
                      onClick={() => handleStatusChange('INACTIVE', 'Deactivated via Feed Details')}
                      disabled={statusLoading}
                      className="bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-medium transition"
                    >
                      Deactivate
                    </button>
                    <button
                      onClick={() => handleStatusChange('RETIRED', 'Retired via Feed Details')}
                      disabled={statusLoading}
                      className="bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800 px-3 py-1.5 rounded-lg text-xs font-medium transition"
                    >
                      Retire Feed
                    </button>
                  </>
                )}
                {feed.status === 'INACTIVE' && (
                  <>
                    <button
                      onClick={() => handleStatusChange('ACTIVE', 'Reactivated via Feed Details')}
                      disabled={statusLoading}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-1.5 rounded-lg text-xs font-medium transition"
                    >
                      Reactivate Feed
                    </button>
                    <button
                      onClick={() => handleStatusChange('RETIRED', 'Retired via Feed Details')}
                      disabled={statusLoading}
                      className="bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800 px-3 py-1.5 rounded-lg text-xs font-medium transition"
                    >
                      Retire Feed
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Pattern Validator Interactive Tool */}
            <div className="mt-4 pt-4 border-t border-slate-800">
              <h3 className="text-xs font-semibold text-slate-300 mb-2">Test Filename Pattern Matcher</h3>
              <form onSubmit={handleTestPattern} className="flex gap-2">
                <input
                  type="text"
                  value={testFilename}
                  onChange={(e) => setTestFilename(e.target.value)}
                  placeholder={`e.g. ${feed.filename_pattern.replace('*', '20260901')}`}
                  className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs font-mono text-white"
                />
                <button
                  type="submit"
                  className="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-xs font-medium"
                >
                  Test Pattern
                </button>
              </form>
              {matchResult !== null && (
                <p className={`text-xs mt-2 font-mono ${matchResult ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {matchResult ? '✓ Filename MATCHES pattern' : '✗ Filename DOES NOT MATCH pattern'}
                </p>
              )}
            </div>
          </div>

          {/* Quick Actions Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2">Build & Profiling Paths</h2>
              <p className="text-xs text-slate-400 leading-relaxed mb-4">
                Use the 5-step guided onboarding wizard or jump directly into individual tools.
              </p>
              <div className="space-y-2">
                <Link
                  href={`/onboarding/${feed.id}`}
                  className="w-full block bg-blue-600 hover:bg-blue-500 text-white text-center py-2.5 rounded-lg text-xs font-bold transition shadow-lg shadow-blue-950/40"
                >
                  Launch 5-Step Onboarding Wizard &rarr;
                </Link>
                <Link
                  href={`/feeds/${feed.id}/samples`}
                  className="w-full block bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 text-center py-2 rounded-lg text-xs font-medium transition"
                >
                  Samples & Profiling &rarr;
                </Link>
                <Link
                  href={`/feeds/${feed.id}/schemas`}
                  className="w-full block bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-center py-2 rounded-lg text-xs font-medium transition"
                >
                  Schema Contracts &rarr;
                </Link>
                <Link
                  href="/landing"
                  className="w-full block bg-slate-800 hover:bg-slate-700 text-slate-300 text-center py-2 rounded-lg text-xs font-medium transition"
                >
                  Go to Landing Controls &rarr;
                </Link>
              </div>
            </div>
          </div>
        </div>

        {/* Version History Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Configuration Version Snapshots ({feed.versions?.length || 0})
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="pb-3 font-medium">Version</th>
                  <th className="pb-3 font-medium">Status</th>
                  <th className="pb-3 font-medium">Change Notes</th>
                  <th className="pb-3 font-medium">Published By</th>
                  <th className="pb-3 font-medium">Created At</th>
                  <th className="pb-3 font-medium">Snapshot</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {feed.versions?.map((v) => (
                  <tr key={v.id} className="hover:bg-slate-800/40">
                    <td className="py-3 font-mono font-bold text-white">v{v.version_number}</td>
                    <td className="py-3">
                      <span
                        className={`px-2 py-0.5 rounded font-semibold ${
                          v.status === 'PUBLISHED'
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            : v.status === 'SUPERSEDED'
                            ? 'bg-slate-800 text-slate-400 border border-slate-700'
                            : 'bg-amber-950 text-amber-400 border border-amber-800'
                        }`}
                      >
                        {v.status}
                      </span>
                    </td>
                    <td className="py-3 text-slate-300">{v.change_notes || '—'}</td>
                    <td className="py-3 text-slate-400 font-mono">{v.published_by || '—'}</td>
                    <td className="py-3 text-slate-400">{new Date(v.created_at).toLocaleString()}</td>
                    <td className="py-3">
                      <pre className="bg-slate-950 p-2 rounded text-[10px] text-blue-300 overflow-x-auto max-w-xs border border-slate-800">
                        {JSON.stringify(v.config_snapshot, null, 2)}
                      </pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Clone Feed Modal */}
        {showCloneModal && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-lg">
              <h2 className="text-lg font-bold text-white mb-2">Clone Feed: {feed.name}</h2>
              <p className="text-xs text-slate-400 mb-4">
                Strict isolation: deep-copies configuration snapshot and provisions an independent feed and version.
              </p>
              <form onSubmit={handleCloneSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">New Cloned Feed Name</label>
                  <input
                    type="text"
                    required
                    value={cloneForm.new_name}
                    onChange={(e) => setCloneForm({ ...cloneForm, new_name: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">New Filename Pattern (optional)</label>
                  <input
                    type="text"
                    value={cloneForm.new_filename_pattern}
                    onChange={(e) => setCloneForm({ ...cloneForm, new_filename_pattern: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Description</label>
                  <input
                    type="text"
                    value={cloneForm.description}
                    onChange={(e) => setCloneForm({ ...cloneForm, description: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                {cloneError && <p className="text-rose-400 text-xs">{cloneError}</p>}
                <div className="flex justify-end space-x-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowCloneModal(false)}
                    className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium"
                  >
                    Create Clone
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

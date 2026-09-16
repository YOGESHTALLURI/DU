'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface FeedItem {
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
  version: number;
  active_version?: {
    version_number: number;
    status: string;
  };
}

export default function FeedsPage() {
  const [feeds, setFeeds] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [cloneFeedTarget, setCloneFeedTarget] = useState<FeedItem | null>(null);

  const [form, setForm] = useState({
    name: '',
    domain: '',
    description: '',
    format: 'CSV',
    landing_folder: './data/landing',
    filename_pattern: '*.csv',
    schedule_expression: 'manual',
    source_system: '',
    data_owner: '',
    sla_expectation: '',
  });

  const [cloneForm, setCloneForm] = useState({
    new_name: '',
    new_filename_pattern: '',
    description: '',
  });

  const [error, setError] = useState('');
  const [cloneError, setCloneError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchFeeds = () => {
    const token = localStorage.getItem('cinqflow_token');
    fetch('/api/v1/feeds', {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setFeeds(data))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchFeeds();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/feeds', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || 'Failed to create feed');
        return;
      }
      setShowModal(false);
      setForm({
        name: '',
        domain: '',
        description: '',
        format: 'CSV',
        landing_folder: './data/landing',
        filename_pattern: '*.csv',
        schedule_expression: 'manual',
        source_system: '',
        data_owner: '',
        sla_expectation: '',
      });
      setSuccess('Feed registered successfully.');
      fetchFeeds();
    } catch {
      setError('Connection error');
    }
  };

  const handleOpenClone = (feed: FeedItem) => {
    setCloneFeedTarget(feed);
    setCloneForm({
      new_name: `${feed.name}_COPY`,
      new_filename_pattern: feed.filename_pattern,
      description: `Cloned from ${feed.name}`,
    });
    setCloneError('');
  };

  const handleCloneSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cloneFeedTarget) return;
    setCloneError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/feeds/${cloneFeedTarget.id}/clone`, {
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
      setCloneFeedTarget(null);
      setSuccess(`Feed ${cloneFeedTarget.name} cloned successfully with strict isolation.`);
      fetchFeeds();
    } catch {
      setCloneError('Connection error');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Feed Registry</h1>
            <p className="text-sm text-slate-400 mt-1">
              Metadata definitions for all source feeds. Pipelines compile dynamically from these rules.
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition"
          >
            + Register Feed
          </button>
        </div>

        {success && (
          <div className="mb-6 p-4 bg-emerald-950/80 border border-emerald-800 rounded-xl text-xs text-emerald-300">
            {success}
          </div>
        )}

        {loading ? (
          <p className="text-slate-400">Loading feeds...</p>
        ) : feeds.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center text-slate-400">
            No feeds configured. Click "+ Register Feed" to create one.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {feeds.map((f) => (
              <div key={f.id} className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-lg text-white font-mono">{f.name}</span>
                      {f.cloned_from_feed_id && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-950 text-purple-300 border border-purple-800">
                          CLONE
                        </span>
                      )}
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-semibold ${
                        f.status === 'ACTIVE'
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : f.status === 'INACTIVE'
                          ? 'bg-slate-800 text-slate-400 border border-slate-700'
                          : f.status === 'RETIRED'
                          ? 'bg-rose-950 text-rose-400 border border-rose-800'
                          : 'bg-amber-950 text-amber-400 border border-amber-800'
                      }`}
                    >
                      {f.status}
                    </span>
                  </div>
                  <p className="text-xs text-blue-400 font-mono mt-1">Domain: {f.domain} | Format: {f.format}</p>
                  <p className="text-sm text-slate-300 mt-2">{f.description || 'No description provided.'}</p>
                  
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs font-mono text-slate-400 mt-3 space-y-1">
                    <p>Landing: {f.landing_folder}</p>
                    <p>Pattern: {f.filename_pattern}</p>
                    {f.data_owner && <p>Owner: {f.data_owner}</p>}
                    <p>Active Ver: {f.active_version ? `v${f.active_version.version_number} (${f.active_version.status})` : 'None published'}</p>
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/onboarding/${f.id}`}
                      className="text-xs bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/40 px-2.5 py-1 rounded font-medium transition"
                    >
                      Onboarding Wizard &rarr;
                    </Link>
                    <button
                      onClick={() => handleOpenClone(f)}
                      className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded font-medium transition"
                    >
                      Clone Feed
                    </button>
                  </div>
                  <Link
                    href={`/feeds/${f.id}`}
                    className="text-xs text-blue-400 hover:text-blue-300 font-medium"
                  >
                    Details &rarr;
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create Feed Modal */}
        {showModal && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-lg">
              <h2 className="text-lg font-bold text-white mb-4">Register New Source Feed</h2>
              <form onSubmit={handleCreate} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Feed Name</label>
                  <input
                    type="text"
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="e.g. CLAIMS_MONTHLY_EXTRACT"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Domain</label>
                  <input
                    type="text"
                    required
                    value={form.domain}
                    onChange={(e) => setForm({ ...form, domain: e.target.value })}
                    placeholder="e.g. CLAIMS"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Landing Folder</label>
                  <input
                    type="text"
                    required
                    value={form.landing_folder}
                    onChange={(e) => setForm({ ...form, landing_folder: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Filename Pattern</label>
                  <input
                    type="text"
                    required
                    value={form.filename_pattern}
                    onChange={(e) => setForm({ ...form, filename_pattern: e.target.value })}
                    placeholder="e.g. CLAIMS_*.csv"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Source System</label>
                  <input
                    type="text"
                    value={form.source_system}
                    onChange={(e) => setForm({ ...form, source_system: e.target.value })}
                    placeholder="e.g. EPIC_EMR"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Data Owner</label>
                  <input
                    type="text"
                    value={form.data_owner}
                    onChange={(e) => setForm({ ...form, data_owner: e.target.value })}
                    placeholder="e.g. Clinical Ops Team"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Description</label>
                  <input
                    type="text"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                {error && <p className="text-rose-400 text-xs">{error}</p>}
                <div className="flex justify-end space-x-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowModal(false)}
                    className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium"
                  >
                    Save Feed
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Clone Feed Modal */}
        {cloneFeedTarget && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-lg">
              <h2 className="text-lg font-bold text-white mb-2">Clone Feed: {cloneFeedTarget.name}</h2>
              <p className="text-xs text-slate-400 mb-4">
                Creates an independent copy with new UUID, draft status, and deeply-copied configuration snapshot.
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
                    onClick={() => setCloneFeedTarget(null)}
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

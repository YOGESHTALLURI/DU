'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';

interface ContractItem {
  id: string;
  source_system: string;
  target_domain: string;
  description: string;
  data_owner: string;
  status: string;
  version: number;
  unknowns: Array<{
    id: string;
    description: string;
    risk_level: string;
    status: string;
  }>;
}

export default function ContractsPage() {
  const [contracts, setContracts] = useState<ContractItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({
    source_system: '',
    target_domain: '',
    description: '',
    data_owner: '',
    story_id: 'CF-V0-E1-01',
  });
  const [error, setError] = useState('');

  const fetchContracts = () => {
    const token = localStorage.getItem('cinqflow_token');
    fetch('/api/v1/contracts', {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setContracts(data))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchContracts();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/contracts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || 'Failed to create contract');
        return;
      }
      setShowModal(false);
      setForm({ source_system: '', target_domain: '', description: '', data_owner: '', story_id: 'CF-V0-E1-01' });
      fetchContracts();
    } catch {
      setError('Connection error');
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Execution-Plane Contract Register</h1>
            <p className="text-sm text-slate-400 mt-1">
              Documents which system reads from or writes to which data domain, including unconfirmed assumptions.
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition"
          >
            + New Contract Entry
          </button>
        </div>

        {loading ? (
          <p className="text-slate-400">Loading contracts...</p>
        ) : contracts.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center text-slate-400">
            No contracts registered. Click "+ New Contract Entry" to create one.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {contracts.map((c) => (
              <div key={c.id} className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center space-x-3">
                      <span className="font-bold text-lg text-white font-mono">{c.source_system}</span>
                      <span className="text-slate-500">&rarr;</span>
                      <span className="font-bold text-lg text-blue-400 font-mono">{c.target_domain}</span>
                      <span className="bg-slate-800 text-slate-300 text-xs px-2 py-0.5 rounded border border-slate-700">
                        v{c.version}
                      </span>
                      <span className="bg-emerald-950 text-emerald-400 border border-emerald-800 text-xs px-2 py-0.5 rounded font-semibold">
                        {c.status}
                      </span>
                    </div>
                    <p className="text-sm text-slate-300 mt-2">{c.description}</p>
                    <p className="text-xs text-slate-500 mt-1">Data Owner: <span className="text-slate-400">{c.data_owner}</span></p>
                  </div>
                </div>

                {/* Unknowns Sub-section */}
                {c.unknowns && c.unknowns.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-slate-800">
                    <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider mb-2">
                      Unconfirmed Production Assumptions ({c.unknowns.length})
                    </p>
                    <div className="space-y-2">
                      {c.unknowns.map((u) => (
                        <div key={u.id} className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
                          <span className="text-xs text-slate-300">{u.description}</span>
                          <div className="flex items-center space-x-2">
                            <span className="bg-amber-950 text-amber-400 border border-amber-800 text-xs px-2 py-0.5 rounded">
                              Risk: {u.risk_level}
                            </span>
                            <span className="text-xs text-slate-400">{u.status}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Modal for Creating Contract */}
        {showModal && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-lg">
              <h2 className="text-lg font-bold text-white mb-4">Create Contract Register Entry</h2>
              <form onSubmit={handleCreate} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Source System</label>
                  <input
                    type="text"
                    required
                    value={form.source_system}
                    onChange={(e) => setForm({ ...form, source_system: e.target.value })}
                    placeholder="e.g. HEALTH_PLAN_SOURCE"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Target Domain</label>
                  <input
                    type="text"
                    required
                    value={form.target_domain}
                    onChange={(e) => setForm({ ...form, target_domain: e.target.value })}
                    placeholder="e.g. MEMBERSHIP"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Description</label>
                  <textarea
                    required
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Describe data flows and schema bounds"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Data Owner</label>
                  <input
                    type="text"
                    required
                    value={form.data_owner}
                    onChange={(e) => setForm({ ...form, data_owner: e.target.value })}
                    placeholder="e.g. Member Operations Team"
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
                    Create Contract
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

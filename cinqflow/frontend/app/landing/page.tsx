'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface InputRecord {
  id: string;
  filename: string;
  file_size_bytes: number;
  file_fingerprint: string;
  status: string;
  rejection_reason?: string;
  is_duplicate: boolean;
  batch?: {
    id: string;
    status: string;
  };
}

export default function LandingPage() {
  const [inputs, setInputs] = useState<InputRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');

  const fetchInputs = () => {
    const token = localStorage.getItem('cinqflow_token');
    fetch('/api/v1/inputs', {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setInputs(data))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchInputs();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/inputs/register', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || ''}`,
        },
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Upload failed');
      } else {
        setResult(data);
        fetchInputs();
      }
    } catch {
      setError('Connection error to server');
    } finally {
      setUploading(false);
    }
  };

  // Quick Demo Ingestion (deterministic 4-row feed)
  const handleQuickDemoFeed = async () => {
    setUploading(true);
    setError('');
    setResult(null);

    const demoCsv =
      'member_id,first_name,last_name,date_of_birth,gender\n' +
      'M001,Alice,Johnson,1985-06-15,F\n' +
      'M002,Bob,Smith,1990-03-22,M\n' +
      'M003,Carol,Williams,1978-11-08,F\n' +
      'M004,David,,2099-01-01,X\n';

    const blob = new Blob([demoCsv], { type: 'text/csv' });
    const file = new File([blob], `MEMBER_DEMO_${Date.now()}.csv`, { type: 'text/csv' });

    const formData = new FormData();
    formData.append('file', file);

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/inputs/register', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || ''}`,
        },
        body: formData,
      });
      const data = await res.json();
      setResult(data);
      fetchInputs();
    } catch {
      setError('Connection error');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Landing Controls & Input Registry</h1>
            <p className="text-sm text-slate-400 mt-1">
              File arrival detection, SHA-256 fingerprinting, duplicate suppression, and schema verification.
            </p>
          </div>
          <button
            onClick={handleQuickDemoFeed}
            disabled={uploading}
            className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
          >
            {uploading ? 'Processing...' : '⚡ Ingest Wave 0 Demo Feed'}
          </button>
        </div>

        {/* Upload & Ingestion Controls */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-8">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Ingest Incoming File
          </h2>
          <div className="flex items-center gap-4">
            <input
              type="file"
              accept=".csv"
              onChange={handleFileUpload}
              disabled={uploading}
              className="text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-blue-400 hover:file:bg-slate-700"
            />
            {uploading && <span className="text-xs text-blue-400 font-mono">Fingerprinting & validating...</span>}
          </div>

          {error && <p className="text-rose-400 text-xs mt-3 bg-rose-950/40 p-2.5 rounded border border-rose-800">{error}</p>}

          {result && (
            <div className={`mt-4 p-4 rounded-lg border text-xs font-mono ${
              result.status === 'ACCEPTED'
                ? 'bg-emerald-950/40 border-emerald-800 text-emerald-300'
                : result.is_duplicate
                ? 'bg-amber-950/40 border-amber-800 text-amber-300'
                : 'bg-rose-950/40 border-rose-800 text-rose-300'
            }`}>
              <div className="flex items-center justify-between">
                <span className="font-bold">Status: {result.status} {result.is_duplicate ? '(DUPLICATE - SKIPPED)' : ''}</span>
                {result.batch && (
                  <Link
                    href={`/batches/${result.batch.id}`}
                    className="underline text-blue-300 hover:text-white"
                  >
                    View Created Batch &rarr;
                  </Link>
                )}
              </div>
              <p className="mt-1">SHA-256 Fingerprint: {result.file_fingerprint}</p>
              {result.rejection_reason && <p className="mt-1 text-rose-400">Rejection: {result.rejection_reason}</p>}
            </div>
          )}
        </div>

        {/* Input Registry Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Registered Inputs History ({inputs.length})
          </h2>
          {loading ? (
            <p className="text-xs text-slate-400">Loading inputs...</p>
          ) : inputs.length === 0 ? (
            <p className="text-xs text-slate-500 py-4">No inputs registered yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-medium">
                    <th className="pb-3">Filename</th>
                    <th className="pb-3">Size (bytes)</th>
                    <th className="pb-3">SHA-256 Fingerprint</th>
                    <th className="pb-3">Status</th>
                    <th className="pb-3">Reason / Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {inputs.map((inp) => (
                    <tr key={inp.id} className="hover:bg-slate-800/40">
                      <td className="py-3 font-mono text-white">{inp.filename}</td>
                      <td className="py-3 font-mono">{inp.file_size_bytes}</td>
                      <td className="py-3 font-mono text-slate-400 text-[10px]">{inp.file_fingerprint}</td>
                      <td className="py-3">
                        <span
                          className={`px-2 py-0.5 rounded font-semibold text-[10px] ${
                            inp.status === 'ACCEPTED'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : inp.status === 'DUPLICATE'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800'
                              : 'bg-rose-950 text-rose-400 border border-rose-800'
                          }`}
                        >
                          {inp.status}
                        </span>
                      </td>
                      <td className="py-3 text-slate-400">
                        {inp.rejection_reason || (inp.is_duplicate ? 'Duplicate fingerprint detected' : 'Valid arrival')}
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

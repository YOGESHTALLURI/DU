'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface SampleItem {
  id: string;
  feed_id: string;
  filename: string;
  file_size_bytes: number;
  file_fingerprint: string;
  mime_type: string;
  uploaded_by: string;
  created_at: string;
}

export default function FeedSamplesPage() {
  const params = useParams();
  const feedId = params?.id as string;
  const [samples, setSamples] = useState<SampleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [profilingId, setProfilingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const fetchSamples = () => {
    if (!feedId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/feeds/${feedId}/samples`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setSamples(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSamples();
  }, [feedId]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !feedId) return;
    setUploading(true);
    setError('');

    const token = localStorage.getItem('cinqflow_token');
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await fetch(`/api/v1/feeds/${feedId}/samples`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || ''}`,
        },
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        setError(err.detail || 'Upload failed');
        return;
      }

      setSelectedFile(null);
      const fileInput = document.getElementById('sample-file-input') as HTMLInputElement;
      if (fileInput) fileInput.value = '';
      fetchSamples();
    } catch {
      setError('Connection error during upload');
    } finally {
      setUploading(false);
    }
  };

  const handleRunProfiling = async (sampleId: string) => {
    setProfilingId(sampleId);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/feeds/${feedId}/samples/${sampleId}/profile`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || ''}`,
        },
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Profiling failed' }));
        setError(err.detail || 'Profiling failed');
        return;
      }

      const run = await res.json();
      window.location.href = `/profiling/${run.id}`;
    } catch {
      setError('Connection error during profiling');
    } finally {
      setProfilingId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href={`/feeds/${feedId}`} className="text-xs text-blue-400 hover:underline">
              &larr; Back to Feed Details
            </Link>
            <h1 className="text-2xl font-bold text-white mt-1">Representative Sample Files</h1>
            <p className="text-xs text-slate-400 mt-1">
              Upload representative CSV samples for this feed to trigger deterministic data profiling.
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-rose-950/60 border border-rose-800 rounded-xl text-rose-300 text-xs">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
          {/* Upload Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-4">
              Upload New Sample
            </h2>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Select CSV File
                </label>
                <input
                  id="sample-file-input"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  className="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-blue-600 file:text-white hover:file:bg-blue-500 cursor-pointer"
                  required
                />
              </div>

              {selectedFile && (
                <div className="p-3 bg-slate-950 rounded-lg text-xs font-mono text-slate-300 border border-slate-800">
                  <p>Name: {selectedFile.name}</p>
                  <p>Size: {selectedFile.size.toLocaleString()} bytes</p>
                </div>
              )}

              <button
                type="submit"
                disabled={uploading || !selectedFile}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-2 rounded-lg text-xs font-medium transition"
              >
                {uploading ? 'Uploading to Storage...' : 'Upload Sample'}
              </button>
            </form>
          </div>

          {/* Sample Guidelines Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 lg:col-span-2">
            <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
              Deterministic Profiling Facts
            </h2>
            <p className="text-xs text-slate-400 leading-relaxed mb-4">
              CINQFLOW runs a deterministic profiling engine directly against the raw uploaded bytes. It extracts empirical facts including:
            </p>
            <ul className="grid grid-cols-2 gap-2 text-xs text-slate-300 list-disc list-inside font-mono">
              <li>Exact Row & Column counts</li>
              <li>Inferred column data types</li>
              <li>Null counts & percentages</li>
              <li>Distinct counts & percentages</li>
              <li>Observed date/time patterns</li>
              <li>Min / Max lexicographical range</li>
            </ul>
            <p className="text-xs text-amber-400/90 mt-4 bg-amber-950/40 p-3 rounded border border-amber-800/60">
              Note: Profiling produces observational facts. It does not alter your sample data or enforce schema decisions until you create a schema contract draft.
            </p>
          </div>
        </div>

        {/* Samples Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-4">
            Uploaded Samples ({samples.length})
          </h2>

          {loading ? (
            <p className="text-xs text-slate-400">Loading samples...</p>
          ) : samples.length === 0 ? (
            <p className="text-xs text-slate-500 py-6 text-center">
              No sample files uploaded yet. Upload a representative CSV above to start profiling.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-3 font-medium">Filename</th>
                    <th className="pb-3 font-medium">Size</th>
                    <th className="pb-3 font-medium">SHA-256 Fingerprint</th>
                    <th className="pb-3 font-medium">Uploaded By</th>
                    <th className="pb-3 font-medium">Uploaded At</th>
                    <th className="pb-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {samples.map((s) => (
                    <tr key={s.id} className="hover:bg-slate-800/40">
                      <td className="py-3 font-mono font-medium text-white">{s.filename}</td>
                      <td className="py-3 text-slate-300 font-mono">
                        {s.file_size_bytes.toLocaleString()} B
                      </td>
                      <td className="py-3 font-mono text-slate-400 text-[10px]">
                        {s.file_fingerprint.slice(0, 16)}...
                      </td>
                      <td className="py-3 text-slate-400 font-mono">{s.uploaded_by}</td>
                      <td className="py-3 text-slate-400">
                        {new Date(s.created_at).toLocaleString()}
                      </td>
                      <td className="py-3 text-right space-x-2">
                        <button
                          onClick={() => handleRunProfiling(s.id)}
                          disabled={profilingId === s.id}
                          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs font-medium transition inline-flex items-center"
                        >
                          {profilingId === s.id ? 'Profiling...' : 'Run Profiler'}
                        </button>
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

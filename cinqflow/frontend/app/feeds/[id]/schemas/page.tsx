'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface SchemaVersionSummary {
  id: string;
  version_number: number;
  status: string;
  change_notes: string | null;
  source_profiling_run_id: string | null;
  published_by: string | null;
  published_at: string | null;
  created_at: string;
  fields: any[];
}

interface SchemaSummary {
  id: string;
  feed_id: string;
  name: string;
  description: string | null;
  created_at: string;
  active_version: SchemaVersionSummary | null;
  draft_version: SchemaVersionSummary | null;
}

export default function FeedSchemasPage() {
  const params = useParams();
  const feedId = params?.id as string;
  const [schemas, setSchemas] = useState<SchemaSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!feedId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/schemas/feed/${feedId}`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setSchemas(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [feedId]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href={`/feeds/${feedId}`} className="text-xs text-blue-400 hover:underline">
              &larr; Back to Feed Details
            </Link>
            <h1 className="text-2xl font-bold text-white mt-1">Schema Contracts</h1>
            <p className="text-xs text-slate-400 mt-1">
              Governed schema contracts and versioned specifications for this feed.
            </p>
          </div>

          <Link
            href={`/feeds/${feedId}/samples`}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition"
          >
            Create from Profiling &rarr;
          </Link>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-rose-950/60 border border-rose-800 rounded-xl text-rose-300 text-xs">
            {error}
          </div>
        )}

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-4">
            Configured Contracts ({schemas.length})
          </h2>

          {loading ? (
            <p className="text-xs text-slate-400">Loading schema contracts...</p>
          ) : schemas.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-xs text-slate-500 mb-3">No schema contracts configured for this feed yet.</p>
              <Link
                href={`/feeds/${feedId}/samples`}
                className="text-xs text-indigo-400 hover:underline"
              >
                Upload a sample and run profiling to generate a draft contract &rarr;
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-3 font-medium">Schema Name</th>
                    <th className="pb-3 font-medium">Description</th>
                    <th className="pb-3 font-medium">Active (Published)</th>
                    <th className="pb-3 font-medium">Draft Version</th>
                    <th className="pb-3 font-medium">Created At</th>
                    <th className="pb-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {schemas.map((s) => (
                    <tr key={s.id} className="hover:bg-slate-800/40">
                      <td className="py-3 font-mono font-bold text-white">{s.name}</td>
                      <td className="py-3 text-slate-300">{s.description || '—'}</td>
                      <td className="py-3 font-mono">
                        {s.active_version ? (
                          <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-semibold">
                            v{s.active_version.version_number} (Published)
                          </span>
                        ) : (
                          <span className="text-slate-600">None</span>
                        )}
                      </td>
                      <td className="py-3 font-mono">
                        {s.draft_version ? (
                          <span className="px-2 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800 font-semibold">
                            v{s.draft_version.version_number} (Draft)
                          </span>
                        ) : (
                          <span className="text-slate-600">None</span>
                        )}
                      </td>
                      <td className="py-3 text-slate-400">
                        {new Date(s.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 text-right">
                        <Link
                          href={`/schemas/${s.id}`}
                          className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-1.5 rounded transition inline-block"
                        >
                          Manage Contract &rarr;
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

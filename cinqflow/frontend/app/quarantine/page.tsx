'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface QuarantineRecord {
  id: string;
  batch_id: string;
  stage_name: string;
  source_row_number: number;
  source_record_raw: string;
  field_name: string;
  field_value: string;
  reason: string;
  reason_detail: string;
  created_at: string;
}

export default function QuarantinePage() {
  const [records, setRecords] = useState<QuarantineRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('cinqflow_token');
    fetch('/api/v1/quarantine', {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setRecords(data))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white">Quarantine Store</h1>
          <p className="text-sm text-slate-400 mt-1">
            Every quarantined record captures complete provenance: feed, batch, stage, row number, raw content, and named failure reason.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Quarantined Records ({records.length})
          </h2>

          {loading ? (
            <p className="text-xs text-slate-400">Loading quarantine...</p>
          ) : records.length === 0 ? (
            <p className="text-xs text-slate-500 py-4">No records in quarantine.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-medium">
                    <th className="pb-3">Batch ID</th>
                    <th className="pb-3">Stage</th>
                    <th className="pb-3">Row #</th>
                    <th className="pb-3">Field</th>
                    <th className="pb-3">Invalid Value</th>
                    <th className="pb-3">Named Reason</th>
                    <th className="pb-3">Detail</th>
                    <th className="pb-3">Raw Content</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-mono">
                  {records.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-800/40">
                      <td className="py-3 text-blue-400">
                        <Link href={`/batches/${r.batch_id}`} className="hover:underline">
                          {r.batch_id.slice(0, 8)}...
                        </Link>
                      </td>
                      <td className="py-3 text-slate-300">{r.stage_name}</td>
                      <td className="py-3 text-white font-bold">{r.source_row_number}</td>
                      <td className="py-3 text-slate-300">{r.field_name || '—'}</td>
                      <td className="py-3 text-rose-400">{r.field_value || '—'}</td>
                      <td className="py-3">
                        <span className="bg-amber-950 text-amber-400 border border-amber-800 px-2 py-0.5 rounded text-[10px] font-semibold">
                          {r.reason}
                        </span>
                      </td>
                      <td className="py-3 text-slate-400 font-sans text-xs">{r.reason_detail}</td>
                      <td className="py-3 text-[10px] text-slate-500 max-w-xs truncate">
                        {r.source_record_raw}
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

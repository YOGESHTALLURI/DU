'use client';
import React from 'react';
import { Layers, ChevronLeft, ChevronRight, Filter, RotateCcw } from 'lucide-react';

export interface OpsStageItem {
  stage_name: string;
  stage_order: number;
  status: string;
  duration_ms: number;
  rows_in: number;
  rows_out: number;
  rows_quarantined: number;
}

export interface OpsBatchMonitorItem {
  batch_id: string;
  feed_id: string;
  feed_name: string;
  domain: string;
  filename: string | null;
  batch_status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  total_duration_ms: number;
  stages: OpsStageItem[];
  dq_action: string;
  has_quarantined_rows: boolean;
  has_drift: boolean;
  drift_severity: string | null;
  reconciliation_status: string;
  error_message: string | null;
}

interface BatchStageMonitorTableProps {
  batches: OpsBatchMonitorItem[];
  total: number;
  page: number;
  limit: number;
  onPageChange: (newPage: number) => void;
  loading: boolean;
  selectedFeedId: string;
  onFeedChange: (feedId: string) => void;
  selectedStatus: string;
  onStatusChange: (status: string) => void;
  feeds: { id: string; name: string }[];
  onSelectBatch: (batchId: string) => void;
  onRestartBatch?: (batch: OpsBatchMonitorItem) => void;
}

export default function BatchStageMonitorTable({
  batches,
  total,
  page,
  limit,
  onPageChange,
  loading,
  selectedFeedId,
  onFeedChange,
  selectedStatus,
  onStatusChange,
  feeds,
  onSelectBatch,
  onRestartBatch,
}: BatchStageMonitorTableProps) {
  const totalPages = Math.max(1, Math.ceil(total / limit));

  const getStageColor = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return 'bg-emerald-500 text-slate-950 font-bold';
      case 'FAILED':
        return 'bg-rose-500 text-white font-bold';
      case 'RUNNING':
        return 'bg-amber-400 text-slate-950 animate-pulse font-bold';
      default:
        return 'bg-slate-800 text-slate-500';
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden mb-8" data-testid="batch-stage-monitor">
      {/* Table Header & Filters */}
      <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4 bg-slate-950/40">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-400" />
          <h2 className="text-lg font-semibold text-white">Batch & Stage Monitor</h2>
          <span className="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">
            {total} Total Batches
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Feed Filter */}
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Filter className="w-3.5 h-3.5" />
            <select
              value={selectedFeedId}
              onChange={(e) => onFeedChange(e.target.value)}
              className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Feeds</option>
              {feeds.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => onStatusChange(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All Statuses</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
            <option value="RUNNING">RUNNING</option>
            <option value="PENDING">PENDING</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950/60 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4 font-semibold">Batch ID / Feed</th>
              <th className="py-3 px-4 font-semibold">Status</th>
              <th className="py-3 px-4 font-semibold">Created</th>
              <th className="py-3 px-4 font-semibold">Duration</th>
              <th className="py-3 px-4 font-semibold">Stage Progression</th>
              <th className="py-3 px-4 font-semibold">Quality & Drift</th>
              <th className="py-3 px-4 font-semibold">Reconciliation</th>
              <th className="py-3 px-4 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {loading ? (
              [...Array(4)].map((_, i) => (
                <tr key={i} className="animate-pulse">
                  <td colSpan={8} className="py-4 px-4 h-12 bg-slate-900/40" />
                </tr>
              ))
            ) : batches.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-slate-500">
                  No batch executions found matching the selected filters.
                </td>
              </tr>
            ) : (
              batches.map((batch) => (
                <tr
                  key={batch.batch_id}
                  onClick={() => onSelectBatch(batch.batch_id)}
                  className="hover:bg-slate-800/50 cursor-pointer transition-colors"
                >
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white">{batch.feed_name}</div>
                    <div className="text-xs font-mono text-slate-500">
                      {batch.batch_id.substring(0, 8)}... • {batch.domain}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      batch.batch_status === 'SUCCESS' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' :
                      batch.batch_status === 'FAILED' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30' :
                      batch.batch_status === 'RUNNING' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
                      'bg-slate-800 text-slate-400'
                    }`}>
                      {batch.batch_status}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-slate-400">
                    {new Date(batch.created_at).toLocaleTimeString()}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    {batch.total_duration_ms} ms
                  </td>
                  <td className="py-3 px-4">
                    {/* Pipeline Stage Progression Pill */}
                    <div className="flex items-center gap-1.5">
                      {batch.stages.map((st) => (
                        <div
                          key={st.stage_name}
                          className={`w-6 h-6 rounded flex items-center justify-center text-[10px] ${getStageColor(st.status)}`}
                          title={`${st.stage_name}: ${st.status} (${st.duration_ms}ms)`}
                        >
                          {st.stage_name.charAt(0)}
                        </div>
                      ))}
                    </div>
                  </td>
                  <td className="py-3 px-4 text-xs space-y-1">
                    <div className="flex items-center gap-1.5 font-mono">
                      <span className="text-slate-400">DQ:</span>
                      <span className={`px-1.5 py-0.2 rounded text-[11px] font-medium ${
                        batch.dq_action === 'ABORT' ? 'bg-rose-950 text-rose-400 border border-rose-800' :
                        batch.has_quarantined_rows ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                        'text-slate-300'
                      }`}>
                        {batch.dq_action}
                      </span>
                    </div>
                    {batch.has_drift && (
                      <div className="flex items-center gap-1 text-[11px] text-rose-400">
                        <span>DRIFT: {batch.drift_severity}</span>
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                      batch.reconciliation_status === 'PASS' ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800' :
                      batch.reconciliation_status === 'FAIL' ? 'bg-rose-950/60 text-rose-300 border border-rose-800' :
                      'text-slate-500'
                    }`}>
                      {batch.reconciliation_status}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    {(batch.batch_status === 'FAILED' || batch.batch_status === 'FAILED_RECONCILIATION') && onRestartBatch && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onRestartBatch(batch);
                        }}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 transition-colors"
                        title="Trigger Governed Batch Restart"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Restart</span>
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="p-3 border-t border-slate-800 bg-slate-950/40 flex items-center justify-between text-xs text-slate-400">
        <div>
          Showing {batches.length > 0 ? (page - 1) * limit + 1 : 0} to{' '}
          {Math.min(page * limit, total)} of {total} batches
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-slate-200"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="font-mono">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-slate-200"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

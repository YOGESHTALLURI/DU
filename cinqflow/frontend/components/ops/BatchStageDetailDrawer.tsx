'use client';
import React, { useEffect, useState } from 'react';
import { X, CheckCircle2, AlertCircle, Clock, Database, ShieldCheck, Activity, RotateCcw, Play, Award } from 'lucide-react';
import { api } from '@/lib/api-client';
import { ActionModalTarget } from './OpsActionModal';
import OpsCertificationView from './OpsCertificationView';

interface OpsStageItem {
  stage_name: string;
  stage_order: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number;
  rows_in: number;
  rows_out: number;
  rows_quarantined: number;
  rows_dropped: number;
  error_message: string | null;
}

interface OpsBatchDetail {
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
  reconciliation: any | null;
  dq_summary: any | null;
  drift_report: any | null;
}

interface BatchStageDetailDrawerProps {
  batchId: string | null;
  onClose: () => void;
  onRequestAction?: (target: ActionModalTarget) => void;
}

export default function BatchStageDetailDrawer({ batchId, onClose, onRequestAction }: BatchStageDetailDrawerProps) {
  const [detail, setDetail] = useState<OpsBatchDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'stages' | 'certification'>('stages');

  useEffect(() => {
    if (!batchId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    api.get<OpsBatchDetail>(`/api/v1/ops/monitor/${batchId}`)
      .then((data) => setDetail(data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [batchId]);

  if (!batchId) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex justify-end"
      data-testid="batch-stage-detail-drawer"
    >
      <div className="w-full max-w-2xl bg-slate-900 border-l border-slate-800 h-full flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
        {/* Drawer Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold text-white">Batch Execution Drilldown</h3>
              {detail && (
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                  detail.batch_status === 'SUCCESS' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                  detail.batch_status === 'FAILED' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                  'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                }`}>
                  {detail.batch_status}
                </span>
              )}
            </div>
            <p className="text-xs font-mono text-slate-400 mt-1">{batchId}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="px-5 border-b border-slate-800 bg-slate-950/30 flex gap-4 text-xs font-medium">
          <button
            onClick={() => setActiveTab('stages')}
            className={`py-2.5 border-b-2 transition-colors flex items-center gap-1.5 ${
              activeTab === 'stages'
                ? 'border-blue-500 text-blue-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            <span>Stages & Telemetry</span>
          </button>
          <button
            onClick={() => setActiveTab('certification')}
            className={`py-2.5 border-b-2 transition-colors flex items-center gap-1.5 ${
              activeTab === 'certification'
                ? 'border-blue-500 text-blue-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Award className="w-3.5 h-3.5" />
            <span>Data Certification & Waivers</span>
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {activeTab === 'certification' && detail ? (
            <OpsCertificationView
              batchId={detail.batch_id}
              onRefreshParent={() => {
                api.get<OpsBatchDetail>(`/api/v1/ops/monitor/${batchId}`)
                  .then((data) => setDetail(data))
                  .catch(() => {});
              }}
            />
          ) : loading ? (
            <div className="space-y-4">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-24 bg-slate-800/40 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : !detail ? (
            <div className="text-center py-12 text-slate-500">Failed to load batch execution details.</div>
          ) : (
            <>
              {/* Batch Metadata Cards */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-slate-950/40 p-3 rounded-lg border border-slate-800">
                  <span className="text-slate-500 block mb-1">Feed / Domain</span>
                  <span className="font-semibold text-white">{detail.feed_name}</span>
                  <span className="text-slate-400 block">{detail.domain}</span>
                </div>
                <div className="bg-slate-950/40 p-3 rounded-lg border border-slate-800">
                  <span className="text-slate-500 block mb-1">Execution Duration</span>
                  <span className="font-semibold text-white font-mono">{detail.total_duration_ms} ms</span>
                  <span className="text-slate-400 block">
                    Started: {detail.started_at ? new Date(detail.started_at).toLocaleTimeString() : 'Pending'}
                  </span>
                </div>
              </div>

              {/* Sanitized Error Alert */}
              {detail.error_message && (
                <div className="bg-rose-950/30 border border-rose-800/60 rounded-lg p-3 text-xs text-rose-300">
                  <div className="font-semibold text-rose-400 mb-1 flex items-center gap-1.5">
                    <AlertCircle className="w-4 h-4" />
                    Operational Error (Sanitized - Zero PHI)
                  </div>
                  <pre className="font-mono whitespace-pre-wrap bg-slate-950/60 p-2 rounded border border-rose-900/40 text-rose-200">
                    {detail.error_message}
                  </pre>
                </div>
              )}

              {/* Pipeline Stages Breakdown */}
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
                  <Activity className="w-4 h-4 text-blue-400" />
                  Stage Progression & Metrics
                </h4>
                <div className="space-y-3">
                  {detail.stages.map((stage) => (
                    <div
                      key={stage.stage_name}
                      className="bg-slate-950/40 border border-slate-800 rounded-lg p-3.5 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                            Stage {stage.stage_order}
                          </span>
                          <span className="font-bold text-white text-sm">{stage.stage_name}</span>
                        </div>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          stage.status === 'SUCCESS' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' :
                          stage.status === 'FAILED' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30' :
                          stage.status === 'RUNNING' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {stage.status}
                        </span>
                      </div>

                      <div className="grid grid-cols-4 gap-2 pt-1 border-t border-slate-800/60 text-xs font-mono">
                        <div>
                          <span className="text-slate-500 block text-[10px]">IN</span>
                          <span className="text-slate-200 font-semibold">{stage.rows_in}</span>
                        </div>
                        <div>
                          <span className="text-slate-500 block text-[10px]">OUT</span>
                          <span className="text-emerald-400 font-semibold">{stage.rows_out}</span>
                        </div>
                        <div>
                          <span className="text-slate-500 block text-[10px]">QUARANTINE</span>
                          <span className={`font-semibold ${stage.rows_quarantined > 0 ? 'text-amber-400' : 'text-slate-400'}`}>
                            {stage.rows_quarantined}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-500 block text-[10px]">TIME</span>
                          <span className="text-slate-300 font-semibold">{stage.duration_ms}ms</span>
                        </div>
                      </div>

                      {stage.error_message && (
                        <div className="text-xs text-rose-400 bg-rose-950/20 p-2 rounded border border-rose-900/30 font-mono mt-2">
                          {stage.error_message}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Data Quality & Schema Drift Insights */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-950/40 p-3.5 rounded-lg border border-slate-800 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                      DQ Engine
                    </span>
                    <span className="text-xs font-mono text-blue-400">{detail.dq_action}</span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    {detail.has_quarantined_rows ? 'Rows were routed to quarantine.' : 'No quality rule rejections.'}
                  </p>
                </div>

                <div className="bg-slate-950/40 p-3.5 rounded-lg border border-slate-800 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                      <Database className="w-3.5 h-3.5 text-amber-400" />
                      Schema Drift
                    </span>
                    <span className={`text-xs font-mono ${
                      detail.drift_severity === 'BREAKING' ? 'text-rose-400' :
                      detail.drift_severity === 'NON_BREAKING' ? 'text-amber-400' :
                      'text-emerald-400'
                    }`}>
                      {detail.drift_severity || 'NO DRIFT'}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    {detail.has_drift ? `Severity: ${detail.drift_severity}` : 'Pre-ingestion schema matched.'}
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Drawer Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {detail && onRequestAction && (detail.batch_status === 'FAILED' || detail.batch_status === 'FAILED_RECONCILIATION') && (
              <button
                onClick={() => {
                  onRequestAction({
                    actionType: 'RESTART_BATCH',
                    targetType: 'BATCH',
                    targetId: detail.batch_id,
                    targetTitle: `Batch ${detail.batch_id.substring(0, 8)} (${detail.feed_name})`,
                    isHighRisk: false,
                  });
                }}
                className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Restart Failed Batch</span>
              </button>
            )}
            {detail && onRequestAction && detail.batch_status === 'SUCCESS' && (
              <button
                onClick={() => {
                  onRequestAction({
                    actionType: 'RETRIGGER_BATCH',
                    targetType: 'BATCH',
                    targetId: detail.batch_id,
                    targetTitle: `Batch ${detail.batch_id.substring(0, 8)} (${detail.feed_name})`,
                    isHighRisk: true,
                  });
                }}
                className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
              >
                <Play className="w-3.5 h-3.5" />
                <span>Retrigger Execution (High Risk)</span>
              </button>
            )}
          </div>

          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

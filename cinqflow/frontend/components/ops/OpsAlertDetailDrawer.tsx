'use client';

import React, { useState } from 'react';
import {
  X,
  AlertOctagon,
  AlertTriangle,
  Info,
  Clock,
  BookOpen,
  CheckCircle2,
  RefreshCw,
  ArrowRight,
  Shield,
  Layers,
  History,
  FileText,
} from 'lucide-react';
import { api } from '@/lib/api-client';
import { FailureFingerprintBadge } from './FailureFingerprintBadge';
import OpsActionModal, { ActionModalTarget } from './OpsActionModal';

export interface AlertDetailData {
  id: string;
  feed_id: string;
  feed_name?: string | null;
  batch_id?: string | null;
  failure_fingerprint_id: string;
  recommended_playbook_version_id?: string | null;
  title: string;
  description: string;
  severity: 'CRITICAL' | 'WARNING' | 'INFO';
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RECOVERY_IN_PROGRESS' | 'RESOLVED' | 'REOPENED';
  occurrence_count: number;
  first_occurred_at: string;
  last_occurred_at: string;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_notes?: string | null;
  fingerprint?: {
    id: string;
    category: string;
    failure_stage?: string | null;
    root_cause_pattern: string;
    canonical_signature: string;
    fingerprint_hash: string;
    total_occurrences: number;
  } | null;
  recommended_playbook_version?: {
    id: string;
    playbook_id: string;
    version_number: number;
    explanation_template: string;
    suggested_action_type?: string | null;
    action_parameters_template: Record<string, any>;
    manual_steps_markdown: string;
    prerequisites: any[];
    risk_assessment: string;
    status: string;
  } | null;
  occurrences?: Array<{
    id: string;
    alert_id: string;
    batch_id?: string | null;
    stage?: string | null;
    error_context: Record<string, any>;
    occurred_at: string;
  }>;
  action_proposal?: {
    action_type?: string | null;
    target_type?: string | null;
    target_id?: string | null;
    parameters: Record<string, any>;
    is_executable: boolean;
    blocking_reason?: string | null;
    risk_level?: string | null;
  } | null;
}

interface OpsAlertDetailDrawerProps {
  alert: AlertDetailData | null;
  onClose: () => void;
  onRefresh: () => void;
}

export default function OpsAlertDetailDrawer({ alert, onClose, onRefresh }: OpsAlertDetailDrawerProps) {
  const [actionTarget, setActionTarget] = useState<ActionModalTarget | null>(null);
  const [loadingAction, setLoadingAction] = useState(false);
  const [resolveNotes, setResolveNotes] = useState('');
  const [showResolveInput, setShowResolveInput] = useState(false);
  const [reopenReason, setReopenReason] = useState('');
  const [showReopenInput, setShowReopenInput] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!alert) return null;

  const handleAcknowledge = async () => {
    setLoadingAction(true);
    setErrorMsg(null);
    try {
      await api.post(`/api/v1/ops/alerts/${alert.id}/acknowledge`, {});
      onRefresh();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to acknowledge alert');
    } finally {
      setLoadingAction(false);
    }
  };

  const handleResolve = async () => {
    setLoadingAction(true);
    setErrorMsg(null);
    try {
      await api.post(`/api/v1/ops/alerts/${alert.id}/resolve`, {
        resolution_notes: resolveNotes.trim() || 'Resolved by operator',
      });
      setShowResolveInput(false);
      onRefresh();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to resolve alert');
    } finally {
      setLoadingAction(false);
    }
  };

  const handleReopen = async () => {
    setLoadingAction(true);
    setErrorMsg(null);
    try {
      await api.post(`/api/v1/ops/alerts/${alert.id}/reopen`, {
        reason: reopenReason.trim() || 'Operator reopened incident',
      });
      setShowReopenInput(false);
      onRefresh();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to reopen alert');
    } finally {
      setLoadingAction(false);
    }
  };

  const triggerPlaybookAction = () => {
    const proposal = alert.action_proposal;
    const pb = alert.recommended_playbook_version;

    const actionType = proposal?.action_type || pb?.suggested_action_type;
    if (!actionType) return;

    const targetType = (proposal?.target_type || 'BATCH') as 'BATCH' | 'QUARANTINE_RECORD' | 'FEED_SCHEDULE';
    const targetId = proposal?.target_id || alert.batch_id || alert.feed_id;
    if (!targetId) return;

    setActionTarget({
      actionType: actionType as any,
      targetType,
      targetId,
      targetTitle: `${alert.title} (Playbook Action: ${actionType})`,
      isHighRisk: proposal?.risk_level === 'HIGH_RISK' || ['RETRIGGER_BATCH', 'DISCARD_QUARANTINE', 'BULK_REPROCESS_QUARANTINE'].includes(actionType),
    });
  };

  const severityColor =
    alert.severity === 'CRITICAL'
      ? 'bg-rose-50 text-rose-700 border-rose-200'
      : alert.severity === 'WARNING'
      ? 'bg-amber-50 text-amber-700 border-amber-200'
      : 'bg-blue-50 text-blue-700 border-blue-200';

  const statusColor =
    alert.status === 'OPEN'
      ? 'bg-rose-100 text-rose-800'
      : alert.status === 'ACKNOWLEDGED'
      ? 'bg-blue-100 text-blue-800'
      : alert.status === 'RECOVERY_IN_PROGRESS'
      ? 'bg-purple-100 text-purple-800'
      : alert.status === 'RESOLVED'
      ? 'bg-emerald-100 text-emerald-800'
      : 'bg-amber-100 text-amber-800';

  return (
    <>
      <div className="fixed inset-0 z-50 overflow-hidden bg-slate-900/40 backdrop-blur-sm flex justify-end">
        <div className="w-full max-w-2xl bg-white shadow-2xl h-full flex flex-col border-l border-slate-200">
          {/* Header */}
          <div className="p-6 border-b border-slate-200 bg-slate-50 flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${severityColor}`}>
                  {alert.severity}
                </span>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${statusColor}`}>
                  {alert.status}
                </span>
                {alert.occurrence_count > 1 && (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-700 border border-purple-200">
                    {alert.occurrence_count} Occurrences (Storm Suppressed)
                  </span>
                )}
              </div>
              <h2 className="text-xl font-bold text-slate-900 leading-tight">{alert.title}</h2>
              <p className="text-xs text-slate-500 mt-1">
                Feed: <span className="font-semibold text-slate-700">{alert.feed_name || alert.feed_id}</span>
                {alert.batch_id && (
                  <>
                    {' '}• Batch: <span className="font-mono text-slate-600">{alert.batch_id.substring(0, 8)}</span>
                  </>
                )}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {errorMsg && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-rose-700 text-xs">
                {errorMsg}
              </div>
            )}

            {/* Explanation */}
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">
                Plain-English Failure Description
              </h3>
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-slate-800 text-sm leading-relaxed">
                {alert.description}
              </div>
            </div>

            {/* Failure Fingerprint */}
            {alert.fingerprint && (
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">
                  Failure Fingerprint & Zero-PHI Signature
                </h3>
                <div className="p-4 bg-white border border-slate-200 rounded-lg shadow-sm space-y-3">
                  <div className="flex items-center justify-between">
                    <FailureFingerprintBadge
                      category={alert.fingerprint.category}
                      fingerprintHash={alert.fingerprint.fingerprint_hash}
                      totalOccurrences={alert.fingerprint.total_occurrences}
                    />
                    {alert.fingerprint.failure_stage && (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                        Stage: {alert.fingerprint.failure_stage}
                      </span>
                    )}
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 font-medium">Root Cause Pattern:</span>
                    <p className="font-mono text-xs text-slate-800 bg-slate-50 p-2 rounded border mt-1 break-words">
                      {alert.fingerprint.root_cause_pattern}
                    </p>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 font-medium">Canonical Hash:</span>
                    <p className="font-mono text-[11px] text-slate-500 break-all select-all">
                      {alert.fingerprint.fingerprint_hash}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Recovery Playbook Card */}
            {alert.recommended_playbook_version ? (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                    <BookOpen className="w-3.5 h-3.5 text-blue-600" />
                    Recommended Recovery Playbook (v{alert.recommended_playbook_version.version_number})
                  </h3>
                  <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                    Governed SOP
                  </span>
                </div>
                <div className="p-4 bg-gradient-to-br from-blue-50/50 to-indigo-50/30 border border-blue-200 rounded-lg space-y-3">
                  <p className="text-sm text-slate-700 leading-relaxed">
                    {alert.recommended_playbook_version.explanation_template}
                  </p>

                  {/* Governed Action Trigger with Precondition Validation */}
                  {(alert.action_proposal?.action_type || alert.recommended_playbook_version.suggested_action_type) && (
                    <div className="pt-2 border-t border-blue-100 flex flex-col gap-2">
                      <div className="flex items-center justify-between">
                        <div className="text-xs text-blue-900 font-medium">
                          Governed Action:{' '}
                          <span className="font-mono font-bold">
                            {alert.action_proposal?.action_type || alert.recommended_playbook_version.suggested_action_type}
                          </span>
                          {alert.action_proposal?.target_type && (
                            <span className="text-[10px] text-blue-600 ml-1">
                              ({alert.action_proposal.target_type}: {alert.action_proposal.target_id?.substring(0, 8)}...)
                            </span>
                          )}
                        </div>
                        {(!alert.action_proposal || alert.action_proposal.is_executable) ? (
                          <button
                            onClick={triggerPlaybookAction}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-700 shadow-sm transition-all"
                          >
                            <Shield className="w-3.5 h-3.5" />
                            Execute Action
                          </button>
                        ) : (
                          <button
                            disabled
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-200 text-slate-400 rounded-lg text-xs font-semibold cursor-not-allowed"
                            title={alert.action_proposal.blocking_reason || 'Preconditions not met'}
                          >
                            <Shield className="w-3.5 h-3.5" />
                            Action Blocked
                          </button>
                        )}
                      </div>
                      {alert.action_proposal && !alert.action_proposal.is_executable && alert.action_proposal.blocking_reason && (
                        <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 flex items-start gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                          <span>{alert.action_proposal.blocking_reason}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Manual Steps */}
                  {alert.recommended_playbook_version.manual_steps_markdown && (
                    <div className="pt-2 border-t border-blue-100">
                      <span className="text-xs font-semibold text-slate-700 block mb-1">Standard Operating Procedure:</span>
                      <pre className="text-xs text-slate-600 bg-white/70 p-2.5 rounded border border-blue-100 whitespace-pre-wrap font-sans">
                        {alert.recommended_playbook_version.manual_steps_markdown}
                      </pre>
                    </div>
                  )}

                  {alert.recommended_playbook_version.risk_assessment && (
                    <div className="text-xs text-slate-500 flex items-center gap-1">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                      <span>Risk Assessment: {alert.recommended_playbook_version.risk_assessment}</span>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-500 flex items-center gap-2">
                <Info className="w-4 h-4 text-slate-400" />
                <span>No approved standard recovery playbook is currently pinned to this failure fingerprint.</span>
              </div>
            )}

            {/* Occurrence Timeline */}
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
                <History className="w-3.5 h-3.5 text-slate-500" />
                Incident Timeline & Deduplication ({alert.occurrences?.length || alert.occurrence_count} events)
              </h3>
              <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 max-h-48 overflow-y-auto bg-white">
                {alert.occurrences && alert.occurrences.length > 0 ? (
                  alert.occurrences.map((occ, idx) => (
                    <div key={occ.id || idx} className="p-3 text-xs flex items-center justify-between hover:bg-slate-50">
                      <div className="flex items-center gap-2">
                        <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="font-mono text-slate-600">
                          {new Date(occ.occurred_at).toLocaleString()}
                        </span>
                        {occ.stage && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-semibold text-[10px]">
                            {occ.stage}
                          </span>
                        )}
                      </div>
                      {occ.batch_id && (
                        <span className="font-mono text-[11px] text-slate-400">
                          batch:{occ.batch_id.substring(0, 8)}
                        </span>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="p-3 text-xs text-slate-500">
                    First occurred: {new Date(alert.first_occurred_at).toLocaleString()} • Last:{' '}
                    {new Date(alert.last_occurred_at).toLocaleString()}
                  </div>
                )}
              </div>
            </div>

            {/* Resolution Details */}
            {alert.status === 'RESOLVED' && alert.resolved_at && (
              <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-1">
                <div className="flex items-center gap-1.5 text-emerald-800 text-xs font-bold">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  Resolved on {new Date(alert.resolved_at).toLocaleString()} by {alert.resolved_by || 'Operator'}
                </div>
                {alert.resolution_notes && (
                  <p className="text-xs text-emerald-700 mt-1">{alert.resolution_notes}</p>
                )}
              </div>
            )}
          </div>

          {/* Footer Action Controls */}
          <div className="p-4 border-t border-slate-200 bg-slate-50 flex flex-col gap-3">
            {showResolveInput && (
              <div className="p-3 bg-white border border-slate-200 rounded-lg space-y-2">
                <label className="text-xs font-bold text-slate-700">Resolution Explanation / Notes:</label>
                <input
                  type="text"
                  value={resolveNotes}
                  onChange={(e) => setResolveNotes(e.target.value)}
                  placeholder="Root cause addressed, schema republished, records remediated..."
                  className="w-full text-xs px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setShowResolveInput(false)}
                    className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleResolve}
                    disabled={loadingAction}
                    className="px-3 py-1 bg-emerald-600 text-white rounded text-xs font-semibold hover:bg-emerald-700 disabled:opacity-50"
                  >
                    Confirm Resolution
                  </button>
                </div>
              </div>
            )}

            {showReopenInput && (
              <div className="p-3 bg-white border border-slate-200 rounded-lg space-y-2">
                <label className="text-xs font-bold text-slate-700">Reopen Reason:</label>
                <input
                  type="text"
                  value={reopenReason}
                  onChange={(e) => setReopenReason(e.target.value)}
                  placeholder="Issue recurring, fix incomplete..."
                  className="w-full text-xs px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-amber-500"
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setShowReopenInput(false)}
                    className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleReopen}
                    disabled={loadingAction}
                    className="px-3 py-1 bg-amber-600 text-white rounded text-xs font-semibold hover:bg-amber-700 disabled:opacity-50"
                  >
                    Confirm Reopen
                  </button>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-400">
                {alert.acknowledged_at && (
                  <span>Ack by {alert.acknowledged_by} at {new Date(alert.acknowledged_at).toLocaleTimeString()}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {alert.status === 'OPEN' || alert.status === 'REOPENED' ? (
                  <button
                    onClick={handleAcknowledge}
                    disabled={loadingAction}
                    className="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition-colors"
                  >
                    Acknowledge
                  </button>
                ) : null}

                {alert.status !== 'RESOLVED' ? (
                  <button
                    onClick={() => setShowResolveInput(true)}
                    className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold transition-colors"
                  >
                    Resolve Incident
                  </button>
                ) : (
                  <button
                    onClick={() => setShowReopenInput(true)}
                    className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold transition-colors"
                  >
                    Reopen Incident
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Governed Action Surface Modal */}
      {actionTarget && (
        <OpsActionModal
          target={actionTarget}
          onClose={() => setActionTarget(null)}
          onActionComplete={() => {
            setActionTarget(null);
            onRefresh();
          }}
        />
      )}
    </>
  );
}

'use client';
import React, { useState } from 'react';
import { ShieldAlert, Check, X, Clock, User, ChevronDown, ChevronUp, AlertCircle, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api-client';

export interface PendingActionItem {
  id: string;
  action_type: string;
  target_type: string;
  target_id: string;
  reason: string;
  requested_by: string;
  requested_by_email: string | null;
  requested_at: string;
  risk_level: string;
  parameters: any;
}

interface OpsPendingActionsBannerProps {
  pendingActions: PendingActionItem[];
  currentUserId?: string;
  onActionProcessed: () => void;
}

export default function OpsPendingActionsBanner({
  pendingActions,
  currentUserId,
  onActionProcessed,
}: OpsPendingActionsBannerProps) {
  const [expanded, setExpanded] = useState(false);
  const [activeDecisionId, setActiveDecisionId] = useState<string | null>(null);
  const [decisionNotes, setDecisionNotes] = useState('');
  const [processing, setProcessing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!pendingActions || pendingActions.length === 0) {
    return null;
  }

  const handleDecision = async (actionId: string, decision: 'approve' | 'reject') => {
    setProcessing(true);
    setActionError(null);
    try {
      await api.post(`/api/v1/ops/actions/${actionId}/${decision}`, {
        decision_notes: decisionNotes.trim() || undefined,
      });
      setActiveDecisionId(null);
      setDecisionNotes('');
      onActionProcessed();
    } catch (err: any) {
      setActionError(err.message || `Failed to ${decision} action.`);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="mb-6 bg-slate-900 border border-amber-500/30 rounded-xl overflow-hidden shadow-lg" data-testid="ops-pending-actions-banner">
      {/* Banner Header */}
      <div className="p-3.5 bg-amber-950/30 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <span>Dual-Control Governance Queue</span>
              <span className="bg-amber-500/20 text-amber-300 text-xs px-2 py-0.5 rounded-full font-mono font-medium border border-amber-500/30">
                {pendingActions.length} Pending Approval
              </span>
            </h3>
            <p className="text-xs text-slate-400">
              High-risk operational interventions require secondary operator authorization before execution.
            </p>
          </div>
        </div>

        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-xs text-amber-300 hover:text-white px-2.5 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 transition-colors"
        >
          <span>{expanded ? 'Collapse Queue' : 'Review Queue'}</span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Action Queue List (Expandable) */}
      {expanded && (
        <div className="p-4 divide-y divide-slate-800/80 bg-slate-950/40">
          {actionError && (
            <div className="mb-3 p-2.5 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{actionError}</span>
            </div>
          )}

          {pendingActions.map((action) => {
            const isSelf = currentUserId && action.requested_by === currentUserId;
            const isDecidingThis = activeDecisionId === action.id;

            return (
              <div key={action.id} className="py-3 first:pt-0 last:pb-0 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 font-mono">
                      {action.action_type}
                    </span>
                    <span className="text-xs font-mono text-slate-400">
                      Target: {action.target_type} ({action.target_id.substring(0, 8)}...)
                    </span>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <User className="w-3 h-3 text-slate-500" />
                      {action.requested_by_email || action.requested_by}
                    </span>
                    <span className="flex items-center gap-1 font-mono">
                      <Clock className="w-3 h-3 text-slate-500" />
                      {new Date(action.requested_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>

                {/* Operator Rationale */}
                <div className="text-xs bg-slate-900 border border-slate-800 rounded-lg p-2.5 text-slate-300">
                  <span className="text-slate-500 font-semibold mr-1">Rationale:</span>
                  {action.reason}
                </div>

                {/* Decision Controls */}
                <div className="flex items-center justify-between pt-1">
                  {isSelf ? (
                    <span className="text-[11px] text-amber-400/80 italic">
                      * Four-Eyes Policy: Another operator must review and authorize this action.
                    </span>
                  ) : (
                    <div className="flex items-center gap-2">
                      {!isDecidingThis ? (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setActiveDecisionId(action.id);
                              setDecisionNotes('');
                            }}
                            className="px-2.5 py-1 text-xs font-semibold rounded bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1 transition-colors"
                          >
                            <Check className="w-3 h-3" />
                            Approve Action
                          </button>
                          <button
                            onClick={() => {
                              setActiveDecisionId(action.id);
                              setDecisionNotes('');
                            }}
                            className="px-2.5 py-1 text-xs font-semibold rounded bg-rose-600/80 hover:bg-rose-600 text-white flex items-center gap-1 transition-colors"
                          >
                            <X className="w-3 h-3" />
                            Reject
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 w-full">
                          <input
                            type="text"
                            placeholder="Optional review notes (zero PHI)..."
                            value={decisionNotes}
                            onChange={(e) => setDecisionNotes(e.target.value)}
                            className="text-xs bg-slate-900 border border-slate-700 text-slate-200 rounded px-2 py-1 w-64 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                          <button
                            disabled={processing}
                            onClick={() => handleDecision(action.id, 'approve')}
                            className="px-2.5 py-1 text-xs font-semibold rounded bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1 disabled:opacity-50"
                          >
                            {processing ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                            Confirm Approve
                          </button>
                          <button
                            disabled={processing}
                            onClick={() => handleDecision(action.id, 'reject')}
                            className="px-2.5 py-1 text-xs font-semibold rounded bg-rose-600 hover:bg-rose-500 text-white flex items-center gap-1 disabled:opacity-50"
                          >
                            Confirm Reject
                          </button>
                          <button
                            disabled={processing}
                            onClick={() => setActiveDecisionId(null)}
                            className="px-2 py-1 text-xs text-slate-400 hover:text-white"
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

'use client';
import React, { useState } from 'react';
import { AlertTriangle, ShieldCheck, CheckCircle2, X, RefreshCw, Layers } from 'lucide-react';
import { api } from '@/lib/api-client';

export interface ActionModalTarget {
  actionType: 'RESTART_BATCH' | 'RETRIGGER_BATCH' | 'REPROCESS_QUARANTINE' | 'DISCARD_QUARANTINE' | 'PAUSE_SCHEDULE' | 'RESUME_SCHEDULE';
  targetType: 'BATCH' | 'QUARANTINE_RECORD' | 'FEED_SCHEDULE';
  targetId: string;
  targetTitle: string;
  isHighRisk?: boolean;
}

interface OpsActionModalProps {
  target: ActionModalTarget | null;
  onClose: () => void;
  onActionComplete: () => void;
}

export default function OpsActionModal({ target, onClose, onActionComplete }: OpsActionModalProps) {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!target) return null;

  const isHighRisk = target.actionType === 'RETRIGGER_BATCH' || target.actionType === 'DISCARD_QUARANTINE';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (reason.trim().length < 5) {
      setError('Please provide an operational rationale (minimum 5 characters).');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const payload = {
        action_type: target.actionType,
        target_type: target.targetType,
        target_id: target.targetId,
        reason: reason.trim(),
        parameters: {},
        idempotency_key: `ui-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
      };

      const res: any = await api.post('/api/v1/ops/actions', payload);

      if (res.status === 'PENDING_APPROVAL' || res.requires_approval) {
        setSuccessMessage('High-risk action submitted. Queued for Four-Eyes dual-control approval.');
      } else {
        setSuccessMessage('Action executed successfully.');
      }

      setTimeout(() => {
        onActionComplete();
        onClose();
      }, 1200);
    } catch (err: any) {
      setError(err.message || 'Action execution failed. Please check permissions or constraints.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      data-testid="ops-action-modal"
    >
      <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-2">
            {isHighRisk ? (
              <div className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400">
                <AlertTriangle className="w-5 h-5" />
              </div>
            ) : (
              <div className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400">
                <Layers className="w-5 h-5" />
              </div>
            )}
            <div>
              <h3 className="text-base font-bold text-white">
                {target.actionType.replace(/_/g, ' ')}
              </h3>
              <p className="text-xs text-slate-400 font-mono">{target.targetTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Governance Notice */}
          {isHighRisk ? (
            <div className="p-3 rounded-lg bg-amber-950/40 border border-amber-800/60 text-amber-300 text-xs flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0 text-amber-400" />
              <div>
                <span className="font-semibold">Four-Eyes Dual Control Enforced:</span> This is a high-risk operation. Upon submission, it will be queued for approval by an independent authorized operator before executing.
              </div>
            </div>
          ) : (
            <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/60 text-slate-300 text-xs flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400" />
              <div>
                <span className="font-semibold text-white">Standard Operational Remedy:</span> This action will execute immediately upon submission. An immutable, zero-PHI audit record will be registered.
              </div>
            </div>
          )}

          {/* Rationale Input */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Reason for Operational Intervention <span className="text-rose-400">*</span>
            </label>
            <textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Provide clear technical rationale for audit trail (e.g. 'Retrying stage after network timeout'). Do not enter patient names or SSNs."
              className="w-full bg-slate-950 border border-slate-800 text-slate-200 text-xs rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder:text-slate-600 font-sans"
              disabled={loading || Boolean(successMessage)}
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Zero-PHI scrubber actively sanitizes identifier patterns before persistence.
            </p>
          </div>

          {/* Feedback states */}
          {error && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {successMessage && (
            <div className="p-3 rounded-lg bg-emerald-950/50 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
              <span>{successMessage}</span>
            </div>
          )}

          {/* Buttons */}
          <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-800/60">
            <button
              type="button"
              onClick={onClose}
              disabled={loading || Boolean(successMessage)}
              className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || Boolean(successMessage) || reason.trim().length < 5}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                isHighRisk
                  ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white'
              }`}
            >
              {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
              {isHighRisk ? 'Submit for Review' : 'Execute Action'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

'use client';
import React, { useState } from 'react';
import { X, ShieldAlert, CheckCircle2, XCircle, AlertTriangle, Clock } from 'lucide-react';
import { api } from '@/lib/api-client';

export interface WaiverModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  variance?: {
    id: string;
    batch_id: string;
    feed_id: string;
    control_type: string;
    control_id: string;
    title: string;
    description: string;
  } | null;
  existingWaiver?: {
    id: string;
    variance_id: string;
    batch_id: string;
    affected_control_type: string;
    business_justification: string;
    risk_assessment: string;
    mitigation_notes: string;
    expires_at: string;
    status: string;
    requested_by: string;
    requested_by_email?: string;
  } | null;
  mode: 'REQUEST' | 'REVIEW';
  currentUserId?: string;
}

export default function OpsWaiverModal({
  isOpen,
  onClose,
  onSuccess,
  variance,
  existingWaiver,
  mode,
  currentUserId,
}: WaiverModalProps) {
  const [justification, setJustification] = useState('');
  const [riskAssessment, setRiskAssessment] = useState('');
  const [mitigationNotes, setMitigationNotes] = useState('');
  const [expiresAt, setExpiresAt] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 16);
  });
  const [decisionNotes, setDecisionNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const isSelfReview =
    mode === 'REVIEW' &&
    existingWaiver &&
    currentUserId &&
    (existingWaiver.requested_by === currentUserId ||
      existingWaiver.requested_by_email === currentUserId);

  const handleSubmitRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!variance) return;
    setError(null);
    setSubmitting(true);

    try {
      await api.post('/api/v1/ops/waivers', {
        variance_id: variance.id,
        scope: 'SINGLE_BATCH',
        business_justification: justification,
        risk_assessment: riskAssessment,
        mitigation_notes: mitigationNotes,
        expires_at: new Date(expiresAt).toISOString(),
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to submit waiver request');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async (decision: 'APPROVE' | 'REJECT') => {
    if (!existingWaiver) return;
    setError(null);
    setSubmitting(true);

    try {
      await api.post(`/api/v1/ops/waivers/${existingWaiver.id}/review`, {
        decision,
        decision_notes: decisionNotes,
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.message || `Failed to ${decision.toLowerCase()} waiver`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-xl shadow-2xl max-w-xl w-full p-6 text-slate-100 relative max-h-[90vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-200 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4 pb-3 border-b border-slate-800">
          <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">
              {mode === 'REQUEST' ? 'Request Control Waiver' : 'Review Waiver Request'}
            </h2>
            <p className="text-xs text-slate-400">
              Four-eyes governed operational exception for non-compliance variance
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
        )}

        {mode === 'REQUEST' && variance && (
          <form onSubmit={handleSubmitRequest} className="space-y-4">
            <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs space-y-1">
              <div className="font-semibold text-slate-200">{variance.title}</div>
              <div className="text-slate-400">{variance.description}</div>
              <div className="text-slate-500 font-mono text-[10px] mt-1">
                Control: {variance.control_type} ({variance.control_id.slice(0, 12)}...)
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Business Justification <span className="text-rose-400">*</span>
              </label>
              <textarea
                required
                minLength={10}
                rows={2}
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Explain why this data is required despite the control non-compliance..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Risk Assessment <span className="text-rose-400">*</span>
              </label>
              <textarea
                required
                minLength={10}
                rows={2}
                value={riskAssessment}
                onChange={(e) => setRiskAssessment(e.target.value)}
                placeholder="Evaluate impact on downstream analytics, reporting, or patient matching..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Mitigation Notes <span className="text-rose-400">*</span>
              </label>
              <textarea
                required
                minLength={10}
                rows={2}
                value={mitigationNotes}
                onChange={(e) => setMitigationNotes(e.target.value)}
                placeholder="Steps taken to notify downstream users, reprocess records, or address root cause..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Expiration Timestamp (Max 30 Days) <span className="text-rose-400">*</span>
              </label>
              <input
                type="datetime-local"
                required
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                {submitting ? 'Submitting...' : 'Submit Waiver Request'}
              </button>
            </div>
          </form>
        )}

        {mode === 'REVIEW' && existingWaiver && (
          <div className="space-y-4">
            <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs space-y-2">
              <div className="flex justify-between items-center">
                <span className="font-semibold text-slate-200">
                  Control: {existingWaiver.affected_control_type}
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  {existingWaiver.status}
                </span>
              </div>
              <div className="text-slate-400">
                <span className="text-slate-500">Requested By:</span> {existingWaiver.requested_by}
              </div>
              <div className="text-slate-400">
                <span className="text-slate-500">Expires:</span>{' '}
                {new Date(existingWaiver.expires_at).toLocaleString()}
              </div>
              <div className="border-t border-slate-800/80 pt-1.5 space-y-1">
                <div>
                  <span className="font-medium text-slate-300">Justification:</span>{' '}
                  <span className="text-slate-400">{existingWaiver.business_justification}</span>
                </div>
                <div>
                  <span className="font-medium text-slate-300">Risk Assessment:</span>{' '}
                  <span className="text-slate-400">{existingWaiver.risk_assessment}</span>
                </div>
                <div>
                  <span className="font-medium text-slate-300">Mitigation:</span>{' '}
                  <span className="text-slate-400">{existingWaiver.mitigation_notes}</span>
                </div>
              </div>
            </div>

            {isSelfReview ? (
              <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2">
                <Clock className="w-4 h-4 shrink-0 text-amber-400" />
                <span>
                  <strong>Dual-Control Enforcement:</strong> You requested this waiver. Another
                  operator must review and approve it.
                </span>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Review Decision Notes <span className="text-rose-400">*</span>
                </label>
                <textarea
                  required
                  minLength={5}
                  rows={2}
                  value={decisionNotes}
                  onChange={(e) => setDecisionNotes(e.target.value)}
                  placeholder="Mandatory notes detailing reason for approval or rejection..."
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
              >
                Close
              </button>
              {!isSelfReview && (
                <>
                  <button
                    type="button"
                    disabled={submitting || decisionNotes.length < 5}
                    onClick={() => handleReview('REJECT')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-rose-200 bg-rose-900/40 hover:bg-rose-900/60 border border-rose-700/50 disabled:opacity-50 rounded-lg transition-colors"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    <span>Reject</span>
                  </button>
                  <button
                    type="button"
                    disabled={submitting || decisionNotes.length < 5}
                    onClick={() => handleReview('APPROVE')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Approve Waiver</span>
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

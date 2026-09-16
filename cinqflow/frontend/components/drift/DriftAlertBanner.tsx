'use client';
import React, { useEffect, useState } from 'react';
import { AlertTriangle, ShieldAlert, CheckCircle, Info, X } from 'lucide-react';

interface SchemaDriftReport {
  id: string;
  batch_id: string;
  feed_id: string;
  expected_schema_version_id: string;
  drift_severity: 'BREAKING' | 'NON_BREAKING';
  missing_fields: string[];
  unexpected_fields: string[];
  type_mismatches: any[];
  detected_delimiter?: string;
  status: 'DETECTED' | 'ACKNOWLEDGED';
  acknowledged_by?: string;
  acknowledged_at?: string;
  acknowledgement_notes?: string;
  created_at: string;
}

interface DriftAlertBannerProps {
  feedId?: string;
  batchId?: string;
  onAcknowledged?: () => void;
}

export default function DriftAlertBanner({ feedId, batchId, onAcknowledged }: DriftAlertBannerProps) {
  const [reports, setReports] = useState<SchemaDriftReport[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedReport, setSelectedReport] = useState<SchemaDriftReport | null>(null);
  const [notes, setNotes] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const fetchReports = async () => {
    try {
      const token = localStorage.getItem('cinqflow_token');
      const params = new URLSearchParams();
      if (feedId) params.append('feed_id', feedId);
      if (batchId) params.append('batch_id', batchId);

      const res = await fetch(`/api/v1/schemas/drift?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (res.ok) {
        const data = await res.json();
        setReports(data.items || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, [feedId, batchId]);

  const handleAcknowledge = async () => {
    if (!selectedReport) return;
    if (!notes.trim() || notes.trim().length < 3) {
      setError('Please provide a justification note of at least 3 characters.');
      return;
    }

    setSubmitting(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/schemas/drift/${selectedReport.id}/acknowledge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ notes: notes.trim() }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: 'Failed to acknowledge' }));
        setError(errData.detail || 'Failed to acknowledge schema drift.');
        return;
      }

      setSelectedReport(null);
      setNotes('');
      await fetchReports();
      if (onAcknowledged) onAcknowledged();
    } catch {
      setError('Network error acknowledging schema drift.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || reports.length === 0) return null;

  const unackReports = reports.filter((r) => r.status === 'DETECTED');
  if (unackReports.length === 0) return null;

  return (
    <div className="space-y-3 mb-6" data-testid="drift-alert-container">
      {unackReports.map((report) => {
        const isBreaking = report.drift_severity === 'BREAKING';
        return (
          <div
            key={report.id}
            data-testid={`drift-alert-${report.id}`}
            className={`rounded-xl border p-4 shadow-sm transition-all ${
              isBreaking
                ? 'bg-rose-950/40 border-rose-800 text-rose-200'
                : 'bg-amber-950/40 border-amber-800 text-amber-200'
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                {isBreaking ? (
                  <ShieldAlert className="w-6 h-6 text-rose-400 mt-0.5 shrink-0" />
                ) : (
                  <AlertTriangle className="w-6 h-6 text-amber-400 mt-0.5 shrink-0" />
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${
                        isBreaking
                          ? 'bg-rose-900/60 border-rose-700 text-rose-300'
                          : 'bg-amber-900/60 border-amber-700 text-amber-300'
                      }`}
                    >
                      {report.drift_severity} DRIFT DETECTED
                    </span>
                    <span className="text-xs text-slate-400 font-mono">
                      Report: {report.id.slice(0, 8)}
                    </span>
                  </div>

                  <p className="text-sm font-semibold mt-1">
                    {isBreaking
                      ? 'Pre-ingestion check failed: Breaking schema drift halted batch at Landing stage.'
                      : 'Non-breaking schema drift detected. Production batch was permitted to proceed.'}
                  </p>

                  <div className="mt-2 text-xs space-y-1 font-mono">
                    {report.missing_fields && report.missing_fields.length > 0 && (
                      <p>
                        <span className="text-slate-400">Missing Required Fields:</span>{' '}
                        <span className="font-bold text-rose-300">{report.missing_fields.join(', ')}</span>
                      </p>
                    )}
                    {report.unexpected_fields && report.unexpected_fields.length > 0 && (
                      <p>
                        <span className="text-slate-400">Unexpected Extra Fields:</span>{' '}
                        <span className="font-bold text-amber-300">{report.unexpected_fields.join(', ')}</span>
                      </p>
                    )}
                    {report.detected_delimiter && (
                      <p>
                        <span className="text-slate-400">Detected Delimiter:</span>{' '}
                        <span className="font-bold">{JSON.stringify(report.detected_delimiter)}</span>
                      </p>
                    )}
                  </div>
                </div>
              </div>

              <div>
                {!isBreaking ? (
                  <button
                    onClick={() => {
                      setSelectedReport(report);
                      setNotes('');
                      setError('');
                    }}
                    data-testid="acknowledge-drift-btn"
                    className="px-3 py-1.5 text-xs font-medium bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold rounded-lg transition-colors"
                  >
                    Acknowledge Drift
                  </button>
                ) : (
                  <span className="text-[11px] text-rose-400 bg-rose-950/80 border border-rose-800 px-2 py-1 rounded">
                    Action Required: Update Schema
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Acknowledge Modal */}
      {selectedReport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 text-slate-100 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="font-bold text-lg flex items-center gap-2 text-amber-400">
                <AlertTriangle className="w-5 h-5" /> Acknowledge Schema Drift
              </h3>
              <button
                onClick={() => setSelectedReport(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-300 mt-4 leading-relaxed">
              Acknowledging this non-breaking schema drift confirms engineering awareness of unexpected
              or missing optional columns without halting downstream pipelines.
            </p>

            <div className="mt-4">
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Justification / Resolution Notes (Required)
              </label>
              <textarea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="e.g. Added optional phone_num column from upstream EHR update. Validated and safe."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-amber-500"
              />
            </div>

            {error && (
              <p className="text-xs text-rose-400 mt-2 bg-rose-950/50 p-2 rounded border border-rose-800">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2 mt-6">
              <button
                type="button"
                onClick={() => setSelectedReport(null)}
                className="px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={submitting || notes.trim().length < 3}
                onClick={handleAcknowledge}
                data-testid="submit-acknowledge-btn"
                className="px-4 py-2 text-xs font-bold bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-slate-950 rounded-lg transition-colors"
              >
                {submitting ? 'Acknowledging...' : 'Confirm Acknowledgment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

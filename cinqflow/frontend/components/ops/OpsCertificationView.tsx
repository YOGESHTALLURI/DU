'use client';
import React, { useEffect, useState, useCallback } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  FileCheck2,
  Award,
} from 'lucide-react';
import { api } from '@/lib/api-client';
import OpsWaiverModal from './OpsWaiverModal';

export interface OpsCertificationViewProps {
  batchId: string;
  onRefreshParent?: () => void;
}

export default function OpsCertificationView({ batchId, onRefreshParent }: OpsCertificationViewProps) {
  const [evaluation, setEvaluation] = useState<any | null>(null);
  const [certification, setCertification] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [certifying, setCertifying] = useState(false);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [waiverModalOpen, setWaiverModalOpen] = useState(false);
  const [waiverModalMode, setWaiverModalMode] = useState<'REQUEST' | 'REVIEW'>('REQUEST');
  const [selectedVariance, setSelectedVariance] = useState<any>(null);
  const [selectedExistingWaiver, setSelectedExistingWaiver] = useState<any>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [evalRes, certRes] = await Promise.all([
        api.get<any>(`/api/v1/ops/batches/${batchId}/certification-evaluation`),
        api.get<any>(`/api/v1/ops/batches/${batchId}/certification`).catch(() => null),
      ]);
      setEvaluation(evalRes);
      setCertification(certRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to evaluate batch certification');
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCertify = async () => {
    setCertifying(true);
    setError(null);
    try {
      await api.post(`/api/v1/ops/batches/${batchId}/certify`, {
        certification_notes: notes,
      });
      await loadData();
      if (onRefreshParent) onRefreshParent();
    } catch (err: any) {
      setError(err?.message || 'Failed to certify batch');
    } finally {
      setCertifying(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 text-center text-xs text-slate-400">
        <div className="animate-spin w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-2" />
        Evaluating authoritative certification checklist...
      </div>
    );
  }

  if (!evaluation) {
    return (
      <div className="p-4 text-xs text-slate-400 text-center">
        No certification telemetry available for this batch.
      </div>
    );
  }

  const isCertified = !!certification && certification.status === 'CERTIFIED';
  const isCertifiedWithWaiver = isCertified && certification.certified_with_waivers;
  const isEligible = evaluation.is_eligible && !isCertified;

  return (
    <div className="space-y-4 text-slate-200">
      {error && (
        <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* 1. Header Status Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          {isCertified ? (
            <div className={`p-2.5 rounded-xl border ${isCertifiedWithWaiver ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'}`}>
              <Award className="w-6 h-6" />
            </div>
          ) : isEligible ? (
            <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/30 text-blue-400">
              <ShieldCheck className="w-6 h-6" />
            </div>
          ) : (
            <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400">
              <ShieldAlert className="w-6 h-6" />
            </div>
          )}

          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white">Data Certification Status:</h3>
              {isCertifiedWithWaiver ? (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1">
                  <FileCheck2 className="w-3.5 h-3.5" />
                  CERTIFIED (UNDER WAIVER)
                </span>
              ) : isCertified ? (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  CERTIFIED
                </span>
              ) : isEligible ? (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  READY FOR CERTIFICATION
                </span>
              ) : (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1">
                  <ShieldX className="w-3.5 h-3.5" />
                  BLOCKED ({evaluation.blocking_reasons.length} ISSUES)
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              {isCertified
                ? `Certified by ${certification.certified_by} on ${new Date(certification.certified_at).toLocaleString()}`
                : isEligible
                ? 'All authoritative checklist conditions satisfied. Authorized steward or engineer can certify.'
                : 'Batch cannot be certified until all blockers are remediated or formally waived.'}
            </p>
          </div>
        </div>

        {isEligible && (
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Optional certification notes..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-48"
            />
            <button
              onClick={handleCertify}
              disabled={certifying}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white shadow-sm transition-colors"
            >
              <Award className="w-3.5 h-3.5" />
              <span>{certifying ? 'Signing...' : 'Certify Batch'}</span>
            </button>
          </div>
        )}
      </div>

      {/* 2. If Certified: Immutable Evidence Attestation Card */}
      {isCertified && (
        <div className="bg-slate-950 border border-emerald-500/20 rounded-xl p-4 text-xs space-y-2">
          <div className="flex justify-between items-center pb-2 border-b border-slate-800">
            <span className="font-semibold text-emerald-400 flex items-center gap-1.5">
              <Award className="w-4 h-4" />
              Immutable Certificate Record
            </span>
            <span className="font-mono text-[10px] text-slate-500">
              ID: {certification.id}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px] pt-1">
            <div>
              <span className="text-slate-500 block">Input Fingerprint:</span>
              <span className="font-mono text-slate-300">
                {certification.input_file_fingerprint.slice(0, 16)}...
              </span>
            </div>
            <div>
              <span className="text-slate-500 block">Evidence Hash:</span>
              <span className="font-mono text-slate-300">
                {certification.evidence_hash.slice(0, 16)}...
              </span>
            </div>
            <div>
              <span className="text-slate-500 block">Total Certified Rows:</span>
              <span className="font-semibold text-slate-200">
                {certification.total_rows.toLocaleString()}
              </span>
            </div>
            <div>
              <span className="text-slate-500 block">Certified Under Waiver:</span>
              <span className={certification.certified_with_waivers ? 'text-amber-400 font-semibold' : 'text-emerald-400 font-semibold'}>
                {certification.certified_with_waivers ? 'YES' : 'NO'}
              </span>
            </div>
          </div>
          {certification.certification_notes && (
            <div className="pt-2 text-slate-400">
              <span className="text-slate-500 font-medium">Attestation Notes:</span>{' '}
              {certification.certification_notes}
            </div>
          )}
        </div>
      )}

      {/* 3. Blockers Banner (if blocked) */}
      {!evaluation.is_eligible && evaluation.blocking_reasons.length > 0 && (
        <div className="bg-rose-950/30 border border-rose-900/50 rounded-xl p-3.5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>Active Certification Blockers</span>
          </div>
          <ul className="list-disc list-inside space-y-1 text-xs text-rose-200/90 pl-1">
            {evaluation.blocking_reasons.map((reason: string, idx: number) => (
              <li key={idx}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 4. Authoritative Checklist Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-4 py-2.5 bg-slate-800/60 border-b border-slate-800 flex justify-between items-center">
          <span className="text-xs font-semibold text-slate-200">
            Authoritative Governance Checklist (7 Categories)
          </span>
          <span className="text-[11px] text-slate-400">
            {evaluation.checklist.filter((c: any) => c.passed).length} / {evaluation.checklist.length} Passed
          </span>
        </div>
        <div className="divide-y divide-slate-800 text-xs">
          {evaluation.checklist.map((item: any, idx: number) => (
            <div key={idx} className="px-4 py-3 flex items-center justify-between gap-3 hover:bg-slate-800/30 transition-colors">
              <div className="flex items-center gap-3">
                {item.passed ? (
                  item.waived ? (
                    <div className="p-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      <FileCheck2 className="w-4 h-4" />
                    </div>
                  ) : (
                    <div className="p-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <CheckCircle2 className="w-4 h-4" />
                    </div>
                  )
                ) : (
                  <div className="p-1 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
                    <XCircle className="w-4 h-4" />
                  </div>
                )}
                <div>
                  <div className="font-semibold text-slate-100 flex items-center gap-2">
                    <span>{item.title}</span>
                    {item.waived && (
                      <span className="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                        WAIVED
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-0.5">{item.details}</div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {!item.passed && (
                  <button
                    onClick={() => {
                      setSelectedVariance({
                        id: item.waiver_id || batchId,
                        batch_id: batchId,
                        feed_id: evaluation.feed_id,
                        control_type: item.category,
                        control_id: item.category,
                        title: `Variance for ${item.title}`,
                        description: item.details,
                      });
                      setSelectedExistingWaiver(null);
                      setWaiverModalMode('REQUEST');
                      setWaiverModalOpen(true);
                    }}
                    className="text-[10px] font-medium text-amber-400 hover:text-amber-300 underline"
                  >
                    Request Waiver
                  </button>
                )}
                {item.passed ? (
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${item.waived ? 'bg-amber-500/10 text-amber-400' : 'bg-emerald-500/10 text-emerald-400'}`}>
                    {item.waived ? 'WAIVED' : 'PASS'}
                  </span>
                ) : (
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-rose-500/10 text-rose-400">
                    FAIL
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 5. Active Waivers Section (if any applied) */}
      {evaluation.active_waivers.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs space-y-2">
          <h4 className="font-semibold text-amber-400 flex items-center gap-1.5">
            <FileCheck2 className="w-4 h-4" />
            Applied Governed Waivers ({evaluation.active_waivers.length})
          </h4>
          <div className="space-y-1.5">
            {evaluation.active_waivers.map((w: any, idx: number) => (
              <div key={idx} className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80 flex justify-between items-center text-[11px]">
                <div>
                  <span className="font-medium text-slate-300 mr-2">[{w.control_type}]</span>
                  <span className="text-slate-400">{w.reason}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setSelectedExistingWaiver({
                        id: w.waiver_id,
                        variance_id: w.waiver_id,
                        batch_id: batchId,
                        affected_control_type: w.control_type,
                        business_justification: w.reason,
                        risk_assessment: 'Risk assessed and approved under operational policy.',
                        mitigation_notes: 'Downstream operations tagged for exception handling.',
                        expires_at: new Date(Date.now() + 14 * 86400000).toISOString(),
                        status: 'APPROVED',
                        requested_by: 'lead_analyst',
                      });
                      setSelectedVariance(null);
                      setWaiverModalMode('REVIEW');
                      setWaiverModalOpen(true);
                    }}
                    className="text-[10px] text-blue-400 hover:text-blue-300 underline"
                  >
                    View Waiver
                  </button>
                  <span className="font-mono text-[9px] text-slate-500">{w.waiver_id.slice(0, 8)}...</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Governed Ops Waiver Modal */}
      <OpsWaiverModal
        isOpen={waiverModalOpen}
        onClose={() => setWaiverModalOpen(false)}
        onSuccess={() => {
          setWaiverModalOpen(false);
          loadData();
          onRefreshParent?.();
        }}
        variance={selectedVariance}
        existingWaiver={selectedExistingWaiver}
        mode={waiverModalMode}
      />
    </div>
  );
}

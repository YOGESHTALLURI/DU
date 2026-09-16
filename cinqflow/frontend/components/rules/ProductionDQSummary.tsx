'use client';
import React, { useEffect, useState } from 'react';
import { ShieldCheck, ShieldAlert, CheckCircle2, AlertOctagon, Info, Clock, Check, AlertTriangle } from 'lucide-react';

interface DQBatchRuleItem {
  rule_id: string;
  rule_version_id: string;
  rule_name: string;
  rule_type: string;
  severity: 'INFO' | 'WARNING' | 'QUARANTINE' | 'REJECT_FILE';
  total_rows_evaluated: number;
  passed_rows: number;
  failed_rows: number;
  pass_rate: number;
  action_taken: 'PASSED' | 'LOGGED' | 'QUARANTINED' | 'BATCH_ABORTED';
  execution_duration_ms: number;
}

interface DQBatchSummaryResponse {
  batch_id: string;
  total_rules_executed: number;
  total_rows_evaluated: number;
  total_violations: number;
  has_quarantined_rows: boolean;
  has_reject_file_violation: boolean;
  batch_action: string;
  rules: DQBatchRuleItem[];
}

interface ProductionDQSummaryProps {
  batchId: string;
}

export default function ProductionDQSummary({ batchId }: ProductionDQSummaryProps) {
  const [summary, setSummary] = useState<DQBatchSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!batchId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/rules/executions/batch/${batchId}`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setSummary(data))
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [batchId]);

  if (loading) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-8 text-xs text-slate-400">
        Loading production data quality results...
      </div>
    );
  }

  if (!summary || summary.total_rules_executed === 0) {
    return null;
  }

  const isAborted = summary.has_reject_file_violation || summary.batch_action === 'BATCH_ABORTED';
  const hasQuarantine = summary.has_quarantined_rows;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-8" data-testid="production-dq-summary">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {isAborted ? (
            <ShieldAlert className="w-5 h-5 text-rose-400" />
          ) : (
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          )}
          <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
            Production Data Quality Execution (Silver Raw Stage)
          </h2>
        </div>
        <span
          className={`px-3 py-1 rounded text-xs font-bold font-mono ${
            isAborted
              ? 'bg-rose-950 text-rose-400 border border-rose-800'
              : hasQuarantine
              ? 'bg-amber-950 text-amber-400 border border-amber-800'
              : 'bg-emerald-950 text-emerald-400 border border-emerald-800'
          }`}
        >
          {summary.batch_action}
        </span>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6 text-center font-mono bg-slate-950 p-4 rounded-lg border border-slate-800">
        <div>
          <p className="text-slate-500 text-xs uppercase">Rules Executed</p>
          <p className="text-2xl font-bold text-white mt-1">{summary.total_rules_executed}</p>
        </div>
        <div>
          <p className="text-slate-500 text-xs uppercase">Rows Evaluated</p>
          <p className="text-2xl font-bold text-blue-400 mt-1">{summary.total_rows_evaluated}</p>
        </div>
        <div>
          <p className="text-slate-500 text-xs uppercase">Total Violations</p>
          <p
            className={`text-2xl font-bold mt-1 ${
              summary.total_violations > 0 ? 'text-amber-400' : 'text-emerald-400'
            }`}
          >
            {summary.total_violations}
          </p>
        </div>
        <div>
          <p className="text-slate-500 text-xs uppercase">Aborted / Quarantine</p>
          <p
            className={`text-2xl font-bold mt-1 ${
              isAborted ? 'text-rose-400' : hasQuarantine ? 'text-amber-400' : 'text-emerald-400'
            }`}
          >
            {isAborted ? 'ABORTED' : hasQuarantine ? 'QUARANTINED' : 'CLEAN'}
          </p>
        </div>
      </div>

      {/* Rule Results Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
              <th className="py-2 px-3">Rule Name</th>
              <th className="py-2 px-3">Type</th>
              <th className="py-2 px-3">Severity</th>
              <th className="py-2 px-3 text-right">Evaluated</th>
              <th className="py-2 px-3 text-right">Passed</th>
              <th className="py-2 px-3 text-right">Failed</th>
              <th className="py-2 px-3 text-right">Pass Rate</th>
              <th className="py-2 px-3">Action Taken</th>
              <th className="py-2 px-3 text-right">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
            {summary.rules.map((rule) => {
              const actionColors: Record<string, string> = {
                PASSED: 'bg-emerald-950/70 text-emerald-400 border border-emerald-800',
                LOGGED_INFO: 'bg-slate-800 text-slate-300 border border-slate-700',
                LOGGED_WARNING: 'bg-blue-950/70 text-blue-400 border border-blue-800',
                QUARANTINED_ROWS: 'bg-amber-950/70 text-amber-400 border border-amber-800',
                BATCH_ABORTED: 'bg-rose-950/70 text-rose-400 border border-rose-800',
              };

              const severityColors: Record<string, string> = {
                INFO: 'text-blue-400',
                WARNING: 'text-amber-300',
                QUARANTINE: 'text-orange-400 font-bold',
                REJECT_FILE: 'text-rose-400 font-bold',
              };

              return (
                <tr key={rule.rule_version_id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-2.5 px-3 font-sans font-medium text-slate-200">{rule.rule_name}</td>
                  <td className="py-2.5 px-3 text-slate-400">{rule.rule_type}</td>
                  <td className={`py-2.5 px-3 ${severityColors[rule.severity] || ''}`}>
                    {rule.severity}
                  </td>
                  <td className="py-2.5 px-3 text-right">{rule.total_rows_evaluated}</td>
                  <td className="py-2.5 px-3 text-right text-emerald-400">{rule.passed_rows}</td>
                  <td className={`py-2.5 px-3 text-right ${rule.failed_rows > 0 ? 'text-rose-400 font-bold' : ''}`}>
                    {rule.failed_rows}
                  </td>
                  <td className="py-2.5 px-3 text-right font-bold">
                    {(rule.pass_rate * 100).toFixed(1)}%
                  </td>
                  <td className="py-2.5 px-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${actionColors[rule.action_taken] || ''}`}>
                      {rule.action_taken}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-right text-slate-500">{rule.execution_duration_ms}ms</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500 font-mono">
        <span>Protected: Zero PHI / Raw Data Persisted in DQ Telemetry</span>
        <span>Deterministic Rule Execution pinned to Published Schema</span>
      </div>
    </div>
  );
}

'use client';
import React from 'react';
import { Activity, CheckCircle, AlertTriangle, Clock, ShieldAlert, Cpu } from 'lucide-react';

export interface OpsKpis {
  active_feeds: number;
  batches_24h_total: number;
  batches_24h_success: number;
  batches_24h_failed: number;
  batches_running: number;
  sla_attainment_pct: number;
  quarantined_rows_24h: number;
  unacknowledged_drift_alerts: number;
  breaking_drift_count: number;
  non_breaking_drift_count: number;
}

interface OpsKpiDeckProps {
  kpis: OpsKpis | null;
  loading: boolean;
}

export default function OpsKpiDeck({ kpis, loading }: OpsKpiDeckProps) {
  if (loading || !kpis) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4 mb-6">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-28 bg-slate-900/60 animate-pulse rounded-xl border border-slate-800" />
        ))}
      </div>
    );
  }

  const successRate = kpis.batches_24h_total > 0
    ? Math.round((kpis.batches_24h_success / kpis.batches_24h_total) * 100)
    : 100;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4 mb-6" data-testid="ops-kpi-deck">
      {/* 1. Active Feeds */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">Active Feeds</span>
          <Activity className="w-4 h-4 text-blue-400" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">{kpis.active_feeds}</div>
          <p className="text-xs text-slate-400 mt-1">Operational Feeds</p>
        </div>
      </div>

      {/* 2. 24h Batches Execution */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">24h Execution</span>
          <CheckCircle className="w-4 h-4 text-emerald-400" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">
            {kpis.batches_24h_success}
            <span className="text-sm font-normal text-slate-400"> / {kpis.batches_24h_total}</span>
          </div>
          <p className="text-xs text-emerald-400 mt-1 font-medium">
            {successRate}% Success ({kpis.batches_24h_failed} failed)
          </p>
        </div>
      </div>

      {/* 3. Running Batches */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">In Flight</span>
          <Cpu className="w-4 h-4 text-indigo-400" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">{kpis.batches_running}</div>
          <p className="text-xs text-indigo-300 mt-1">Active Batches Running</p>
        </div>
      </div>

      {/* 4. SLA Attainment */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">SLA Attainment</span>
          <Clock className="w-4 h-4 text-amber-400" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">
            {kpis.sla_attainment_pct.toFixed(1)}%
          </div>
          <p className="text-xs text-slate-400 mt-1">Arrival Window Adherence</p>
        </div>
      </div>

      {/* 5. Quarantined Records 24h */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">Quarantine 24h</span>
          <ShieldAlert className="w-4 h-4 text-amber-500" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">{kpis.quarantined_rows_24h.toLocaleString()}</div>
          <p className="text-xs text-slate-400 mt-1">Quarantined Data Rows</p>
        </div>
      </div>

      {/* 6. Schema Drift Alerts */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-semibold uppercase tracking-wider">Drift Alerts</span>
          <AlertTriangle className="w-4 h-4 text-rose-400" />
        </div>
        <div className="mt-2">
          <div className="text-2xl font-bold text-white">{kpis.unacknowledged_drift_alerts}</div>
          <p className="text-xs text-rose-400 mt-1 font-medium">
            {kpis.breaking_drift_count} Breaking / {kpis.non_breaking_drift_count} Warn
          </p>
        </div>
      </div>
    </div>
  );
}

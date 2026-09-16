'use client';

import React, { useState, useEffect } from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  Info,
  CheckCircle2,
  RefreshCw,
  BookOpen,
  ArrowRight,
  ShieldAlert,
  SlidersHorizontal,
} from 'lucide-react';
import { api } from '@/lib/api-client';
import { FailureFingerprintBadge } from './FailureFingerprintBadge';
import OpsAlertDetailDrawer, { AlertDetailData } from './OpsAlertDetailDrawer';

export default function OpsAlertsDeck() {
  const [alerts, setAlerts] = useState<AlertDetailData[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedAlert, setSelectedAlert] = useState<AlertDetailData | null>(null);
  const [filterTab, setFilterTab] = useState<'ACTIVE' | 'CRITICAL' | 'WARNING' | 'RESOLVED'>('ACTIVE');

  const fetchAlerts = async () => {
    try {
      setLoading(true);
      const data: AlertDetailData[] = await api.get('/api/v1/ops/alerts?limit=50');
      setAlerts(data || []);
    } catch (err) {
      console.error('Failed to fetch operational alerts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 15000); // 15s refresh
    return () => clearInterval(interval);
  }, []);

  const activeAlerts = alerts.filter((a) => a.status !== 'RESOLVED');
  const criticalAlerts = alerts.filter((a) => a.severity === 'CRITICAL' && a.status !== 'RESOLVED');
  const warningAlerts = alerts.filter((a) => a.severity === 'WARNING' && a.status !== 'RESOLVED');
  const resolvedAlerts = alerts.filter((a) => a.status === 'RESOLVED');

  const displayedAlerts =
    filterTab === 'ACTIVE'
      ? activeAlerts
      : filterTab === 'CRITICAL'
      ? criticalAlerts
      : filterTab === 'WARNING'
      ? warningAlerts
      : resolvedAlerts;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-8">
      {/* Header Bar */}
      <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/70 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-100 text-rose-700">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              Operational Incidents & Self-Explaining Alerts
              {activeAlerts.length > 0 && (
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-600 text-white">
                  {activeAlerts.length}
                </span>
              )}
            </h2>
            <p className="text-xs text-slate-500">
              Storm-suppressed failure signatures, root cause fingerprinting, and governed recovery playbooks.
            </p>
          </div>
        </div>

        {/* Filter Controls & Refresh */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-slate-200/70 p-1 rounded-lg text-xs font-semibold text-slate-600">
            <button
              onClick={() => setFilterTab('ACTIVE')}
              className={`px-3 py-1 rounded-md transition-colors ${
                filterTab === 'ACTIVE' ? 'bg-white text-slate-900 shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Active ({activeAlerts.length})
            </button>
            <button
              onClick={() => setFilterTab('CRITICAL')}
              className={`px-3 py-1 rounded-md transition-colors ${
                filterTab === 'CRITICAL' ? 'bg-white text-rose-700 shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Critical ({criticalAlerts.length})
            </button>
            <button
              onClick={() => setFilterTab('WARNING')}
              className={`px-3 py-1 rounded-md transition-colors ${
                filterTab === 'WARNING' ? 'bg-white text-amber-700 shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Warnings ({warningAlerts.length})
            </button>
            <button
              onClick={() => setFilterTab('RESOLVED')}
              className={`px-3 py-1 rounded-md transition-colors ${
                filterTab === 'RESOLVED' ? 'bg-white text-slate-900 shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Resolved ({resolvedAlerts.length})
            </button>
          </div>

          <button
            onClick={fetchAlerts}
            disabled={loading}
            className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
            title="Refresh alerts"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-600' : ''}`} />
          </button>
        </div>
      </div>

      {/* Alert Deck Content */}
      <div className="p-6">
        {displayedAlerts.length === 0 ? (
          <div className="text-center py-8 text-slate-400">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-80" />
            <p className="text-sm font-semibold text-slate-700">All Systems Normal</p>
            <p className="text-xs text-slate-500 mt-0.5">
              {filterTab === 'RESOLVED' ? 'No resolved incidents on record.' : 'Zero active operational incidents.'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {displayedAlerts.map((alert) => {
              const isCritical = alert.severity === 'CRITICAL';
              return (
                <div
                  key={alert.id}
                  onClick={() => setSelectedAlert(alert)}
                  className={`p-4 rounded-xl border transition-all cursor-pointer hover:shadow-md flex flex-col justify-between ${
                    isCritical
                      ? 'bg-rose-50/40 border-rose-200 hover:border-rose-300'
                      : 'bg-slate-50/50 border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div>
                    {/* Badge Row */}
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            isCritical ? 'bg-rose-600 text-white' : 'bg-amber-500 text-white'
                          }`}
                        >
                          {alert.severity}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-white border border-slate-200 text-slate-700">
                          {alert.status}
                        </span>
                      </div>
                      {alert.occurrence_count > 1 && (
                        <span
                          className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700 border border-purple-200"
                          title="Storm suppressed: repeated identical failures collapsed into this alert"
                        >
                          {alert.occurrence_count}× Suppressed
                        </span>
                      )}
                    </div>

                    {/* Title & Feed */}
                    <h3 className="text-sm font-bold text-slate-900 line-clamp-1 mb-1">{alert.title}</h3>
                    <p className="text-xs text-slate-500 mb-3">
                      Feed: <span className="font-semibold text-slate-700">{alert.feed_name || alert.feed_id}</span>
                    </p>

                    {/* Snippet */}
                    <p className="text-xs text-slate-600 line-clamp-2 mb-3 bg-white/70 p-2 rounded border border-slate-200/60 leading-relaxed">
                      {alert.description}
                    </p>

                    {/* Fingerprint Badge */}
                    {alert.fingerprint && (
                      <div className="mb-3">
                        <FailureFingerprintBadge
                          category={alert.fingerprint.category}
                          fingerprintHash={alert.fingerprint.fingerprint_hash}
                          showOccurrences={false}
                        />
                      </div>
                    )}
                  </div>

                  {/* Footer Playbook / Action Teaser */}
                  <div className="pt-3 border-t border-slate-200/80 flex items-center justify-between text-xs">
                    {alert.recommended_playbook_version ? (
                      <span className="inline-flex items-center gap-1 text-blue-700 font-medium truncate max-w-[170px]">
                        <BookOpen className="w-3.5 h-3.5 flex-shrink-0" />
                        <span className="truncate">
                          Playbook v{alert.recommended_playbook_version.version_number}
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-400">Advisory review</span>
                    )}

                    <span className="inline-flex items-center gap-1 text-blue-600 font-semibold hover:text-blue-800">
                      Investigate <ArrowRight className="w-3.5 h-3.5" />
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Detail Slide-Over Drawer */}
      <OpsAlertDetailDrawer
        alert={selectedAlert}
        onClose={() => setSelectedAlert(null)}
        onRefresh={() => {
          fetchAlerts();
          if (selectedAlert) {
            // update selected alert data
            api.get(`/api/v1/ops/alerts/${selectedAlert.id}`).then((res: any) => setSelectedAlert(res)).catch(() => {});
          }
        }}
      />
    </div>
  );
}

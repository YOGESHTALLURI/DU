'use client';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import Navbar from '@/components/Navbar';
import OpsKpiDeck, { OpsKpis } from '@/components/ops/OpsKpiDeck';
import FileArrivalBoard, { OpsArrivalSlotItem } from '@/components/ops/FileArrivalBoard';
import BatchStageMonitorTable, { OpsBatchMonitorItem } from '@/components/ops/BatchStageMonitorTable';
import BatchStageDetailDrawer from '@/components/ops/BatchStageDetailDrawer';
import OpsActionModal, { ActionModalTarget } from '@/components/ops/OpsActionModal';
import OpsPendingActionsBanner, { PendingActionItem } from '@/components/ops/OpsPendingActionsBanner';
import OpsAlertsDeck from '@/components/ops/OpsAlertsDeck';
import { RefreshCw, Radio, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api-client';

export default function OperationsPage() {
  // State
  const [kpis, setKpis] = useState<OpsKpis | null>(null);
  const [kpisLoading, setKpisLoading] = useState(true);

  const [arrivalSlots, setArrivalSlots] = useState<OpsArrivalSlotItem[]>([]);
  const [arrivalsLoading, setArrivalsLoading] = useState(true);
  const [horizonHours, setHorizonHours] = useState(24);
  const [arrivalFeedId, setArrivalFeedId] = useState('');

  const [batches, setBatches] = useState<OpsBatchMonitorItem[]>([]);
  const [batchesTotal, setBatchesTotal] = useState(0);
  const [monitorPage, setMonitorPage] = useState(1);
  const [monitorFeedId, setMonitorFeedId] = useState('');
  const [monitorStatus, setMonitorStatus] = useState('');
  const [monitorLoading, setMonitorLoading] = useState(true);

  const [feeds, setFeeds] = useState<{ id: string; name: string }[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);

  // Governed Action Surface State
  const [actionTarget, setActionTarget] = useState<ActionModalTarget | null>(null);
  const [pendingActions, setPendingActions] = useState<PendingActionItem[]>([]);
  const [currentUserId, setCurrentUserId] = useState<string | undefined>(undefined);

  // Polling control
  const [refreshIntervalSec, setRefreshIntervalSec] = useState(30);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date>(new Date());
  const sessionLoggedRef = useRef(false);

  // 1. Initial Session Audit Event (Logged ONCE per dashboard entry, zero polling noise)
  useEffect(() => {
    if (!sessionLoggedRef.current) {
      sessionLoggedRef.current = true;
      api.post('/api/v1/ops/session-start', {})
        .catch(() => {
          // Non-blocking telemetry
        });
    }
  }, []);

  // 2. Load Feeds list & Current User Profile
  useEffect(() => {
    api.get<any[]>('/api/v1/feeds')
      .then((data) => {
        setFeeds(data.map((f) => ({ id: f.id, name: f.name })));
      })
      .catch(() => setFeeds([]));

    api.get<any>('/api/v1/auth/me')
      .then((user) => setCurrentUserId(user.id))
      .catch(() => {});
  }, []);

  // 3. Data Fetchers
  const fetchKpis = useCallback(async () => {
    try {
      const data = await api.get<{ kpis: OpsKpis }>('/api/v1/ops/home');
      setKpis(data.kpis);
    } catch {
      // keep prior kpis
    } finally {
      setKpisLoading(false);
    }
  }, []);

  const fetchArrivals = useCallback(async () => {
    try {
      let url = `/api/v1/ops/arrivals?window_hours=${horizonHours}`;
      if (arrivalFeedId) url += `&feed_id=${arrivalFeedId}`;
      const data = await api.get<{ items: OpsArrivalSlotItem[] }>(url);
      setArrivalSlots(data.items);
    } catch {
      // keep prior slots
    } finally {
      setArrivalsLoading(false);
    }
  }, [horizonHours, arrivalFeedId]);

  const fetchBatches = useCallback(async () => {
    try {
      let url = `/api/v1/ops/monitor?page=${monitorPage}&limit=10`;
      if (monitorFeedId) url += `&feed_id=${monitorFeedId}`;
      if (monitorStatus) url += `&status=${monitorStatus}`;
      const data = await api.get<{ total: number; items: OpsBatchMonitorItem[] }>(url);
      setBatches(data.items);
      setBatchesTotal(data.total);
    } catch {
      // keep prior batches
    } finally {
      setMonitorLoading(false);
    }
  }, [monitorPage, monitorFeedId, monitorStatus]);

  const fetchPendingActions = useCallback(async () => {
    try {
      const data = await api.get<{ items: PendingActionItem[] }>('/api/v1/ops/actions/pending');
      setPendingActions(data.items || []);
    } catch {
      setPendingActions([]);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setIsRefreshing(true);
    await Promise.all([fetchKpis(), fetchArrivals(), fetchBatches(), fetchPendingActions()]);
    setLastRefreshedAt(new Date());
    setIsRefreshing(false);
  }, [fetchKpis, fetchArrivals, fetchBatches, fetchPendingActions]);

  // Initial load
  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Periodic REST Polling (SWR-style, zero audit noise)
  useEffect(() => {
    if (refreshIntervalSec <= 0) return;
    const interval = setInterval(() => {
      refreshAll();
    }, refreshIntervalSec * 1000);
    return () => clearInterval(interval);
  }, [refreshIntervalSec, refreshAll]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Top Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-6 border-b border-slate-800">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white tracking-tight">
                Operations Control Center
              </h1>
              <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                <Radio className="w-3 h-3 animate-pulse text-emerald-400" />
                LIVE
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              File-arrival SLA monitoring, 24-hour health telemetry, and batch/stage pipeline execution.
            </p>
          </div>

          {/* Controls: Auto-refresh & Manual Refresh */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1 text-xs text-slate-400">
              <span>Auto-refresh:</span>
              <select
                value={refreshIntervalSec}
                onChange={(e) => setRefreshIntervalSec(Number(e.target.value))}
                className="bg-slate-800 text-slate-200 rounded px-1.5 py-0.5 text-xs focus:outline-none"
              >
                <option value={10}>10s</option>
                <option value={30}>30s</option>
                <option value={60}>60s</option>
                <option value={0}>Off</option>
              </select>
            </div>

            <button
              onClick={() => refreshAll()}
              disabled={isRefreshing}
              className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span>Refresh Now</span>
            </button>
          </div>
        </div>

        {/* 0. Dual-Control Governance Queue Banner */}
        <OpsPendingActionsBanner
          pendingActions={pendingActions}
          currentUserId={currentUserId}
          onActionProcessed={() => refreshAll()}
        />

        {/* 1. Macro KPI Deck */}
        <OpsKpiDeck kpis={kpis} loading={kpisLoading} />

        {/* 1.5 Incidents & Self-Explaining Alerts Deck */}
        <OpsAlertsDeck />

        {/* 2. File-Arrival Board */}
        <FileArrivalBoard
          slots={arrivalSlots}
          loading={arrivalsLoading}
          horizonHours={horizonHours}
          onHorizonChange={setHorizonHours}
          selectedFeedId={arrivalFeedId}
          onFeedChange={setArrivalFeedId}
          feeds={feeds}
        />

        {/* 3. Batch & Stage Monitor */}
        <BatchStageMonitorTable
          batches={batches}
          total={batchesTotal}
          page={monitorPage}
          limit={10}
          onPageChange={setMonitorPage}
          loading={monitorLoading}
          selectedFeedId={monitorFeedId}
          onFeedChange={setMonitorFeedId}
          selectedStatus={monitorStatus}
          onStatusChange={setMonitorStatus}
          feeds={feeds}
          onSelectBatch={(id) => setSelectedBatchId(id)}
          onRestartBatch={(batch) => {
            setActionTarget({
              actionType: 'RESTART_BATCH',
              targetType: 'BATCH',
              targetId: batch.batch_id,
              targetTitle: `Batch ${batch.batch_id.substring(0, 8)} (${batch.feed_name})`,
              isHighRisk: false,
            });
          }}
        />

        {/* 4. Batch Stage Detail Drawer */}
        <BatchStageDetailDrawer
          batchId={selectedBatchId}
          onClose={() => setSelectedBatchId(null)}
          onRequestAction={(target) => setActionTarget(target)}
        />

        {/* 5. Governed Action Modal */}
        <OpsActionModal
          target={actionTarget}
          onClose={() => setActionTarget(null)}
          onActionComplete={() => refreshAll()}
        />
      </main>
    </div>
  );
}

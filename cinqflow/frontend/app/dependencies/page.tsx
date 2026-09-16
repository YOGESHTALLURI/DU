'use client';
import { useEffect, useState, useMemo } from 'react';
import Navbar from '@/components/Navbar';
import {
  Network,
  Clock,
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Plus,
  Trash2,
  Play,
  Pause,
  Power,
  Edit2,
  RefreshCw,
} from 'lucide-react';

interface FeedItem {
  id: string;
  name: string;
  domain: string;
  status: string;
  schedule_expression?: string;
}

interface DAGNode {
  id: string;
  feed_id: string;
  name: string;
  domain: string;
  status: string;
  schedule_expression?: string;
  schedule_status?: 'ACTIVE' | 'PAUSED' | 'DISABLED';
  next_run_at?: string;
  is_gate_cleared: boolean;
}

interface DAGEdge {
  id: string;
  source_feed_id: string;
  target_feed_id: string;
  dependency_type: 'HARD' | 'SOFT';
  is_active: boolean;
  max_lag_hours?: number;
}

interface DAGGraphResponse {
  nodes: DAGNode[];
  edges: DAGEdge[];
  total_feeds: number;
  total_dependencies: number;
  is_acyclic: boolean;
}

interface DependencyGateItem {
  dependency_id: string;
  upstream_feed_id: string;
  upstream_feed_name: string;
  dependency_type: 'HARD' | 'SOFT';
  latest_batch_id?: string;
  latest_batch_status?: string;
  latest_batch_completed_at?: string;
  quarantine_rate_pct?: number;
  reconciliation_balanced?: boolean;
  has_reject_file_severity: boolean;
  lag_hours?: number;
  is_satisfied: boolean;
  blocking_reason?: string;
  warning_reason?: string;
}

interface GateCheckResult {
  feed_id: string;
  feed_name: string;
  is_allowed: boolean;
  evaluated_at: string;
  blocking_reasons: string[];
  warnings: string[];
  dependencies_evaluated: DependencyGateItem[];
}

interface FeedSchedule {
  id: string;
  feed_id: string;
  schedule_expression: string;
  timezone: string;
  status: 'ACTIVE' | 'PAUSED' | 'DISABLED';
  next_run_at?: string;
  last_run_at?: string;
  version: number;
}

interface UserProfile {
  email: string;
  roles: string[];
}

export default function DependenciesPage() {
  const [dag, setDag] = useState<DAGGraphResponse | null>(null);
  const [feeds, setFeeds] = useState<FeedItem[]>([]);
  const [schedules, setSchedules] = useState<Record<string, FeedSchedule>>({});
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedFeedGate, setSelectedFeedGate] = useState<GateCheckResult | null>(null);

  // Modals & Forms
  const [showAddModal, setShowAddModal] = useState(false);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [editingFeed, setEditingFeed] = useState<FeedItem | null>(null);
  const [cronInput, setCronInput] = useState('');
  const [timezoneInput, setTimezoneInput] = useState('UTC');
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleSubmitting, setScheduleSubmitting] = useState(false);

  const [addForm, setAddForm] = useState({
    downstream_feed_id: '',
    upstream_feed_id: '',
    dependency_type: 'HARD' as 'HARD' | 'SOFT',
    max_lag_hours: 24,
    block_on_upstream_failure: true,
    block_on_reject_file: true,
    block_on_unbalanced_reconciliation: true,
    max_quarantine_rate_pct: 5.0,
  });
  const [addError, setAddError] = useState('');
  const [addSubmitting, setAddSubmitting] = useState(false);

  const isEngineer = useMemo(() => user?.roles?.includes('ENGINEER') ?? false, [user]);

  const token = typeof window !== 'undefined' ? localStorage.getItem('cinqflow_token') || '' : '';
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }), [token]);

  const loadData = async () => {
    try {
      setRefreshing(true);
      // Fetch user profile
      const userRes = await fetch('/api/v1/auth/me', { headers });
      if (userRes.ok) {
        setUser(await userRes.json());
      }

      // Fetch feeds
      const fRes = await fetch('/api/v1/feeds', { headers });
      const feedsData: FeedItem[] = fRes.ok ? await fRes.json() : [];
      setFeeds(feedsData);

      // Fetch DAG
      const dagRes = await fetch('/api/v1/dependencies/dag', { headers });
      if (dagRes.ok) {
        const dagData: DAGGraphResponse = await dagRes.json();
        setDag(dagData);
        const schedMap: Record<string, FeedSchedule> = {};
        dagData.nodes.forEach((n) => {
          schedMap[n.feed_id] = {
            id: n.id,
            feed_id: n.feed_id,
            schedule_expression: n.schedule_expression || '0 0 * * *',
            timezone: 'UTC',
            status: n.schedule_status || 'ACTIVE',
            next_run_at: n.next_run_at,
            version: 1,
          };
        });
        setSchedules(schedMap);
      }
    } catch (err) {
      console.error('Failed to load dependency data:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleInspectGate = async (feedId: string) => {
    setSelectedFeedGate(null);
    try {
      const res = await fetch(`/api/v1/dependencies/gate-check/${feedId}`, { headers });
      if (res.ok) {
        setSelectedFeedGate(await res.json());
      }
    } catch (err) {
      console.error('Gate check inspection failed:', err);
    }
  };

  const handleAddDependency = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError('');
    if (!addForm.downstream_feed_id || !addForm.upstream_feed_id) {
      setAddError('Both downstream and upstream feeds must be selected.');
      return;
    }
    if (addForm.downstream_feed_id === addForm.upstream_feed_id) {
      setAddError('A feed cannot depend on itself.');
      return;
    }

    setAddSubmitting(true);
    try {
      const res = await fetch('/api/v1/dependencies/', {
        method: 'POST',
        headers,
        body: JSON.stringify(addForm),
      });

      if (!res.ok) {
        const errData = await res.json();
        setAddError(errData.detail || 'Failed to create dependency.');
        return;
      }

      setShowAddModal(false);
      setAddForm({
        downstream_feed_id: '',
        upstream_feed_id: '',
        dependency_type: 'HARD',
        max_lag_hours: 24,
        block_on_upstream_failure: true,
        block_on_reject_file: true,
        block_on_unbalanced_reconciliation: true,
        max_quarantine_rate_pct: 5.0,
      });
      await loadData();
    } catch {
      setAddError('Connection error occurred.');
    } finally {
      setAddSubmitting(false);
    }
  };

  const handleDeleteDependency = async (depId: string) => {
    if (!confirm('Are you sure you want to remove this dependency edge?')) return;
    try {
      const res = await fetch(`/api/v1/dependencies/${depId}`, {
        method: 'DELETE',
        headers,
      });
      if (res.ok) {
        await loadData();
        if (selectedFeedGate) setSelectedFeedGate(null);
      } else {
        const errData = await res.json();
        alert(errData.detail || 'Failed to delete dependency');
      }
    } catch {
      alert('Network error while deleting dependency.');
    }
  };

  const handleScheduleAction = async (feedId: string, action: 'pause' | 'resume' | 'disable' | 'enable') => {
    try {
      const res = await fetch(`/api/v1/schedules/feed/${feedId}/${action}`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        await loadData();
      } else {
        const errData = await res.json();
        alert(errData.detail || `Failed to ${action} schedule.`);
      }
    } catch {
      alert(`Network error while performing ${action}.`);
    }
  };

  const handleOpenEditSchedule = (feed: FeedItem) => {
    const existing = schedules[feed.id];
    setEditingFeed(feed);
    setCronInput(existing ? existing.schedule_expression : feed.schedule_expression || '0 0 * * *');
    setTimezoneInput(existing ? existing.timezone : 'UTC');
    setScheduleError('');
    setShowScheduleModal(true);
  };

  const handleSaveSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingFeed) return;
    setScheduleSubmitting(true);
    setScheduleError('');
    try {
      const res = await fetch(`/api/v1/schedules/feed/${editingFeed.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({
          schedule_expression: cronInput.trim(),
          timezone: timezoneInput.trim() || 'UTC',
        }),
      });
      if (!res.ok) {
        const errData = await res.json();
        setScheduleError(errData.detail || 'Failed to update schedule.');
        return;
      }
      setShowScheduleModal(false);
      await loadData();
    } catch {
      setScheduleError('Network error while saving schedule.');
    } finally {
      setScheduleSubmitting(false);
    }
  };

  const feedMap = useMemo(() => {
    const map = new Map<string, string>();
    feeds.forEach((f) => map.set(f.id, f.name));
    return map;
  }, [feeds]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <div className="flex items-center gap-2">
              <Network className="h-7 w-7 text-indigo-400" />
              <h1 className="text-2xl font-bold tracking-tight text-white">
                DAG & Operational Scheduling
              </h1>
            </div>
            <p className="mt-1 text-sm text-slate-400">
              Wave 1 Slice 6: Multi-feed dependency topology, pre-flight gate protection, and authoritative schedules.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadData}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin text-indigo-400' : ''}`} />
              Refresh
            </button>

            {isEngineer ? (
              <button
                onClick={() => setShowAddModal(true)}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium text-white shadow-sm transition-colors"
              >
                <Plus className="h-4 w-4" />
                Add Dependency
              </button>
            ) : (
              <span className="text-xs px-2.5 py-1 rounded bg-slate-800 text-slate-400 border border-slate-700">
                Read-Only (Requires ENGINEER role to mutate)
              </span>
            )}
          </div>
        </div>

        {/* Section 1: DAG Topology Visualizer */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <span>System Dependency DAG</span>
              {dag && (
                <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  {dag.total_feeds} feeds · {dag.total_dependencies} edges · {dag.is_acyclic ? 'Acyclic (Valid)' : 'Cycle Detected'}
                </span>
              )}
            </h2>
            <span className="text-xs text-slate-400">Click any feed to inspect execution gate evaluation</span>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-500 bg-slate-900/40 rounded-xl border border-slate-800">
              Loading topological DAG...
            </div>
          ) : !dag || dag.nodes.length === 0 ? (
            <div className="p-8 text-center text-slate-400 bg-slate-900/30 rounded-xl border border-slate-800">
              No feeds registered in the platform yet.
            </div>
          ) : (
            <div className="bg-slate-900/60 rounded-xl border border-slate-800 p-6 shadow-inner space-y-6">
              {/* Nodes Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {dag.nodes.map((node) => {
                  const sched = schedules[node.feed_id];
                  const schedStatus = sched ? sched.status : 'ACTIVE';
                  const isBlocked = !node.is_gate_cleared;

                  return (
                    <div
                      key={node.id}
                      onClick={() => handleInspectGate(node.feed_id)}
                      className={`p-4 rounded-xl border transition-all cursor-pointer ${
                        selectedFeedGate?.feed_id === node.feed_id
                          ? 'border-indigo-500 bg-slate-800/80 ring-1 ring-indigo-500'
                          : 'border-slate-800 bg-slate-900/90 hover:border-slate-700 hover:bg-slate-800/50'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-white text-base">{node.name}</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded uppercase font-bold bg-slate-800 text-slate-400 border border-slate-700">
                              {node.domain}
                            </span>
                          </div>
                          <span className="text-xs text-slate-400 font-mono mt-0.5 block">
                            Cron: {sched ? sched.schedule_expression : node.schedule_expression || 'manual'}
                          </span>
                        </div>

                        <div>
                          {isBlocked ? (
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-400 bg-rose-950/60 border border-rose-800 px-2 py-0.5 rounded-full">
                              <ShieldAlert className="h-3 w-3" />
                              Gate Blocked
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-2 py-0.5 rounded-full">
                              <ShieldCheck className="h-3 w-3" />
                              Gate Cleared
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
                        <div className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5 text-slate-500" />
                          <span>Status:</span>
                          <span
                            className={`font-semibold ${
                              schedStatus === 'ACTIVE'
                                ? 'text-emerald-400'
                                : schedStatus === 'PAUSED'
                                ? 'text-amber-400'
                                : 'text-slate-500'
                            }`}
                          >
                            {schedStatus}
                          </span>
                        </div>

                        {sched?.next_run_at && (
                          <div className="text-[11px] text-slate-500 font-mono">
                            Next: {new Date(sched.next_run_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Edge Visualizer / Summary */}
              {dag.edges.length > 0 && (
                <div className="pt-4 border-t border-slate-800 space-y-2">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Directed Execution Dependencies
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {dag.edges.map((edge) => (
                      <div
                        key={edge.id}
                        className="inline-flex items-center gap-2 text-xs bg-slate-800/80 border border-slate-700/80 px-3 py-1.5 rounded-lg"
                      >
                        <span className="text-indigo-300 font-medium">{feedMap.get(edge.source_feed_id) || 'Upstream'}</span>
                        <ArrowRight className="h-3 w-3 text-slate-500" />
                        <span className="text-white font-medium">{feedMap.get(edge.target_feed_id) || 'Downstream'}</span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${
                            edge.dependency_type === 'HARD'
                              ? 'bg-rose-950 text-rose-400 border border-rose-800'
                              : 'bg-amber-950 text-amber-400 border border-amber-800'
                          }`}
                        >
                          {edge.dependency_type}
                        </span>
                        {edge.max_lag_hours && (
                          <span className="text-[10px] text-slate-400">max {edge.max_lag_hours}h lag</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Selected Feed Gate Inspector Panel */}
        {selectedFeedGate && (
          <div className="bg-slate-900 border border-indigo-900/60 rounded-xl p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`p-2 rounded-lg ${
                    selectedFeedGate.is_allowed ? 'bg-emerald-950 text-emerald-400' : 'bg-rose-950 text-rose-400'
                  }`}
                >
                  {selectedFeedGate.is_allowed ? (
                    <CheckCircle className="h-6 w-6" />
                  ) : (
                    <XCircle className="h-6 w-6" />
                  )}
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">
                    Pre-Flight Gate Check: {selectedFeedGate.feed_name}
                  </h3>
                  <p className="text-xs text-slate-400">
                    Evaluated at {new Date(selectedFeedGate.evaluated_at).toLocaleString()}
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSelectedFeedGate(null)}
                className="text-xs text-slate-400 hover:text-white px-2 py-1 rounded bg-slate-800 hover:bg-slate-700"
              >
                Close Inspector
              </button>
            </div>

            {/* Blocking reasons */}
            {selectedFeedGate.blocking_reasons.length > 0 && (
              <div className="p-3 bg-rose-950/40 border border-rose-900/60 rounded-lg text-rose-300 text-xs space-y-1">
                <span className="font-bold block text-rose-200 uppercase tracking-wider text-[11px]">
                  Execution Blocking Violations (HTTP 412)
                </span>
                <ul className="list-disc list-inside space-y-0.5">
                  {selectedFeedGate.blocking_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Warnings */}
            {selectedFeedGate.warnings.length > 0 && (
              <div className="p-3 bg-amber-950/40 border border-amber-900/60 rounded-lg text-amber-300 text-xs space-y-1">
                <span className="font-bold block text-amber-200 uppercase tracking-wider text-[11px]">
                  Soft Dependency Warnings (Non-Blocking)
                </span>
                <ul className="list-disc list-inside space-y-0.5">
                  {selectedFeedGate.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Items table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-800/60 uppercase text-[10px] text-slate-400">
                  <tr>
                    <th className="p-2.5">Upstream Feed</th>
                    <th className="p-2.5">Type</th>
                    <th className="p-2.5">Latest Batch Status</th>
                    <th className="p-2.5">Quarantine Rate</th>
                    <th className="p-2.5">Reconciliation</th>
                    <th className="p-2.5">REJECT_FILE</th>
                    <th className="p-2.5">Lag (hrs)</th>
                    <th className="p-2.5">Gate Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {selectedFeedGate.dependencies_evaluated.map((item) => (
                    <tr key={item.dependency_id} className="hover:bg-slate-800/40">
                      <td className="p-2.5 font-medium text-white">{item.upstream_feed_name}</td>
                      <td className="p-2.5">
                        <span
                          className={`px-1.5 py-0.5 rounded font-bold uppercase text-[10px] ${
                            item.dependency_type === 'HARD'
                              ? 'bg-rose-950 text-rose-400 border border-rose-800'
                              : 'bg-amber-950 text-amber-400 border border-amber-800'
                          }`}
                        >
                          {item.dependency_type}
                        </span>
                      </td>
                      <td className="p-2.5 font-mono">{item.latest_batch_status || 'NO_BATCH'}</td>
                      <td className="p-2.5">
                        {item.quarantine_rate_pct !== undefined ? `${item.quarantine_rate_pct}%` : 'N/A'}
                      </td>
                      <td className="p-2.5">
                        {item.reconciliation_balanced === undefined
                          ? 'N/A'
                          : item.reconciliation_balanced
                          ? 'BALANCED'
                          : 'UNBALANCED'}
                      </td>
                      <td className="p-2.5">
                        {item.has_reject_file_severity ? (
                          <span className="text-rose-400 font-bold">YES</span>
                        ) : (
                          <span className="text-slate-500">None</span>
                        )}
                      </td>
                      <td className="p-2.5 font-mono">{item.lag_hours !== undefined ? item.lag_hours : 'N/A'}</td>
                      <td className="p-2.5">
                        {item.is_satisfied ? (
                          <span className="text-emerald-400 font-semibold">Satisfied</span>
                        ) : item.dependency_type === 'HARD' ? (
                          <span className="text-rose-400 font-semibold">Blocked</span>
                        ) : (
                          <span className="text-amber-400 font-semibold">Warning</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 2: Dependency Matrix & Rules Table */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-white">Dependency Governance Matrix</h2>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-800/80 text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-3.5">Downstream Feed</th>
                    <th className="p-3.5">Upstream Feed</th>
                    <th className="p-3.5">Type</th>
                    <th className="p-3.5">Max Lag SLA</th>
                    <th className="p-3.5">Gate Protection Policies</th>
                    <th className="p-3.5">Active</th>
                    <th className="p-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {!dag || dag.edges.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="p-6 text-center text-slate-500 text-xs">
                        No dependencies configured yet. Click &quot;Add Dependency&quot; above to create one.
                      </td>
                    </tr>
                  ) : (
                    dag.edges.map((edge) => (
                      <tr key={edge.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3.5 font-semibold text-white">
                          {feedMap.get(edge.target_feed_id) || edge.target_feed_id}
                        </td>
                        <td className="p-3.5 font-medium text-indigo-300">
                          {feedMap.get(edge.source_feed_id) || edge.source_feed_id}
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${
                              edge.dependency_type === 'HARD'
                                ? 'bg-rose-950 text-rose-400 border border-rose-800'
                                : 'bg-amber-950 text-amber-400 border border-amber-800'
                            }`}
                          >
                            {edge.dependency_type}
                          </span>
                        </td>
                        <td className="p-3.5 font-mono text-xs">{edge.max_lag_hours ? `${edge.max_lag_hours}h` : 'None'}</td>
                        <td className="p-3.5 text-xs text-slate-400 space-x-1">
                          <span className="px-1.5 py-0.5 bg-slate-800 rounded border border-slate-700">Failure Block</span>
                          <span className="px-1.5 py-0.5 bg-slate-800 rounded border border-slate-700">REJECT_FILE</span>
                          <span className="px-1.5 py-0.5 bg-slate-800 rounded border border-slate-700">Recon Balance</span>
                          <span className="px-1.5 py-0.5 bg-slate-800 rounded border border-slate-700">Quarantine ≤5%</span>
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`inline-block w-2 h-2 rounded-full ${
                              edge.is_active ? 'bg-emerald-400' : 'bg-slate-600'
                            }`}
                          />
                        </td>
                        <td className="p-3.5 text-right">
                          {isEngineer ? (
                            <button
                              onClick={() => handleDeleteDependency(edge.id)}
                              className="text-slate-400 hover:text-rose-400 transition-colors p-1.5 rounded hover:bg-slate-800"
                              title="Delete dependency edge"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          ) : (
                            <span className="text-xs text-slate-600">Locked</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Section 3: Authoritative Feed Schedules */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-white">Authoritative Feed Schedules & State Machine</h2>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-800/80 text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-3.5">Feed Name</th>
                    <th className="p-3.5">Cron Expression</th>
                    <th className="p-3.5">Timezone</th>
                    <th className="p-3.5">Schedule Status</th>
                    <th className="p-3.5">Next Run At</th>
                    <th className="p-3.5 text-right">Controls</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {feeds.map((feed) => {
                    const sched = schedules[feed.id];
                    const status = sched?.status || 'ACTIVE';
                    const expr = sched?.schedule_expression || feed.schedule_expression || '0 0 * * *';
                    const tz = sched?.timezone || 'UTC';

                    return (
                      <tr key={feed.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3.5 font-medium text-white">{feed.name}</td>
                        <td className="p-3.5 font-mono text-xs text-indigo-300">{expr}</td>
                        <td className="p-3.5 font-mono text-xs text-slate-400">{tz}</td>
                        <td className="p-3.5">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${
                              status === 'ACTIVE'
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                : status === 'PAUSED'
                                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                                : 'bg-rose-950 text-rose-400 border border-rose-800'
                            }`}
                          >
                            {status}
                          </span>
                        </td>
                        <td className="p-3.5 font-mono text-xs text-slate-400">
                          {sched?.next_run_at ? new Date(sched.next_run_at).toLocaleString() : 'Not calculated'}
                        </td>
                        <td className="p-3.5 text-right space-x-1">
                          {isEngineer ? (
                            <>
                              <button
                                onClick={() => handleOpenEditSchedule(feed)}
                                className="p-1.5 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors"
                                title="Edit schedule cron syntax"
                              >
                                <Edit2 className="h-4 w-4" />
                              </button>

                              {status === 'ACTIVE' ? (
                                <button
                                  onClick={() => handleScheduleAction(feed.id, 'pause')}
                                  className="p-1.5 text-amber-400 hover:text-amber-300 rounded hover:bg-slate-800 transition-colors"
                                  title="Pause schedule"
                                >
                                  <Pause className="h-4 w-4" />
                                </button>
                              ) : status === 'PAUSED' ? (
                                <button
                                  onClick={() => handleScheduleAction(feed.id, 'resume')}
                                  className="p-1.5 text-emerald-400 hover:text-emerald-300 rounded hover:bg-slate-800 transition-colors"
                                  title="Resume schedule"
                                >
                                  <Play className="h-4 w-4" />
                                </button>
                              ) : null}

                              {status !== 'DISABLED' ? (
                                <button
                                  onClick={() => handleScheduleAction(feed.id, 'disable')}
                                  className="p-1.5 text-rose-400 hover:text-rose-300 rounded hover:bg-slate-800 transition-colors"
                                  title="Disable schedule"
                                >
                                  <Power className="h-4 w-4" />
                                </button>
                              ) : (
                                <button
                                  onClick={() => handleScheduleAction(feed.id, 'enable')}
                                  className="p-1.5 text-emerald-400 hover:text-emerald-300 rounded hover:bg-slate-800 transition-colors"
                                  title="Enable schedule"
                                >
                                  <Power className="h-4 w-4" />
                                </button>
                              )}
                            </>
                          ) : (
                            <span className="text-xs text-slate-600">Read-Only</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </main>

      {/* Add Dependency Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Network className="h-5 w-5 text-indigo-400" />
                Add Dependency Edge
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {addError && (
              <div className="p-3 bg-rose-950/70 border border-rose-800 rounded-lg text-rose-300 text-xs space-y-1">
                <div className="flex items-center gap-1.5 font-bold text-rose-200">
                  <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
                  <span>Validation or Cycle Detection Error</span>
                </div>
                <p>{addError}</p>
              </div>
            )}

            <form onSubmit={handleAddDependency} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Downstream Feed (Waiting for upstream)
                </label>
                <select
                  value={addForm.downstream_feed_id}
                  onChange={(e) => setAddForm({ ...addForm, downstream_feed_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white focus:ring-1 focus:ring-indigo-500"
                  required
                >
                  <option value="">Select downstream feed...</option>
                  {feeds.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.domain})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Upstream Feed (Must complete cleanly)
                </label>
                <select
                  value={addForm.upstream_feed_id}
                  onChange={(e) => setAddForm({ ...addForm, upstream_feed_id: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white focus:ring-1 focus:ring-indigo-500"
                  required
                >
                  <option value="">Select upstream feed...</option>
                  {feeds
                    .filter((f) => f.id !== addForm.downstream_feed_id)
                    .map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name} ({f.domain})
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Dependency Enforcement Type</label>
                <div className="grid grid-cols-2 gap-3">
                  <label
                    className={`p-3 rounded-lg border cursor-pointer flex flex-col gap-1 ${
                      addForm.dependency_type === 'HARD'
                        ? 'border-indigo-500 bg-indigo-950/30'
                        : 'border-slate-800 bg-slate-950'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="dependency_type"
                        value="HARD"
                        checked={addForm.dependency_type === 'HARD'}
                        onChange={() => setAddForm({ ...addForm, dependency_type: 'HARD' })}
                      />
                      <span className="font-bold text-white">HARD Gate</span>
                    </div>
                    <span className="text-[11px] text-slate-400">Strictly blocks downstream execution (HTTP 412)</span>
                  </label>

                  <label
                    className={`p-3 rounded-lg border cursor-pointer flex flex-col gap-1 ${
                      addForm.dependency_type === 'SOFT'
                        ? 'border-indigo-500 bg-indigo-950/30'
                        : 'border-slate-800 bg-slate-950'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="dependency_type"
                        value="SOFT"
                        checked={addForm.dependency_type === 'SOFT'}
                        onChange={() => setAddForm({ ...addForm, dependency_type: 'SOFT' })}
                      />
                      <span className="font-bold text-white">SOFT Gate</span>
                    </div>
                    <span className="text-[11px] text-slate-400">Emits warnings, allows downstream execution</span>
                  </label>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Max Upstream Lag (Hours)</label>
                  <input
                    type="number"
                    min="1"
                    max="720"
                    value={addForm.max_lag_hours}
                    onChange={(e) => setAddForm({ ...addForm, max_lag_hours: parseInt(e.target.value) || 24 })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Max Quarantine Rate (%)</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={addForm.max_quarantine_rate_pct}
                    onChange={(e) => setAddForm({ ...addForm, max_quarantine_rate_pct: parseFloat(e.target.value) || 5.0 })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white"
                  />
                </div>
              </div>

              <div className="space-y-2 pt-2 border-t border-slate-800">
                <span className="font-semibold text-slate-300 block">Protection Gates</span>
                <label className="flex items-center gap-2 text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={addForm.block_on_upstream_failure}
                    onChange={(e) => setAddForm({ ...addForm, block_on_upstream_failure: e.target.checked })}
                  />
                  <span>Block if latest upstream batch failed or still in progress</span>
                </label>
                <label className="flex items-center gap-2 text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={addForm.block_on_reject_file}
                    onChange={(e) => setAddForm({ ...addForm, block_on_reject_file: e.target.checked })}
                  />
                  <span>Block on upstream REJECT_FILE DQ violations</span>
                </label>
                <label className="flex items-center gap-2 text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={addForm.block_on_unbalanced_reconciliation}
                    onChange={(e) => setAddForm({ ...addForm, block_on_unbalanced_reconciliation: e.target.checked })}
                  />
                  <span>Block if upstream reconciliation is unbalanced</span>
                </label>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addSubmitting}
                  className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50"
                >
                  {addSubmitting ? 'Saving...' : 'Add Dependency'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Schedule Modal */}
      {showScheduleModal && editingFeed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Clock className="h-5 w-5 text-indigo-400" />
                Edit Schedule: {editingFeed.name}
              </h3>
              <button
                onClick={() => setShowScheduleModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {scheduleError && (
              <div className="p-3 bg-rose-950/70 border border-rose-800 rounded-lg text-rose-300 text-xs">
                {scheduleError}
              </div>
            )}

            <form onSubmit={handleSaveSchedule} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Cron Expression (5-part: min hour day month weekday)
                </label>
                <input
                  type="text"
                  value={cronInput}
                  onChange={(e) => setCronInput(e.target.value)}
                  placeholder="0 0 * * *"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white font-mono"
                  required
                />
                <span className="text-[11px] text-slate-500 mt-1 block">
                  Example: 0 0 * * * (Daily at midnight UTC) or */15 * * * * (Every 15 min)
                </span>
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Timezone</label>
                <input
                  type="text"
                  value={timezoneInput}
                  onChange={(e) => setTimezoneInput(e.target.value)}
                  placeholder="UTC"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-white font-mono"
                  required
                />
                <span className="text-[11px] text-slate-500 mt-1 block">
                  IANA standard timezone (e.g. UTC, America/New_York)
                </span>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowScheduleModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={scheduleSubmitting}
                  className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50"
                >
                  {scheduleSubmitting ? 'Saving...' : 'Update Schedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

'use client';
import React, { useState } from 'react';
import Link from 'next/link';
import { Clock, Filter, ArrowUpRight, CheckCircle2, AlertCircle, HelpCircle, PauseCircle, FileQuestion } from 'lucide-react';

export interface OpsArrivalSlotItem {
  slot_id: string;
  feed_id: string;
  feed_name: string;
  domain: string;
  timezone: string;
  cron_expression: string;
  expected_at_utc: string;
  expected_at_local: string;
  sla_deadline_utc: string;
  sla_deadline_local: string;
  actual_arrival_at_utc: string | null;
  status: 'EXPECTED' | 'ON_TIME' | 'LATE' | 'MISSED_SLA' | 'PAUSED' | 'UNSCHEDULED_ARRIVAL';
  delay_minutes: number;
  input_registry_id: string | null;
  filename: string | null;
  file_fingerprint_preview: string | null;
  batch_id: string | null;
  batch_status: string | null;
}

interface FileArrivalBoardProps {
  slots: OpsArrivalSlotItem[];
  loading: boolean;
  horizonHours: number;
  onHorizonChange: (hours: number) => void;
  selectedFeedId: string;
  onFeedChange: (feedId: string) => void;
  feeds: { id: string; name: string }[];
}

export default function FileArrivalBoard({
  slots,
  loading,
  horizonHours,
  onHorizonChange,
  selectedFeedId,
  onFeedChange,
  feeds,
}: FileArrivalBoardProps) {
  const [useLocalTime, setUseLocalTime] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  const filteredSlots = slots.filter((slot) => {
    if (statusFilter !== 'ALL' && slot.status !== statusFilter) return false;
    return true;
  });

  const getStatusBadge = (status: OpsArrivalSlotItem['status'], delayMins: number) => {
    switch (status) {
      case 'ON_TIME':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            ON TIME
          </span>
        );
      case 'LATE':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <AlertCircle className="w-3.5 h-3.5" />
            LATE (+{delayMins}m)
          </span>
        );
      case 'MISSED_SLA':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
            <AlertCircle className="w-3.5 h-3.5" />
            MISSED SLA (+{delayMins}m)
          </span>
        );
      case 'EXPECTED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
            <Clock className="w-3.5 h-3.5" />
            EXPECTED
          </span>
        );
      case 'PAUSED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/30">
            <PauseCircle className="w-3.5 h-3.5" />
            PAUSED
          </span>
        );
      case 'UNSCHEDULED_ARRIVAL':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/30">
            <FileQuestion className="w-3.5 h-3.5" />
            UNSCHEDULED
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400">
            <HelpCircle className="w-3.5 h-3.5" />
            {status}
          </span>
        );
    }
  };

  const formatTime = (utcIso: string | null, localStr: string) => {
    if (!utcIso) return '—';
    if (!useLocalTime) {
      const d = new Date(utcIso);
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    }
    return localStr || new Date(utcIso).toLocaleString();
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden mb-8" data-testid="file-arrival-board">
      {/* Header Controls */}
      <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4 bg-slate-950/40">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">File-Arrival Board</h2>
          <span className="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">
            {filteredSlots.length} Slots
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Feed Filter */}
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Filter className="w-3.5 h-3.5" />
            <select
              value={selectedFeedId}
              onChange={(e) => onFeedChange(e.target.value)}
              className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All Feeds</option>
              {feeds.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="ALL">All Statuses</option>
            <option value="EXPECTED">EXPECTED</option>
            <option value="ON_TIME">ON TIME</option>
            <option value="LATE">LATE</option>
            <option value="MISSED_SLA">MISSED SLA</option>
            <option value="PAUSED">PAUSED</option>
            <option value="UNSCHEDULED_ARRIVAL">UNSCHEDULED</option>
          </select>

          {/* Horizon Selection */}
          <div className="flex items-center bg-slate-800 rounded p-0.5 border border-slate-700 text-xs">
            {[6, 12, 24, 48].map((h) => (
              <button
                key={h}
                onClick={() => onHorizonChange(h)}
                className={`px-2 py-0.5 rounded font-medium transition-colors ${
                  horizonHours === h ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                {h}h
              </button>
            ))}
          </div>

          {/* Timezone Toggle */}
          <button
            onClick={() => setUseLocalTime(!useLocalTime)}
            className="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 px-2.5 py-1 rounded text-xs font-medium transition-colors"
          >
            {useLocalTime ? 'Feed Timezone' : 'UTC Time'}
          </button>
        </div>
      </div>

      {/* Slots Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950/60 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4 font-semibold">Feed / Domain</th>
              <th className="py-3 px-4 font-semibold">Expected Arrival</th>
              <th className="py-3 px-4 font-semibold">SLA Deadline</th>
              <th className="py-3 px-4 font-semibold">Actual Arrival</th>
              <th className="py-3 px-4 font-semibold">SLA Status</th>
              <th className="py-3 px-4 font-semibold">Matched File</th>
              <th className="py-3 px-4 font-semibold">Linked Batch</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {loading ? (
              [...Array(4)].map((_, i) => (
                <tr key={i} className="animate-pulse">
                  <td colSpan={7} className="py-4 px-4 h-12 bg-slate-900/40" />
                </tr>
              ))
            ) : filteredSlots.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-500">
                  No scheduled arrival slots detected in the selected {horizonHours}-hour window.
                </td>
              </tr>
            ) : (
              filteredSlots.map((slot) => (
                <tr key={slot.slot_id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-medium text-white">{slot.feed_name}</div>
                    <div className="text-xs text-slate-500">{slot.domain} • {slot.cron_expression}</div>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    {formatTime(slot.expected_at_utc, slot.expected_at_local)}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-slate-400">
                    {formatTime(slot.sla_deadline_utc, slot.sla_deadline_local)}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    {slot.actual_arrival_at_utc ? (
                      formatTime(slot.actual_arrival_at_utc, new Date(slot.actual_arrival_at_utc).toLocaleString())
                    ) : (
                      <span className="text-slate-500 italic">Pending arrival</span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    {getStatusBadge(slot.status, slot.delay_minutes)}
                  </td>
                  <td className="py-3 px-4 text-xs font-mono">
                    {slot.filename ? (
                      <div>
                        <span className="text-blue-300 font-medium">{slot.filename}</span>
                        {slot.file_fingerprint_preview && (
                          <span className="text-slate-500 ml-1.5">({slot.file_fingerprint_preview}...)</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    {slot.batch_id ? (
                      <Link
                        href={`/batches/${slot.batch_id}`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-blue-400 hover:text-blue-300 bg-blue-500/10 hover:bg-blue-500/20 px-2 py-1 rounded border border-blue-500/30 transition-colors"
                      >
                        <span>{slot.batch_status}</span>
                        <ArrowUpRight className="w-3 h-3" />
                      </Link>
                    ) : (
                      <span className="text-xs text-slate-500">Not queued</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

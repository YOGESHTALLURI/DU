'use client';

import React from 'react';
import { Tag, ShieldAlert, GitCommit, AlertTriangle } from 'lucide-react';

interface FailureFingerprintBadgeProps {
  category: string;
  fingerprintHash: string;
  totalOccurrences?: number;
  className?: string;
  showOccurrences?: boolean;
}

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  SCHEMA_DRIFT: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  DATA_QUALITY: { bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200' },
  STAGE_EXECUTION: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  RECONCILIATION: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  DEPENDENCY_GATE: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  NETWORK_STORAGE: { bg: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-200' },
  SYSTEM_TIMEOUT: { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
};

export const FailureFingerprintBadge: React.FC<FailureFingerprintBadgeProps> = ({
  category,
  fingerprintHash,
  totalOccurrences,
  className = '',
  showOccurrences = true,
}) => {
  const shortHash = fingerprintHash ? fingerprintHash.substring(0, 8) : 'unknown';
  const colors = CATEGORY_COLORS[category] || {
    bg: 'bg-gray-50',
    text: 'text-gray-700',
    border: 'border-gray-200',
  };

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono font-medium border ${colors.bg} ${colors.text} ${colors.border} ${className}`}
      title={`Fingerprint SHA-256: ${fingerprintHash}\nCategory: ${category}`}
    >
      <Tag className="w-3 h-3 flex-shrink-0" />
      <span>{category}</span>
      <span className="opacity-40">/</span>
      <span className="font-semibold">{shortHash}</span>
      {showOccurrences && totalOccurrences !== undefined && totalOccurrences > 1 && (
        <span
          className="ml-1 px-1.5 py-0.2 rounded-full bg-white/80 font-sans text-[10px] font-bold border"
          title={`${totalOccurrences} total system-wide occurrences of this failure fingerprint`}
        >
          {totalOccurrences}×
        </span>
      )}
    </div>
  );
};

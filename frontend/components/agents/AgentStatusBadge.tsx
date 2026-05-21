'use client';

import { AgentStatus } from '@/lib/types';

const STATUS_CONFIG: Record<AgentStatus, { dot: string; text: string; label: string }> = {
  ACTIVE:  { dot: 'bg-emerald-400 animate-pulse', text: 'text-emerald-400', label: 'ACTIVE' },
  WAITING: { dot: 'bg-gray-500',                  text: 'text-gray-500',    label: 'WAITING' },
  STOPPED: { dot: 'bg-red-500',                   text: 'text-red-400',     label: 'STOPPED' },
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.WAITING;
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      <span className={`text-xs font-bold tracking-widest ${cfg.text}`}>{cfg.label}</span>
    </div>
  );
}

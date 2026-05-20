'use client';

import { AgentState } from '@/lib/types';

const STATUS_CONFIG = {
  THINKING: {
    dot: 'bg-yellow-400 animate-pulse',
    text: 'text-yellow-400',
    label: 'THINKING',
  },
  EXECUTING: {
    dot: 'bg-emerald-400 animate-ping',
    text: 'text-emerald-400',
    label: 'EXECUTING',
  },
  IDLE: {
    dot: 'bg-gray-500',
    text: 'text-gray-500',
    label: 'IDLE',
  },
};

export function AgentStatusBadge({ status }: { status: AgentState['status'] }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      <span className={`text-xs font-bold tracking-widest ${cfg.text}`}>{cfg.label}</span>
    </div>
  );
}

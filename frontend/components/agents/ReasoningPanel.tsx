'use client';

import { useAgentStore } from '@/store/agentStore';

const DECISION_COLORS: Record<string, string> = {
  BUY:  'text-emerald-400',
  SELL: 'text-red-400',
  HOLD: 'text-gray-500',
};

export function ReasoningPanel({ agentId }: { agentId: string }) {
  const history = useAgentStore((s) => s.decisionHistory[agentId] || []);

  if (history.length === 0) {
    return (
      <div className="flex items-center justify-center h-10">
        <p className="text-xs text-gray-700">Waiting for first on-chain decision…</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 max-h-28 overflow-y-auto pr-1">
      {history.slice(0, 6).map((entry, i) => {
        const decision = entry.split(' ')[0];
        const color = DECISION_COLORS[decision] ?? 'text-gray-400';
        return (
          <p
            key={i}
            className={`text-xs font-mono ${i === 0 ? color : 'text-gray-600'}`}
          >
            {i === 0 ? <span className="animate-[fadeIn_0.3s_ease-in]">{entry}</span> : entry}
          </p>
        );
      })}
    </div>
  );
}

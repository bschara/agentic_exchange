'use client';

import { useAgentStore } from '@/store/agentStore';

const DECISION_COLORS: Record<string, string> = {
  BUY:  'text-emerald-400',
  SELL: 'text-red-400',
  HOLD: 'text-gray-500',
};

export function ReasoningPanel({ agentId }: { agentId: string }) {
  const history = useAgentStore((s) => s.decisionHistory[agentId] || []);
  const context = useAgentStore((s) => s.agents[agentId]?.last_context ?? '');

  if (history.length === 0 && !context) {
    return (
      <div className="flex items-center justify-center h-10">
        <p className="text-xs text-gray-700">Waiting for first on-chain decision…</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto pr-1">
      {/* Live LLM prompt — what Somnia validators actually received */}
      {context && (
        <p
          className="text-[10px] font-mono text-gray-500 leading-tight bg-white/5 rounded px-1.5 py-1 animate-[fadeIn_0.3s_ease-in]"
          title="Full LLM prompt sent to Somnia validators"
        >
          {context}
        </p>
      )}
      {history.slice(0, 5).map((entry, i) => {
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

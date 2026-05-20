'use client';

import { useAgentStore } from '@/store/agentStore';

export function ReasoningPanel({ agentId }: { agentId: string }) {
  const history = useAgentStore((s) => s.reasoningHistory[agentId] || []);

  return (
    <div className="flex flex-col gap-1.5 max-h-28 overflow-y-auto pr-1">
      {history.slice(0, 4).map((text, i) => (
        <p
          key={i}
          className={`text-xs leading-relaxed ${
            i === 0 ? 'text-gray-200' : 'text-gray-600'
          }`}
        >
          {i === 0 ? (
            <span className="animate-[fadeIn_0.3s_ease-in]">{text}</span>
          ) : (
            text
          )}
        </p>
      ))}
    </div>
  );
}

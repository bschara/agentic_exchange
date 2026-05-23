'use client';

import { useMemo, useRef } from 'react';
import { useAgentStore } from '@/store/agentStore';

const ETH_LATENCY_MS = 12000;
const SOL_LATENCY_MS = 400;

export function LatencyHero() {
  const agents = useAgentStore((s) => s.agents);
  const recentFills = useAgentStore((s) => s.recentFills);
  const somniaBlockMs = useAgentStore((s) => s.somniaBlockMs);

  const fillCount = recentFills.length;
  const fillKey = useRef(0);
  const prevFillCount = useRef(fillCount);
  if (fillCount !== prevFillCount.current) {
    fillKey.current++;
    prevFillCount.current = fillCount;
  }

  const avgLatencyMs = useMemo(() => {
    const agentList = Object.values(agents).filter((a) => a.decision_latency_count > 0);
    if (agentList.length === 0) return somniaBlockMs || 400;
    const sum = agentList.reduce((acc, a) => acc + a.avg_decision_latency_ms, 0);
    return Math.round(sum / agentList.length);
  }, [agents, somniaBlockMs]);

  const somniaWidth = Math.min(100, Math.round((avgLatencyMs / ETH_LATENCY_MS) * 100));
  const solWidth = Math.round((SOL_LATENCY_MS / ETH_LATENCY_MS) * 100);

  const lastFill = recentFills[0];

  return (
    <div className="border-b border-white/10 bg-gradient-to-r from-black/80 to-black/60 px-6 py-2.5 flex items-center gap-8">
      {/* Hero latency number */}
      <div className="flex flex-col items-center min-w-[110px]">
        <span
          key={fillKey.current}
          className="text-3xl font-mono font-black text-emerald-400 tabular-nums animate-pulse"
        >
          {avgLatencyMs > 0 ? `${avgLatencyMs}ms` : '—'}
        </span>
        <span className="text-[9px] text-gray-600 uppercase tracking-widest mt-0.5">
          Somnia Settlement
        </span>
      </div>

      {/* Comparison bars */}
      <div className="flex-1 flex flex-col gap-1.5 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-500 w-16 text-right flex-none">Somnia</span>
          <div className="flex-1 bg-white/5 rounded-full h-2 overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-700"
              style={{ width: `${somniaWidth}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-emerald-400 w-14 flex-none">
            {avgLatencyMs > 0 ? `${avgLatencyMs}ms` : '—'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-600 w-16 text-right flex-none">Solana</span>
          <div className="flex-1 bg-white/5 rounded-full h-2 overflow-hidden">
            <div
              className="h-full bg-gray-600 rounded-full"
              style={{ width: `${solWidth}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-gray-600 w-14 flex-none">~400ms</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-600 w-16 text-right flex-none">Ethereum</span>
          <div className="flex-1 bg-white/5 rounded-full h-2 overflow-hidden">
            <div className="h-full bg-gray-700 rounded-full" style={{ width: '100%' }} />
          </div>
          <span className="text-[10px] font-mono text-gray-600 w-14 flex-none">~12,000ms</span>
        </div>
      </div>

      {/* Last trade flash */}
      {lastFill && (
        <div className="flex flex-col items-end min-w-[120px] text-right">
          <span className="text-[9px] text-gray-600 uppercase tracking-wider">Last Trade</span>
          <span className="text-sm font-mono font-bold text-white">
            ${lastFill.price.toFixed(2)}
          </span>
          <span className="text-[10px] text-gray-600 font-mono">
            {lastFill.buyer_agent !== 'external' ? lastFill.buyer_agent.replace('_', ' ') : ''}{' '}
            vs{' '}
            {lastFill.seller_agent !== 'external' ? lastFill.seller_agent.replace('_', ' ') : ''}
          </span>
        </div>
      )}

      {/* Somnia branding pill */}
      <div className="flex-none hidden lg:flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/5">
        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">
          Somnia Network
        </span>
      </div>
    </div>
  );
}

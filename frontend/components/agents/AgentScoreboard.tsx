'use client';

import { useAgentStore } from '@/store/agentStore';
import { AgentState } from '@/lib/types';

const AGENT_ICONS: Record<string, string> = {
  market_maker:    '⚖️',
  momentum_trader: '📈',
  arbitrage_agent: '🔍',
  risk_manager:    '🛡️',
  noise_trader:    '🎲',
};

const MEDALS = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟'];

function pnlColor(pnl: number): string {
  if (pnl > 0) return 'text-emerald-400';
  if (pnl < 0) return 'text-red-400';
  return 'text-gray-500';
}

function pnlBg(pnl: number): string {
  if (pnl > 0.5) return 'border-emerald-500/20 bg-emerald-500/5';
  if (pnl < -0.5) return 'border-red-500/20 bg-red-500/5';
  return 'border-white/5';
}

function fmtBalance(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}

function fmt(n: number): string {
  const abs = Math.abs(n);
  const sign = n >= 0 ? '+' : '-';
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function AgentScoreboard() {
  const agents = useAgentStore((s) => s.agents);

  const ranked: AgentState[] = Object.values(agents).sort(
    (a, b) =>
      ((b.trade_pnl ?? 0) + (b.unrealized_pnl ?? 0)) -
      ((a.trade_pnl ?? 0) + (a.unrealized_pnl ?? 0))
  );

  const hasData = ranked.some((a) => a.decisions_total > 0);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Agent War — P&amp;L Scoreboard
        </span>
        {!hasData && (
          <span className="text-xs text-gray-700 italic">waiting for first trades…</span>
        )}
      </div>

      {ranked.map((agent, idx) => {
        const realizedPnl   = agent.trade_pnl ?? 0;
        const unrealizedPnl = agent.unrealized_pnl ?? 0;
        const pnl           = realizedPnl + unrealizedPnl;
        const buyVol        = agent.total_buy_volume ?? 0;
        const sellVol       = agent.total_sell_volume ?? 0;
        const latency       = agent.avg_decision_latency_ms ?? 0;
        const quoteBalance  = agent.quote_balance ?? 0;
        const hasTrades     = buyVol + sellVol > 0;
        const hasPnl        = Math.abs(realizedPnl) > 0.01 || Math.abs(unrealizedPnl) > 0.01;

        return (
          <div
            key={agent.agent_id}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all duration-300 ${pnlBg(pnl)}`}
          >
            {/* Rank */}
            <span className="text-base w-5 text-center flex-none">{MEDALS[idx] ?? `${idx + 1}.`}</span>

            {/* Agent identity */}
            <span className="text-base flex-none">{AGENT_ICONS[agent.agent_id] ?? '🤖'}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-bold text-white truncate">{agent.agent_name}</div>
              {hasTrades ? (
                <div className="text-[10px] text-gray-600 font-mono">
                  ↑${sellVol.toFixed(0)} ↓${buyVol.toFixed(0)}
                </div>
              ) : (
                <div className="text-[10px] text-gray-700">no fills yet</div>
              )}
              {quoteBalance > 0 && (
                <div className="text-[10px] text-gray-600 font-mono">
                  💰 ${fmtBalance(quoteBalance)}
                </div>
              )}
            </div>

            {/* P&L */}
            <div className="text-right flex-none">
              <div className={`text-sm font-mono font-bold ${pnlColor(pnl)}`}>
                {fmt(pnl)}
              </div>
              {hasPnl && (
                <div className="text-[10px] font-mono text-gray-500">
                  <span className={pnlColor(realizedPnl)}>R {fmt(realizedPnl)}</span>
                  {' / '}
                  <span className={pnlColor(unrealizedPnl)}>U {fmt(unrealizedPnl)}</span>
                </div>
              )}
              {latency > 0 && (
                <div className="text-[10px] text-gray-600 font-mono">
                  ~{latency.toFixed(0)}ms
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

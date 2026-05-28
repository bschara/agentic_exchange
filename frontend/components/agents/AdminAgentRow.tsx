'use client';

import { useState } from 'react';
import { PauseCircle, PlayCircle, Coins } from 'lucide-react';
import { AgentState, AgentStatus } from '@/lib/types';
import { AgentStatusBadge } from './AgentStatusBadge';

const SYSTEM_ICONS: Record<string, string> = {
  market_maker:    '⚖️',
  momentum_trader: '📈',
  arbitrage_agent: '🔍',
  risk_manager:    '🛡️',
  noise_trader:    '🎲',
};

function agentStatus(state?: AgentState): AgentStatus {
  if (!state) return 'WAITING';
  if (state.loop_stopped) return 'STOPPED';
  if (state.decisions_total > 0 || state.orders_placed > 0) return 'ACTIVE';
  return 'WAITING';
}

interface Props {
  agentId:     string;
  agentState?: AgentState;
  isUserAgent: boolean;
  ownerAddress?: string;
  icon?: string;
  riskLevel?: number;
  onPause:  () => Promise<{ ok: boolean; error?: string }>;
  onResume: () => Promise<{ ok: boolean; error?: string }>;
  onFund:   (amount: number) => Promise<{ ok: boolean; error?: string }>;
}

export function AdminAgentRow({
  agentId, agentState, isUserAgent, ownerAddress, icon, riskLevel,
  onPause, onResume, onFund,
}: Props) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [fundAmount, setFundAmount]       = useState('100');
  const [showFund, setShowFund]           = useState(false);
  const [feedback, setFeedback]           = useState<string | null>(null);

  const status   = agentStatus(agentState);
  const isPaused = agentState?.loop_stopped && agentState?.loop_stopped_reason === 'paused';
  const displayIcon = icon ?? SYSTEM_ICONS[agentId] ?? '🤖';
  const displayName = agentState?.agent_name ?? agentId;

  const handle = async (action: string, fn: () => Promise<{ ok: boolean; error?: string }>) => {
    if (actionLoading) return;
    setActionLoading(action);
    setFeedback(null);
    const res = await fn();
    if (!res.ok) setFeedback(res.error?.slice(0, 60) ?? 'Error');
    else setFeedback(null);
    setActionLoading(null);
  };

  return (
    <div className="flex items-center gap-2 px-2 py-2 rounded-lg bg-white/3 hover:bg-white/5 transition-all">
      {/* Icon + name */}
      <span className="text-base w-6 text-center flex-none">{displayIcon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-bold text-white truncate">{displayName}</div>
        {isUserAgent && ownerAddress && (
          <div className="text-[10px] text-gray-700 font-mono truncate">
            {ownerAddress.slice(0, 8)}…{ownerAddress.slice(-4)}
            {riskLevel && (
              <span className={`ml-1.5 ${riskLevel <= 2 ? 'text-emerald-600' : riskLevel >= 4 ? 'text-orange-600' : 'text-blue-600'}`}>
                risk {riskLevel}/5
              </span>
            )}
          </div>
        )}
      </div>

      {/* Status */}
      <AgentStatusBadge status={status} />

      {/* Controls */}
      <div className="flex items-center gap-1 flex-none">
        {isPaused ? (
          <button
            onClick={() => handle('resume', onResume)}
            disabled={!!actionLoading}
            title="Resume"
            className="px-2 py-1 text-[10px] font-bold border border-emerald-500/40 text-emerald-400 rounded bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 transition-all"
          >
            {actionLoading === 'resume' ? '…' : <PlayCircle className="w-3 h-3" />}
          </button>
        ) : (
          <button
            onClick={() => handle('pause', onPause)}
            disabled={!!actionLoading || agentId === 'noise_trader'}
            title={agentId === 'noise_trader' ? 'Python-only agent' : 'Pause'}
            className="px-2 py-1 text-[10px] font-bold border border-orange-500/40 text-orange-400 rounded bg-orange-500/10 hover:bg-orange-500/20 disabled:opacity-40 transition-all"
          >
            {actionLoading === 'pause' ? '…' : <PauseCircle className="w-3 h-3" />}
          </button>
        )}

        <button
          onClick={() => setShowFund((v) => !v)}
          title="Fund (mint AGT)"
          className="px-2 py-1 text-[10px] font-bold border border-blue-500/40 text-blue-400 rounded bg-blue-500/10 hover:bg-blue-500/20 transition-all"
        >
          <Coins className="w-3 h-3" />
        </button>
      </div>

      {/* Inline fund input */}
      {showFund && (
        <div className="flex items-center gap-1 flex-none">
          <input
            type="number"
            min="1"
            value={fundAmount}
            onChange={(e) => setFundAmount(e.target.value)}
            className="w-14 px-1.5 py-1 text-[10px] font-mono bg-black/40 border border-white/10 rounded text-white text-center"
          />
          <button
            onClick={() => handle('fund', () => onFund(parseFloat(fundAmount) || 100)).then(() => setShowFund(false))}
            disabled={!!actionLoading}
            className="px-2 py-1 text-[10px] font-bold border border-blue-500/40 text-blue-300 rounded bg-blue-500/10 disabled:opacity-40 transition-all"
          >
            {actionLoading === 'fund' ? '…' : 'SEND'}
          </button>
        </div>
      )}

      {feedback && <p className="text-[10px] text-red-400 truncate max-w-[100px]">{feedback}</p>}
    </div>
  );
}

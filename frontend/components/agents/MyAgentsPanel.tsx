'use client';

import { useState } from 'react';
import { Plus, RefreshCw, Zap } from 'lucide-react';
import { useUserAgents } from '@/hooks/useUserAgents';
import { UserAgentCard } from './UserAgentCard';
import { CreateAgentModal } from './CreateAgentModal';

interface Props {
  walletAddress: string;
}

export function MyAgentsPanel({ walletAddress }: Props) {
  const { agents, sttBalance, loading, createAgent, pauseAgent, resumeAgent, fundAgent, refetch, refreshSttBalance } =
    useUserAgents(walletAddress);
  const [showModal, setShowModal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [topping, setTopping] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refetch();
    setRefreshing(false);
  };

  const handleModalClose = () => {
    setShowModal(false);
    // Retry across 30s to cover the backend's 5s event-polling cycle
    [3000, 8000, 15000, 25000].forEach((delay) => setTimeout(refetch, delay));
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Panel header */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            My Agents
          </span>
          <span className="text-[10px] font-mono text-cyan-500/70 bg-cyan-500/10 border border-cyan-500/20 px-1.5 py-0.5 rounded">
            {agents.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            title="Refresh"
            className="p-1 text-gray-600 hover:text-gray-400 disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold border border-cyan-500/40 text-cyan-400 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 transition-all"
          >
            <Plus className="w-3 h-3" />
            CREATE AGENT
          </button>
        </div>
      </div>

      {/* STT Pool banner */}
      {agents.length > 0 && (
        <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-black/30 border border-violet-500/20">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 uppercase tracking-widest">⛽ STT Pool</span>
            <span className={`text-xs font-mono font-bold ${
              sttBalance > 0.5 ? 'text-emerald-400' :
              sttBalance > 0.1 ? 'text-amber-400' : 'text-red-400'
            }`}>
              {sttBalance.toFixed(4)} STT
            </span>
            {sttBalance < 0.1 && (
              <span className="text-[9px] font-bold text-red-400 animate-pulse">⚠ LOW</span>
            )}
          </div>
          <button
            onClick={async () => {
              setTopping(true);
              try { await fundAgent(0.5); } catch { /* handled in hook */ }
              setTopping(false);
            }}
            disabled={topping}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-bold border border-violet-500/40 text-violet-400 rounded bg-violet-500/10 hover:bg-violet-500/20 disabled:opacity-40 transition-all"
          >
            <Zap className="w-3 h-3" />
            {topping ? '...' : '+ 0.5 STT'}
          </button>
        </div>
      )}

      {/* Agent list */}
      {loading && agents.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-xs text-gray-600">
          Loading…
        </div>
      ) : agents.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <span className="text-4xl opacity-30">🤖</span>
          <p className="text-xs text-gray-600">No agents yet.</p>
          <p className="text-[11px] text-gray-700 max-w-[200px]">
            Create your first autonomous trading agent — defined by you, running on-chain.
          </p>
          <button
            onClick={() => setShowModal(true)}
            className="mt-1 flex items-center gap-1.5 px-4 py-2 text-xs font-bold border border-cyan-500/40 text-cyan-400 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 transition-all"
          >
            <Plus className="w-3 h-3" />
            Create My First Agent
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {agents.map((agent) => (
            <UserAgentCard
              key={agent.agent_id}
              agent={agent}
              onPause={() => pauseAgent(agent.agent_id)}
              onResume={() => resumeAgent(agent.agent_id)}
              onFund={fundAgent}
            />
          ))}
        </div>
      )}

      {/* Create modal */}
      {showModal && (
        <CreateAgentModal
          onClose={handleModalClose}
          onCreate={createAgent}
          onFund={fundAgent}
        />
      )}
    </div>
  );
}

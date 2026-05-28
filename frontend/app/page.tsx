'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { Header } from '@/components/layout/Header';
import { LatencyHero } from '@/components/layout/LatencyHero';
import { ActivityFeed } from '@/components/layout/ActivityFeed';
import { OrderBook } from '@/components/chart/OrderBook';
import { RecentTrades } from '@/components/chart/RecentTrades';
import { AgentGrid } from '@/components/agents/AgentGrid';
import { AgentScoreboard } from '@/components/agents/AgentScoreboard';
import { MyAgentsPanel } from '@/components/agents/MyAgentsPanel';
import { AdminPanel } from '@/components/agents/AdminPanel';
import { useUserStore } from '@/store/userStore';
import { isOwnerAddress } from '@/hooks/useAdminActions';

const CandlestickChart = dynamic(
  () => import('@/components/chart/CandlestickChart').then((m) => m.CandlestickChart),
  { ssr: false, loading: () => <div className="w-full h-full bg-[#080808] animate-pulse" /> }
);

type AgentTab = 'system' | 'mine' | 'admin';

export default function Dashboard() {
  const [agentTab, setAgentTab] = useState<AgentTab>('system');
  const walletAddress = useUserStore((s) => s.walletAddress);
  const isAdmin = !!walletAddress && isOwnerAddress(walletAddress);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header />
      <LatencyHero />

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden gap-0">
        {/* Left: Chart + Orderbook + Trades */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-white/10">
          {/* Candlestick chart */}
          <div className="flex-1 min-h-0">
            <CandlestickChart />
          </div>

          {/* Bottom left: Orderbook + Recent Trades */}
          <div className="flex border-t border-white/10 h-64">
            <div className="flex-1 border-r border-white/10 overflow-hidden">
              <OrderBook />
            </div>
            <div className="w-64 overflow-hidden">
              <RecentTrades />
            </div>
          </div>
        </div>

        {/* Right: Agent grid + scoreboard */}
        <div className="w-[480px] xl:w-[560px] flex-none flex flex-col overflow-hidden">
          {/* Tab switcher */}
          <div className="flex gap-1 px-3 pt-3 pb-0 border-b border-white/5">
            <button
              onClick={() => setAgentTab('system')}
              className={`px-3 py-1.5 text-[11px] font-bold rounded-t-lg transition-all ${
                agentTab === 'system'
                  ? 'text-violet-300 border-b-2 border-violet-400 bg-violet-500/10'
                  : 'text-gray-600 hover:text-gray-400'
              }`}
            >
              SYSTEM
            </button>
            <button
              onClick={() => setAgentTab('mine')}
              className={`px-3 py-1.5 text-[11px] font-bold rounded-t-lg transition-all flex items-center gap-1.5 ${
                agentTab === 'mine'
                  ? 'text-cyan-300 border-b-2 border-cyan-400 bg-cyan-500/10'
                  : 'text-gray-600 hover:text-gray-400'
              }`}
            >
              MY AGENTS
              {walletAddress && (
                <span className="text-[9px] px-1 bg-cyan-500/20 text-cyan-500 rounded">
                  {walletAddress.slice(0, 4)}…{walletAddress.slice(-3)}
                </span>
              )}
            </button>
            {isAdmin && (
              <button
                onClick={() => setAgentTab('admin')}
                className={`px-3 py-1.5 text-[11px] font-bold rounded-t-lg transition-all flex items-center gap-1 ${
                  agentTab === 'admin'
                    ? 'text-yellow-300 border-b-2 border-yellow-400 bg-yellow-500/10'
                    : 'text-gray-600 hover:text-gray-400'
                }`}
              >
                ⚡ ADMIN
              </button>
            )}
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-3 pb-2">
            {agentTab === 'system' ? (
              <AgentGrid />
            ) : agentTab === 'admin' && walletAddress ? (
              <AdminPanel walletAddress={walletAddress} />
            ) : walletAddress ? (
              <MyAgentsPanel walletAddress={walletAddress} />
            ) : (
              <div className="flex flex-col items-center justify-center gap-3 h-full text-center">
                <span className="text-4xl opacity-20">🔒</span>
                <p className="text-xs text-gray-600">Connect your wallet to manage agents.</p>
                <p className="text-[11px] text-gray-700 max-w-[200px]">
                  Click CONNECT in the header to get started.
                </p>
              </div>
            )}
          </div>

          {agentTab === 'system' && (
            <div className="flex-none px-3 pb-3 border-t border-white/5 pt-3">
              <AgentScoreboard />
            </div>
          )}
        </div>
      </div>

      {/* Bottom: Activity feed */}
      <ActivityFeed />
    </div>
  );
}

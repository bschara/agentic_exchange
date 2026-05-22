'use client';

import dynamic from 'next/dynamic';
import { Header } from '@/components/layout/Header';
import { ActivityFeed } from '@/components/layout/ActivityFeed';
import { OrderBook } from '@/components/chart/OrderBook';
import { RecentTrades } from '@/components/chart/RecentTrades';
import { AgentGrid } from '@/components/agents/AgentGrid';
import { AgentScoreboard } from '@/components/agents/AgentScoreboard';

const CandlestickChart = dynamic(
  () => import('@/components/chart/CandlestickChart').then((m) => m.CandlestickChart),
  { ssr: false, loading: () => <div className="w-full h-full bg-[#080808] animate-pulse" /> }
);

export default function Dashboard() {
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header />

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
          <div className="flex-none p-3 pb-2">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3 px-1">
              Autonomous Agents
            </div>
            <AgentGrid />
          </div>
          <div className="flex-1 px-3 pb-3 overflow-y-auto border-t border-white/5 pt-3">
            <AgentScoreboard />
          </div>
        </div>
      </div>

      {/* Bottom: Activity feed */}
      <ActivityFeed />
    </div>
  );
}

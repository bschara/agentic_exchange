'use client';

import { useMarketStore } from '@/store/marketStore';

function timeAgo(ts: number): string {
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s`;
  return `${Math.floor(diff / 60)}m`;
}

export function RecentTrades() {
  const trades = useMarketStore((s) => s.recentTrades);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-white/5">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Recent Trades</span>
      </div>
      <div className="grid grid-cols-3 px-3 py-1 text-xs text-gray-600 border-b border-white/5">
        <span>Price</span>
        <span className="text-center">Size</span>
        <span className="text-right">Age</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {trades.slice(0, 30).map((trade) => (
          <div key={trade.id} className="grid grid-cols-3 px-3 py-0.5 text-xs hover:bg-white/5">
            <span className={`font-mono ${trade.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}`}>
              ${trade.price.toFixed(2)}
            </span>
            <span className="text-center text-gray-300 font-mono">{trade.amount.toFixed(3)}</span>
            <span className="text-right text-gray-600">{timeAgo(trade.timestamp)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

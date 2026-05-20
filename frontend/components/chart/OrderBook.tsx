'use client';

import { useMarketStore } from '@/store/marketStore';

export function OrderBook() {
  const { orderBook, currentPrice } = useMarketStore();
  const { bids, asks } = orderBook;

  const maxSize = Math.max(
    ...bids.map((b) => b.size),
    ...asks.map((a) => a.size),
    0.1
  );

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-white/5">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Order Book</span>
      </div>

      {/* Header */}
      <div className="grid grid-cols-2 px-3 py-1 text-xs text-gray-600 border-b border-white/5">
        <span>Price</span>
        <span className="text-right">Size</span>
      </div>

      {/* Asks (reversed — lowest ask at bottom) */}
      <div className="flex-1 overflow-hidden">
        {[...asks].reverse().slice(0, 8).map((ask, i) => (
          <div key={i} className="relative grid grid-cols-2 px-3 py-0.5 text-xs hover:bg-white/5">
            <div
              className="absolute inset-y-0 right-0 bg-red-500/10"
              style={{ width: `${(ask.size / maxSize) * 100}%` }}
            />
            <span className="text-red-400 font-mono z-10">${ask.price.toFixed(2)}</span>
            <span className="text-right text-gray-300 font-mono z-10">{ask.size.toFixed(3)}</span>
          </div>
        ))}
      </div>

      {/* Mid price */}
      <div className="px-3 py-1.5 border-y border-white/10 bg-white/5">
        <span className="text-sm font-bold font-mono text-white">${currentPrice.toFixed(2)}</span>
      </div>

      {/* Bids */}
      <div className="flex-1 overflow-hidden">
        {bids.slice(0, 8).map((bid, i) => (
          <div key={i} className="relative grid grid-cols-2 px-3 py-0.5 text-xs hover:bg-white/5">
            <div
              className="absolute inset-y-0 right-0 bg-emerald-500/10"
              style={{ width: `${(bid.size / maxSize) * 100}%` }}
            />
            <span className="text-emerald-400 font-mono z-10">${bid.price.toFixed(2)}</span>
            <span className="text-right text-gray-300 font-mono z-10">{bid.size.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

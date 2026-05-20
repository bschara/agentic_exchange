'use client';

import { useFeedStore } from '@/store/feedStore';
import { ActivityFeedItem } from '@/lib/types';

const CATEGORY_COLORS: Record<ActivityFeedItem['category'], string> = {
  order: 'text-blue-400',
  trade: 'text-emerald-400',
  warning: 'text-yellow-400',
  event: 'text-violet-400',
  system: 'text-gray-400',
};

const CATEGORY_BG: Record<ActivityFeedItem['category'], string> = {
  order: 'bg-blue-500/10',
  trade: 'bg-emerald-500/10',
  warning: 'bg-yellow-500/10',
  event: 'bg-violet-500/10',
  system: 'bg-gray-500/10',
};

function timeAgo(ts: number): string {
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export function ActivityFeed() {
  const items = useFeedStore((s) => s.items);

  return (
    <div className="border-t border-white/10 bg-black/40">
      <div className="px-4 py-2 border-b border-white/5">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Live Activity</span>
      </div>
      <div className="flex gap-0 overflow-x-auto scrollbar-hide h-10 items-center px-2">
        {items.slice(0, 20).map((item) => (
          <div
            key={item.id}
            className={`flex-none flex items-center gap-2 px-3 py-1 rounded-md mx-1 ${CATEGORY_BG[item.category]}`}
          >
            <span className={`text-xs font-semibold ${CATEGORY_COLORS[item.category]}`}>
              {item.agent_name}
            </span>
            <span className="text-xs text-gray-300 max-w-[260px] truncate">{item.message}</span>
            <span className="text-xs text-gray-600 ml-1 whitespace-nowrap">{timeAgo(item.timestamp)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

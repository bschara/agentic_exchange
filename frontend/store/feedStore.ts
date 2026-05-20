import { create } from 'zustand';
import { ActivityFeedItem } from '@/lib/types';
import { FAKE_FEED_ITEMS } from '@/lib/fake-data';

interface FeedStore {
  items: ActivityFeedItem[];
  addItem: (item: ActivityFeedItem) => void;
  clearFeed: () => void;
}

export const useFeedStore = create<FeedStore>((set) => ({
  items: FAKE_FEED_ITEMS,

  addItem: (item) =>
    set((s) => ({ items: [item, ...s.items].slice(0, 100) })),

  clearFeed: () => set({ items: [] }),
}));

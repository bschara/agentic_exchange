import { create } from 'zustand';
import { ActivityFeedItem } from '@/lib/types';

interface FeedStore {
  items: ActivityFeedItem[];
  addItem: (item: ActivityFeedItem) => void;
  clearFeed: () => void;
}

export const useFeedStore = create<FeedStore>((set) => ({
  items: [],

  addItem: (item) =>
    set((s) => ({ items: [item, ...s.items].slice(0, 100) })),

  clearFeed: () => set({ items: [] }),
}));

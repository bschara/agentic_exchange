'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface UserStore {
  walletAddress: string | null;
  setWalletAddress: (addr: string | null) => void;
}

export const useUserStore = create<UserStore>()(
  persist(
    (set) => ({
      walletAddress: null,
      setWalletAddress: (addr) => set({ walletAddress: addr }),
    }),
    { name: 'agentic-exchange-wallet' }
  )
);

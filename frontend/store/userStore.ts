'use client';

import { create } from 'zustand';

interface UserStore {
  walletAddress: string | null;
  setWalletAddress: (addr: string | null) => void;
}

export const useUserStore = create<UserStore>((set) => ({
  walletAddress: null,
  setWalletAddress: (addr) => set({ walletAddress: addr }),
}));

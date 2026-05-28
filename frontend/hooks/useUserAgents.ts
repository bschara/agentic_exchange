'use client';

import { useState, useCallback, useEffect } from 'react';
import { Interface } from 'ethers';
import { UserAgentRecord } from '@/lib/types';
import { useAgentStore } from '@/store/agentStore';

const API_URL             = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REGISTRY_ADDRESS    = process.env.NEXT_PUBLIC_REGISTRY_ADDRESS || '';
const COORDINATOR_ADDRESS = process.env.NEXT_PUBLIC_COORDINATOR_ADDRESS || '';

// Default price feed — same as system agents (Somnia JSON API reads ETH/USD from CoinGecko)
const DEFAULT_PRICE_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd';
const DEFAULT_SELECTOR  = 'ethereum.usd';
const DEFAULT_DECIMALS  = 0;

// Registry handles create/pause/resume; coordinator only handles fund()
const REGISTRY_ABI = [
  'function registerAgent(string agentId, string name, string icon, uint8 riskLevel, string systemPrompt, string priceUrl, string selector, uint8 decimals) external',
  'function pauseAgent(string agentId) external',
  'function resumeAgent(string agentId) external',
];
const COORDINATOR_ABI = [
  'function fund() external payable',
];

const registryIface    = new Interface(REGISTRY_ABI);
const coordinatorIface = new Interface(COORDINATOR_ABI);
// keep legacy alias so createAgent/pause/resume can use registryIface
const iface = registryIface;

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 12);
}

function randomHex(bytes: number): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr).map((b) => b.toString(16).padStart(2, '0')).join('');
}

function toHex(n: bigint): string {
  return '0x' + n.toString(16);
}

async function sendTx(from: string, to: string, data: string, value?: bigint): Promise<string> {
  if (!window.ethereum) throw new Error('MetaMask not found');
  const params: Record<string, string> = { from, to, data };
  if (value !== undefined && value > 0n) params.value = toHex(value);
  return window.ethereum.request({ method: 'eth_sendTransaction', params: [params] }) as Promise<string>;
}

export function useUserAgents(walletAddress: string | null) {
  const [agents, setAgents] = useState<UserAgentRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const liveAgents = useAgentStore((s) => s.agents);

  const fetchAgents = useCallback(async () => {
    if (!walletAddress) { setAgents([]); return; }
    try {
      const res = await fetch(`${API_URL}/user/agents?address=${walletAddress}`);
      if (!res.ok) return;
      const data = await res.json();
      const records: UserAgentRecord[] = (data.agents || []).map((r: UserAgentRecord) => ({
        ...r,
        metrics: liveAgents[r.agent_id] ?? undefined,
      }));
      setAgents(records);
    } catch (e) {
      console.error('[useUserAgents] fetchAgents failed:', e);
    }
  }, [walletAddress]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-merge live metrics whenever chain data updates
  useEffect(() => {
    setAgents((prev) =>
      prev.map((r) => ({ ...r, metrics: liveAgents[r.agent_id] ?? r.metrics }))
    );
  }, [liveAgents]);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  // ── On-chain actions ────────────────────────────────────────────────────────

  const createAgent = useCallback(async (
    name: string,
    systemPrompt: string,
    icon: string = '🤖',
    riskLevel: number = 3,
  ): Promise<string> => {
    if (!walletAddress || !REGISTRY_ADDRESS) throw new Error('Wallet not connected or registry not configured');
    const suffix   = walletAddress.slice(-6).toLowerCase();
    const agentId  = `user_${suffix}_${slugify(name)}_${randomHex(2)}`;
    const calldata = registryIface.encodeFunctionData('registerAgent', [
      agentId,
      name,
      icon,
      riskLevel,
      systemPrompt,
      DEFAULT_PRICE_URL,
      DEFAULT_SELECTOR,
      DEFAULT_DECIMALS,
    ]);
    setLoading(true);
    setError(null);
    try {
      const txHash = await sendTx(walletAddress, REGISTRY_ADDRESS, calldata);
      return txHash;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [walletAddress]);

  const pauseAgent = useCallback(async (agentId: string): Promise<string> => {
    if (!walletAddress || !REGISTRY_ADDRESS) throw new Error('Wallet not connected or registry not configured');
    const calldata = registryIface.encodeFunctionData('pauseAgent', [agentId]);
    setLoading(true);
    setError(null);
    try {
      return await sendTx(walletAddress, REGISTRY_ADDRESS, calldata);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [walletAddress]);

  const resumeAgent = useCallback(async (agentId: string): Promise<string> => {
    if (!walletAddress || !REGISTRY_ADDRESS) throw new Error('Wallet not connected or registry not configured');
    const calldata = registryIface.encodeFunctionData('resumeAgent', [agentId]);
    setLoading(true);
    setError(null);
    try {
      return await sendTx(walletAddress, REGISTRY_ADDRESS, calldata);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [walletAddress]);

  const fundAgent = useCallback(async (amountEth: number): Promise<string> => {
    if (!walletAddress || !COORDINATOR_ADDRESS) throw new Error('Wallet not connected or coordinator not configured');
    const value    = BigInt(Math.round(amountEth * 1e18));
    const calldata = coordinatorIface.encodeFunctionData('fund', []);
    setLoading(true);
    setError(null);
    try {
      return await sendTx(walletAddress, COORDINATOR_ADDRESS, calldata, value);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [walletAddress]);

  return { agents, loading, error, createAgent, pauseAgent, resumeAgent, fundAgent, refetch: fetchAgents };
}

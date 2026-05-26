'use client';

import { useState } from 'react';
import { useMarketStore } from '@/store/marketStore';
import { useAgentStore } from '@/store/agentStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import { connectWallet, isOwnerAddress, pauseAll, resumeAll, fundAll } from '@/hooks/useAdminActions';
import { Badge } from '@/components/ui/badge';
import { Zap, Activity, Wallet, PauseCircle, PlayCircle, Coins } from 'lucide-react';

const EVENTS = [
  { type: 'whale_buy', label: 'WHALE BUY +3%', className: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/30' },
  { type: 'whale_sell', label: 'WHALE SELL -3%', className: 'bg-red-500/20 text-red-400 border-red-500/30 hover:bg-red-500/30' },
  { type: 'volatility_spike', label: 'VOL SPIKE', className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30 hover:bg-yellow-500/30' },
  { type: 'news_event', label: 'NEWS EVENT', className: 'bg-blue-500/20 text-blue-400 border-blue-500/30 hover:bg-blue-500/30' },
  { type: 'flash_crash', label: 'FLASH CRASH', className: 'bg-orange-500/20 text-orange-400 border-orange-500/30 hover:bg-orange-500/30' },
];

export function Header() {
  const { currentPrice, priceChange24h, volume24h, isConnected } = useMarketStore();
  const { agents, somniaBlockMs } = useAgentStore();
  const { injectEvent } = useWebSocket();
  const [cooldowns, setCooldowns] = useState<Record<string, boolean>>({});
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [adminLoading, setAdminLoading] = useState<string | null>(null);
  const [fundAmount, setFundAmount] = useState<string>('100');
  const isOwner = !!walletAddress && isOwnerAddress(walletAddress);

  const handleConnect = async () => {
    const addr = await connectWallet();
    if (addr) setWalletAddress(addr);
  };

  const handleAdmin = async (action: string, fn: () => Promise<{ ok: boolean; error?: string }>) => {
    if (adminLoading) return;
    setAdminLoading(action);
    const res = await fn();
    if (!res.ok) console.error(`[admin] ${action} failed:`, res.error);
    setAdminLoading(null);
  };

  // Average latency across agents that have completed at least one decision cycle
  const agentList = Object.values(agents);
  const latencyAgents = agentList.filter((a) => a.decision_latency_count > 0);
  const avgLatencyMs = latencyAgents.length
    ? latencyAgents.reduce((s, a) => s + a.avg_decision_latency_ms, 0) / latencyAgents.length
    : 0;
  const ethEquivMs = somniaBlockMs > 0 && avgLatencyMs > 0
    ? Math.round((avgLatencyMs / somniaBlockMs) * 12000)
    : 0;

  const handleEvent = (type: string) => {
    if (cooldowns[type]) return;
    injectEvent(type);
    setCooldowns((c) => ({ ...c, [type]: true }));
    setTimeout(() => setCooldowns((c) => ({ ...c, [type]: false })), 10000);
  };

  const priceUp = priceChange24h >= 0;

  return (
    <header className="border-b border-white/10 bg-black/60 backdrop-blur-md px-6 py-3">
      <div className="flex items-center justify-between gap-4">
        {/* Logo */}
        <div className="flex items-center gap-3 min-w-fit">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-violet-400" />
            <span className="text-white font-bold text-lg tracking-tight">AGENTIC EXCHANGE</span>
          </div>
          <Badge variant="outline" className="text-xs border-violet-500/50 text-violet-400">
            SOMNIA TESTNET
          </Badge>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            <span className="text-xs text-gray-500">{isConnected ? 'LIVE' : 'OFFLINE'}</span>
          </div>
        </div>

        {/* Price ticker */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <span className="text-2xl font-mono font-bold text-white">
              ${currentPrice.toFixed(2)}
            </span>
            <span className={`text-sm font-mono font-semibold ${priceUp ? 'text-emerald-400' : 'text-red-400'}`}>
              {priceUp ? '+' : ''}{priceChange24h.toFixed(2)}%
            </span>
          </div>
          <div className="flex items-center gap-1 text-gray-500 text-xs">
            <Activity className="w-3 h-3" />
            <span>Vol: ${(volume24h / 1000).toFixed(1)}K</span>
          </div>

          {/* Latency ticker */}
          {somniaBlockMs > 0 && avgLatencyMs > 0 ? (
            <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <Zap className="w-3 h-3 text-emerald-400" />
              <div className="text-xs font-mono">
                <span className="text-emerald-400 font-bold">{avgLatencyMs.toFixed(0)}ms</span>
                <span className="text-gray-600 mx-1">on Somnia</span>
                <span className="text-gray-700">vs</span>
                <span className="text-red-500/70 ml-1 font-bold">~{(ethEquivMs / 1000).toFixed(0)}s</span>
                <span className="text-gray-700 ml-1">on ETH</span>
              </div>
            </div>
          ) : somniaBlockMs === 0 && isConnected ? (
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-violet-500/10 border border-violet-500/20">
              <Zap className="w-3 h-3 text-violet-400" />
              <span className="text-xs font-mono text-violet-400">local node</span>
            </div>
          ) : null}
        </div>

        {/* Event buttons */}
        <div className="flex items-center gap-2">
          {EVENTS.map((e) => (
            <button
              key={e.type}
              onClick={() => handleEvent(e.type)}
              disabled={cooldowns[e.type]}
              className={`px-3 py-1.5 text-xs font-bold border rounded-md transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed ${e.className}`}
            >
              {cooldowns[e.type] ? 'INJECTING...' : e.label}
            </button>
          ))}
        </div>

        {/* Admin controls — visible only to deployer wallet */}
        <div className="flex items-center gap-2 border-l border-white/10 pl-3">
          {!walletAddress ? (
            <button
              onClick={handleConnect}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold border border-violet-500/40 text-violet-400 rounded-md bg-violet-500/10 hover:bg-violet-500/20 transition-all"
            >
              <Wallet className="w-3 h-3" />
              CONNECT
            </button>
          ) : !isOwner ? (
            <span className="text-xs text-gray-600 font-mono">
              {walletAddress.slice(0, 6)}…{walletAddress.slice(-4)}
            </span>
          ) : (
            <>
              <span className="text-xs text-violet-400 font-mono mr-1">
                {walletAddress.slice(0, 6)}…{walletAddress.slice(-4)}
              </span>
              <button
                onClick={() => handleAdmin('pause-all', () => pauseAll(walletAddress))}
                disabled={!!adminLoading}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold border border-orange-500/40 text-orange-400 rounded-md bg-orange-500/10 hover:bg-orange-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                <PauseCircle className="w-3 h-3" />
                {adminLoading === 'pause-all' ? '...' : 'PAUSE ALL'}
              </button>
              <button
                onClick={() => handleAdmin('resume-all', () => resumeAll(walletAddress))}
                disabled={!!adminLoading}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold border border-emerald-500/40 text-emerald-400 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                <PlayCircle className="w-3 h-3" />
                {adminLoading === 'resume-all' ? '...' : 'RESUME ALL'}
              </button>
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min="1"
                  value={fundAmount}
                  onChange={(e) => setFundAmount(e.target.value)}
                  className="w-16 px-2 py-1.5 text-xs font-mono bg-black/40 border border-white/10 rounded-md text-white text-center"
                />
                <button
                  onClick={() => handleAdmin('fund-all', () => fundAll(walletAddress, parseFloat(fundAmount) || 100))}
                  disabled={!!adminLoading}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold border border-blue-500/40 text-blue-400 rounded-md bg-blue-500/10 hover:bg-blue-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  <Coins className="w-3 h-3" />
                  {adminLoading === 'fund-all' ? '...' : 'FUND ALL'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

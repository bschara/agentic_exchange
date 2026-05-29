'use client';

import { useState } from 'react';
import { PauseCircle, PlayCircle } from 'lucide-react';
import { useAgentStore } from '@/store/agentStore';
import { pauseAll, resumeAll } from '@/hooks/useAdminActions';
import { AdminAgentRow } from './AdminAgentRow';

const SYSTEM_AGENT_IDS = new Set(['market_maker', 'momentum_trader', 'arbitrage_agent', 'risk_manager', 'noise_trader']);

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Props {
  walletAddress: string;
}

export function AdminPanel({ walletAddress }: Props) {
  const agents = useAgentStore((s) => s.agents);
  const [bulkLoading, setBulkLoading] = useState<string | null>(null);
  const [bulkFeedback, setBulkFeedback] = useState<string | null>(null);

  const allAgentIds    = Object.keys(agents);
  const systemAgentIds = allAgentIds.filter((id) => SYSTEM_AGENT_IDS.has(id));
  const userAgentIds   = allAgentIds.filter((id) => !SYSTEM_AGENT_IDS.has(id));

  const handleBulk = async (action: string, fn: () => Promise<{ ok: boolean; error?: string }>) => {
    if (bulkLoading) return;
    setBulkLoading(action);
    setBulkFeedback(null);
    const res = await fn();
    if (!res.ok) setBulkFeedback(res.error?.slice(0, 80) ?? 'Error');
    setBulkLoading(null);
  };

  const agentAction = async (
    agentId: string,
    endpoint: string,
    body?: Record<string, unknown>,
  ): Promise<{ ok: boolean; error?: string }> => {
    try {
      const timestamp = Math.floor(Date.now() / 1000);
      const action    = endpoint.split('/').pop() ?? endpoint;
      const message   = `admin:${action}:${timestamp}`;
      const signature: string = await window.ethereum!.request({
        method: 'personal_sign',
        params: [message, walletAddress],
      });
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type':   'application/json',
          'X-Admin-Sig':     signature,
          'X-Admin-Message': message,
          'X-Admin-Address': walletAddress,
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await res.json();
      if (!res.ok) return { ok: false, error: data?.detail ?? `HTTP ${res.status}` };
      return { ok: true };
    } catch (e: unknown) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Admin Panel</span>
        <div className="flex gap-1.5">
          <button
            onClick={() => handleBulk('pause-all', () => pauseAll(walletAddress))}
            disabled={!!bulkLoading}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold border border-orange-500/40 text-orange-400 rounded-lg bg-orange-500/10 hover:bg-orange-500/20 disabled:opacity-40 transition-all"
          >
            <PauseCircle className="w-3 h-3" />
            {bulkLoading === 'pause-all' ? '…' : 'PAUSE ALL'}
          </button>
          <button
            onClick={() => handleBulk('resume-all', () => resumeAll(walletAddress))}
            disabled={!!bulkLoading}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold border border-emerald-500/40 text-emerald-400 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 transition-all"
          >
            <PlayCircle className="w-3 h-3" />
            {bulkLoading === 'resume-all' ? '…' : 'RESUME ALL'}
          </button>
        </div>
      </div>

      {bulkFeedback && <p className="text-[11px] text-red-400 px-1">{bulkFeedback}</p>}

      {/* System agents */}
      <div className="flex flex-col gap-1">
        <div className="text-[10px] text-gray-700 uppercase tracking-widest px-1 mb-0.5">System Agents</div>
        {systemAgentIds.map((id) => (
          <AdminAgentRow
            key={id}
            agentId={id}
            agentState={agents[id]}
            isUserAgent={false}
            onPause={()  => agentAction(id, `/agents/${id}/pause`)}
            onResume={() => agentAction(id, `/agents/${id}/resume`)}
            onFund={(amt) => agentAction(id, `/agents/${id}/fund`, { amount: amt })}
          />
        ))}
      </div>

      {/* User agents */}
      {userAgentIds.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="text-[10px] text-gray-700 uppercase tracking-widest px-1 mb-0.5 border-t border-white/5 pt-2">
            User Agents ({userAgentIds.length})
          </div>
          {userAgentIds.map((id) => {
            const state = agents[id];
            return (
              <AdminAgentRow
                key={id}
                agentId={id}
                agentState={state}
                isUserAgent={true}
                ownerAddress={(state as unknown as { owner_address?: string })?.owner_address}
                icon={(state as unknown as { icon?: string })?.icon}
                riskLevel={(state as unknown as { risk_level?: number })?.risk_level}
                onPause={()  => agentAction(id, `/agents/${id}/pause`)}
                onResume={() => agentAction(id, `/agents/${id}/resume`)}
                onFund={(amt) => agentAction(id, `/agents/${id}/fund`, { amount: amt })}
              />
            );
          })}
        </div>
      )}

      {userAgentIds.length === 0 && (
        <p className="text-[11px] text-gray-700 px-1">No user agents registered yet.</p>
      )}
    </div>
  );
}

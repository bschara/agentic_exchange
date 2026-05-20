'use client';

import { useAgentStore } from '@/store/agentStore';
import { AgentCard } from './AgentCard';

export function AgentGrid() {
  const agents = useAgentStore((s) => s.agents);

  const agentList = [
    'market_maker',
    'momentum_trader',
    'arbitrage_agent',
    'risk_manager',
  ].map((id) => agents[id]).filter(Boolean);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 h-full overflow-y-auto pr-1">
      {agentList.map((agent) => (
        <AgentCard key={agent.agent_id} agent={agent} />
      ))}
    </div>
  );
}

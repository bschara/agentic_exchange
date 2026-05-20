import { create } from 'zustand';
import { AgentState } from '@/lib/types';
import { FAKE_AGENTS } from '@/lib/fake-data';

interface AgentStore {
  agents: Record<string, AgentState>;
  reasoningHistory: Record<string, string[]>;

  updateAgent: (state: AgentState) => void;
  appendReasoning: (agent_id: string, reasoning: string) => void;
}

const initAgents: Record<string, AgentState> = {};
for (const a of FAKE_AGENTS) initAgents[a.agent_id] = a;

export const useAgentStore = create<AgentStore>((set) => ({
  agents: initAgents,
  reasoningHistory: Object.fromEntries(FAKE_AGENTS.map((a) => [a.agent_id, [a.reasoning]])),

  updateAgent: (agentState) =>
    set((s) => ({
      agents: { ...s.agents, [agentState.agent_id]: agentState },
    })),

  appendReasoning: (agent_id, reasoning) =>
    set((s) => {
      const history = [reasoning, ...(s.reasoningHistory[agent_id] || [])].slice(0, 20);
      return { reasoningHistory: { ...s.reasoningHistory, [agent_id]: history } };
    }),
}));

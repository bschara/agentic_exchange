'use client';

import { useEffect, useRef, useCallback } from 'react';
import { WSMessage } from '@/lib/types';
import { useMarketStore } from '@/store/marketStore';
import { useAgentStore } from '@/store/agentStore';
import { useFeedStore } from '@/store/feedStore';

function dispatch(msg: WSMessage) {
  switch (msg.type) {
    case 'market_snapshot':
      useMarketStore.getState().setMarketSnapshot(msg.data);
      break;

    case 'candle':
      useMarketStore.getState().addCandle(msg.data);
      break;

    case 'chain_metrics': {
      const prevAgents = useAgentStore.getState().agents;
      useAgentStore.getState().updateFromChainMetrics(msg.data);

      for (const [id, agent] of Object.entries(msg.data.agents)) {
        const prev = prevAgents[id];

        if (prev && agent.decisions_total > prev.decisions_total && agent.last_decision) {
          const price = agent.last_price > 0 ? `$${agent.last_price.toFixed(2)}` : '—';
          useFeedStore.getState().addItem({
            id: `${Date.now()}-${id}`,
            agent_id: id,
            agent_name: agent.agent_name,
            message: `${agent.last_decision} order at ${price}`,
            category: agent.last_decision === 'HOLD' ? 'system' : 'order',
            timestamp: Math.floor(Date.now() / 1000),
          });
        }

        if (prev && !prev.loop_stopped && agent.loop_stopped) {
          useFeedStore.getState().addItem({
            id: `${Date.now()}-stop-${id}`,
            agent_id: id,
            agent_name: agent.agent_name,
            message: `Loop stopped: ${agent.loop_stopped_reason || 'insufficient balance'}`,
            category: 'warning',
            timestamp: Math.floor(Date.now() / 1000),
          });
        }
      }
      break;
    }

    case 'risk_warning':
      useFeedStore.getState().addItem({
        id: String(Date.now()),
        agent_id: msg.data.from_agent,
        agent_name: 'Risk-Shield',
        message: msg.data.message,
        category: 'warning',
        timestamp: Math.floor(Date.now() / 1000),
      });
      break;

    case 'event_injected':
      useFeedStore.getState().addItem({
        id: String(Date.now()),
        agent_id: 'system',
        agent_name: 'System',
        message: msg.data.description,
        category: 'event',
        timestamp: Math.floor(Date.now() / 1000),
      });
      break;
  }
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const pingTimer = useRef<ReturnType<typeof setInterval>>();

  const connect = useCallback(() => {
    const url = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      useMarketStore.getState().setConnected(true);
      clearTimeout(reconnectTimer.current);
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        dispatch(msg);
      } catch {}
    };

    ws.onclose = () => {
      useMarketStore.getState().setConnected(false);
      clearInterval(pingTimer.current);
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      clearInterval(pingTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const injectEvent = useCallback((event_type: string) => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    fetch(`${apiUrl}/events/inject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type, params: {} }),
    }).catch(() => {});
  }, []);

  return { injectEvent };
}

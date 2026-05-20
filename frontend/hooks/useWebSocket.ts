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
    case 'agent_update':
      useAgentStore.getState().updateAgent(msg.data);
      useAgentStore.getState().appendReasoning(msg.data.agent_id, msg.data.reasoning);
      break;
    case 'activity_feed':
      useFeedStore.getState().addItem(msg.data);
      break;
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

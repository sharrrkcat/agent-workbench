import { useEffect } from 'react';
import { API_BASE_URL, joinApiUrl } from '../api/client';
import { useModelsStore } from '../store/useModelsStore';
import type { RuntimeEvent } from '../types';

export function useModelEvents() {
  useEffect(() => {
    let closed = false;
    let socket: WebSocket;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    function connect() {
      const url = new URL(joinApiUrl(API_BASE_URL, '/api/models/runtimes/events'), window.location.origin);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url);
      const next = () => { if (!closed && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'next_event' })); };
      socket.addEventListener('open', () => {
        void useModelsStore.getState().reloadRuntimes().catch(() => undefined);
        void useModelsStore.getState().reload().catch(() => undefined);
        next();
      });
      socket.addEventListener('message', (event) => {
        try {
          const value = JSON.parse(event.data) as RuntimeEvent;
          if (value.type !== 'pong') { useModelsStore.getState().applyModelEvent(value); next(); }
        } catch { next(); }
      });
      socket.addEventListener('close', () => { if (!closed) reconnect = setTimeout(connect, 1500); });
    }
    connect();
    return () => { closed = true; clearTimeout(reconnect); socket.close(); };
  }, []);
}

'use client';

import { useWebSocket } from '@/hooks/useWebSocket';

export function Providers({ children }: { children: React.ReactNode }) {
  useWebSocket();
  return <>{children}</>;
}

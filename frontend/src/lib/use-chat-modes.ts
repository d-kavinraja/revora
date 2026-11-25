'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export const CHAT_MODES_KEY = ['chat-modes'] as const;

export function useChatModes() {
  return useQuery({
    queryKey: CHAT_MODES_KEY,
    queryFn: ({ signal }) => api.getChatModes(signal),
    staleTime: 5_000,
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

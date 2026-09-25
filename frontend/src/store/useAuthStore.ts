import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  image?: string;
  /** GitHub login handle from OAuth (non-secret identity field). */
  github_username?: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      setAuth: (token, user) => set({ token, user, isAuthenticated: true }),
      logout: () => {
        document.cookie = 'revora_auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
        set({ token: null, user: null, isAuthenticated: false });
      },
    }),
    {
      name: 'revora-auth',
    }
  )
);

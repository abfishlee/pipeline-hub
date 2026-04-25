import { create } from "zustand";

const STORAGE_KEY = "udp.auth";

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: {
    user_id: number;
    login_id: string;
    display_name: string;
    roles: string[];
  } | null;
}

interface AuthActions {
  setTokens: (access: string, refresh: string) => void;
  setUser: (user: AuthState["user"]) => void;
  clear: () => void;
  hasRole: (role: string) => boolean;
}

type Persisted = Pick<AuthState, "accessToken" | "refreshToken" | "user">;

function loadPersisted(): Persisted {
  if (typeof window === "undefined") {
    return { accessToken: null, refreshToken: null, user: null };
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { accessToken: null, refreshToken: null, user: null };
    const parsed = JSON.parse(raw) as Partial<Persisted>;
    return {
      accessToken: parsed.accessToken ?? null,
      refreshToken: parsed.refreshToken ?? null,
      user: parsed.user ?? null,
    };
  } catch {
    return { accessToken: null, refreshToken: null, user: null };
  }
}

function savePersisted(state: Persisted): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function clearPersisted(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(STORAGE_KEY);
}

export const useAuthStore = create<AuthState & AuthActions>((set, get) => ({
  ...loadPersisted(),

  setTokens: (access, refresh) => {
    set((s) => {
      const next = { ...s, accessToken: access, refreshToken: refresh };
      savePersisted({
        accessToken: next.accessToken,
        refreshToken: next.refreshToken,
        user: next.user,
      });
      return next;
    });
  },

  setUser: (user) => {
    set((s) => {
      const next = { ...s, user };
      savePersisted({
        accessToken: next.accessToken,
        refreshToken: next.refreshToken,
        user: next.user,
      });
      return next;
    });
  },

  clear: () => {
    clearPersisted();
    set({ accessToken: null, refreshToken: null, user: null });
  },

  hasRole: (role) => {
    const u = get().user;
    return !!u && u.roles.includes(role);
  },
}));

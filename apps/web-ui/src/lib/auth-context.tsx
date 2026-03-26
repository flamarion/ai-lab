"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { auth, type AuthResponse } from "./api";

interface AuthState {
  user: AuthResponse | null;
  loading: boolean;
  login: (username: string, pin: string) => Promise<void>;
  register: (username: string, pin: string) => Promise<void>;
  logout: () => void;
  updatePreferences: (prefs: Record<string, unknown>) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY = "ailab_uid";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore session from localStorage
  useEffect(() => {
    const uid = localStorage.getItem(STORAGE_KEY);
    if (uid) {
      auth
        .session(uid)
        .then((data) => setUser(data))
        .catch(() => localStorage.removeItem(STORAGE_KEY))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (username: string, pin: string) => {
    const data = await auth.login(username, pin);
    localStorage.setItem(STORAGE_KEY, data.user_id);
    setUser(data);
  }, []);

  const register = useCallback(async (username: string, pin: string) => {
    const data = await auth.register(username, pin);
    localStorage.setItem(STORAGE_KEY, data.user_id);
    setUser(data);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setUser(null);
  }, []);

  const updatePreferences = useCallback(
    async (prefs: Record<string, unknown>) => {
      if (!user) return;
      // Merge with existing preferences so keys not in the form
      // (e.g. seed, num_ctx set via API) are preserved.
      const merged = { ...(user.preferences || {}), ...prefs };
      await auth.updatePreferences(user.user_id, merged);
      setUser((prev) => (prev ? { ...prev, preferences: merged } : prev));
    },
    [user]
  );

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, updatePreferences }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

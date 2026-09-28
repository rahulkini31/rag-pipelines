"use client";

import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

interface AuthContextType {
  token: string | null;
  tenantId: string | null;
  login: (token: string, tenantId?: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem("id_token"));
      setTenantId(localStorage.getItem("tenant_id"));
    }
  }, []);

  const login = (newToken: string, newTenantId?: string) => {
    localStorage.setItem("id_token", newToken);
    if (newTenantId) localStorage.setItem("tenant_id", newTenantId);
    setToken(newToken);
    setTenantId(newTenantId || null);
  };

  const logout = () => {
    localStorage.removeItem("id_token");
    localStorage.removeItem("tenant_id");
    setToken(null);
    setTenantId(null);
  };

  return (
    <AuthContext.Provider value={{ token, tenantId, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

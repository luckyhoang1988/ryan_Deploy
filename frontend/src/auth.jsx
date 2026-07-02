import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.csrf().catch(() => {});
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    await api.csrf();
    const u = await api.login(username, password);
    setUser(u);
    return u;
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  const hasRole = (...roles) => user && user.roles?.some((r) => roles.includes(r));

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, hasRole }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);

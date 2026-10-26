import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext(null);

// Access token lifetime in minutes – must match ACCESS_TOKEN_EXPIRE_MINUTES in app/auth.py.
// We refresh 5 minutes before expiry.
const ACCESS_TOKEN_EXPIRE_MINUTES = 30;
const AUTO_REFRESH_INTERVAL_MS = (ACCESS_TOKEN_EXPIRE_MINUTES - 5) * 60 * 1000;

let _accessToken = (() => {
  try {
    return localStorage.getItem('access_token') || sessionStorage.getItem('access_token') || null;
  } catch {
    return null;
  }
})();

export function getAccessToken() {
  return _accessToken;
}

export function setAccessToken(token) {
  _accessToken = token;
  try {
    if (token) {
      localStorage.setItem('access_token', token);
      sessionStorage.setItem('access_token', token);
    } else {
      localStorage.removeItem('access_token');
      sessionStorage.removeItem('access_token');
    }
  } catch {}
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupComplete, setSetupComplete] = useState(null);

  const refreshToken = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include', // send httpOnly refresh cookie
      });
      if (res.ok) {
        const data = await res.json();
        setAccessToken(data.access_token);
        // Re-fetch user with new token
        const userRes = await fetch('/api/auth/me', {
          headers: { Authorization: `Bearer ${data.access_token}` },
        });
        if (userRes.ok) {
          setUser(await userRes.json());
          return true;
        }
      }
    } catch { /* ignore */ }
    setAccessToken(null);
    setUser(null);
    return false;
  }, []);

  const fetchUser = useCallback(async () => {
    if (!_accessToken) {
      setLoading(false);
      return;
    }
    try {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${_accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else {
        // Token might be expired, try refresh
        const refreshed = await refreshToken();
        if (!refreshed) {
          setAccessToken(null);
          setUser(null);
        }
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [refreshToken]);

  const logout = useCallback(async () => {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {});
    setAccessToken(null);
    setUser(null);
  }, []);

  const checkSetup = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/setup-status');
      const data = await res.json();
      setSetupComplete(data.setup_complete);
      return data.setup_complete;
    } catch {
      return null;
    }
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password }),
    });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text || res.statusText };
    }
    if (!res.ok) {
      const d = data.detail;
      const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg || x).join('; ') : 'Login failed';
      throw new Error(msg);
    }
    setAccessToken(data.access_token);
    await fetchUser();
    await checkSetup();
    return true;
  }, [fetchUser, checkSetup]);

  const register = useCallback(async (username, email, password) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email, password }),
    });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text || res.statusText };
    }
    if (!res.ok) {
      const d = data.detail;
      const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg || x).join('; ') : 'Registration failed';
      throw new Error(msg);
    }
    return login(username, password);
  }, [login]);

  // On mount: check setup status, try cached token first, then fallback to refresh cookie
  useEffect(() => {
    (async () => {
      await checkSetup();
      const currentToken = getAccessToken();
      if (currentToken) {
        try {
          const userRes = await fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${currentToken}` },
          });
          if (userRes.ok) {
            setUser(await userRes.json());
            setLoading(false);
            return;
          }
        } catch { /* ignore */ }
      }
      await refreshToken();
      setLoading(false);
    })();
  }, [checkSetup, refreshToken]);

  // Auto-refresh access token before expiry (every 25 minutes)
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(() => {
      refreshToken();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [user, refreshToken]);

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      setupComplete,
      login,
      register,
      logout,
      refreshToken,
      checkSetup,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

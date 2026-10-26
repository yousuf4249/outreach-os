import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { FileUploadArea } from '../components/ui/FileUploadArea';
import logo from '../assets/weblinx_logo.svg';
import { RiEyeLine, RiEyeOffLine } from 'react-icons/ri';

const BACKUP_MIN_PASSWORD_LEN = 8;

function parseDetailMessage(text) {
  try {
    const j = JSON.parse(text);
    const d = j.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d))
      return d.map(x => (typeof x === 'string' ? x : x.msg || JSON.stringify(x))).join(' ');
  } catch {
    /* ignore */
  }
  return text;
}

export default function Login() {
  const { setupComplete, login, register } = useAuth();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [authError, setAuthError] = useState('');
  const [authBusy, setAuthBusy] = useState(false);

  const [restoreExpanded, setRestoreExpanded] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [restoreFileKey, setRestoreFileKey] = useState(0);
  const [restorePassword, setRestorePassword] = useState('');
  const [showRestorePassword, setShowRestorePassword] = useState(false);
  const [restoreMeta, setRestoreMeta] = useState(null);
  const [restoreMetaBusy, setRestoreMetaBusy] = useState(false);
  const [restorePreview, setRestorePreview] = useState(null);
  const [restorePreviewBusy, setRestorePreviewBusy] = useState(false);
  const [restoreExecuteBusy, setRestoreExecuteBusy] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState(null);

  const isFirstUser = setupComplete === false;

  useEffect(() => {
    if (!isFirstUser || !restoreExpanded || !restoreFile) {
      return undefined;
    }
    let cancelled = false;
    setRestoreMetaBusy(true);
    setRestoreMeta(null);
    setRestorePreview(null);
    setRestoreMsg(null);
    (async () => {
      try {
        const form = new FormData();
        form.append('file', restoreFile);
        const res = await fetch('/api/auth/restore-setup/metadata', { method: 'POST', body: form });
        const text = await res.text();
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          data = { detail: text || res.statusText };
        }
        if (!res.ok) {
          throw new Error(parseDetailMessage(text) || res.statusText);
        }
        if (!cancelled) {
          setRestoreMeta(data);
        }
      } catch (e) {
        if (!cancelled) {
          setRestoreMsg({ type: 'err', text: e.message || 'Could not read backup file' });
        }
      } finally {
        if (!cancelled) {
          setRestoreMetaBusy(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isFirstUser, restoreExpanded, restoreFile]);

  const clearRestoreWizard = () => {
    setRestoreFile(null);
    setRestoreFileKey(k => k + 1);
    setRestorePassword('');
    setRestoreMeta(null);
    setRestorePreview(null);
    setRestoreMsg(null);
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setAuthError('');
    setAuthBusy(true);
    try {
      if (isFirstUser) {
        if (!username.trim() || !email.trim() || !password) {
          throw new Error('Please fill in all fields');
        }
        await register(username.trim(), email.trim(), password);
      } else {
        if (!username.trim() || !password) {
          throw new Error('Please enter username and password');
        }
        await login(username.trim(), password);
      }
    } catch (err) {
      setAuthError(err.message || 'Authentication failed');
    } finally {
      setAuthBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-indigo-950 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-8 space-y-6 border border-gray-100 dark:border-gray-800">
        
        {/* Logo & Header */}
        <div className="flex flex-col items-center text-center">
          <img src={logo} alt="Weblinx Outreach OS" className="h-12 w-12 mb-3 shadow-md rounded-xl" />
          <h1 className="text-2xl font-extrabold text-gray-900 dark:text-white tracking-tight">
            Weblinx Outreach OS
          </h1>
          <p className="mt-1 text-xs font-medium text-blue-600 dark:text-blue-400">
            Weblinx Solution • Enterprise Sales Automation
          </p>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            {isFirstUser ? 'Create your primary administrator account' : 'Sign in to access your outreach dashboard'}
          </p>
        </div>

        {authError && (
          <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-xs text-red-600 dark:text-red-400">
            {authError}
          </div>
        )}

        {/* Credentials Form */}
        <form onSubmit={handlePasswordSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
              Username
            </label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:text-white transition"
            />
          </div>

          {isFirstUser && (
            <div>
              <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                Admin Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@weblinxsolution.com"
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:text-white transition"
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
              Password {isFirstUser && <span className="text-[10px] text-gray-400 font-normal">(Min 8 chars, 1 uppercase, 1 digit)</span>}
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full px-3 py-2 pr-10 text-sm border border-gray-300 dark:border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:text-white transition"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors cursor-pointer"
              >
                {showPassword ? <RiEyeOffLine size={18} /> : <RiEyeLine size={18} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={authBusy}
            className="w-full py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition shadow-md hover:shadow-lg disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {authBusy ? 'Authenticating...' : isFirstUser ? 'Create Admin Account' : 'Sign In'}
          </button>
        </form>

        {/* Divider */}
        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-700"></div>
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="px-2 bg-white dark:bg-gray-900 text-gray-400">or continue with OAuth</span>
          </div>
        </div>

        {/* OAuth Buttons */}
        <div className="space-y-2.5">
          <a
            href="/oauth/app/google/authorize"
            className="w-full flex items-center justify-center gap-3 py-2 px-4 border border-gray-300 dark:border-gray-700 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-750 transition"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google Workspace
          </a>

          <a
            href="/oauth/app/microsoft/authorize"
            className="w-full flex items-center justify-center gap-3 py-2 px-4 border border-gray-300 dark:border-gray-700 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-750 transition"
          >
            <svg className="w-4 h-4" viewBox="0 0 21 21">
              <rect fill="#F25022" x="1" y="1" width="9" height="9"/>
              <rect fill="#7FBA00" x="11" y="1" width="9" height="9"/>
              <rect fill="#00A4EF" x="1" y="11" width="9" height="9"/>
              <rect fill="#FFB900" x="11" y="11" width="9" height="9"/>
            </svg>
            Sign in with Microsoft 365
          </a>
        </div>

        {/* Restore from backup option */}
        {isFirstUser && (
          <div className="pt-4 border-t border-gray-100 dark:border-gray-800 text-center">
            {!restoreExpanded ? (
              <button
                type="button"
                onClick={() => setRestoreExpanded(true)}
                className="text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline"
              >
                Need to restore from an existing database backup?
              </button>
            ) : (
              <div className="space-y-3 text-left">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-gray-800 dark:text-gray-200">Restore Backup (.qbk)</p>
                  <button
                    type="button"
                    onClick={() => {
                      setRestoreExpanded(false);
                      clearRestoreWizard();
                    }}
                    className="text-[11px] text-gray-500 hover:text-gray-700"
                  >
                    Cancel
                  </button>
                </div>

                <div className="flex items-stretch gap-2">
                  <FileUploadArea
                    key={restoreFileKey}
                    size="full"
                    className="text-xs flex-1 min-w-0"
                    accept=".qbk,application/octet-stream"
                    disabled={restoreMetaBusy || restorePreviewBusy || restoreExecuteBusy}
                    onChange={e => {
                      setRestoreMsg(null);
                      setRestorePreview(null);
                      setRestoreMeta(null);
                      setRestoreFile(e.target.files?.[0] || null);
                    }}
                  >
                    {restoreFile ? (
                      <span className="truncate text-gray-800">{restoreFile.name}</span>
                    ) : (
                      <span className="text-gray-500">Choose backup file (.qbk)</span>
                    )}
                  </FileUploadArea>
                  {restoreFile && (
                    <button
                      type="button"
                      onClick={clearRestoreWizard}
                      className="px-2 text-xs border border-gray-300 rounded"
                    >
                      ×
                    </button>
                  )}
                </div>

                {restoreMeta && restoreMeta.encrypted && !restorePreview && (
                  <div className="space-y-2">
                    <div className="relative">
                      <input
                        type={showRestorePassword ? 'text' : 'password'}
                        placeholder="Backup decryption password"
                        value={restorePassword}
                        onChange={e => setRestorePassword(e.target.value)}
                        className="w-full px-3 py-1.5 pr-8 text-xs border border-gray-300 rounded"
                      />
                      <button
                        type="button"
                        onClick={() => setShowRestorePassword(!showRestorePassword)}
                        tabIndex={-1}
                        aria-label={showRestorePassword ? 'Hide password' : 'Show password'}
                        className="absolute inset-y-0 right-0 pr-2 flex items-center text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
                      >
                        {showRestorePassword ? <RiEyeOffLine size={14} /> : <RiEyeLine size={14} />}
                      </button>
                    </div>
                    <button
                      type="button"
                      disabled={restorePreviewBusy || restorePassword.length < BACKUP_MIN_PASSWORD_LEN}
                      onClick={async () => {
                        setRestorePreviewBusy(true);
                        try {
                          const form = new FormData();
                          form.append('file', restoreFile);
                          form.append('password', restorePassword);
                          const res = await fetch('/api/auth/restore-setup/preview', { method: 'POST', body: form });
                          if (!res.ok) throw new Error(await res.text());
                          setRestorePreview(await res.json());
                        } catch (e) {
                          setRestoreMsg({ type: 'err', text: e.message || 'Invalid password' });
                        } finally {
                          setRestorePreviewBusy(false);
                        }
                      }}
                      className="w-full py-1 text-xs bg-gray-800 text-white rounded"
                    >
                      Verify Password
                    </button>
                  </div>
                )}

                {restorePreview && (
                  <button
                    type="button"
                    disabled={restoreExecuteBusy}
                    onClick={async () => {
                      if (!window.confirm('Restore and replace current database?')) return;
                      setRestoreExecuteBusy(true);
                      try {
                        const res = await fetch('/api/auth/restore-setup/execute', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ restore_token: restorePreview.restore_token }),
                        });
                        if (!res.ok) throw new Error(await res.text());
                        window.location.reload();
                      } catch (e) {
                        setRestoreMsg({ type: 'err', text: e.message });
                      } finally {
                        setRestoreExecuteBusy(false);
                      }
                    }}
                    className="w-full py-1.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded"
                  >
                    Execute Restore
                  </button>
                )}

                {restoreMsg && (
                  <p className={`text-xs ${restoreMsg.type === 'err' ? 'text-red-500' : 'text-emerald-500'}`}>
                    {restoreMsg.text}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="pt-2 text-center text-[11px] text-gray-400">
          <p>© {new Date().getFullYear()} <a href="https://weblinxsolution.com" target="_blank" rel="noreferrer" className="text-blue-500 hover:underline">Weblinx Solution</a>. All rights reserved.</p>
        </div>

      </div>
    </div>
  );
}

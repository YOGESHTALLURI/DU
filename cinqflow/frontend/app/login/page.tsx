'use client';
import { useState } from 'react';

export default function LoginPage() {
  const [credential, setCredential] = useState('engineer:engineer123');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      });
      if (!res.ok) {
        setError('Invalid credentials');
        return;
      }
      const data = await res.json();
      localStorage.setItem('cinqflow_token', data.access_token);
      window.location.href = '/dashboard';
    } catch {
      setError('Connection error to CINQFLOW API');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-slate-950 text-slate-100">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-extrabold text-blue-400 tracking-tight">CINQFLOW</h1>
          <p className="text-slate-400 text-sm mt-1">Healthcare Data Management Platform — Wave 0</p>
          <div className="mt-2 inline-block bg-blue-950 border border-blue-800 text-blue-300 text-xs px-2.5 py-0.5 rounded-full font-mono">
            AuthProvider: Mock (DEV)
          </div>
        </div>

        <form onSubmit={handleSubmit} className="bg-slate-900 p-8 rounded-xl shadow-xl border border-slate-800 space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Credential (username:password)</label>
            <input
              type="text"
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
              placeholder="engineer:engineer123"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
              required
            />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setCredential('engineer:engineer123')}
              className="flex-1 bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 py-1.5 rounded border border-slate-700 transition"
            >
              Fill: Engineer
            </button>
            <button
              type="button"
              onClick={() => setCredential('readonly:readonly123')}
              className="flex-1 bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 py-1.5 rounded border border-slate-700 transition"
            >
              Fill: Read-Only
            </button>
          </div>

          {error && <p className="text-rose-400 text-sm bg-rose-950/40 p-2.5 rounded border border-rose-800/60">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors shadow-lg shadow-blue-600/20"
          >
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>
      </div>
    </main>
  );
}
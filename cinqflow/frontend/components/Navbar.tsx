'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

interface UserProfile {
  email: string;
  roles: string[];
}

export default function Navbar() {
  const pathname = usePathname();
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    fetch('/api/v1/auth/me', {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}`,
      },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUser(data))
      .catch(() => setUser(null));
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('cinqflow_token');
    window.location.href = '/login';
  };

  const navLinks = [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/ops', label: 'Operations' },
    { href: '/contracts', label: 'Contracts' },
    { href: '/ods', label: 'Canonical ODS' },
    { href: '/feeds', label: 'Feeds' },
    { href: '/dependencies', label: 'DAG & Dependencies' },
    { href: '/glossary', label: 'Business Glossary' },
    { href: '/landing', label: 'Landing & Inputs' },
    { href: '/quarantine', label: 'Quarantine' },
    { href: '/reconciliation', label: 'Reconciliation' },
    { href: '/audit', label: 'Audit Trail' },
  ];

  return (
    <nav className="bg-slate-900 text-white border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-8">
            <Link href="/dashboard" className="flex items-center space-x-2">
              <span className="font-bold text-xl tracking-tight text-blue-400">CINQFLOW</span>
              <span className="text-xs bg-indigo-900/60 text-indigo-300 px-2 py-0.5 rounded border border-indigo-700">Wave 1</span>
            </Link>
            <div className="hidden md:flex space-x-1">
              {navLinks.map((link) => {
                const active = pathname.startsWith(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      active
                        ? 'bg-blue-600 text-white'
                        : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                    }`}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>
          </div>
          <div className="flex items-center space-x-4">
            {user ? (
              <div className="flex items-center space-x-3 text-sm">
                <span className="text-slate-300">{user.email}</span>
                <span className="bg-slate-800 text-slate-300 px-2 py-0.5 rounded text-xs border border-slate-700 font-mono">
                  {user.roles.join(', ')}
                </span>
                <button
                  onClick={handleLogout}
                  className="text-xs text-rose-400 hover:text-rose-300 px-2 py-1 rounded hover:bg-slate-800 transition"
                >
                  Logout
                </button>
              </div>
            ) : (
              <Link
                href="/login"
                className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-500"
              >
                Sign In
              </Link>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}

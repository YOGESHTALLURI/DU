import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">CINQFLOW</h1>
        <p className="text-lg text-gray-600 mb-2">Healthcare Data Management Platform</p>
        <p className="text-sm text-blue-600 font-medium mb-8">Wave 0 — Working Foundation</p>
        <Link
          href="/login"
          className="inline-block bg-blue-600 text-white px-8 py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors"
        >
          Sign In
        </Link>
      </div>
    </main>
  );
}
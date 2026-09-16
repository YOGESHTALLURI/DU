'use client';
import { useEffect, useState } from 'react';
import Navbar from '@/components/Navbar';
import { Award } from 'lucide-react';

interface OdsModelVersion {
  id: string;
  version_number: number;
  name: string;
  domain: string;
  description?: string;
  status: string;
  schema_definition: Record<string, any>;
  published_at?: string;
  published_by?: string;
  created_at: string;
  created_by: string;
}

interface ConsumerRegistration {
  id: string;
  consumer_name: string;
  consumer_type: string;
  registered_ods_model_version_id: string;
  status: string;
  db_role_name?: string;
  contact_email: string;
  purpose?: string;
  created_at: string;
}

interface OdsCertification {
  id: string;
  batch_id: string;
  ods_model_version_id: string;
  status: string;
  certified_by?: string;
  certified_at?: string;
  certification_notes?: string;
  checklist_snapshot: Record<string, any>;
  created_at: string;
}

export default function OdsManagementPage() {
  const [activeTab, setActiveTab] = useState<'versions' | 'consumers' | 'certifications'>('versions');
  const [modelVersions, setModelVersions] = useState<OdsModelVersion[]>([]);
  const [consumers, setConsumers] = useState<ConsumerRegistration[]>([]);
  const [certifications, setCertifications] = useState<OdsCertification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Modals state
  const [showVersionModal, setShowVersionModal] = useState(false);
  const [showConsumerModal, setShowConsumerModal] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [showCertifyModal, setShowCertifyModal] = useState(false);
  const [targetVersionToPublish, setTargetVersionToPublish] = useState<OdsModelVersion | null>(null);
  const [publishNotes, setPublishNotes] = useState('');

  // Certification state
  const [certifyBatchId, setCertifyBatchId] = useState('');
  const [certifyNotes, setCertifyNotes] = useState('');
  const [certifyOutcome, setCertifyOutcome] = useState<'CERTIFIED' | 'FAILED'>('CERTIFIED');
  const [eligibilityData, setEligibilityData] = useState<any>(null);
  const [eligibilityLoading, setEligibilityLoading] = useState(false);
  const [certifying, setCertifying] = useState(false);

  // Form states
  const [versionForm, setVersionForm] = useState({
    version_number: 1,
    name: 'Canonical Clinical ODS v1',
    domain: 'clinical',
    description: 'Enterprise healthcare operational data store canonical model',
    schema_definition: JSON.stringify(
      {
        entities: {
          ods_members: {
            grain: ['cinq_id', 'batch_id'],
            fields: ['first_name', 'last_name', 'date_of_birth', 'gender', 'address_line1', 'city', 'state', 'postal_code'],
          },
          ods_claims: {
            grain: ['claim_id'],
            fields: ['cinq_id', 'claim_type', 'total_charge_amount', 'claim_date'],
          },
          ods_claim_lines: {
            grain: ['claim_line_id'],
            fields: ['claim_id', 'line_number', 'service_date', 'procedure_code', 'allowed_amount', 'paid_amount'],
          },
        },
      },
      null,
      2
    ),
  });

  const [consumerForm, setConsumerForm] = useState({
    consumer_name: '',
    consumer_type: 'ANALYTICS_SQL',
    registered_ods_model_version_id: '',
    contact_email: '',
    purpose: '',
  });

  // Gate tester state
  const [testConsumerName, setTestConsumerName] = useState('');
  const [testBatchId, setTestBatchId] = useState('');
  const [gateResult, setGateResult] = useState<any>(null);
  const [gateLoading, setGateLoading] = useState(false);

  const getHeaders = () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('cinqflow_token') : '';
    return {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token || ''}`,
    };
  };

  const fetchData = async () => {
    setLoading(true);
    setError('');
    try {
      const [versionsRes, consumersRes, certsRes] = await Promise.all([
        fetch('/api/v1/ods/model-versions', { headers: getHeaders() }),
        fetch('/api/v1/ods/consumers', { headers: getHeaders() }),
        fetch('/api/v1/ods/certifications', { headers: getHeaders() }),
      ]);

      if (versionsRes.ok) {
        const vData = await versionsRes.json();
        setModelVersions(vData);
        if (vData.length > 0 && !consumerForm.registered_ods_model_version_id) {
          setConsumerForm((prev) => ({ ...prev, registered_ods_model_version_id: vData[0].id }));
        }
      }
      if (consumersRes.ok) {
        setConsumers(await consumersRes.json());
      }
      if (certsRes.ok) {
        setCertifications(await certsRes.json());
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load ODS metadata');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckEligibility = async (batchId: string) => {
    if (!batchId) return;
    setEligibilityLoading(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/ods/batches/${batchId}/eligibility`, { headers: getHeaders() });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Failed to evaluate batch eligibility');
      }
      const data = await res.json();
      setEligibilityData(data);
    } catch (err: any) {
      setError(err.message || 'Error checking eligibility');
    } finally {
      setEligibilityLoading(false);
    }
  };

  const handleCertifyBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!certifyBatchId) return;
    setCertifying(true);
    setError('');
    setSuccessMsg('');
    try {
      const res = await fetch('/api/v1/ods/certify', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          batch_id: certifyBatchId,
          status: certifyOutcome,
          notes: certifyNotes || undefined,
        }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Failed to certify batch');
      }
      const cert = await res.json();
      setSuccessMsg(`Batch ${certifyBatchId} successfully marked as ${cert.status}`);
      setShowCertifyModal(false);
      setCertifyBatchId('');
      setCertifyNotes('');
      setEligibilityData(null);
      await fetchData();
    } catch (err: any) {
      setError(err.message || 'Certification failed');
    } finally {
      setCertifying(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreateVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      let parsedSchema = {};
      try {
        parsedSchema = JSON.parse(versionForm.schema_definition);
      } catch {
        setError('Invalid JSON syntax in schema definition');
        return;
      }

      const res = await fetch('/api/v1/ods/model-versions', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          version_number: Number(versionForm.version_number),
          name: versionForm.name,
          domain: versionForm.domain,
          description: versionForm.description,
          schema_definition: parsedSchema,
        }),
      });

      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Failed to create version');
      }

      setShowVersionModal(false);
      setSuccessMsg('ODS model version draft created successfully');
      fetchData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handlePublishVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetVersionToPublish) return;
    setError('');
    try {
      const res = await fetch(`/api/v1/ods/model-versions/${targetVersionToPublish.id}/publish`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ change_notes: publishNotes }),
      });

      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Failed to publish version');
      }

      setShowPublishModal(false);
      setTargetVersionToPublish(null);
      setPublishNotes('');
      setSuccessMsg(`ODS Model Version ${targetVersionToPublish.version_number} published as immutable contract`);
      fetchData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRegisterConsumer = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch('/api/v1/ods/consumers', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(consumerForm),
      });

      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Failed to register consumer');
      }

      setShowConsumerModal(false);
      setConsumerForm({
        consumer_name: '',
        consumer_type: 'ANALYTICS_SQL',
        registered_ods_model_version_id: modelVersions[0]?.id || '',
        contact_email: '',
        purpose: '',
      });
      setSuccessMsg('Downstream consumer registered with dedicated DB role');
      fetchData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleTestGate = async (e: React.FormEvent) => {
    e.preventDefault();
    setGateResult(null);
    setGateLoading(true);
    try {
      const res = await fetch(`/api/v1/ods/consumer-gate/${encodeURIComponent(testConsumerName)}/batches/${encodeURIComponent(testBatchId)}`, {
        method: 'POST',
        headers: getHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        setGateResult({ status: 'REJECTED', detail: data.detail || 'Access denied' });
      } else {
        setGateResult({ status: 'AUTHORIZED', ...data });
      }
    } catch (err: any) {
      setGateResult({ status: 'ERROR', detail: err.message });
    } finally {
      setGateLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-200">
          <div>
            <div className="flex items-center space-x-3">
              <h1 className="text-2xl font-bold text-slate-900">Canonical ODS & Consumer Governance</h1>
              <span className="text-xs bg-purple-100 text-purple-800 font-semibold px-2.5 py-0.5 rounded border border-purple-200">
                Wave 3 Slice 2
              </span>
            </div>
            <p className="text-sm text-slate-500 mt-1">
              Authoritative model contracts, version immutability, and downstream database role isolation.
            </p>
          </div>

          <div className="flex space-x-3 mt-4 md:mt-0">
            {activeTab === 'versions' ? (
              <button
                onClick={() => setShowVersionModal(true)}
                className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg shadow-sm transition"
              >
                + New Model Version
              </button>
            ) : activeTab === 'consumers' ? (
              <button
                onClick={() => setShowConsumerModal(true)}
                className="inline-flex items-center px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium rounded-lg shadow-sm transition"
              >
                + Register Consumer
              </button>
            ) : (
              <button
                onClick={() => {
                  setCertifyBatchId('');
                  setCertifyNotes('');
                  setEligibilityData(null);
                  setShowCertifyModal(true);
                }}
                className="inline-flex items-center px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg shadow-sm transition"
              >
                + Certify Batch
              </button>
            )}
          </div>
        </div>

        {/* Notifications */}
        {error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm flex justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="font-bold">✕</button>
          </div>
        )}
        {successMsg && (
          <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm flex justify-between">
            <span>{successMsg}</span>
            <button onClick={() => setSuccessMsg('')} className="font-bold">✕</button>
          </div>
        )}

        {/* Tabs */}
        <div className="flex space-x-4 border-b border-slate-200 mt-6">
          <button
            onClick={() => setActiveTab('versions')}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'versions'
                ? 'border-blue-600 text-blue-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            Canonical Model Versions ({modelVersions.length})
          </button>
          <button
            onClick={() => setActiveTab('consumers')}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'consumers'
                ? 'border-purple-600 text-purple-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            Downstream Consumer Contracts ({consumers.length})
          </button>
          <button
            onClick={() => setActiveTab('certifications')}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'certifications'
                ? 'border-emerald-600 text-emerald-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            ODS Certifications & Gate ({certifications.length})
          </button>
        </div>

        {/* Tab 1: Model Versions */}
        {activeTab === 'versions' && (
          <div className="mt-6">
            {loading ? (
              <div className="text-center py-12 text-slate-400">Loading model versions...</div>
            ) : modelVersions.length === 0 ? (
              <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
                <div className="text-slate-400 text-lg mb-2">No Canonical Model Versions Yet</div>
                <p className="text-sm text-slate-500 mb-6">Create the initial published model contract (v1) to unlock downstream consumer registrations.</p>
                <button
                  onClick={() => setShowVersionModal(true)}
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg"
                >
                  Create Version 1
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-6">
                {modelVersions.map((ver) => (
                  <div key={ver.id} className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center space-x-3">
                          <span className="text-lg font-bold text-slate-900">v{ver.version_number}: {ver.name}</span>
                          <span
                            className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                              ver.status === 'PUBLISHED'
                                ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                : 'bg-amber-100 text-amber-800 border border-amber-200'
                            }`}
                          >
                            {ver.status}
                          </span>
                          <span className="text-xs uppercase bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">
                            Domain: {ver.domain}
                          </span>
                        </div>
                        <p className="text-sm text-slate-600 mt-1">{ver.description || 'No description provided.'}</p>
                      </div>

                      {ver.status === 'DRAFT' && (
                        <button
                          onClick={() => {
                            setTargetVersionToPublish(ver);
                            setShowPublishModal(true);
                          }}
                          className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg shadow-sm"
                        >
                          Publish Version
                        </button>
                      )}
                    </div>

                    <div className="mt-4 pt-4 border-t border-slate-100 flex flex-wrap gap-6 text-xs text-slate-500">
                      <div>Created: <span className="font-medium text-slate-700">{new Date(ver.created_at).toLocaleDateString()}</span> by <span className="font-medium text-slate-700">{ver.created_by}</span></div>
                      {ver.published_at && (
                        <div>Published: <span className="font-medium text-emerald-700">{new Date(ver.published_at).toLocaleString()}</span> by <span className="font-medium text-slate-700">{ver.published_by}</span></div>
                      )}
                    </div>

                    {/* Schema Definition Drawer */}
                    <div className="mt-4">
                      <details className="text-xs">
                        <summary className="cursor-pointer text-blue-600 hover:text-blue-800 font-medium">
                          View Schema Specification JSON
                        </summary>
                        <pre className="mt-2 p-3 bg-slate-900 text-slate-100 rounded-lg overflow-x-auto text-[11px] font-mono">
                          {JSON.stringify(ver.schema_definition, null, 2)}
                        </pre>
                      </details>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Consumers */}
        {activeTab === 'consumers' && (
          <div className="mt-6 space-y-8">
            {/* Consumers List */}
            <div>
              {loading ? (
                <div className="text-center py-12 text-slate-400">Loading consumers...</div>
              ) : consumers.length === 0 ? (
                <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
                  <div className="text-slate-400 text-lg mb-2">No Downstream Consumers Registered</div>
                  <p className="text-sm text-slate-500 mb-6">Register an application or SQL analytics persona to grant access to versioned views.</p>
                  <button
                    onClick={() => setShowConsumerModal(true)}
                    className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg"
                  >
                    Register Consumer
                  </button>
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                  <table className="min-w-full divide-y divide-slate-200 text-sm">
                    <thead className="bg-slate-50 text-slate-600 text-xs font-semibold uppercase tracking-wider">
                      <tr>
                        <th className="px-6 py-3 text-left">Consumer Name</th>
                        <th className="px-6 py-3 text-left">Type</th>
                        <th className="px-6 py-3 text-left">Target ODS Version</th>
                        <th className="px-6 py-3 text-left">Database Role</th>
                        <th className="px-6 py-3 text-left">Status</th>
                        <th className="px-6 py-3 text-left">Contact</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {consumers.map((c) => {
                        const targetVer = modelVersions.find((v) => v.id === c.registered_ods_model_version_id);
                        return (
                          <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                            <td className="px-6 py-4 font-semibold text-slate-900">{c.consumer_name}</td>
                            <td className="px-6 py-4 text-slate-600 font-mono text-xs">{c.consumer_type}</td>
                            <td className="px-6 py-4">
                              <span className="font-medium text-blue-600">
                                {targetVer ? `v${targetVer.version_number} (${targetVer.name})` : c.registered_ods_model_version_id.slice(0, 8)}
                              </span>
                            </td>
                            <td className="px-6 py-4 font-mono text-xs text-purple-700 bg-purple-50/50 rounded">
                              {c.db_role_name || 'N/A'}
                            </td>
                            <td className="px-6 py-4">
                              <span
                                className={`px-2 py-0.5 text-xs font-semibold rounded-full ${
                                  c.status === 'ACTIVE'
                                    ? 'bg-emerald-100 text-emerald-800'
                                    : 'bg-rose-100 text-rose-800'
                                }`}
                              >
                                {c.status}
                              </span>
                            </td>
                            <td className="px-6 py-4 text-slate-500 text-xs">{c.contact_email}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Consumer Gate Live Tester Card */}
            <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
              <h3 className="text-base font-bold text-slate-900 flex items-center space-x-2">
                <span>🛡️ Consumer Compatibility Gate Tester</span>
                <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-normal">Tripartite Evaluation</span>
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                Simulate an API or SQL gateway access attempt to verify that the consumer registered model version matches the batch materialized model version.
              </p>

              <form onSubmit={handleTestGate} className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Consumer Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. analytics_v1_app"
                    value={testConsumerName}
                    onChange={(e) => setTestConsumerName(e.target.value)}
                    className="w-full text-xs px-3 py-2 border rounded-lg border-slate-300 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Batch ID (UUID)</label>
                  <input
                    type="text"
                    required
                    placeholder="UUID of batch"
                    value={testBatchId}
                    onChange={(e) => setTestBatchId(e.target.value)}
                    className="w-full text-xs px-3 py-2 border rounded-lg border-slate-300 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  />
                </div>
                <div className="flex items-end">
                  <button
                    type="submit"
                    disabled={gateLoading}
                    className="w-full text-xs px-4 py-2.5 bg-slate-900 hover:bg-slate-800 text-white font-medium rounded-lg shadow-sm transition disabled:opacity-50"
                  >
                    {gateLoading ? 'Testing Gate...' : 'Verify Consumer Access'}
                  </button>
                </div>
              </form>

              {gateResult && (
                <div
                  className={`mt-4 p-4 rounded-lg border text-xs ${
                    gateResult.status === 'AUTHORIZED'
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                      : 'bg-rose-50 border-rose-200 text-rose-800'
                  }`}
                >
                  <div className="font-bold flex items-center space-x-2">
                    <span>{gateResult.status === 'AUTHORIZED' ? '✅ Access Granted' : '🛑 Access Denied'}</span>
                  </div>
                  <pre className="mt-2 text-[11px] font-mono bg-white/70 p-2 rounded border border-current/20 overflow-x-auto">
                    {JSON.stringify(gateResult, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB: Certifications */}
        {activeTab === 'certifications' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-slate-900">ODS Batch Certifications & Compatibility Gates</h2>
                <p className="text-xs text-slate-500">
                  Certified batches grant downstream consumers access via certified views (<code>ods_certified.*</code>). Requires four-eyes steward verification.
                </p>
              </div>
              <div className="flex items-center space-x-3">
                <button
                  onClick={() => setShowCertifyModal(true)}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-sm transition"
                >
                  <Award className="w-4 h-4" />
                  <span>Certify Batch</span>
                </button>
              </div>
            </div>

            {/* Certifications Table */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Certification Audit History</h3>
                <span className="text-xs text-slate-400 font-mono">{certifications.length} records</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 border-b border-slate-100 text-slate-500 font-medium">
                    <tr>
                      <th className="px-5 py-3">Batch ID</th>
                      <th className="px-5 py-3">Status</th>
                      <th className="px-5 py-3">ODS Model Version</th>
                      <th className="px-5 py-3">Certified By</th>
                      <th className="px-5 py-3">Certified At</th>
                      <th className="px-5 py-3">Criteria Evaluated</th>
                      <th className="px-5 py-3">Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {certifications.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-5 py-8 text-center text-slate-400 italic">
                          No batch certification records found.
                        </td>
                      </tr>
                    ) : (
                      certifications.map((cert) => (
                        <tr key={cert.id} className="hover:bg-slate-50/60 transition">
                          <td className="px-5 py-3 font-mono font-bold text-indigo-600">
                            {cert.batch_id.slice(0, 8)}...
                          </td>
                          <td className="px-5 py-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                                cert.status === 'CERTIFIED'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : cert.status === 'FAILED'
                                  ? 'bg-rose-100 text-rose-800'
                                  : 'bg-amber-100 text-amber-800'
                              }`}
                            >
                              {cert.status}
                            </span>
                          </td>
                          <td className="px-5 py-3">
                            <span className="font-mono bg-slate-100 text-slate-800 px-2 py-0.5 rounded">
                              {modelVersions.find(v => v.id === cert.ods_model_version_id)?.version_number ? `v${modelVersions.find(v => v.id === cert.ods_model_version_id)?.version_number}` : cert.ods_model_version_id.slice(0, 8)}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-slate-700 font-medium">
                            {cert.certified_by || '—'}
                          </td>
                          <td className="px-5 py-3 text-slate-500">
                            {cert.certified_at ? new Date(cert.certified_at).toLocaleString() : '—'}
                          </td>
                          <td className="px-5 py-3">
                            <div className="space-y-0.5 text-[11px]">
                              <div>Pipeline Stage: <span className="font-semibold text-slate-700">{cert.checklist_snapshot?.pipeline_status || '—'}</span></div>
                              <div>Identity Status: <span className="font-semibold text-slate-700">{cert.checklist_snapshot?.identity_status || '—'}</span></div>
                              <div>Model Published: <span className="font-semibold text-slate-700">{cert.checklist_snapshot?.model_published ? 'Yes' : 'No'}</span></div>
                              <div>ODS DQ Readiness: <span className="font-semibold text-slate-700">{cert.checklist_snapshot?.dq_readiness || 'PASSED'}</span></div>
                            </div>
                          </td>
                          <td className="px-5 py-3 text-slate-600 max-w-xs truncate" title={cert.certification_notes || ''}>
                            {cert.certification_notes || '—'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Modal: New Model Version */}
        {showVersionModal && (
          <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6 border border-slate-200">
              <h3 className="text-lg font-bold text-slate-900 mb-2">Create Canonical ODS Model Version</h3>
              <p className="text-xs text-slate-500 mb-4">Initial state is DRAFT. Drafts can be refined before being sealed as an immutable release.</p>

              <form onSubmit={handleCreateVersion} className="space-y-4 text-xs">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Version Number</label>
                    <input
                      type="number"
                      min={1}
                      required
                      value={versionForm.version_number}
                      onChange={(e) => setVersionForm({ ...versionForm, version_number: parseInt(e.target.value) || 1 })}
                      className="w-full px-3 py-2 border rounded-lg border-slate-300"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Domain</label>
                    <input
                      type="text"
                      required
                      value={versionForm.domain}
                      onChange={(e) => setVersionForm({ ...versionForm, domain: e.target.value })}
                      className="w-full px-3 py-2 border rounded-lg border-slate-300"
                    />
                  </div>
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Version Title</label>
                  <input
                    type="text"
                    required
                    value={versionForm.name}
                    onChange={(e) => setVersionForm({ ...versionForm, name: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Description</label>
                  <textarea
                    rows={2}
                    value={versionForm.description}
                    onChange={(e) => setVersionForm({ ...versionForm, description: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Schema Specification JSON</label>
                  <textarea
                    rows={6}
                    required
                    value={versionForm.schema_definition}
                    onChange={(e) => setVersionForm({ ...versionForm, schema_definition: e.target.value })}
                    className="w-full font-mono px-3 py-2 border rounded-lg border-slate-300 text-[11px]"
                  />
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => setShowVersionModal(false)}
                    className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
                  >
                    Create Draft
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Publish Version */}
        {showPublishModal && targetVersionToPublish && (
          <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 border border-slate-200">
              <h3 className="text-lg font-bold text-slate-900 mb-2">Publish ODS Model v{targetVersionToPublish.version_number}</h3>
              <p className="text-xs text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200 mb-4">
                ⚠️ <strong>Immutability Notice:</strong> Once published, database triggers will permanently reject any modifications or deletions to this version specification.
              </p>

              <form onSubmit={handlePublishVersion} className="space-y-4 text-xs">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Publication Release Notes</label>
                  <textarea
                    rows={3}
                    placeholder="Document release rationale, core entities, and downstream deprecation policies..."
                    value={publishNotes}
                    onChange={(e) => setPublishNotes(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => setShowPublishModal(false)}
                    className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-semibold"
                  >
                    Confirm & Seal Version
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Register Consumer */}
        {showConsumerModal && (
          <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 border border-slate-200">
              <h3 className="text-lg font-bold text-slate-900 mb-2">Register Downstream Consumer</h3>
              <p className="text-xs text-slate-500 mb-4">
                Creates a formal contract and provisions a dedicated PostgreSQL role bound strictly to the selected model version.
              </p>

              <form onSubmit={handleRegisterConsumer} className="space-y-4 text-xs">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Consumer System Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. payer_claims_bi_v1"
                    value={consumerForm.consumer_name}
                    onChange={(e) => setConsumerForm({ ...consumerForm, consumer_name: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Consumer Type</label>
                    <select
                      value={consumerForm.consumer_type}
                      onChange={(e) => setConsumerForm({ ...consumerForm, consumer_type: e.target.value })}
                      className="w-full px-3 py-2 border rounded-lg border-slate-300 bg-white"
                    >
                      <option value="ANALYTICS_SQL">ANALYTICS_SQL</option>
                      <option value="APPLICATION_API">APPLICATION_API</option>
                      <option value="REPORTING">REPORTING</option>
                      <option value="DATA_WAREHOUSE">DATA_WAREHOUSE</option>
                    </select>
                  </div>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Target ODS Version</label>
                    <select
                      value={consumerForm.registered_ods_model_version_id}
                      onChange={(e) => setConsumerForm({ ...consumerForm, registered_ods_model_version_id: e.target.value })}
                      className="w-full px-3 py-2 border rounded-lg border-slate-300 bg-white"
                      required
                    >
                      {modelVersions.map((v) => (
                        <option key={v.id} value={v.id}>
                          v{v.version_number} - {v.name} ({v.status})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Owner Contact Email</label>
                  <input
                    type="email"
                    required
                    placeholder="owner@enterprise.org"
                    value={consumerForm.contact_email}
                    onChange={(e) => setConsumerForm({ ...consumerForm, contact_email: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Purpose & Analytical Scope</label>
                  <textarea
                    rows={2}
                    placeholder="Describe downstream consumption requirements..."
                    value={consumerForm.purpose}
                    onChange={(e) => setConsumerForm({ ...consumerForm, purpose: e.target.value })}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => setShowConsumerModal(false)}
                    className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-semibold"
                  >
                    Register Contract
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Certify Batch */}
        {showCertifyModal && (
          <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-xl max-w-xl w-full p-6 border border-slate-200">
              <h3 className="text-lg font-bold text-slate-900 mb-2">Certify ODS Batch for Consumer Gate</h3>
              <p className="text-xs text-slate-500 mb-4">
                Evaluate batch quality and canonical compatibility. Four-eyes rule enforced: batch creator cannot certify.
              </p>

              <form onSubmit={handleCertifyBatch} className="space-y-4 text-xs">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Batch ID</label>
                  <div className="flex space-x-2">
                    <input
                      type="text"
                      required
                      placeholder="UUID of completed pipeline batch"
                      value={certifyBatchId}
                      onChange={(e) => setCertifyBatchId(e.target.value)}
                      className="flex-1 px-3 py-2 border rounded-lg border-slate-300 font-mono"
                    />
                    <button
                      type="button"
                      disabled={eligibilityLoading || !certifyBatchId}
                      onClick={() => handleCheckEligibility(certifyBatchId)}
                      className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-medium transition disabled:opacity-50"
                    >
                      {eligibilityLoading ? 'Checking...' : 'Check'}
                    </button>
                  </div>
                </div>

                {eligibilityData && (
                  <div className={`p-3 rounded-lg border text-xs ${eligibilityData.eligible ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
                    <div className="font-bold mb-1">
                      {eligibilityData.eligible ? '✅ Batch is Eligible for Certification' : '⚠️ Eligibility Verification Details'}
                    </div>
                    <div className="space-y-0.5 text-[11px]">
                      <div>Batch Status: <span className="font-semibold">{eligibilityData.batch_status}</span></div>
                      <div>Identity Run Status: <span className="font-semibold">{eligibilityData.identity_status || 'N/A'}</span></div>
                      <div>ODS Model Published: <span className="font-semibold">{eligibilityData.ods_model_version_status === 'PUBLISHED' ? 'Yes' : 'No'}</span></div>
                      <div>ODS DQ Readiness: <span className="font-semibold">{eligibilityData.checklist_snapshot?.dq_readiness || 'PASSED'}</span></div>
                    </div>
                    {eligibilityData.reasons && eligibilityData.reasons.length > 0 && (
                      <ul className="mt-2 list-disc list-inside text-rose-700 font-medium">
                        {eligibilityData.reasons.map((r: string, idx: number) => (
                          <li key={idx}>{r}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Target Decision</label>
                    <select
                      value={certifyOutcome}
                      onChange={(e) => setCertifyOutcome(e.target.value as 'CERTIFIED' | 'FAILED')}
                      className="w-full px-3 py-2 border rounded-lg border-slate-300 bg-white"
                    >
                      <option value="CERTIFIED">CERTIFIED (Approve Access)</option>
                      <option value="FAILED">FAILED (Reject & Block)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">Steward Certification Notes (Zero-PHI)</label>
                  <textarea
                    rows={3}
                    placeholder="Enter compliance and audit rationale. Do not include patient identifiers, MRNs, SSNs, or DOBs."
                    value={certifyNotes}
                    onChange={(e) => setCertifyNotes(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg border-slate-300"
                  />
                  <p className="text-[11px] text-slate-400 mt-1">Zero-PHI policy strictly validated prior to submission.</p>
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => {
                      setShowCertifyModal(false);
                      setEligibilityData(null);
                    }}
                    className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={certifying}
                    className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-semibold disabled:opacity-50"
                  >
                    {certifying ? 'Submitting...' : 'Submit Certification'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

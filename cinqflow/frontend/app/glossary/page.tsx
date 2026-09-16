'use client';
import { useState, useEffect, useMemo } from 'react';
import Navbar from '@/components/Navbar';
import { 
  BookOpen, Search, Filter, Plus, CheckCircle, AlertTriangle, ShieldAlert,
  Tag, Link2, X, ExternalLink, RefreshCw, Trash2, ArrowRight
} from 'lucide-react';

interface CanonicalFieldLink {
  link_id: string;
  canonical_field_id: string;
  canonical_field_name: string;
  canonical_model_id: string;
  canonical_model_name: string;
  data_type: string;
  is_required: boolean;
  is_nullable: boolean;
}

interface GlossaryTerm {
  id: string;
  name: string;
  normalized_name: string;
  acronym?: string;
  synonyms: string[];
  domain: string;
  definition: string;
  clinical_context?: string;
  data_steward?: string;
  status: 'DRAFT' | 'APPROVED' | 'DEPRECATED';
  phi_classification: 'NONE' | 'POTENTIAL_PHI' | 'CONFIRMED_PHI';
  code_set: string;
  deprecation_reason?: string;
  linked_canonical_fields_count: number;
  linked_canonical_fields: CanonicalFieldLink[];
  created_at: string;
  version: number;
}

interface UserProfile {
  email: string;
  roles: string[];
}

interface CanonicalModelItem {
  id: string;
  name: string;
  fields: { id: string; field_name: string; data_type: string }[];
}

export default function GlossaryPage() {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [user, setUser] = useState<UserProfile | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('ALL');
  const [selectedPhi, setSelectedPhi] = useState('ALL');
  const [selectedStatus, setSelectedStatus] = useState('ALL');
  const [selectedCodeSet, setSelectedCodeSet] = useState('ALL');

  // Selected Term Drawer
  const [selectedTerm, setSelectedTerm] = useState<GlossaryTerm | null>(null);

  // Modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDeprecateModal, setShowDeprecateModal] = useState(false);
  const [deprecationReason, setDeprecateReason] = useState('');

  // Canonical Model References for Linking
  const [canonicalModels, setCanonicalModels] = useState<CanonicalModelItem[]>([]);
  const [selectedFieldToLink, setSelectedFieldToLink] = useState('');

  // New Term Form
  const [newTerm, setNewTerm] = useState({
    name: '',
    acronym: '',
    synonyms: '',
    domain: 'Clinical',
    definition: '',
    clinical_context: '',
    phi_classification: 'NONE',
    code_set: 'NONE',
  });

  const isReadOnly = user?.roles?.includes('READ_ONLY') && !user?.roles?.includes('ENGINEER') && !user?.roles?.includes('DATA_STEWARD');
  const isStewardOrEngineer = user?.roles?.includes('DATA_STEWARD') || user?.roles?.includes('ENGINEER');

  useEffect(() => {
    fetchUser();
    fetchTerms();
    fetchCanonicalModels();
  }, []);

  const fetchUser = () => {
    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUser(data))
      .catch(() => setUser(null));
  };

  const fetchTerms = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/glossary', {
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        const data = await res.json();
        setTerms(data.items || []);
      } else {
        setError('Failed to load glossary terms');
      }
    } catch {
      setError('Connection error loading glossary');
    } finally {
      setLoading(false);
    }
  };

  const fetchCanonicalModels = async () => {
    try {
      const res = await fetch('/api/v1/canonical-models', {
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        const data = await res.json();
        setCanonicalModels(data || []);
      }
    } catch {
      // Non-critical
    }
  };

  const handleBootstrapSeed = async () => {
    try {
      const res = await fetch('/api/v1/glossary/seed/bootstrap', {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        await fetchTerms();
      }
    } catch {
      setError('Seed failed');
    }
  };

  const handleCreateTerm = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        name: newTerm.name,
        acronym: newTerm.acronym || undefined,
        synonyms: newTerm.synonyms ? newTerm.synonyms.split(',').map((s) => s.trim()) : [],
        domain: newTerm.domain,
        definition: newTerm.definition,
        clinical_context: newTerm.clinical_context || undefined,
        phi_classification: newTerm.phi_classification,
        code_set: newTerm.code_set,
      };

      const res = await fetch('/api/v1/glossary', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}`,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Failed to create term');
        return;
      }

      setShowCreateModal(false);
      setNewTerm({
        name: '',
        acronym: '',
        synonyms: '',
        domain: 'Clinical',
        definition: '',
        clinical_context: '',
        phi_classification: 'NONE',
        code_set: 'NONE',
      });
      await fetchTerms();
    } catch {
      alert('Error creating term');
    }
  };

  const handleApprove = async (termId: string) => {
    try {
      const res = await fetch(`/api/v1/glossary/${termId}/approve`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        const updated = await res.json();
        setSelectedTerm(updated);
        await fetchTerms();
      } else {
        const err = await res.json();
        alert(err.detail || 'Approval failed');
      }
    } catch {
      alert('Network error');
    }
  };

  const handleDeprecate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTerm) return;

    try {
      const res = await fetch(`/api/v1/glossary/${selectedTerm.id}/deprecate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}`,
        },
        body: JSON.stringify({ deprecation_reason: deprecationReason }),
      });

      if (res.ok) {
        const updated = await res.json();
        setSelectedTerm(updated);
        setShowDeprecateModal(false);
        setDeprecateReason('');
        await fetchTerms();
      } else {
        const err = await res.json();
        alert(err.detail || 'Deprecation failed');
      }
    } catch {
      alert('Network error');
    }
  };

  const handleDeleteDraft = async (termId: string) => {
    if (!confirm('Are you sure you want to delete this draft term?')) return;
    try {
      const res = await fetch(`/api/v1/glossary/${termId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        setSelectedTerm(null);
        await fetchTerms();
      } else {
        const err = await res.json();
        alert(err.detail || 'Delete failed');
      }
    } catch {
      alert('Network error');
    }
  };

  const handleLinkCanonical = async () => {
    if (!selectedTerm || !selectedFieldToLink) return;
    try {
      const res = await fetch(`/api/v1/glossary/${selectedTerm.id}/links`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}`,
        },
        body: JSON.stringify({ canonical_field_id: selectedFieldToLink }),
      });

      if (res.ok) {
        // Refresh term detail
        const termRes = await fetch(`/api/v1/glossary/${selectedTerm.id}`, {
          headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
        });
        if (termRes.ok) {
          const updated = await termRes.json();
          setSelectedTerm(updated);
        }
        setSelectedFieldToLink('');
        await fetchTerms();
      } else {
        const err = await res.json();
        alert(err.detail || 'Link failed');
      }
    } catch {
      alert('Network error');
    }
  };

  const handleUnlink = async (fieldId: string) => {
    if (!selectedTerm) return;
    try {
      const res = await fetch(`/api/v1/glossary/${selectedTerm.id}/links/${fieldId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
      });
      if (res.ok) {
        const termRes = await fetch(`/api/v1/glossary/${selectedTerm.id}`, {
          headers: { Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}` },
        });
        if (termRes.ok) {
          const updated = await termRes.json();
          setSelectedTerm(updated);
        }
        await fetchTerms();
      }
    } catch {
      alert('Network error');
    }
  };

  // Filtered terms
  const filteredTerms = useMemo(() => {
    return terms.filter((term) => {
      const matchesSearch =
        !searchQuery ||
        term.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (term.acronym && term.acronym.toLowerCase().includes(searchQuery.toLowerCase())) ||
        term.definition.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesDomain = selectedDomain === 'ALL' || term.domain === selectedDomain;
      const matchesPhi = selectedPhi === 'ALL' || term.phi_classification === selectedPhi;
      const matchesStatus = selectedStatus === 'ALL' || term.status === selectedStatus;
      const matchesCodeSet = selectedCodeSet === 'ALL' || term.code_set === selectedCodeSet;

      return matchesSearch && matchesDomain && matchesPhi && matchesStatus && matchesCodeSet;
    });
  }, [terms, searchQuery, selectedDomain, selectedPhi, selectedStatus, selectedCodeSet]);

  const stats = useMemo(() => {
    const approved = terms.filter((t) => t.status === 'APPROVED').length;
    const draft = terms.filter((t) => t.status === 'DRAFT').length;
    const phi = terms.filter((t) => t.phi_classification === 'CONFIRMED_PHI').length;
    return { total: terms.length, approved, draft, phi };
  }, [terms]);

  const allAvailableFields = useMemo(() => {
    const fields: { id: string; label: string }[] = [];
    canonicalModels.forEach((model) => {
      model.fields?.forEach((f) => {
        fields.push({ id: f.id, label: `${model.name}.${f.field_name} (${f.data_type})` });
      });
    });
    return fields;
  }, [canonicalModels]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-800 gap-4">
          <div>
            <div className="flex items-center gap-2">
              <BookOpen className="w-8 h-8 text-blue-400" />
              <h1 className="text-2xl font-bold tracking-tight text-white">Enterprise Business Glossary</h1>
              <span className="text-xs bg-blue-900/60 text-blue-300 px-2 py-0.5 rounded border border-blue-700">Wave 1 Slice 7</span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Authoritative healthcare terminology, clinical definitions, PHI classifications, and canonical model linkages.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {isReadOnly && (
              <span className="text-xs bg-amber-900/40 text-amber-300 border border-amber-800 px-3 py-1 rounded-full flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" /> Read-Only Mode
              </span>
            )}
            {isStewardOrEngineer && (
              <button
                onClick={handleBootstrapSeed}
                className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 flex items-center gap-1.5 transition-colors"
                title="Seed core healthcare terms if empty"
              >
                <RefreshCw className="w-3.5 h-3.5 text-blue-400" /> Seed Standard Dictionary
              </button>
            )}
            {!isReadOnly && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg shadow-sm flex items-center gap-2 transition-colors"
              >
                <Plus className="w-4 h-4" /> Propose New Term
              </button>
            )}
          </div>
        </div>

        {/* Stats Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 my-6">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 uppercase tracking-wider">Total Defined Terms</span>
            <div className="text-2xl font-bold text-white mt-1">{stats.total}</div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 uppercase tracking-wider">Approved Standards</span>
            <div className="text-2xl font-bold text-emerald-400 mt-1">{stats.approved}</div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 uppercase tracking-wider">Draft Proposals</span>
            <div className="text-2xl font-bold text-amber-400 mt-1">{stats.draft}</div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 uppercase tracking-wider">Confirmed PHI Terms</span>
            <div className="text-2xl font-bold text-rose-400 mt-1">{stats.phi}</div>
          </div>
        </div>

        {/* Search & Filter Controls */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6 flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
            <input
              type="text"
              placeholder="Search by term name, acronym, or clinical definition..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={selectedDomain}
              onChange={(e) => setSelectedDomain(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value="ALL">All Domains</option>
              <option value="Eligibility">Eligibility</option>
              <option value="Claims">Claims</option>
              <option value="Clinical">Clinical</option>
              <option value="Provider">Provider</option>
              <option value="Financial">Financial</option>
              <option value="Common">Common</option>
            </select>

            <select
              value={selectedPhi}
              onChange={(e) => setSelectedPhi(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value="ALL">All PHI Levels</option>
              <option value="NONE">No PHI</option>
              <option value="POTENTIAL_PHI">Potential PHI</option>
              <option value="CONFIRMED_PHI">Confirmed PHI</option>
            </select>

            <select
              value={selectedCodeSet}
              onChange={(e) => setSelectedCodeSet(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value="ALL">All Code Sets</option>
              <option value="NONE">None</option>
              <option value="LOINC">LOINC</option>
              <option value="NPI">NPI</option>
              <option value="ICD_10">ICD-10</option>
              <option value="CPT">CPT</option>
              <option value="SNOMED_CT">SNOMED CT</option>
              <option value="NDC">NDC</option>
            </select>

            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500"
            >
              <option value="ALL">All Statuses</option>
              <option value="APPROVED">Approved</option>
              <option value="DRAFT">Draft</option>
              <option value="DEPRECATED">Deprecated</option>
            </select>
          </div>
        </div>

        {/* Content Layout: Term Cards & Detail Drawer */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Term List */}
          <div className="lg:col-span-2 space-y-3">
            {loading ? (
              <div className="text-center py-12 text-slate-500 text-sm">Loading terminology dictionary...</div>
            ) : filteredTerms.length === 0 ? (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
                <BookOpen className="w-10 h-10 text-slate-600 mx-auto mb-2" />
                <h3 className="text-base font-semibold text-slate-300">No glossary terms found</h3>
                <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
                  Try adjusting search parameters or click "Seed Standard Dictionary" to load healthcare core terminology.
                </p>
              </div>
            ) : (
              filteredTerms.map((term) => {
                const isSelected = selectedTerm?.id === term.id;
                return (
                  <div
                    key={term.id}
                    onClick={() => setSelectedTerm(term)}
                    className={`bg-slate-900 border rounded-xl p-5 cursor-pointer transition-all hover:border-slate-700 ${
                      isSelected ? 'border-blue-500 bg-slate-900/90 shadow-md shadow-blue-500/10' : 'border-slate-800'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-white text-base">{term.name}</h3>
                          {term.acronym && (
                            <span className="text-xs font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
                              {term.acronym}
                            </span>
                          )}
                          <span className="text-xs font-medium text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded">
                            {term.domain}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {term.phi_classification === 'CONFIRMED_PHI' && (
                          <span className="text-xs bg-rose-950/70 text-rose-300 border border-rose-800 px-2 py-0.5 rounded font-medium flex items-center gap-1">
                            <ShieldAlert className="w-3 h-3" /> PHI
                          </span>
                        )}
                        {term.phi_classification === 'POTENTIAL_PHI' && (
                          <span className="text-xs bg-amber-950/70 text-amber-300 border border-amber-800 px-2 py-0.5 rounded font-medium">
                            Potential PHI
                          </span>
                        )}
                        {term.code_set !== 'NONE' && (
                          <span className="text-xs bg-indigo-950/70 text-indigo-300 border border-indigo-800 px-2 py-0.5 rounded font-medium font-mono">
                            {term.code_set}
                          </span>
                        )}
                        <span
                          className={`text-xs px-2.5 py-0.5 rounded-full font-semibold ${
                            term.status === 'APPROVED'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : term.status === 'DRAFT'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          {term.status}
                        </span>
                      </div>
                    </div>

                    <p className="text-sm text-slate-300 mt-2 line-clamp-2 leading-relaxed">{term.definition}</p>

                    {/* Linked Canonical Fields */}
                    {term.linked_canonical_fields_count > 0 && (
                      <div className="mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center gap-2">
                        <span className="text-xs text-slate-400 flex items-center gap-1">
                          <Link2 className="w-3 h-3 text-blue-400" /> Linked Canonical:
                        </span>
                        {term.linked_canonical_fields.map((lf) => (
                          <span
                            key={lf.link_id}
                            className="text-xs bg-blue-950/40 text-blue-300 border border-blue-900/60 px-2 py-0.5 rounded font-mono"
                          >
                            {lf.canonical_model_name}.{lf.canonical_field_name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Selected Term Detail Panel */}
          <div className="lg:col-span-1">
            {selectedTerm ? (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 sticky top-6 space-y-5">
                <div className="flex items-start justify-between">
                  <div>
                    <span className="text-xs uppercase tracking-wider text-slate-400">Term Detail</span>
                    <h2 className="text-xl font-bold text-white mt-0.5">{selectedTerm.name}</h2>
                    {selectedTerm.acronym && (
                      <span className="text-xs font-mono text-slate-400">Acronym: {selectedTerm.acronym}</span>
                    )}
                  </div>
                  <button
                    onClick={() => setSelectedTerm(null)}
                    className="text-slate-400 hover:text-slate-200 p-1"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1">Official Definition</h4>
                  <p className="text-sm text-slate-200 bg-slate-950 p-3 rounded-lg border border-slate-800 leading-relaxed">
                    {selectedTerm.definition}
                  </p>
                </div>

                {selectedTerm.clinical_context && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1">Clinical Context</h4>
                    <p className="text-xs text-slate-400 bg-slate-950/50 p-3 rounded-lg border border-slate-800/80 leading-relaxed">
                      {selectedTerm.clinical_context}
                    </p>
                  </div>
                )}

                {selectedTerm.synonyms && selectedTerm.synonyms.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Synonyms / Aliases</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedTerm.synonyms.map((syn, idx) => (
                        <span key={idx} className="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                          {syn}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Classification Metadata */}
                <div className="grid grid-cols-2 gap-3 text-xs bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <div>
                    <span className="text-slate-500">Domain:</span>
                    <p className="font-semibold text-slate-300 mt-0.5">{selectedTerm.domain}</p>
                  </div>
                  <div>
                    <span className="text-slate-500">PHI Sensitivity:</span>
                    <p className="font-semibold text-slate-300 mt-0.5">{selectedTerm.phi_classification}</p>
                  </div>
                  <div>
                    <span className="text-slate-500">Standard Code Set:</span>
                    <p className="font-semibold text-slate-300 mt-0.5">{selectedTerm.code_set}</p>
                  </div>
                  <div>
                    <span className="text-slate-500">Governance Version:</span>
                    <p className="font-semibold text-slate-300 mt-0.5">v{selectedTerm.version}</p>
                  </div>
                </div>

                {selectedTerm.deprecation_reason && (
                  <div className="bg-rose-950/40 border border-rose-900/60 p-3 rounded-lg text-xs">
                    <span className="font-semibold text-rose-300">Deprecation Reason:</span>
                    <p className="text-rose-200 mt-0.5">{selectedTerm.deprecation_reason}</p>
                  </div>
                )}

                {/* Linked Canonical Fields */}
                <div>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase mb-2 flex items-center justify-between">
                    <span>Linked Canonical Fields ({selectedTerm.linked_canonical_fields_count})</span>
                  </h4>
                  <div className="space-y-2">
                    {selectedTerm.linked_canonical_fields.map((lf) => (
                      <div
                        key={lf.link_id}
                        className="flex items-center justify-between p-2 bg-slate-950 rounded-lg border border-slate-800 text-xs"
                      >
                        <div>
                          <span className="font-semibold text-blue-300 font-mono">
                            {lf.canonical_model_name}.{lf.canonical_field_name}
                          </span>
                          <span className="text-slate-500 ml-1.5 font-mono">({lf.data_type})</span>
                        </div>
                        {!isReadOnly && (
                          <button
                            onClick={() => handleUnlink(lf.canonical_field_id)}
                            className="text-slate-500 hover:text-rose-400 p-1"
                            title="Unlink field"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Add Link Dropdown */}
                  {!isReadOnly && (
                    <div className="mt-3 flex gap-2">
                      <select
                        value={selectedFieldToLink}
                        onChange={(e) => setSelectedFieldToLink(e.target.value)}
                        className="flex-1 bg-slate-950 border border-slate-700 text-xs rounded-lg px-2 py-1.5 text-slate-200 focus:outline-none"
                      >
                        <option value="">Select Canonical Field to Link...</option>
                        {allAvailableFields.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={handleLinkCanonical}
                        disabled={!selectedFieldToLink}
                        className="px-2.5 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium"
                      >
                        Link
                      </button>
                    </div>
                  )}
                </div>

                {/* Governance Actions */}
                {!isReadOnly && (
                  <div className="pt-4 border-t border-slate-800 space-y-2">
                    {selectedTerm.status === 'DRAFT' && isStewardOrEngineer && (
                      <button
                        onClick={() => handleApprove(selectedTerm.id)}
                        className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm"
                      >
                        <CheckCircle className="w-4 h-4" /> Approve as Enterprise Standard
                      </button>
                    )}

                    {selectedTerm.status === 'APPROVED' && isStewardOrEngineer && (
                      <button
                        onClick={() => setShowDeprecateModal(true)}
                        className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-rose-300 border border-rose-900/60 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5"
                      >
                        <AlertTriangle className="w-4 h-4 text-rose-400" /> Deprecate Term
                      </button>
                    )}

                    {selectedTerm.status === 'DRAFT' && (
                      <button
                        onClick={() => handleDeleteDraft(selectedTerm.id)}
                        className="w-full py-2 bg-slate-800 hover:bg-rose-950/40 text-slate-400 hover:text-rose-300 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Discard Draft Term
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-8 text-center text-slate-500 text-sm">
                Select a business term from the catalog to view clinical guidelines, data steward ownership, and linked canonical schema attributes.
              </div>
            )}
          </div>
        </div>

        {/* Modal: Create Term */}
        {showCreateModal && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="font-bold text-white text-base">Propose Business Glossary Term</h3>
                <button onClick={() => setShowCreateModal(false)} className="text-slate-400 hover:text-slate-200">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleCreateTerm} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Term Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g., Claim Adjudication Date"
                    value={newTerm.name}
                    onChange={(e) => setNewTerm({ ...newTerm, name: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Acronym / Abbreviation</label>
                    <input
                      type="text"
                      placeholder="e.g., CAD"
                      value={newTerm.acronym}
                      onChange={(e) => setNewTerm({ ...newTerm, acronym: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Domain *</label>
                    <select
                      value={newTerm.domain}
                      onChange={(e) => setNewTerm({ ...newTerm, domain: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    >
                      <option value="Eligibility">Eligibility</option>
                      <option value="Claims">Claims</option>
                      <option value="Clinical">Clinical</option>
                      <option value="Provider">Provider</option>
                      <option value="Financial">Financial</option>
                      <option value="Common">Common</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Business / Clinical Definition *</label>
                  <textarea
                    required
                    rows={3}
                    placeholder="Provide unambiguous, standard business definition..."
                    value={newTerm.definition}
                    onChange={(e) => setNewTerm({ ...newTerm, definition: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Clinical Context & Guidelines</label>
                  <input
                    type="text"
                    placeholder="Usage in pipelines, EDI 837, or EMR interoperability"
                    value={newTerm.clinical_context}
                    onChange={(e) => setNewTerm({ ...newTerm, clinical_context: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">PHI Sensitivity</label>
                    <select
                      value={newTerm.phi_classification}
                      onChange={(e) => setNewTerm({ ...newTerm, phi_classification: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    >
                      <option value="NONE">None</option>
                      <option value="POTENTIAL_PHI">Potential PHI</option>
                      <option value="CONFIRMED_PHI">Confirmed PHI</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Code Set Standard</label>
                    <select
                      value={newTerm.code_set}
                      onChange={(e) => setNewTerm({ ...newTerm, code_set: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                    >
                      <option value="NONE">None</option>
                      <option value="LOINC">LOINC</option>
                      <option value="NPI">NPI</option>
                      <option value="ICD_10">ICD-10</option>
                      <option value="CPT">CPT</option>
                      <option value="SNOMED_CT">SNOMED CT</option>
                      <option value="NDC">NDC</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Synonyms (comma separated)</label>
                  <input
                    type="text"
                    placeholder="Adjudication Date, Process Date"
                    value={newTerm.synonyms}
                    onChange={(e) => setNewTerm({ ...newTerm, synonyms: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
                  >
                    Create Term (DRAFT)
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Deprecate Term */}
        {showDeprecateModal && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <h3 className="font-bold text-white text-base">Deprecate Glossary Term</h3>
                <button onClick={() => setShowDeprecateModal(false)} className="text-slate-400 hover:text-slate-200">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleDeprecate} className="space-y-4">
                <p className="text-xs text-slate-400">
                  Retiring <span className="font-semibold text-white">{selectedTerm?.name}</span>. A mandatory deprecation reason is required for governance lineage.
                </p>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Deprecation Reason *</label>
                  <textarea
                    required
                    rows={3}
                    placeholder="Explain why this term is being retired or superseded..."
                    value={deprecationReason}
                    onChange={(e) => setDeprecateReason(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-rose-500"
                  />
                </div>

                <div className="pt-3 border-t border-slate-800 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowDeprecateModal(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white rounded-lg"
                  >
                    Confirm Deprecation
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

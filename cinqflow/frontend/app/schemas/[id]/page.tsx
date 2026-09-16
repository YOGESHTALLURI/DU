'use client';
import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';

interface SchemaField {
  id?: string;
  field_name: string;
  ordinal_position: number;
  data_type: string;
  is_nullable: boolean;
  is_required: boolean;
  format_pattern: string | null;
  description: string | null;
  source_metadata: any;
}

interface SchemaVersion {
  id: string;
  schema_id: string;
  version_number: number;
  status: string;
  change_notes: string | null;
  source_profiling_run_id: string | null;
  source_sample_file_id: string | null;
  published_by: string | null;
  published_at: string | null;
  created_at: string;
  fields: SchemaField[];
}

interface SchemaDetail {
  id: string;
  feed_id: string;
  name: string;
  description: string | null;
  created_at: string;
  active_version: SchemaVersion | null;
  draft_version: SchemaVersion | null;
}

const DATA_TYPES = ['STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'TIMESTAMP'];

export default function SchemaContractDetailPage() {
  const params = useParams();
  const schemaId = params?.id as string;
  const [schema, setSchema] = useState<SchemaDetail | null>(null);
  const [versions, setVersions] = useState<SchemaVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>('');
  const [currentVersion, setCurrentVersion] = useState<SchemaVersion | null>(null);
  const [fields, setFields] = useState<SchemaField[]>([]);
  const [changeNotes, setChangeNotes] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchSchemaData = () => {
    if (!schemaId) return;
    const token = localStorage.getItem('cinqflow_token');
    const headers = { Authorization: `Bearer ${token || ''}` };

    Promise.all([
      fetch(`/api/v1/schemas/${schemaId}`, { headers }).then((r) => r.json()),
      fetch(`/api/v1/schemas/${schemaId}/versions`, { headers }).then((r) => r.json()),
    ])
      .then(([schemaData, versionsData]) => {
        setSchema(schemaData);
        setVersions(versionsData);

        // Default to draft version if available, else active version, else first
        const defaultVer =
          schemaData.draft_version ||
          schemaData.active_version ||
          versionsData[versionsData.length - 1];

        if (defaultVer) {
          setSelectedVersionId(defaultVer.id);
          setCurrentVersion(defaultVer);
          setFields(defaultVer.fields || []);
          setChangeNotes(defaultVer.change_notes || '');
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSchemaData();
  }, [schemaId]);

  const handleVersionSelect = (vId: string) => {
    setSelectedVersionId(vId);
    const ver = versions.find((v) => v.id === vId);
    if (ver) {
      setCurrentVersion(ver);
      setFields(ver.fields || []);
      setChangeNotes(ver.change_notes || '');
      setError('');
      setSuccess('');
    }
  };

  const handleFieldChange = (index: number, key: keyof SchemaField, value: any) => {
    const updated = [...fields];
    updated[index] = { ...updated[index], [key]: value };
    setFields(updated);
  };

  const handleAddField = () => {
    const newField: SchemaField = {
      field_name: `new_field_${fields.length + 1}`,
      ordinal_position: fields.length + 1,
      data_type: 'STRING',
      is_nullable: true,
      is_required: false,
      format_pattern: null,
      description: '',
      source_metadata: null,
    };
    setFields([...fields, newField]);
  };

  const handleRemoveField = (index: number) => {
    const updated = fields.filter((_, i) => i !== index).map((f, i) => ({ ...f, ordinal_position: i + 1 }));
    setFields(updated);
  };

  const handleSaveDraft = async () => {
    if (!currentVersion || currentVersion.status !== 'DRAFT') return;
    setSaving(true);
    setError('');
    setSuccess('');

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/schemas/${schemaId}/versions/${currentVersion.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({
          change_notes: changeNotes,
          fields: fields.map((f) => ({
            field_name: f.field_name,
            ordinal_position: f.ordinal_position,
            data_type: f.data_type,
            is_nullable: f.is_nullable,
            is_required: f.is_required,
            format_pattern: f.format_pattern || null,
            description: f.description || null,
            source_metadata: f.source_metadata,
          })),
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Save failed' }));
        setError(err.detail || 'Save failed');
        return;
      }

      setSuccess('Draft version saved successfully.');
      fetchSchemaData();
    } catch {
      setError('Connection error saving draft.');
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async () => {
    if (!currentVersion || currentVersion.status !== 'DRAFT') return;
    if (!confirm('Are you sure you want to publish this schema version? Published versions are permanently locked and cannot be edited.')) {
      return;
    }

    setPublishing(true);
    setError('');
    setSuccess('');

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/schemas/${schemaId}/versions/${currentVersion.id}/publish`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ change_notes: changeNotes }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Publish failed' }));
        setError(err.detail || 'Publish failed');
        return;
      }

      setSuccess('Schema version published! It is now immutable.');
      fetchSchemaData();
    } catch {
      setError('Connection error publishing version.');
    } finally {
      setPublishing(false);
    }
  };

  const handleNewDraftFromCurrent = async () => {
    if (!currentVersion) return;
    setSaving(true);
    setError('');
    setSuccess('');

    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/schemas/${schemaId}/versions/${currentVersion.id}/new-draft`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token || ''}`,
        },
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to create new draft' }));
        setError(err.detail || 'Failed to create new draft');
        return;
      }

      setSuccess('New incremented draft version created.');
      fetchSchemaData();
    } catch {
      setError('Connection error creating draft.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-xs text-slate-400">Loading schema details...</div>
      </div>
    );
  }

  if (!schema || !currentVersion) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-8 text-xs text-rose-400">Schema not found.</div>
      </div>
    );
  }

  const isDraft = currentVersion.status === 'DRAFT';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href={`/feeds/${schema.feed_id}/schemas`} className="text-xs text-blue-400 hover:underline">
              &larr; Back to Feed Schemas
            </Link>
            <div className="flex items-center space-x-3 mt-1">
              <h1 className="text-2xl font-bold text-white font-mono">{schema.name}</h1>
              <span
                className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                  isDraft
                    ? 'bg-amber-950 text-amber-400 border border-amber-800'
                    : 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                }`}
              >
                v{currentVersion.version_number} ({currentVersion.status})
              </span>
            </div>
            {currentVersion.source_profiling_run_id && (
              <p className="text-xs text-indigo-400 mt-1 font-mono">
                Lineage: Seeded from Profiling Run{' '}
                <Link href={`/profiling/${currentVersion.source_profiling_run_id}`} className="underline">
                  {currentVersion.source_profiling_run_id.slice(0, 8)}
                </Link>
              </p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex space-x-3">
            {isDraft ? (
              <>
                <button
                  onClick={handleSaveDraft}
                  disabled={saving}
                  className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-2 rounded-lg text-xs font-medium transition"
                >
                  {saving ? 'Saving...' : 'Save Draft'}
                </button>
                <button
                  onClick={handlePublish}
                  disabled={publishing}
                  className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition"
                >
                  {publishing ? 'Publishing...' : 'Publish (Lock Version)'}
                </button>
              </>
            ) : (
              <button
                onClick={handleNewDraftFromCurrent}
                disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition"
              >
                Create New Draft from v{currentVersion.version_number} &rarr;
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-rose-950/60 border border-rose-800 rounded-xl text-rose-300 text-xs">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-6 p-4 bg-emerald-950/60 border border-emerald-800 rounded-xl text-emerald-300 text-xs">
            {success}
          </div>
        )}

        {/* Version Switcher Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <span className="text-xs text-slate-400 uppercase font-semibold">Select Version:</span>
            <div className="flex space-x-2">
              {versions.map((v) => (
                <button
                  key={v.id}
                  onClick={() => handleVersionSelect(v.id)}
                  className={`px-3 py-1 rounded text-xs font-mono font-medium transition ${
                    v.id === selectedVersionId
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white'
                  }`}
                >
                  v{v.version_number} ({v.status})
                </button>
              ))}
            </div>
          </div>

          <div className="text-xs text-slate-400 font-mono">
            {isDraft ? (
              <span className="text-amber-400">Draft Mode: Editable</span>
            ) : (
              <span className="text-emerald-400">Locked: Published by {currentVersion.published_by}</span>
            )}
          </div>
        </div>

        {/* Change Notes */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
          <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
            Change Notes
          </label>
          {isDraft ? (
            <input
              type="text"
              value={changeNotes}
              onChange={(e) => setChangeNotes(e.target.value)}
              placeholder="e.g. Added middle_name column and made SSN required"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-xs text-white font-mono"
            />
          ) : (
            <p className="text-xs text-slate-300 font-mono">{currentVersion.change_notes || 'No change notes provided.'}</p>
          )}
        </div>

        {/* Field Contract Specification Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
                Field Contract Specification ({fields.length} fields)
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Defines what CINQFLOW expects from the incoming data feed.
              </p>
            </div>
            {isDraft && (
              <button
                onClick={handleAddField}
                className="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-xs font-medium transition"
              >
                + Add Field
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-medium">
                  <th className="pb-3">#</th>
                  <th className="pb-3">Field Name</th>
                  <th className="pb-3">Schema Decision (Type)</th>
                  <th className="pb-3">Profiling Fact (Inferred)</th>
                  <th className="pb-3">Nullable</th>
                  <th className="pb-3">Required</th>
                  <th className="pb-3">Format / Pattern</th>
                  <th className="pb-3">Description</th>
                  {isDraft && <th className="pb-3 text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {fields.map((f, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-3 font-mono text-slate-500">{f.ordinal_position}</td>
                    <td className="py-3 font-mono font-bold text-white">
                      {isDraft ? (
                        <input
                          type="text"
                          value={f.field_name}
                          onChange={(e) => handleFieldChange(idx, 'field_name', e.target.value)}
                          className="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs font-mono text-white w-40"
                        />
                      ) : (
                        f.field_name
                      )}
                    </td>
                    <td className="py-3 font-mono">
                      {isDraft ? (
                        <select
                          value={f.data_type}
                          onChange={(e) => handleFieldChange(idx, 'data_type', e.target.value)}
                          className="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs font-mono text-white"
                        >
                          {DATA_TYPES.map((dt) => (
                            <option key={dt} value={dt}>
                              {dt}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-semibold">
                          {f.data_type}
                        </span>
                      )}
                    </td>
                    <td className="py-3 font-mono text-slate-400 text-[11px]">
                      {f.source_metadata?.profiling_inferred_type ? (
                        <span className="text-slate-400">
                          {f.source_metadata.profiling_inferred_type} (Null: {f.source_metadata.profiling_null_pct}%)
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="py-3 font-mono">
                      {isDraft ? (
                        <input
                          type="checkbox"
                          checked={f.is_nullable}
                          onChange={(e) => handleFieldChange(idx, 'is_nullable', e.target.checked)}
                          className="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-0"
                        />
                      ) : (
                        <span>{f.is_nullable ? 'Yes' : 'No'}</span>
                      )}
                    </td>
                    <td className="py-3 font-mono">
                      {isDraft ? (
                        <input
                          type="checkbox"
                          checked={f.is_required}
                          onChange={(e) => handleFieldChange(idx, 'is_required', e.target.checked)}
                          className="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-0"
                        />
                      ) : (
                        <span>{f.is_required ? 'Yes' : 'No'}</span>
                      )}
                    </td>
                    <td className="py-3 font-mono">
                      {isDraft ? (
                        <input
                          type="text"
                          value={f.format_pattern || ''}
                          placeholder="e.g. YYYY-MM-DD"
                          onChange={(e) => handleFieldChange(idx, 'format_pattern', e.target.value)}
                          className="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs font-mono text-white w-32"
                        />
                      ) : (
                        f.format_pattern || '—'
                      )}
                    </td>
                    <td className="py-3 text-slate-300">
                      {isDraft ? (
                        <input
                          type="text"
                          value={f.description || ''}
                          placeholder="Optional field description"
                          onChange={(e) => handleFieldChange(idx, 'description', e.target.value)}
                          className="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-white w-48"
                        />
                      ) : (
                        f.description || '—'
                      )}
                    </td>
                    {isDraft && (
                      <td className="py-3 text-right">
                        <button
                          onClick={() => handleRemoveField(idx)}
                          className="text-rose-400 hover:text-rose-300 text-xs"
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

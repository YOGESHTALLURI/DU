'use client';
import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Link from 'next/link';
import {
  CheckCircle2,
  Circle,
  AlertCircle,
  ArrowRight,
  ArrowLeft,
  RefreshCw,
  Upload,
  FileText,
  Check,
  ShieldCheck,
  Lock,
  Plus,
  Trash2,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
  Database,
  Layers,
  Scale,
  AlertTriangle,
  Play,
  Send,
  XCircle,
  Clock,
  Eye,
  FileCheck,
} from 'lucide-react';

interface FeedDetail {
  id: string;
  name: string;
  domain: string;
  description: string;
  format: string;
  landing_folder: string;
  filename_pattern: string;
  schedule_expression: string;
  source_system?: string;
  data_owner?: string;
  sla_expectation?: string;
  cloned_from_feed_id?: string;
  status: string;
}

interface OnboardingSession {
  id: string;
  feed_id: string;
  current_step: number;
  completed_steps: number[];
  sample_file_id: string | null;
  profiling_run_id: string | null;
  schema_id: string | null;
  status: string;
}

interface ColumnStat {
  column_name: string;
  ordinal_position: number;
  inferred_type: string;
  null_count: number;
  null_percentage: number;
  distinct_count: number;
  distinct_percentage: number;
  min_value: string | null;
  max_value: string | null;
  sample_values: any[];
  detected_date_patterns: any[];
}

interface SchemaField {
  field_name: string;
  ordinal_position: number;
  data_type: string;
  is_nullable: boolean;
  is_required: boolean;
  format_pattern: string | null;
  description: string | null;
}

interface CanonicalField {
  id: string;
  canonical_model_id: string;
  field_name: string;
  data_type: string;
  is_required: boolean;
  is_nullable: boolean;
  description: string | null;
  ordinal_position: number;
}

interface CanonicalModel {
  id: string;
  name: string;
  domain: string;
  description: string | null;
  field_count: number;
}

interface MappingLine {
  id?: string;
  canonical_field_id: string;
  canonical_field_name?: string;
  canonical_data_type?: string;
  canonical_is_required?: boolean;
  source_field_names: string[];
  transform_type: string;
  transform_params: any;
  notes?: string | null;
}

interface RuleDetail {
  id: string;
  feed_id: string;
  schema_id: string;
  name: string;
  description: string | null;
  is_deleted: boolean;
  active_version?: any;
  draft_version?: any;
  versions: any[];
}

const RULE_TYPES = ['NOT_NULL', 'RANGE', 'REGEX', 'ENUM', 'LENGTH', 'DATE_RANGE', 'CROSS_FIELD'];
const SEVERITIES = ['INFO', 'WARNING', 'QUARANTINE', 'REJECT_FILE'];

const DATA_TYPES = ['STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'TIMESTAMP'];
const TRANSFORM_TYPES = [
  'DIRECT',
  'CONSTANT',
  'VALUE_MAP',
  'DATE_FORMAT',
  'CONCAT',
  'STRING_CLEAN',
  'COALESCE',
  'EXPLODE',
  'FLATTEN',
  'PATH_EXTRACT',
  'ARRAY_MAP',
  'UNNEST',
];

const STEPS = [
  { step: 1, title: 'Feed Setup', desc: 'Metadata & Ingestion Rules' },
  { step: 2, title: 'Sample & Profiling', desc: 'Data Profiling Facts' },
  { step: 3, title: 'Schema Contract', desc: 'Governed Contract & Publish' },
  { step: 4, title: 'Mapping & Rules', desc: 'Source Mappings & DQ Rules' },
  { step: 5, title: 'Review & Activate', desc: 'Governed Activation' },
];

export default function OnboardingWizardPage() {
  const params = useParams();
  const router = useRouter();
  const feedId = params?.id as string;

  const [feed, setFeed] = useState<FeedDetail | null>(null);
  const [session, setSession] = useState<OnboardingSession | null>(null);
  const [activeStep, setActiveStep] = useState<number>(1);
  const [loading, setLoading] = useState(true);
  const [savingStep, setSavingStep] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Step 1 Edit Form
  const [feedForm, setFeedForm] = useState({
    description: '',
    source_system: '',
    data_owner: '',
    sla_expectation: '',
    landing_folder: '',
    filename_pattern: '',
  });

  // Step 2 Sample & Profiling State
  const [sampleFile, setSampleFile] = useState<File | null>(null);
  const [uploadingSample, setUploadingSample] = useState(false);
  const [columnStats, setColumnStats] = useState<ColumnStat[]>([]);
  const [profilingSummary, setProfilingSummary] = useState<any>(null);

  // Step 3 Schema State
  const [schemaObj, setSchemaObj] = useState<any>(null);
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([]);
  const [schemaStatus, setSchemaStatus] = useState<string>('DRAFT');
  const [savingSchema, setSavingSchema] = useState(false);
  const [publishingSchema, setPublishingSchema] = useState(false);

  // Step 4 Mapping Studio State
  const [canonicalModels, setCanonicalModels] = useState<CanonicalModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>('');
  const [canonicalFields, setCanonicalFields] = useState<CanonicalField[]>([]);
  const [mappingObj, setMappingObj] = useState<any>(null);
  const [mappingVersion, setMappingVersion] = useState<any>(null);
  const [mappingLines, setMappingLines] = useState<MappingLine[]>([]);
  const [mappingStatus, setMappingStatus] = useState<string>('DRAFT');
  const [savingMapping, setSavingMapping] = useState(false);
  const [validatingMapping, setValidatingMapping] = useState(false);
  const [publishingMapping, setPublishingMapping] = useState(false);
  const [spawningVersion, setSpawningVersion] = useState(false);
  const [validationReport, setValidationReport] = useState<any>(null);
  const [showUnmappedTrays, setShowUnmappedTrays] = useState(false);

// Step 4 Tab Navigation: 'mapping' | 'rules'
  const [step4SubTab, setStep4SubTab] = useState<'mapping' | 'rules'>('mapping');

  // Step 4 Data Quality Rules State
  const [rulesList, setRulesList] = useState<RuleDetail[]>([]);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [ruleModalMode, setRuleModalMode] = useState<'create' | 'edit' | 'view'>('create');
  const [editingRule, setEditingRule] = useState<any>(null);
  const [ruleForm, setRuleForm] = useState<any>({
    name: '',
    target_field: '',
    rule_type: 'NOT_NULL',
    severity: 'QUARANTINE',
    rule_config: {},
    error_message_template: '',
    description: '',
    needs_review: false,
  });
  const [savingRule, setSavingRule] = useState(false);
  const [validatingRule, setValidatingRule] = useState(false);
  const [ruleValidationRep, setRuleValidationRep] = useState<any>(null);
  const [testingRule, setTestingRule] = useState(false);
  const [testRunResult, setTestRunResult] = useState<any>(null);
  const [publishingRule, setPublishingRule] = useState(false);
  const [spawningRuleVersion, setSpawningRuleVersion] = useState(false);
  const [deletingRule, setDeletingRule] = useState(false);

  // Transform Modal State
  const [modalTargetField, setModalTargetField] = useState<CanonicalField | null>(null);
  const [modalLineState, setModalLineState] = useState<MappingLine | null>(null);
  const [structuralTestInput, setStructuralTestInput] = useState<string>(
    '{\\n  "patient": {\\n    "name": [{"family": "Smith", "given": ["John"]}],\\n    "telecom": [{"system": "phone", "value": "555-0199"}]\\n  }\\n}'
  );
  const [structuralTestResult, setStructuralTestResult] = useState<any>(null);
  const [runningStructuralTest, setRunningStructuralTest] = useState<boolean>(false);

  // Step 5 Review & Activate State
  const [reviewPacket, setReviewPacket] = useState<any>(null);
  const [loadingPacket, setLoadingPacket] = useState(false);
  const [runningSandbox, setRunningSandbox] = useState(false);
  const [submittingApproval, setSubmittingApproval] = useState(false);
  const [approvingFeed, setApprovingFeed] = useState(false);
  const [rejectingFeed, setRejectingFeed] = useState(false);
  const [submissionNotes, setSubmissionNotes] = useState('');
  const [decisionNotes, setDecisionNotes] = useState('');
  const [submitModalOpen, setSubmitModalOpen] = useState(false);
  const [approveModalOpen, setApproveModalOpen] = useState(false);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);

  // Load all initial data
  const loadData = async () => {
    if (!feedId) return;
    const token = localStorage.getItem('cinqflow_token');
    try {
      // 1. Fetch Feed
      const rFeed = await fetch(`/api/v1/feeds/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!rFeed.ok) throw new Error('Failed to load feed');
      const feedData = await rFeed.json();
      setFeed(feedData);
      setFeedForm({
        description: feedData.description || '',
        source_system: feedData.source_system || '',
        data_owner: feedData.data_owner || '',
        sla_expectation: feedData.sla_expectation || '',
        landing_folder: feedData.landing_folder || '',
        filename_pattern: feedData.filename_pattern || '',
      });

      // 2. Fetch Onboarding Session
      const rSess = await fetch(`/api/v1/onboarding/feed/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rSess.ok) {
        const sessData = await rSess.json();
        setSession(sessData);
        setActiveStep(sessData.current_step || 1);
      }

      // 3. Fetch Profiling Samples
      const rSamples = await fetch(`/api/v1/feeds/${feedId}/samples`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rSamples.ok) {
        const samples = await rSamples.json();
        if (samples && samples.length > 0) {
          const sampleId = samples[0].id;
          const rRuns = await fetch(`/api/v1/feeds/${feedId}/samples/${sampleId}/profile`, {
            headers: { Authorization: `Bearer ${token || ''}` },
          });
          if (rRuns.ok) {
            const run = await rRuns.json();
            if (run && run.status === 'COMPLETED') {
              setColumnStats(run.column_stats || []);
              setProfilingSummary(run.profiling_summary || null);
            }
          }
        }
      }

      // 4. Fetch Schema Contract
      const rSchema = await fetch(`/api/v1/schemas/feed/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rSchema.ok) {
        const schData = await rSchema.json();
        const sch = Array.isArray(schData) ? (schData.length > 0 ? schData[0] : null) : schData;
        if (sch) {
          setSchemaObj(sch);
          const activeVer = sch.active_version || sch.draft_version;
          if (activeVer) {
            setSchemaStatus(activeVer.status);
            const rVer = await fetch(`/api/v1/schemas/${sch.id}/versions/${activeVer.id}`, {
              headers: { Authorization: `Bearer ${token || ''}` },
            });
            if (rVer.ok) {
              const verData = await rVer.json();
              setSchemaFields(verData.fields || []);
            }
          }
        }
      }

      // 5. Fetch Canonical Models
      const rModels = await fetch('/api/v1/canonical-models', {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rModels.ok) {
        const models = await rModels.json();
        setCanonicalModels(models || []);
        if (models && models.length > 0) {
          setSelectedModelId(models[0].id);
        }
      }

      // 6. Fetch Existing Mappings for Feed
      const rMappings = await fetch(`/api/v1/mappings/feed/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rMappings.ok) {
        const mappings = await rMappings.json();
        if (mappings && mappings.length > 0) {
          const m = mappings[0];
          setMappingObj(m);
          setSelectedModelId(m.canonical_model_id);
          const targetVer = m.active_version || m.draft_version;
          if (targetVer) {
            setMappingStatus(targetVer.status);
            const rVerDetail = await fetch(`/api/v1/mappings/${m.id}/versions/${targetVer.id}`, {
              headers: { Authorization: `Bearer ${token || ''}` },
            });
            if (rVerDetail.ok) {
              const vd = await rVerDetail.json();
              setMappingVersion(vd);
              setMappingLines(vd.lines || []);
            }
          }
        }
      }
// 7. Fetch Data Quality Rules for Feed
      const rRules = await fetch(`/api/v1/rules/feed/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (rRules.ok) {
        const rules = await rRules.json();
        setRulesList(rules || []);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load onboarding session');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [feedId]);

  // Load canonical fields when selected model changes
  useEffect(() => {
    if (!selectedModelId) return;
    const token = localStorage.getItem('cinqflow_token');
    fetch(`/api/v1/canonical-models/${selectedModelId}`, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.fields) {
          setCanonicalFields(data.fields);
        }
      });
  }, [selectedModelId]);

  // Load Review Packet when navigating to Step 5
  useEffect(() => {
    if (activeStep === 5) {
      loadReviewPacket();
    }
  }, [activeStep, feedId]);

  // Advance Session Step
  const updateSessionStep = async (newStep: number, completedStep?: number) => {
    setSavingStep(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/step`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({
          current_step: newStep,
          mark_step_completed: completedStep,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to advance onboarding step');
      }
      const updated = await res.json();
      setSession(updated);
      setActiveStep(newStep);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingStep(false);
    }
  };

  // Step 1: Save Metadata
  const handleSaveStep1 = async () => {
    setSavingStep(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/feeds/${feedId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify(feedForm),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to save feed metadata');
      }
      const updatedFeed = await res.json();
      setFeed(updatedFeed);
      setSuccessMsg('Feed metadata successfully updated.');
      await updateSessionStep(2, 1);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingStep(false);
    }
  };

  // Step 2: Upload Sample and Profile
  const handleUploadAndProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sampleFile) {
      setError('Please select a CSV sample file');
      return;
    }
    setUploadingSample(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const formData = new FormData();
      formData.append('file', sampleFile);
      const resUpload = await fetch(`/api/v1/feeds/${feedId}/samples`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
        body: formData,
      });
      if (!resUpload.ok) {
        const err = await resUpload.json();
        throw new Error(err.detail || 'Sample upload failed');
      }
      const sample = await resUpload.json();

      const resProf = await fetch(`/api/v1/feeds/${feedId}/samples/${sample.id}/profile`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!resProf.ok) {
        const err = await resProf.json();
        throw new Error(err.detail || 'Profiling execution failed');
      }
      const run = await resProf.json();
      setColumnStats(run.column_stats || []);
      setProfilingSummary(run.profiling_summary || null);

      if (schemaFields.length === 0 && run.column_stats) {
        const inferred = run.column_stats.map((c: ColumnStat) => ({
          field_name: c.column_name,
          ordinal_position: c.ordinal_position,
          data_type: c.inferred_type,
          is_nullable: c.null_count > 0,
          is_required: c.null_count === 0,
          format_pattern: c.detected_date_patterns?.[0] || null,
          description: `Imported from sample profiling (${c.distinct_count} distinct values)`,
        }));
        setSchemaFields(inferred);
      }

      setSuccessMsg('Sample uploaded and deterministic profiling completed.');
      await updateSessionStep(2, 2);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploadingSample(false);
    }
  };

  // Step 3: Save Schema Draft
  const handleSaveSchemaDraft = async () => {
    setSavingSchema(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      if (!schemaObj) {
        const resCreate = await fetch('/api/v1/schemas', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token || ''}`,
          },
          body: JSON.stringify({
            feed_id: feedId,
            name: `${feed?.name}_Schema_Contract`,
            description: 'Governed schema contract derived from profiling',
            initial_fields: schemaFields,
          }),
        });
        if (!resCreate.ok) {
          const err = await resCreate.json();
          throw new Error(err.detail || 'Failed to create schema contract');
        }
        const created = await resCreate.json();
        setSchemaObj(created);
        setSchemaStatus(created.draft_version?.status || 'DRAFT');
      } else {
        const draftId = schemaObj.draft_version?.id || schemaObj.active_version?.id;
        const resUpdate = await fetch(`/api/v1/schemas/${schemaObj.id}/versions/${draftId}/fields`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token || ''}`,
          },
          body: JSON.stringify({ fields: schemaFields }),
        });
        if (!resUpdate.ok) {
          const err = await resUpdate.json();
          throw new Error(err.detail || 'Failed to update schema draft');
        }
      }
      setSuccessMsg('Schema contract draft saved successfully.');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingSchema(false);
    }
  };

  // Step 3: Publish Schema Contract
  const handlePublishSchema = async () => {
    setPublishingSchema(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      if (!schemaObj) {
        throw new Error('Please save the schema draft before publishing.');
      }
      const draftId = schemaObj.draft_version?.id || schemaObj.active_version?.id;
      if (!draftId) throw new Error('No draft version found to publish.');

      const resPub = await fetch(`/api/v1/schemas/${schemaObj.id}/versions/${draftId}/publish`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ change_notes: 'Published via Onboarding Wizard' }),
      });
      if (!resPub.ok) {
        const err = await resPub.json();
        throw new Error(err.detail || 'Failed to publish schema');
      }
      setSchemaStatus('PUBLISHED');
      setSuccessMsg('Schema contract PUBLISHED and locked into immutable governance.');
      await updateSessionStep(4, 3);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPublishingSchema(false);
    }
  };

  // Step 4: Ensure or Load Mapping
  const ensureMappingForModel = async (modelId: string) => {
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch('/api/v1/mappings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({
          feed_id: feedId,
          canonical_model_id: modelId,
        }),
      });
      if (res.status === 201) {
        const created = await res.json();
        setMappingObj(created);
        const draftVer = created.draft_version || created.active_version;
        if (draftVer) {
          setMappingStatus(draftVer.status);
          const rVer = await fetch(`/api/v1/mappings/${created.id}/versions/${draftVer.id}`, {
            headers: { Authorization: `Bearer ${token || ''}` },
          });
          if (rVer.ok) {
            const vd = await rVer.json();
            setMappingVersion(vd);
            setMappingLines(vd.lines || []);
          }
        }
      } else if (res.status === 400) {
        // Already exists, fetch it
        const rList = await fetch(`/api/v1/mappings/feed/${feedId}`, {
          headers: { Authorization: `Bearer ${token || ''}` },
        });
        if (rList.ok) {
          const list = await rList.json();
          const found = list.find((m: any) => m.canonical_model_id === modelId);
          if (found) {
            setMappingObj(found);
            const targetVer = found.active_version || found.draft_version;
            if (targetVer) {
              setMappingStatus(targetVer.status);
              const rVer = await fetch(`/api/v1/mappings/${found.id}/versions/${targetVer.id}`, {
                headers: { Authorization: `Bearer ${token || ''}` },
              });
              if (rVer.ok) {
                const vd = await rVer.json();
                setMappingVersion(vd);
                setMappingLines(vd.lines || []);
              }
            }
          }
        }
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  // Step 4: Save Mapping Draft Lines
  const handleSaveMappingDraft = async () => {
    if (!mappingObj || !mappingVersion) return;
    setSavingMapping(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const payloadLines = mappingLines.map((l) => ({
        canonical_field_id: l.canonical_field_id,
        source_field_names: l.source_field_names || [],
        transform_type: l.transform_type,
        transform_params: l.transform_params || {},
        notes: l.notes || null,
      }));

      const res = await fetch(`/api/v1/mappings/${mappingObj.id}/versions/${mappingVersion.id}/lines`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ lines: payloadLines }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to save mapping draft');
      }
      const updated = await res.json();
      setMappingVersion(updated);
      setMappingLines(updated.lines || []);
      setSuccessMsg('Mapping draft lines successfully saved.');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingMapping(false);
    }
  };

  // Step 4: Validate Mapping
  const handleValidateMapping = async () => {
    if (!mappingObj || !mappingVersion) return;
    setValidatingMapping(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/mappings/${mappingObj.id}/versions/${mappingVersion.id}/validate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Validation request failed');
      }
      const rep = await res.json();
      setValidationReport(rep);
      if (rep.is_valid) {
        setSuccessMsg('All mapping lines are structurally valid and complete!');
      } else {
        setError(`Validation flagged ${rep.errors.length} issue(s). Please review.`);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setValidatingMapping(false);
    }
  };

  // Step 4: Publish Mapping Contract
  const handlePublishMapping = async () => {
    if (!mappingObj || !mappingVersion) return;
    setPublishingMapping(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/mappings/${mappingObj.id}/versions/${mappingVersion.id}/publish`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ change_notes: 'Published via Mapping Studio' }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to publish mapping');
      }
      const publishedVer = await res.json();
      setMappingVersion(publishedVer);
      setMappingStatus('PUBLISHED');
      setSuccessMsg('Mapping contract PUBLISHED and locked into immutable governance.');
      await updateSessionStep(5, 4);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPublishingMapping(false);
    }
  };

  // Step 4: Spawn New Mapping Version
  const handleSpawnNewVersion = async () => {
    if (!mappingObj) return;
    setSpawningVersion(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/mappings/${mappingObj.id}/versions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({
          change_notes: 'Spawned new draft version for edits',
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to create new version');
      }
      const newVer = await res.json();
      setMappingVersion(newVer);
      setMappingStatus('DRAFT');
      setMappingLines(newVer.lines || []);
      setSuccessMsg(`Created new independent DRAFT v${newVer.version_number}. Previous version remains immutable.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSpawningVersion(false);
    }
  };

  // Step 5: Review & Activate Methods
  const loadReviewPacket = async () => {
    if (!feedId) return;
    setLoadingPacket(true);
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/review-packet`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (res.ok) {
        const data = await res.json();
        setReviewPacket(data);
      }
    } catch (err: any) {
      console.error('Failed to load review packet:', err);
    } finally {
      setLoadingPacket(false);
    }
  };

  const handleRunSandbox = async () => {
    setRunningSandbox(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/sandbox-test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Sandbox test execution failed');
      }
      const data = await res.json();
      setSuccessMsg(`Sandbox execution completed: ${data.passed_rows}/${data.total_rows} rows passed (${data.pass_rate}%). Reconciliation: ${data.reconciliation_status}.`);
      await loadReviewPacket();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunningSandbox(false);
    }
  };

  const handleSubmitApproval = async () => {
    setSubmittingApproval(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/submit-approval`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ notes: submissionNotes || null }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to submit for approval');
      }
      setSuccessMsg('Feed successfully submitted for engineering activation review.');
      setSubmitModalOpen(false);
      setSubmissionNotes('');
      await loadReviewPacket();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmittingApproval(false);
    }
  };

  const handleApproveActivation = async () => {
    setApprovingFeed(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ decision_notes: decisionNotes || null }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to approve activation');
      }
      const data = await res.json();
      setSuccessMsg('Feed successfully ACTIVATED into production! Immutable record locked into ledger.');
      setApproveModalOpen(false);
      setDecisionNotes('');
      if (feed) {
        setFeed({ ...feed, status: 'ACTIVE' });
      }
      await updateSessionStep(5, 5);
      await loadReviewPacket();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setApprovingFeed(false);
    }
  };

  const handleRejectActivation = async () => {
    if (!decisionNotes || decisionNotes.trim().length < 3) {
      setError('A mandatory reason (at least 3 characters) is required to reject activation.');
      return;
    }
    setRejectingFeed(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/onboarding/feed/${feedId}/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ decision_notes: decisionNotes }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to reject activation');
      }
      setSuccessMsg('Activation request rejected. Feedback recorded and feed reverted to draft.');
      setRejectModalOpen(false);
      setDecisionNotes('');
      await loadReviewPacket();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRejectingFeed(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-6xl mx-auto px-4 py-16 text-center text-slate-400">
          Loading Feed Onboarding Wizard...
        </div>
      </div>
    );
  }

  if (!feed) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <Navbar />
        <div className="max-w-6xl mx-auto px-4 py-16 text-center text-slate-400">
          Feed not found.
        </div>
      </div>
    );
  }

const refreshRules = async () => {
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/feed/${feedId}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (res.ok) {
        const data = await res.json();
        setRulesList(data || []);
      }
    } catch {}
  };

  const openCreateRuleModal = () => {
    const defaultField = schemaFields.length > 0 ? schemaFields[0].field_name : '';
    setRuleForm({
      name: '',
      target_field: defaultField,
      rule_type: 'NOT_NULL',
      severity: 'QUARANTINE',
      rule_config: {},
      error_message_template: '',
      description: '',
      needs_review: false,
    });
    setEditingRule(null);
    setRuleModalMode('create');
    setRuleValidationRep(null);
    setTestRunResult(null);
    setRuleModalOpen(true);
  };

  const openEditRuleModal = async (rule: RuleDetail) => {
    const targetVer = rule.draft_version || rule.active_version;
    if (!targetVer) return;
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${rule.id}/versions/${targetVer.id}`, {
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (res.ok) {
        const vd = await res.json();
        setEditingRule({ rule, version: vd });
        setRuleForm({
          name: rule.name,
          target_field: vd.target_field,
          rule_type: vd.rule_type,
          severity: vd.severity,
          rule_config: vd.rule_config || {},
          error_message_template: vd.error_message_template || '',
          description: rule.description || '',
          needs_review: vd.needs_review,
        });
        setRuleModalMode(vd.status === 'PUBLISHED' ? 'view' : 'edit');
        setRuleValidationRep(null);
        setTestRunResult(vd.latest_test_run || null);
        setRuleModalOpen(true);
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleSaveRule = async () => {
    setSavingRule(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      if (ruleModalMode === 'create') {
        const res = await fetch('/api/v1/rules', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token || ''}`,
          },
          body: JSON.stringify({
            feed_id: feedId,
            name: ruleForm.name,
            target_field: ruleForm.target_field,
            rule_type: ruleForm.rule_type,
            severity: ruleForm.severity,
            rule_config: ruleForm.rule_config,
            error_message_template: ruleForm.error_message_template || null,
            description: ruleForm.description || null,
            needs_review: ruleForm.needs_review,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Failed to create rule');
        }
        setSuccessMsg(`Rule '${ruleForm.name}' created successfully.`);
      } else if (ruleModalMode === 'edit' && editingRule) {
        const res = await fetch(`/api/v1/rules/${editingRule.rule.id}/versions/${editingRule.version.id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token || ''}`,
          },
          body: JSON.stringify({
            rule_type: ruleForm.rule_type,
            target_field: ruleForm.target_field,
            severity: ruleForm.severity,
            rule_config: ruleForm.rule_config,
            error_message_template: ruleForm.error_message_template || null,
            needs_review: ruleForm.needs_review,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Failed to update rule');
        }
        setSuccessMsg(`Rule draft updated successfully.`);
      }
      setRuleModalOpen(false);
      await refreshRules();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingRule(false);
    }
  };

  const handleValidateRule = async (ruleId: string, versionId: string) => {
    setValidatingRule(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}/versions/${versionId}/validate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Validation failed');
      }
      const rep = await res.json();
      setRuleValidationRep(rep);
      if (rep.is_valid) {
        setSuccessMsg('Rule configuration is structurally valid!');
      } else {
        setError(`Validation flagged ${rep.errors.length} issue(s).`);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setValidatingRule(false);
    }
  };

  const handleTestRule = async (ruleId: string, versionId: string) => {
    setTestingRule(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}/versions/${versionId}/test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Test execution failed');
      }
      const result = await res.json();
      setTestRunResult(result);
      setSuccessMsg(`Tested against ${result.total_rows} sample rows: ${result.pass_rate}% passed.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setTestingRule(false);
    }
  };

  const handlePublishRule = async (ruleId: string, versionId: string) => {
    setPublishingRule(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}/versions/${versionId}/publish`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ change_notes: 'Published via Rule Builder' }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to publish rule');
      }
      setSuccessMsg('Rule version PUBLISHED and locked into immutable governance.');
      setRuleModalOpen(false);
      await refreshRules();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPublishingRule(false);
    }
  };

  const handleSpawnRuleVersion = async (ruleId: string) => {
    setSpawningRuleVersion(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}/versions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token || ''}`,
        },
        body: JSON.stringify({ change_notes: 'Spawned new draft version for edits' }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to spawn new rule version');
      }
      setSuccessMsg('Created new independent DRAFT version. Previous version remains immutable.');
      setRuleModalOpen(false);
      await refreshRules();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSpawningRuleVersion(false);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!confirm('Are you sure you want to soft-delete this draft rule?')) return;
    setDeletingRule(true);
    setError('');
    const token = localStorage.getItem('cinqflow_token');
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token || ''}` },
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to delete rule');
      }
      setSuccessMsg('Rule soft-deleted successfully.');
      setRuleModalOpen(false);
      await refreshRules();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setDeletingRule(false);
    }
  };

  // Helper: find mapping line for canonical field
  const getLineForField = (fieldId: string): MappingLine | undefined => {
    return mappingLines.find((l) => l.canonical_field_id === fieldId);
  };

  // Helper: open transform modal for canonical field
  const openTransformModal = (cf: CanonicalField) => {
    const existing = getLineForField(cf.id);
    const initialLine: MappingLine = existing
      ? JSON.parse(JSON.stringify(existing))
      : {
          canonical_field_id: cf.id,
          canonical_field_name: cf.field_name,
          canonical_data_type: cf.data_type,
          canonical_is_required: cf.is_required,
          source_field_names: [],
          transform_type: 'DIRECT',
          transform_params: {},
          notes: '',
        };
    setModalTargetField(cf);
    setModalLineState(initialLine);
  };

  // Helper: save transform modal state to mappingLines
  const saveTransformModal = () => {
    if (!modalLineState || !modalTargetField) return;
    const copy = [...mappingLines.filter((l) => l.canonical_field_id !== modalTargetField.id)];
    copy.push(modalLineState);
    setMappingLines(copy);
    setModalTargetField(null);
    setModalLineState(null);
  };

  const handleRunStructuralTest = async () => {
    if (!modalLineState) return;
    setRunningStructuralTest(true);
    setStructuralTestResult(null);
    try {
      let parsedInput = {};
      try {
        parsedInput = JSON.parse(structuralTestInput);
      } catch (e: any) {
        setStructuralTestResult({ success: false, error: `Invalid JSON input: ${e.message}` });
        setRunningStructuralTest(false);
        return;
      }

      const res = await fetch('/api/v1/mappings/test-structural-transform', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cinqflow_token') || ''}`,
        },
        body: JSON.stringify({
          transform_type: modalLineState.transform_type,
          transform_params: modalLineState.transform_params || {},
          source_fields: modalLineState.source_field_names || [],
          sample_input: parsedInput,
        }),
      });
      const data = await res.json();
      setStructuralTestResult(data);
    } catch (err: any) {
      setStructuralTestResult({ success: false, error: err.message || 'Connection error' });
    } finally {
      setRunningStructuralTest(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-20">
      <Navbar />

      {/* Header & Sub-navigation */}
      <div className="border-b border-slate-800 bg-slate-900/50">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-xs font-mono text-slate-400 mb-1">
                <Link href="/feeds" className="hover:text-slate-200">Feeds</Link>
                <span>/</span>
                <Link href={`/feeds/${feed.id}`} className="hover:text-slate-200">{feed.name}</Link>
                <span>/</span>
                <span className="text-blue-400">Onboarding Wizard</span>
              </div>
              <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
                {feed.name}
                <span className="text-xs font-mono px-2.5 py-0.5 rounded-full border border-slate-700 bg-slate-800 text-slate-300">
                  {feed.domain}
                </span>
                <span className={`text-xs font-mono px-2.5 py-0.5 rounded-full font-bold ${
                  feed.status === 'ACTIVE' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
                }`}>
                  {feed.status}
                </span>
              </h1>
            </div>

            {/* Stepper Navigation Pills */}
            <div className="flex items-center gap-1 overflow-x-auto pb-2 md:pb-0">
              {STEPS.map((s) => {
                const isCompleted = session?.completed_steps.includes(s.step);
                const isCurrent = activeStep === s.step;
                return (
                  <button
                    key={s.step}
                    onClick={() => setActiveStep(s.step)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition whitespace-nowrap ${
                      isCurrent
                        ? 'bg-blue-600 text-white shadow-md shadow-blue-900/40'
                        : isCompleted
                        ? 'bg-slate-800/80 hover:bg-slate-800 text-slate-200 border border-slate-700'
                        : 'bg-slate-900 text-slate-400 hover:text-slate-300 border border-slate-800/60'
                    }`}
                  >
                    <div className="w-4 h-4 flex items-center justify-center rounded-full text-[10px] font-bold">
                      {isCompleted ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : s.step}
                    </div>
                    {s.title}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Notifications */}
      <div className="max-w-7xl mx-auto px-4 mt-6">
        {error && (
          <div className="mb-4 p-4 rounded-xl bg-rose-950/80 border border-rose-800 text-rose-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError('')} className="text-rose-400 hover:text-rose-200 text-xs">Dismiss</button>
          </div>
        )}
        {successMsg && (
          <div className="mb-4 p-4 rounded-xl bg-emerald-950/80 border border-emerald-800 text-emerald-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>{successMsg}</span>
            </div>
            <button onClick={() => setSuccessMsg('')} className="text-emerald-400 hover:text-emerald-200 text-xs">Dismiss</button>
          </div>
        )}

        {/* Wizard Main Container */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
          {/* STEP 1: FEED SETUP */}
          {activeStep === 1 && (
            <div className="space-y-6">
              <div className="border-b border-slate-800 pb-4">
                <h2 className="text-lg font-bold text-white">Step 1: Ingestion & Governance Metadata</h2>
                <p className="text-xs text-slate-400 mt-1">Configure feed ownership, SLA expectation, and physical landing rules.</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Landing Directory</label>
                  <input
                    type="text"
                    value={feedForm.landing_folder}
                    onChange={(e) => setFeedForm({ ...feedForm, landing_folder: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Filename Pattern (Glob)</label>
                  <input
                    type="text"
                    value={feedForm.filename_pattern}
                    onChange={(e) => setFeedForm({ ...feedForm, filename_pattern: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Source System</label>
                  <input
                    type="text"
                    value={feedForm.source_system}
                    onChange={(e) => setFeedForm({ ...feedForm, source_system: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Data Owner</label>
                  <input
                    type="text"
                    value={feedForm.data_owner}
                    onChange={(e) => setFeedForm({ ...feedForm, data_owner: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">SLA Expectation</label>
                  <input
                    type="text"
                    value={feedForm.sla_expectation}
                    onChange={(e) => setFeedForm({ ...feedForm, sla_expectation: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Feed Description</label>
                  <input
                    type="text"
                    value={feedForm.description}
                    onChange={(e) => setFeedForm({ ...feedForm, description: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-white"
                  />
                </div>
              </div>

              <div className="flex justify-between pt-4 border-t border-slate-800">
                <div />
                <button
                  onClick={handleSaveStep1}
                  disabled={savingStep}
                  className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg text-xs font-bold transition"
                >
                  Save & Proceed to Profiling &rarr;
                </button>
              </div>
            </div>
          )}

          {/* STEP 2: SAMPLE & PROFILING */}
          {activeStep === 2 && (
            <div className="space-y-6">
              <div className="border-b border-slate-800 pb-4">
                <h2 className="text-lg font-bold text-white">Step 2: Upload Sample & Run Deterministic Profiler</h2>
                <p className="text-xs text-slate-400 mt-1">Upload representative sample file to compute column facts and nullability.</p>
              </div>

              <form onSubmit={handleUploadAndProfile} className="p-5 bg-slate-950 border border-slate-800 rounded-xl space-y-4">
                <div className="flex flex-col sm:flex-row items-center gap-4">
                  <input
                    type="file"
                    accept=".csv,.json,.ndjson,.xml,.txt"
                    onChange={(e) => setSampleFile(e.target.files?.[0] || null)}
                    className="text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-slate-200 hover:file:bg-slate-700 cursor-pointer"
                  />
                  <button
                    type="submit"
                    disabled={uploadingSample || !sampleFile}
                    className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-xs font-medium transition"
                  >
                    <Upload className="w-4 h-4" />
                    {uploadingSample ? 'Profiling Sample...' : 'Upload & Profile'}
                  </button>
                </div>
              </form>

              {columnStats.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Observed Profiling Facts ({columnStats.length} columns/paths)
                    </h3>
                    {profilingSummary && (
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800 font-bold">
                          Format: {profilingSummary.format || 'CSV'}
                        </span>
                        {profilingSummary.is_complex && (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 font-bold">
                            Hierarchical Paths: {profilingSummary.hierarchical_paths_count}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="overflow-x-auto border border-slate-800 rounded-xl">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-950 text-slate-400 font-mono">
                        <tr>
                          <th className="p-3">#</th>
                          <th className="p-3">Column Name</th>
                          <th className="p-3">Inferred Type</th>
                          <th className="p-3">Null %</th>
                          <th className="p-3">Distinct %</th>
                          <th className="p-3">Min / Max</th>
                          <th className="p-3">Sample Values</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {columnStats.map((c) => (
                          <tr key={c.column_name} className="hover:bg-slate-800/40">
                            <td className="p-3 font-mono text-slate-500">{c.ordinal_position}</td>
                            <td className="p-3 font-mono font-bold text-white">{c.column_name}</td>
                            <td className="p-3 font-mono text-cyan-400">{c.inferred_type}</td>
                            <td className="p-3 font-mono">{c.null_percentage.toFixed(1)}%</td>
                            <td className="p-3 font-mono">{c.distinct_percentage.toFixed(1)}%</td>
                            <td className="p-3 font-mono text-slate-400">
                              {c.min_value !== null ? `${c.min_value} → ${c.max_value}` : '—'}
                            </td>
                            <td className="p-3 font-mono text-slate-400 truncate max-w-xs">
                              {c.sample_values ? c.sample_values.slice(0, 3).join(', ') : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="flex justify-between pt-4 border-t border-slate-800">
                <button
                  onClick={() => setActiveStep(1)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-xs font-medium"
                >
                  <ArrowLeft className="w-4 h-4" /> Back to Step 1
                </button>
                <button
                  onClick={() => setActiveStep(3)}
                  className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg text-xs font-bold transition"
                >
                  Proceed to Schema Contract &rarr;
                </button>
              </div>
            </div>
          )}

          {/* STEP 3: SCHEMA CONTRACT */}
          {activeStep === 3 && (
            <div className="space-y-6">
              <div className="border-b border-slate-800 pb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-bold text-white">Step 3: Governed Schema Contract</h2>
                  <p className="text-xs text-slate-400 mt-1">Review, customize constraints, and publish immutable schema contract.</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-mono">Contract Status:</span>
                  <span className={`text-xs font-bold font-mono px-3 py-1 rounded-full border ${
                    schemaStatus === 'PUBLISHED' ? 'bg-emerald-950 text-emerald-300 border-emerald-800' : 'bg-amber-950 text-amber-300 border-amber-800'
                  }`}>
                    {schemaStatus}
                  </span>
                </div>
              </div>

              <div className="overflow-x-auto border border-slate-800 rounded-xl">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950 text-slate-400 font-mono">
                    <tr>
                      <th className="p-3">#</th>
                      <th className="p-3">Field Name</th>
                      <th className="p-3">Data Type</th>
                      <th className="p-3 text-center">Nullable</th>
                      <th className="p-3 text-center">Required</th>
                      <th className="p-3">Format Pattern</th>
                      <th className="p-3">Description</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {schemaFields.map((field, idx) => (
                      <tr key={field.field_name} className="hover:bg-slate-800/30">
                        <td className="p-3 font-mono text-slate-500">{field.ordinal_position}</td>
                        <td className="p-3 font-mono font-bold text-white">{field.field_name}</td>
                        <td className="p-3">
                          {schemaStatus === 'DRAFT' ? (
                            <select
                              value={field.data_type}
                              onChange={(e) => {
                                const copy = [...schemaFields];
                                copy[idx].data_type = e.target.value;
                                setSchemaFields(copy);
                              }}
                              className="px-2 py-1 bg-slate-950 border border-slate-700 rounded text-xs font-mono text-cyan-300"
                            >
                              {DATA_TYPES.map((t) => (
                                <option key={t} value={t}>{t}</option>
                              ))}
                            </select>
                          ) : (
                            <span className="font-mono text-cyan-300">{field.data_type}</span>
                          )}
                        </td>
                        <td className="p-3 text-center">
                          <input
                            type="checkbox"
                            disabled={schemaStatus !== 'DRAFT'}
                            checked={field.is_nullable}
                            onChange={(e) => {
                              const copy = [...schemaFields];
                              copy[idx].is_nullable = e.target.checked;
                              setSchemaFields(copy);
                            }}
                            className="rounded bg-slate-950 border-slate-700"
                          />
                        </td>
                        <td className="p-3 text-center">
                          <input
                            type="checkbox"
                            disabled={schemaStatus !== 'DRAFT'}
                            checked={field.is_required}
                            onChange={(e) => {
                              const copy = [...schemaFields];
                              copy[idx].is_required = e.target.checked;
                              setSchemaFields(copy);
                            }}
                            className="rounded bg-slate-950 border-slate-700"
                          />
                        </td>
                        <td className="p-3">
                          {schemaStatus === 'DRAFT' ? (
                            <input
                              type="text"
                              value={field.format_pattern || ''}
                              onChange={(e) => {
                                const copy = [...schemaFields];
                                copy[idx].format_pattern = e.target.value || null;
                                setSchemaFields(copy);
                              }}
                              placeholder="e.g. DD/MM/YYYY"
                              className="px-2 py-1 bg-slate-950 border border-slate-700 rounded text-xs font-mono text-white w-28"
                            />
                          ) : (
                            <span className="font-mono text-slate-300">{field.format_pattern || '—'}</span>
                          )}
                        </td>
                        <td className="p-3">
                          {schemaStatus === 'DRAFT' ? (
                            <input
                              type="text"
                              value={field.description || ''}
                              onChange={(e) => {
                                const copy = [...schemaFields];
                                copy[idx].description = e.target.value;
                                setSchemaFields(copy);
                              }}
                              className="px-2 py-1 bg-slate-950 border border-slate-700 rounded text-xs text-slate-300 w-full"
                            />
                          ) : (
                            <span className="text-slate-400">{field.description || '—'}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-between pt-4 border-t border-slate-800">
                <button
                  onClick={() => setActiveStep(2)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-xs font-medium"
                >
                  <ArrowLeft className="w-4 h-4" /> Back to Step 2
                </button>
                <div className="flex items-center gap-3">
                  {schemaStatus === 'DRAFT' && (
                    <>
                      <button
                        onClick={handleSaveSchemaDraft}
                        disabled={savingSchema || schemaFields.length === 0}
                        className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-2 rounded-lg text-xs font-medium transition"
                      >
                        {savingSchema ? 'Saving...' : 'Save Draft'}
                      </button>
                      <button
                        onClick={handlePublishSchema}
                        disabled={publishingSchema || schemaFields.length === 0}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-2 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        {publishingSchema ? 'Publishing...' : 'Publish Schema Contract'}
                      </button>
                    </>
                  )}
                  {schemaStatus === 'PUBLISHED' && (
                    <button
                      onClick={() => updateSessionStep(4, 3)}
                      className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                    >
                      Proceed to Step 4 (Mapping Studio) &rarr;
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: MAPPING & RULES */}
          {activeStep === 4 && (
            <div className="space-y-6">
              {/* Step 4 Sub-Tabs: Mapping Studio vs Data Quality Rules */}
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setStep4SubTab('mapping')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition ${
                      step4SubTab === 'mapping'
                        ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40'
                        : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
                    }`}
                  >
                    <Database className="w-4 h-4" />
                    Mapping Studio
                    {mappingStatus === 'PUBLISHED' && (
                      <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
                    )}
                  </button>

                  <button
                    onClick={() => setStep4SubTab('rules')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition ${
                      step4SubTab === 'rules'
                        ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40'
                        : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
                    }`}
                  >
                    <Scale className="w-4 h-4" />
                    Data Quality Rules
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                      {rulesList.filter((r) => !r.is_deleted).length}
                    </span>
                  </button>
                </div>

                <div className="text-xs text-slate-400 font-mono">
                  Feed: <span className="text-white font-bold">{feed.name}</span>
                </div>
              </div>

              {/* TAB 1: MAPPING STUDIO */}
              {step4SubTab === 'mapping' && (
                <div className="space-y-6">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <h3 className="text-base font-bold text-white flex items-center gap-2">
                        <Database className="w-4 h-4 text-blue-400" />
                        Canonical Model Mappings
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Map feed schema fields to standardized healthcare canonical models with field-level transforms.
                      </p>
                    </div>

                {/* Governance Info Pills */}
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {schemaObj?.active_version && (
                    <span className="px-3 py-1 rounded-full bg-slate-800 border border-slate-700 text-slate-300 font-mono">
                      Based on Schema v{schemaObj.active_version.version_number}
                    </span>
                  )}
                  <span className={`px-3 py-1 rounded-full border font-mono font-bold flex items-center gap-1.5 ${
                    mappingStatus === 'PUBLISHED'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : 'bg-amber-950 text-amber-300 border-amber-800'
                  }`}>
                    {mappingStatus === 'PUBLISHED' && <Lock className="w-3.5 h-3.5 text-emerald-400" />}
                    Mapping: {mappingStatus}
                  </span>
                  {mappingStatus === 'PUBLISHED' && (
                    <button
                      onClick={handleSpawnNewVersion}
                      disabled={spawningVersion}
                      className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-full font-medium transition flex items-center gap-1 text-[11px]"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      {spawningVersion ? 'Spawning...' : 'Create New Version'}
                    </button>
                  )}
                </div>
              </div>

              {/* Canonical Model Picker Cards */}
              <div className="space-y-2">
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Select Target Canonical Healthcare Entity
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {canonicalModels.map((m) => {
                    const isSelected = selectedModelId === m.id;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          setSelectedModelId(m.id);
                          ensureMappingForModel(m.id);
                        }}
                        className={`p-3 rounded-xl border text-left transition ${
                          isSelected
                            ? 'bg-blue-950/70 border-blue-600 shadow-md shadow-blue-950/40'
                            : 'bg-slate-950/60 border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className={`text-sm font-bold ${isSelected ? 'text-white' : 'text-slate-300'}`}>{m.name}</span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400">{m.domain}</span>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{m.description}</p>
                        <span className="inline-block text-[10px] font-mono text-cyan-400 mt-2">{m.field_count} attributes</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Validation Feedback Banner */}
              {validationReport && (
                <div className={`p-4 rounded-xl border text-xs space-y-2 ${
                  validationReport.is_valid ? 'bg-emerald-950/70 border-emerald-800 text-emerald-200' : 'bg-rose-950/70 border-rose-800 text-rose-200'
                }`}>
                  <div className="flex items-center justify-between font-bold">
                    <div className="flex items-center gap-2">
                      {validationReport.is_valid ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <AlertCircle className="w-4 h-4 text-rose-400" />}
                      <span>{validationReport.is_valid ? 'Mapping Specification is Authoritatively Valid' : 'Validation Flagged Errors'}</span>
                    </div>
                    <span className="font-mono text-[11px]">{validationReport.errors.length} errors, {validationReport.warnings.length} warnings</span>
                  </div>
                  {validationReport.errors.length > 0 && (
                    <ul className="list-disc list-inside space-y-1 text-[11px] text-rose-300 pl-1">
                      {validationReport.errors.map((e: string, i: number) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  )}
                  {validationReport.warnings.length > 0 && (
                    <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-300 pl-1">
                      {validationReport.warnings.map((w: string, i: number) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {/* TWO-PANE MAPPING CANVAS */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Left Pane: Source Schema Fields (with read-only profiling context) */}
                <div className="lg:col-span-4 bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                      <Layers className="w-3.5 h-3.5 text-cyan-400" />
                      Source Schema Fields ({schemaFields.length})
                    </h3>
                    <span className="text-[10px] font-mono text-slate-500">Read-Only Context</span>
                  </div>
                  <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                    {schemaFields.map((sf) => {
                      const stat = columnStats.find((c) => c.column_name === sf.field_name);
                      return (
                        <div key={sf.field_name} className="p-2.5 rounded-lg bg-slate-900 border border-slate-800/80 text-xs hover:border-slate-700">
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-bold text-white">{sf.field_name}</span>
                            <span className="text-[10px] font-mono text-cyan-400 px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800">
                              {sf.data_type}
                            </span>
                          </div>
                          {/* Display sample value context if available */}
                          {stat?.sample_values && stat.sample_values.length > 0 && (
                            <p className="text-[10px] text-slate-400 mt-1 font-mono truncate">
                              Sample: {stat.sample_values.slice(0, 2).join(', ')}
                            </p>
                          )}
                          {sf.format_pattern && (
                            <span className="inline-block mt-1 text-[10px] font-mono text-slate-400 bg-slate-950 px-1.5 py-0.5 rounded">
                              Pattern: {sf.format_pattern}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Right Pane: Canonical Target Attributes & Mapping Slots */}
                <div className="lg:col-span-8 bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                      <Database className="w-3.5 h-3.5 text-blue-400" />
                      Canonical Attributes ({canonicalFields.length})
                    </h3>
                    <button
                      type="button"
                      onClick={() => setShowUnmappedTrays(!showUnmappedTrays)}
                      className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1"
                    >
                      {showUnmappedTrays ? 'Hide Trays' : 'Show Unmapped Attributes Trays'}
                      {showUnmappedTrays ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    </button>
                  </div>

                  {/* Optional Unmapped Attributes Tray */}
                  {showUnmappedTrays && (
                    <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-xs space-y-2">
                      <div className="text-[11px] text-slate-400">
                        <strong className="text-slate-300">Unmapped Source Columns:</strong>{' ' }
                        {schemaFields
                          .filter((sf) => !mappingLines.some((l) => l.source_field_names?.includes(sf.field_name)))
                          .map((sf) => sf.field_name)
                          .join(', ') || 'None'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        <strong className="text-slate-300">Unmapped Optional Target Attributes:</strong>{' ' }
                        {canonicalFields
                          .filter((cf) => !cf.is_required && !getLineForField(cf.id))
                          .map((cf) => cf.field_name)
                          .join(', ') || 'None'}
                      </div>
                    </div>
                  )}

                  {/* Canonical Field Mapping Rows */}
                  <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
                    {canonicalFields.map((cf) => {
                      const line = getLineForField(cf.id);
                      const isMapped = !!line;
                      return (
                        <div
                          key={cf.id}
                          className={`p-3 rounded-lg border transition ${
                            isMapped
                              ? 'bg-slate-900 border-slate-700/80'
                              : cf.is_required
                              ? 'bg-rose-950/20 border-rose-900/40'
                              : 'bg-slate-900/40 border-slate-800'
                          }`}
                        >
                          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-white text-xs">{cf.field_name}</span>
                                <span className="text-[10px] font-mono text-cyan-300 px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800">
                                  {cf.data_type}
                                </span>
                                {cf.is_required ? (
                                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800 font-bold">
                                    REQUIRED
                                  </span>
                                ) : (
                                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-950 text-slate-400 border border-slate-800">
                                    OPTIONAL
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-slate-400 mt-0.5">{cf.description}</p>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {isMapped ? (
                                <div className="flex items-center gap-2">
                                  <span className="text-[11px] font-mono px-2 py-1 rounded bg-blue-950 text-blue-300 border border-blue-800 font-semibold">
                                    {line.transform_type}
                                  </span>
                                  <span className="text-xs font-mono text-slate-300 max-w-[140px] truncate">
                                    {line.transform_type === 'CONSTANT'
                                      ? `"${line.transform_params?.value}"`
                                      : line.source_field_names.join(', ')}
                                  </span>
                                  {mappingStatus === 'DRAFT' && (
                                    <button
                                      type="button"
                                      onClick={() => openTransformModal(cf)}
                                      className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
                                      title="Edit Transform"
                                    >
                                      <SlidersHorizontal className="w-3.5 h-3.5" />
                                    </button>
                                  )}
                                </div>
                              ) : (
                                mappingStatus === 'DRAFT' && (
                                  <button
                                    type="button"
                                    onClick={() => openTransformModal(cf)}
                                    className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded bg-slate-800 hover:bg-blue-600 hover:text-white text-slate-300 border border-slate-700 transition"
                                  >
                                    <Plus className="w-3.5 h-3.5" /> Map Attribute
                                  </button>
                                )
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Action Governance Bar */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-slate-800">
                <button
                  onClick={() => setActiveStep(3)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-xs font-medium"
                >
                  <ArrowLeft className="w-4 h-4" /> Back to Step 3
                </button>

                <div className="flex items-center gap-3">
                  {mappingStatus === 'DRAFT' && (
                    <>
                      <button
                        onClick={handleSaveMappingDraft}
                        disabled={savingMapping || mappingLines.length === 0}
                        className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-2 rounded-lg text-xs font-medium transition"
                      >
                        {savingMapping ? 'Saving Draft...' : 'Save Draft'}
                      </button>
                      <button
                        onClick={handleValidateMapping}
                        disabled={validatingMapping || mappingLines.length === 0}
                        className="bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 px-4 py-2 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${validatingMapping ? 'animate-spin' : ''}`} />
                        Validate
                      </button>
                      <button
                        onClick={handlePublishMapping}
                        disabled={publishingMapping || mappingLines.length === 0}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-2 rounded-lg text-xs font-medium transition flex items-center gap-1.5 shadow-lg shadow-emerald-950/40"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        {publishingMapping ? 'Publishing...' : 'Publish Mapping Contract'}
                      </button>
                    </>
                  )}

                  {mappingStatus === 'PUBLISHED' && (
                    <button
                      onClick={() => updateSessionStep(5, 4)}
                      className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg text-xs font-bold transition flex items-center gap-1.5"
                    >
                      Proceed to Step 5 (Review & Activate) &rarr;
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

              {/* TAB 2: DATA QUALITY RULES */}
              {step4SubTab === 'rules' && (
                <div className="space-y-6">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <h3 className="text-base font-bold text-white flex items-center gap-2">
                        <Scale className="w-4 h-4 text-cyan-400" />
                        Deterministic Data Quality Rules
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Define row-level validation constraints that route invalid records to Quarantine with named reasons.
                      </p>
                    </div>

                    <button
                      onClick={openCreateRuleModal}
                      className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-blue-900/30"
                    >
                      <Plus className="w-4 h-4" />
                      Add Rule
                    </button>
                  </div>

                  {/* Rules Summary & Status Checklist */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                      <p className="text-xs text-slate-400">Total Active Rules</p>
                      <p className="text-2xl font-bold text-white mt-1">
                        {rulesList.filter((r) => !r.is_deleted).length}
                      </p>
                    </div>
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                      <p className="text-xs text-slate-400">Published Rules</p>
                      <p className="text-2xl font-bold text-emerald-400 mt-1">
                        {rulesList.filter((r) => !r.is_deleted && r.active_version).length}
                      </p>
                    </div>
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
                      <p className="text-xs text-slate-400">Draft / Pending</p>
                      <p className="text-2xl font-bold text-amber-400 mt-1">
                        {rulesList.filter((r) => !r.is_deleted && !r.active_version).length}
                      </p>
                    </div>
                  </div>

                  {/* Rules Table */}
                  <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900 text-slate-400 font-mono border-b border-slate-800">
                        <tr>
                          <th className="p-3">Rule Name</th>
                          <th className="p-3">Target Field</th>
                          <th className="p-3">Rule Type</th>
                          <th className="p-3">Severity</th>
                          <th className="p-3">Status</th>
                          <th className="p-3">Version</th>
                          <th className="p-3 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {rulesList.filter((r) => !r.is_deleted).length === 0 ? (
                          <tr>
                            <td colSpan={7} className="p-8 text-center text-slate-500 text-xs">
                              No data quality rules created yet. Click "+ Add Rule" to create structured validation rules.
                            </td>
                          </tr>
                        ) : (
                          rulesList
                            .filter((r) => !r.is_deleted)
                            .map((rule) => {
                              const activeVer = rule.active_version;
                              const draftVer = rule.draft_version;
                              const currentVer = draftVer || activeVer;
                              const isPub = currentVer?.status === 'PUBLISHED';
                              return (
                                <tr key={rule.id} className="hover:bg-slate-900/40">
                                  <td className="p-3 font-semibold text-white flex items-center gap-2">
                                    <Scale className="w-3.5 h-3.5 text-slate-400" />
                                    {rule.name}
                                    {currentVer?.needs_review && (
                                      <span className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800 text-[10px]">
                                        Review
                                      </span>
                                    )}
                                  </td>
                                  <td className="p-3 font-mono text-cyan-300">
                                    {currentVer?.target_field || '—'}
                                  </td>
                                  <td className="p-3 font-mono text-slate-300">
                                    {currentVer?.rule_type || '—'}
                                  </td>
                                  <td className="p-3">
                                    <span
                                      className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono border ${
                                        currentVer?.severity === 'INFO'
                                          ? 'bg-blue-950 text-blue-300 border-blue-800'
                                          : currentVer?.severity === 'WARNING'
                                          ? 'bg-amber-950 text-amber-300 border-amber-800'
                                          : currentVer?.severity === 'QUARANTINE'
                                          ? 'bg-orange-950 text-orange-300 border-orange-800'
                                          : 'bg-rose-950 text-rose-300 border-rose-800'
                                      }`}
                                    >
                                      {currentVer?.severity || 'QUARANTINE'}
                                    </span>
                                  </td>
                                  <td className="p-3">
                                    <span
                                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold font-mono border flex items-center gap-1 w-fit ${
                                        isPub
                                          ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                                          : 'bg-amber-950 text-amber-300 border-amber-800'
                                      }`}
                                    >
                                      {isPub && <Lock className="w-3 h-3 text-emerald-400" />}
                                      {currentVer?.status || 'DRAFT'}
                                    </span>
                                  </td>
                                  <td className="p-3 font-mono text-slate-400">
                                    v{currentVer?.version_number || 1}
                                  </td>
                                  <td className="p-3 text-right">
                                    <div className="flex items-center justify-end gap-2">
                                      <button
                                        onClick={() => openEditRuleModal(rule)}
                                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium"
                                      >
                                        {isPub ? 'View' : 'Edit'}
                                      </button>
                                      {currentVer && (
                                        <button
                                          onClick={() => handleTestRule(rule.id, currentVer.id)}
                                          disabled={testingRule}
                                          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs font-medium flex items-center gap-1"
                                        >
                                          <Play className="w-3 h-3" />
                                          Test
                                        </button>
                                      )}
                                      {!isPub && rule.versions.every((v) => v.status === 'DRAFT') && (
                                        <button
                                          onClick={() => handleDeleteRule(rule.id)}
                                          disabled={deletingRule}
                                          className="p-1 text-slate-500 hover:text-rose-400 transition"
                                          title="Delete draft rule"
                                        >
                                          <Trash2 className="w-3.5 h-3.5" />
                                        </button>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Step 4 Footer Navigation for Rules Tab */}
                  <div className="flex justify-between pt-4 border-t border-slate-800">
                    <button
                      onClick={() => setStep4SubTab('mapping')}
                      className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-xs font-medium"
                    >
                      <ArrowLeft className="w-4 h-4" /> Back to Mapping Studio
                    </button>

                    <button
                      onClick={() => updateSessionStep(5, 4)}
                      className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg text-xs font-bold transition flex items-center gap-1.5"
                    >
                      Proceed to Step 5 (Review & Activate) &rarr;
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 5: REVIEW & ACTIVATE */}
          {activeStep === 5 && (
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
                <div>
                  <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-emerald-400" />
                    Step 5: Review & Activate
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">
                    Unified Review Packet with Both-Sides Impact, In-Memory Deterministic Sandbox Evidence Pack, and Governed Activation with Four-Eyes Principle.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {reviewPacket?.feed_metadata && (
                    <span className={`px-2.5 py-1 rounded text-xs font-mono font-bold ${
                      reviewPacket.feed_metadata.status === 'ACTIVE'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : reviewPacket.approval_status?.status === 'PENDING_APPROVAL'
                        ? 'bg-amber-950 text-amber-300 border border-amber-800 animate-pulse'
                        : 'bg-slate-900 text-slate-300 border border-slate-800'
                    }`}>
                      {reviewPacket.approval_status?.status === 'PENDING_APPROVAL' ? 'PENDING APPROVAL' : reviewPacket.feed_metadata.status}
                    </span>
                  )}
                  <button
                    onClick={loadReviewPacket}
                    disabled={loadingPacket}
                    className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition"
                    title="Refresh Review Packet"
                  >
                    <RefreshCw className={`w-4 h-4 ${loadingPacket ? 'animate-spin text-cyan-400' : ''}`} />
                  </button>
                </div>
              </div>

              {/* 1. BOTH-SIDES IMPACT REVIEW PACKET */}
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  Both-Sides Impact Review Packet
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-3 text-xs">
                  {/* Card 1: Feed Metadata */}
                  <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1.5">
                    <p className="text-[11px] font-semibold text-slate-400 uppercase">1. Ingestion Metadata</p>
                    <p className="font-bold text-white truncate">{feed.name}</p>
                    <div className="text-[11px] text-slate-400 space-y-0.5">
                      <p>Domain: <span className="text-cyan-300 font-mono">{feed.domain}</span></p>
                      <p className="truncate font-mono text-[10px] text-slate-400">{feed.landing_folder}</p>
                      <p className="truncate font-mono text-[10px] text-slate-500">{feed.filename_pattern}</p>
                    </div>
                  </div>

                  {/* Card 2: Profiling Facts */}
                  <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1.5">
                    <p className="text-[11px] font-semibold text-slate-400 uppercase">2. Profiling Facts</p>
                    <p className="font-bold text-white">
                      {reviewPacket?.profiling_summary ? `${reviewPacket.profiling_summary.total_rows} Rows` : `${columnStats.length} Cols`}
                    </p>
                    <div className="text-[11px] text-slate-400 space-y-0.5">
                      <p>Columns: <span className="text-cyan-300 font-mono">{reviewPacket?.profiling_summary?.total_columns || columnStats.length}</span></p>
                      <p className="truncate text-[10px] text-slate-400">{reviewPacket?.profiling_summary?.sample_file_name || 'sample.csv'}</p>
                      <p className="text-emerald-400 font-medium text-[10px]">Deterministic Facts Observed</p>
                    </div>
                  </div>

                  {/* Card 3: Schema Contract */}
                  <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1.5">
                    <p className="text-[11px] font-semibold text-slate-400 uppercase">3. Schema Contract</p>
                    <div className="flex items-center justify-between">
                      <p className="font-bold text-white">
                        {reviewPacket?.schema_summary?.version_number ? `Version v${reviewPacket.schema_summary.version_number}` : 'No Contract'}
                      </p>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                        reviewPacket?.schema_summary?.status === 'PUBLISHED'
                          ? 'bg-emerald-950 text-emerald-300'
                          : 'bg-amber-950 text-amber-300'
                      }`}>
                        {reviewPacket?.schema_summary?.status || schemaStatus}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 space-y-0.5">
                      <p>Fields: <span className="text-cyan-300 font-mono">{reviewPacket?.schema_summary?.total_fields || schemaFields.length}</span></p>
                      <p>Required: <span className="text-slate-300 font-mono">{reviewPacket?.schema_summary?.required_fields_count || 0}</span></p>
                      <p className="text-[10px] text-slate-500">Immutable Contract Boundary</p>
                    </div>
                  </div>

                  {/* Card 4: Canonical Mapping */}
                  <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1.5">
                    <p className="text-[11px] font-semibold text-slate-400 uppercase">4. Canonical Mapping</p>
                    <div className="flex items-center justify-between">
                      <p className="font-bold text-white truncate">
                        {reviewPacket?.mapping_summary?.canonical_model_name || 'Canonical Model'}
                      </p>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                        reviewPacket?.mapping_summary?.status === 'PUBLISHED'
                          ? 'bg-emerald-950 text-emerald-300'
                          : 'bg-amber-950 text-amber-300'
                      }`}>
                        {reviewPacket?.mapping_summary?.status || mappingStatus}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 space-y-0.5">
                      <p>Mapped: <span className="text-emerald-400 font-mono">{reviewPacket?.mapping_summary?.mapped_fields_count || 0}</span> | Unmapped: <span className="text-slate-500 font-mono">{reviewPacket?.mapping_summary?.unmapped_fields_count || 0}</span></p>
                      <p className="text-[10px] text-slate-400">
                        {reviewPacket?.mapping_summary?.transform_counts
                          ? Object.entries(reviewPacket.mapping_summary.transform_counts).map(([k, v]) => `${k}:${v}`).join(', ')
                          : 'Direct mappings'}
                      </p>
                    </div>
                  </div>

                  {/* Card 5: DQ Rules */}
                  <div className="p-3.5 bg-slate-950 border border-slate-800 rounded-xl space-y-1.5">
                    <p className="text-[11px] font-semibold text-slate-400 uppercase">5. DQ Rules Engine</p>
                    <p className="font-bold text-white">
                      {reviewPacket?.rules_summary?.active_rules_count ?? rulesList.length} Active Rules
                    </p>
                    <div className="text-[11px] text-slate-400 space-y-0.5">
                      <p>Published: <span className="text-emerald-400 font-mono">{reviewPacket?.rules_summary?.published_rules_count ?? 0}</span> | Draft: <span className="text-amber-400 font-mono">{reviewPacket?.rules_summary?.draft_rules_count ?? 0}</span></p>
                      <p className="text-[10px] text-slate-400">
                        {reviewPacket?.rules_summary?.severities
                          ? Object.entries(reviewPacket.rules_summary.severities).map(([k, v]) => `${k}:${v}`).join(', ')
                          : '7 Rule Types'}
                      </p>
                      {reviewPacket?.rules_summary?.needs_review_count > 0 && (
                        <p className="text-amber-400 text-[10px]">
                          {reviewPacket.rules_summary.needs_review_count} flagged for review
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* 2. READINESS CHECKLIST GATING */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Governed Activation Readiness Checklist
                  </h3>
                  <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${
                    reviewPacket?.readiness_checklist?.all_prerequisites_met
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                      : 'bg-amber-950 text-amber-400 border border-amber-800'
                  }`}>
                    {reviewPacket?.readiness_checklist?.all_prerequisites_met ? 'ALL PREREQUISITES MET' : 'PREREQUISITES PENDING'}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                  {/* Step 1 */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step1_metadata_valid ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 1: Feed Ingestion Metadata Valid</span>
                  </div>

                  {/* Step 2 */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step2_profiling_complete ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 2: Representative Sample Profiling Complete</span>
                  </div>

                  {/* Step 3 */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step3_schema_published ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 3: Governed Schema Contract Published</span>
                  </div>

                  {/* Step 4 Mapping */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step4_mapping_published ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 4: Canonical Mapping Published & Schema-Aligned</span>
                  </div>

                  {/* Step 4 Rules */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step4_rules_published ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 4: Data Quality Rules Published (No Unaligned Drafts)</span>
                  </div>

                  {/* Step 5 Sandbox */}
                  <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                    {reviewPacket?.readiness_checklist?.step5_sandbox_passed ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    )}
                    <span className="text-slate-200">Step 5: Deterministic Sandbox Test Passed (Balanced)</span>
                  </div>
                </div>
              </div>

              {/* 3. DETERMINISTIC SANDBOX EXECUTION & EVIDENCE PACK */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                      <Play className="w-4 h-4 text-cyan-400" />
                      Deterministic Sandbox Execution & Evidence Pack
                    </h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Executes isolated in-memory test on representative sample with zero production database contamination.
                    </p>
                  </div>
                  <button
                    onClick={handleRunSandbox}
                    disabled={runningSandbox || !reviewPacket?.readiness_checklist?.step3_schema_published || !reviewPacket?.readiness_checklist?.step4_mapping_published}
                    className="flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:hover:bg-cyan-600 text-white px-4 py-2 rounded-lg text-xs font-bold transition shadow-lg shadow-cyan-950/50 shrink-0"
                  >
                    <Play className={`w-3.5 h-3.5 ${runningSandbox ? 'animate-spin' : ''}`} />
                    {runningSandbox ? 'Executing Sandbox Run...' : 'Run Sandbox Pipeline Test'}
                  </button>
                </div>

                {reviewPacket?.latest_sandbox_run ? (
                  <div className="space-y-4">
                    {/* Metrics Row */}
                    <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-slate-400 uppercase font-semibold">Total Sample Rows</p>
                        <p className="text-lg font-bold text-white font-mono">{reviewPacket.latest_sandbox_run.total_rows}</p>
                      </div>
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-emerald-400 uppercase font-semibold">Passed Rows</p>
                        <p className="text-lg font-bold text-emerald-400 font-mono">{reviewPacket.latest_sandbox_run.passed_rows}</p>
                      </div>
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-amber-400 uppercase font-semibold">Quarantined Rows</p>
                        <p className="text-lg font-bold text-amber-400 font-mono">{reviewPacket.latest_sandbox_run.quarantined_rows}</p>
                      </div>
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-slate-400 uppercase font-semibold">Pass Rate</p>
                        <p className="text-lg font-bold text-cyan-300 font-mono">{reviewPacket.latest_sandbox_run.pass_rate}%</p>
                      </div>
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-slate-400 uppercase font-semibold">Reconciliation</p>
                        <span className={`inline-block mt-1 px-2 py-0.5 rounded text-xs font-mono font-bold ${
                          reviewPacket.latest_sandbox_run.reconciliation_status === 'BALANCED'
                            ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                            : 'bg-rose-950 text-rose-300 border border-rose-800'
                        }`}>
                          {reviewPacket.latest_sandbox_run.reconciliation_status}
                        </span>
                      </div>
                      <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 text-center">
                        <p className="text-[10px] text-slate-400 uppercase font-semibold">Execution Time</p>
                        <p className="text-lg font-bold text-slate-300 font-mono">{reviewPacket.latest_sandbox_run.execution_duration_ms} ms</p>
                      </div>
                    </div>

                    {/* REJECT_FILE Critical Alert */}
                    {reviewPacket.latest_sandbox_run.has_reject_file_violation && (
                      <div className="p-3.5 bg-rose-950/80 border border-rose-700 rounded-xl flex items-center gap-3 text-xs text-rose-200">
                        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
                        <div>
                          <p className="font-bold text-white">REJECT_FILE Critical Severity Violation Detected</p>
                          <p className="text-rose-300 text-[11px] mt-0.5">
                            One or more rows violated a rule configured with REJECT_FILE severity. In production, this batch would be halted.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Per-Rule Breakdown */}
                    {reviewPacket.latest_sandbox_run.rule_metrics && Object.keys(reviewPacket.latest_sandbox_run.rule_metrics).length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-bold text-slate-300">Data Quality Rule Breakdown</p>
                        <div className="overflow-x-auto border border-slate-800 rounded-lg">
                          <table className="w-full text-left text-xs">
                            <thead className="bg-slate-900 text-slate-400 font-mono">
                              <tr>
                                <th className="p-2.5">Rule Name</th>
                                <th className="p-2.5">Severity</th>
                                <th className="p-2.5">Evaluated</th>
                                <th className="p-2.5">Failed</th>
                                <th className="p-2.5">Pass Rate</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800">
                              {Object.entries(reviewPacket.latest_sandbox_run.rule_metrics).map(([rName, m]: [string, any]) => (
                                <tr key={rName} className="hover:bg-slate-900/40">
                                  <td className="p-2.5 font-bold text-white">{rName}</td>
                                  <td className="p-2.5">
                                    <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                                      m.severity === 'REJECT_FILE'
                                        ? 'bg-rose-950 text-rose-300 border border-rose-800'
                                        : m.severity === 'QUARANTINE'
                                        ? 'bg-amber-950 text-amber-300 border border-amber-800'
                                        : 'bg-blue-950 text-blue-300 border border-blue-800'
                                    }`}>
                                      {m.severity}
                                    </span>
                                  </td>
                                  <td className="p-2.5 font-mono text-slate-300">{m.evaluated_count}</td>
                                  <td className="p-2.5 font-mono text-rose-400 font-bold">{m.failed_count}</td>
                                  <td className="p-2.5 font-mono text-emerald-400 font-bold">{m.pass_rate}%</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Privacy-Safe Transformed Canonical Preview */}
                    {reviewPacket.latest_sandbox_run.canonical_sample_preview && reviewPacket.latest_sandbox_run.canonical_sample_preview.length > 0 && (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                            <Eye className="w-3.5 h-3.5 text-cyan-400" />
                            Transformed Canonical Output Preview (Privacy Safe)
                          </p>
                          <span className="text-[10px] text-slate-400 italic">
                            Sample preview capped at 5 rows with PHI masking
                          </span>
                        </div>
                        <div className="overflow-x-auto border border-slate-800 rounded-lg max-h-48 overflow-y-auto">
                          <table className="w-full text-left text-xs">
                            <thead className="bg-slate-900 text-slate-400 font-mono">
                              <tr>
                                {Object.keys(reviewPacket.latest_sandbox_run.canonical_sample_preview[0]).map((col) => (
                                  <th key={col} className="p-2 whitespace-nowrap">{col}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800 font-mono text-[11px]">
                              {reviewPacket.latest_sandbox_run.canonical_sample_preview.map((row: any, rIdx: number) => (
                                <tr key={rIdx} className="hover:bg-slate-900/30">
                                  {Object.entries(row).map(([k, val]: [string, any], cIdx: number) => (
                                    <td key={cIdx} className="p-2 whitespace-nowrap text-slate-300">
                                      {val === null || val === undefined ? (
                                        <span className="text-slate-600 italic">null</span>
                                      ) : String(val).includes('***') ? (
                                        <span className="text-amber-300/80 font-bold">{String(val)}</span>
                                      ) : (
                                        String(val)
                                      )}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-8 text-slate-500 text-xs">
                    No sandbox execution run found yet. Click "Run Sandbox Pipeline Test" to produce evidence metrics.
                  </div>
                )}
              </div>

              {/* 4. GOVERNED ACTIVATION WORKFLOW (FOUR-EYES PRINCIPLE) */}
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-5 space-y-4">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Governed Activation & Four-Eyes Principle Sign-off
                </h3>

                {/* State A: Feed is ACTIVE */}
                {feed.status === 'ACTIVE' ? (
                  <div className="p-5 bg-emerald-950/60 border border-emerald-800 rounded-xl flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <ShieldCheck className="w-8 h-8 text-emerald-400 shrink-0" />
                      <div>
                        <h4 className="text-sm font-bold text-white">Feed is ACTIVATED & Ingestion Ready</h4>
                        <p className="text-xs text-emerald-300">
                          Governing activation record locked into immutable ledger. Live automated batch pipeline execution is enabled.
                        </p>
                      </div>
                    </div>
                    <Link
                      href={`/feeds/${feed.id}`}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-xs font-medium shrink-0"
                    >
                      View Feed Dashboard &rarr;
                    </Link>
                  </div>
                ) : reviewPacket?.approval_status?.status === 'PENDING_APPROVAL' ? (
                  /* State B: Approval is PENDING */
                  <div className="space-y-4">
                    <div className="p-4 bg-amber-950/40 border border-amber-800/80 rounded-xl space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-2 font-bold text-amber-300">
                          <Clock className="w-4 h-4 text-amber-400" />
                          Activation Review Pending Engineering Sign-off
                        </span>
                        <span className="text-slate-400 font-mono text-[11px]">
                          Submitted: {new Date(reviewPacket.approval_status.submitted_at).toLocaleString()}
                        </span>
                      </div>
                      <p className="text-slate-300">
                        Submitted by: <span className="font-mono text-cyan-300">{reviewPacket.approval_status.submitted_by_email || reviewPacket.approval_status.submitted_by}</span>
                      </p>
                      {reviewPacket.approval_status.submission_notes && (
                        <p className="text-slate-400 italic">
                          Notes: "{reviewPacket.approval_status.submission_notes}"
                        </p>
                      )}
                    </div>

                    {/* Four-Eyes Principle Warning for Submitter */}
                    {reviewPacket?.user_capabilities?.is_author && (
                      <div className="p-4 bg-blue-950/50 border border-blue-800 rounded-xl flex items-start gap-3 text-xs text-blue-200">
                        <AlertCircle className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
                        <div>
                          <p className="font-bold text-white">Four-Eyes Principle Enforced</p>
                          <p className="text-slate-300 text-[11px] mt-0.5">
                            You submitted this feed for activation review. Under the Four-Eyes Principle, an independent Engineer must review the evidence packet and approve this feed for production.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Approver Controls (Only for independent Engineer) */}
                    {reviewPacket?.user_capabilities?.can_approve && (
                      <div className="p-4 bg-slate-900 border border-slate-800 rounded-xl space-y-3">
                        <p className="text-xs font-bold text-white">Independent Engineer Decision Console</p>
                        <div className="flex flex-col sm:flex-row items-center gap-3">
                          <button
                            onClick={() => { setDecisionNotes(''); setApproveModalOpen(true); }}
                            className="w-full sm:w-auto flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-2.5 rounded-lg text-xs font-bold transition shadow-lg shadow-emerald-950/40"
                          >
                            <ShieldCheck className="w-4 h-4" />
                            Approve Feed Activation
                          </button>
                          <button
                            onClick={() => { setDecisionNotes(''); setRejectModalOpen(true); }}
                            className="w-full sm:w-auto flex items-center justify-center gap-2 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-800 px-5 py-2.5 rounded-lg text-xs font-bold transition"
                          >
                            <XCircle className="w-4 h-4" />
                            Reject Activation
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  /* State C: DRAFT / Ready for Submission or Rejection Follow-up */
                  <div className="space-y-3">
                    {reviewPacket?.approval_status?.status === 'REJECTED' && (
                      <div className="p-3.5 bg-rose-950/60 border border-rose-800 rounded-xl text-xs space-y-1">
                        <p className="font-bold text-rose-300 flex items-center gap-1.5">
                          <XCircle className="w-4 h-4 text-rose-400" />
                          Previous Activation Request Was Rejected
                        </p>
                        <p className="text-slate-300">
                          Feedback: "{reviewPacket.approval_status.decision_notes}"
                        </p>
                        <p className="text-[11px] text-slate-400">
                          Please address reviewer comments, run a new sandbox test, and resubmit when ready.
                        </p>
                      </div>
                    )}

                    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-4 bg-slate-900 border border-slate-800 rounded-xl">
                      <div>
                        <h4 className="text-sm font-bold text-white">Submit for Governed Activation</h4>
                        <p className="text-xs text-slate-400 mt-0.5">
                          Formal submission gates feed activation behind independent engineering review.
                        </p>
                      </div>
                      <button
                        onClick={() => { setSubmissionNotes(''); setSubmitModalOpen(true); }}
                        disabled={!reviewPacket?.readiness_checklist?.all_prerequisites_met || submittingApproval}
                        className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white px-6 py-2.5 rounded-lg text-xs font-bold transition shadow-lg shadow-blue-950/50 shrink-0"
                      >
                        <Send className="w-3.5 h-3.5" />
                        Submit for Activation Review
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Step 5 Footer Navigation */}
              <div className="flex justify-between pt-4 border-t border-slate-800">
                <button
                  onClick={() => setActiveStep(4)}
                  className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-xs font-medium"
                >
                  <ArrowLeft className="w-4 h-4" /> Back to Step 4
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* TRANSFORM CONFIGURATION MODAL */}
      {modalTargetField && modalLineState && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <SlidersHorizontal className="w-4 h-4 text-blue-400" />
                  Configure Transform for '{modalTargetField.field_name}'
                </h3>
                <p className="text-[11px] text-slate-400">
                  Target Type: <span className="text-cyan-300 font-mono">{modalTargetField.data_type}</span> | Required: {modalTargetField.is_required ? 'Yes' : 'No'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setModalTargetField(null);
                  setModalLineState(null);
                }}
                className="text-slate-400 hover:text-white text-xs"
              >
                Cancel
              </button>
            </div>

            {/* Transform Type Selector */}
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-slate-300">Transform Type</label>
              <select
                value={modalLineState.transform_type}
                onChange={(e) => {
                  setModalLineState({
                    ...modalLineState,
                    transform_type: e.target.value,
                    transform_params: {},
                  });
                }}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-cyan-300"
              >
                {TRANSFORM_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            {/* Source Field(s) Picker */}
            {modalLineState.transform_type !== 'CONSTANT' && (
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-slate-300">
                  Source Field(s)
                  {['CONCAT', 'COALESCE'].includes(modalLineState.transform_type) && (
                    <span className="text-slate-400 font-normal ml-1">(Select 2 or more)</span>
                  )}
                </label>
                <div className="grid grid-cols-2 gap-2 max-h-36 overflow-y-auto p-2 bg-slate-950 border border-slate-800 rounded-lg">
                  {schemaFields.map((sf) => {
                    const isChecked = modalLineState.source_field_names?.includes(sf.field_name);
                    return (
                      <label key={sf.field_name} className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                        <input
                          type={['CONCAT', 'COALESCE'].includes(modalLineState.transform_type) ? 'checkbox' : 'radio'}
                          name="source_field_selector"
                          checked={isChecked}
                          onChange={(e) => {
                            if (['CONCAT', 'COALESCE'].includes(modalLineState.transform_type)) {
                              const current = modalLineState.source_field_names || [];
                              const updated = e.target.checked
                                ? [...current, sf.field_name]
                                : current.filter((x) => x !== sf.field_name);
                              setModalLineState({ ...modalLineState, source_field_names: updated });
                            } else {
                              setModalLineState({ ...modalLineState, source_field_names: [sf.field_name] });
                            }
                          }}
                          className="rounded bg-slate-900 border-slate-700 text-blue-600"
                        />
                        <span className="font-mono">{sf.field_name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Transform Specific Parameters */}
            {modalLineState.transform_type === 'CONSTANT' && (
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-slate-300">Constant Value</label>
                <input
                  type="text"
                  value={modalLineState.transform_params?.value ?? ''}
                  onChange={(e) => {
                    setModalLineState({
                      ...modalLineState,
                      transform_params: { ...modalLineState.transform_params, value: e.target.value },
                    });
                  }}
                  placeholder="Enter static constant value"
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                />
              </div>
            )}

            {modalLineState.transform_type === 'CONCAT' && (
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-slate-300">Delimiter</label>
                <input
                  type="text"
                  value={modalLineState.transform_params?.delimiter ?? ' ' }
                  onChange={(e) => {
                    setModalLineState({
                      ...modalLineState,
                      transform_params: { ...modalLineState.transform_params, delimiter: e.target.value },
                    });
                  }}
                  placeholder="Delimiter, e.g. single space or comma"
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                />
              </div>
            )}

            {modalLineState.transform_type === 'DATE_FORMAT' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300">Source Format</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.source_format ?? 'DD/MM/YYYY'}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, source_format: e.target.value },
                      });
                    }}
                    placeholder="e.g. DD/MM/YYYY"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300">Target Format</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.target_format ?? 'YYYY-MM-DD'}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, target_format: e.target.value },
                      });
                    }}
                    placeholder="YYYY-MM-DD"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'STRING_CLEAN' && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="trim_cb"
                    checked={modalLineState.transform_params?.trim ?? true}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, trim: e.target.checked },
                      });
                    }}
                    className="rounded bg-slate-950 border-slate-700"
                  />
                  <label htmlFor="trim_cb" className="text-xs text-slate-300 cursor-pointer">Trim leading & trailing whitespace</label>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Casing</label>
                  <select
                    value={modalLineState.transform_params?.casing ?? 'UPPER'}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, casing: e.target.value },
                      });
                    }}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-cyan-300"
                  >
                    <option value="NONE">NONE (Preserve source)</option>
                    <option value="UPPER">UPPERCASE</option>
                    <option value="LOWER">lowercase</option>
                  </select>
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'VALUE_MAP' && (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Dictionary (JSON)</label>
                  <textarea
                    rows={3}
                    value={
                      typeof modalLineState.transform_params?.dictionary === 'object'
                        ? JSON.stringify(modalLineState.transform_params.dictionary, null, 2)
                        : '{\\n  "M": "MALE",\\n  "F": "FEMALE"\\n}'
                    }
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value);
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, dictionary: parsed },
                        });
                      } catch {}
                    }}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-cyan-300"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">On Unmapped</label>
                    <select
                      value={modalLineState.transform_params?.on_unmapped ?? 'DEFAULT'}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, on_unmapped: e.target.value },
                        });
                      }}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    >
                      <option value="DEFAULT">DEFAULT</option>
                      <option value="NULL">NULL</option>
                      <option value="ERROR">ERROR</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Default Fallback</label>
                    <input
                      type="text"
                      value={modalLineState.transform_params?.default ?? 'UNKNOWN'}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, default: e.target.value },
                        });
                      }}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Structural Transform Parameters */}
            {modalLineState.transform_type === 'EXPLODE' && (
              <div className="space-y-3 p-3 bg-slate-950 border border-slate-800 rounded-lg">
                <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">EXPLODE Parameters</span>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Array Path</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.array_path ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, array_path: e.target.value },
                      });
                    }}
                    placeholder="e.g. entry, diagnoses[*], or telecom"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Target Element Field (Optional)</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.target_field ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, target_field: e.target.value },
                      });
                    }}
                    placeholder="e.g. diagnosis_item"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="outer_join_cb"
                    checked={modalLineState.transform_params?.outer_join ?? true}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, outer_join: e.target.checked },
                      });
                    }}
                    className="rounded bg-slate-900 border-slate-700"
                  />
                  <label htmlFor="outer_join_cb" className="text-xs text-slate-300 cursor-pointer">
                    Outer Join (retain row with NULL if array is empty)
                  </label>
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'FLATTEN' && (
              <div className="space-y-3 p-3 bg-slate-950 border border-slate-800 rounded-lg">
                <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">FLATTEN Parameters</span>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Prefix (Optional)</label>
                    <input
                      type="text"
                      value={modalLineState.transform_params?.prefix ?? ''}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, prefix: e.target.value },
                        });
                      }}
                      placeholder="e.g. patient"
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Separator</label>
                    <input
                      type="text"
                      value={modalLineState.transform_params?.separator ?? '_'}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, separator: e.target.value },
                        });
                      }}
                      placeholder="_"
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Max Depth</label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={modalLineState.transform_params?.max_depth ?? 5}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, max_depth: parseInt(e.target.value) || 5 },
                        });
                      }}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'PATH_EXTRACT' && (
              <div className="space-y-3 p-3 bg-slate-950 border border-slate-800 rounded-lg">
                <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">PATH_EXTRACT Parameters</span>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">JSONPath / Dot-Path</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.path ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, path: e.target.value },
                      });
                    }}
                    placeholder="e.g. entry[*].resource.id, patient.name[0].family, or telecom[?(@.system=='phone')].value"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Default Fallback Value (Optional)</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.default ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, default: e.target.value },
                      });
                    }}
                    placeholder="Value if path not found"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'ARRAY_MAP' && (
              <div className="space-y-3 p-3 bg-slate-950 border border-slate-800 rounded-lg">
                <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">ARRAY_MAP Parameters</span>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Array Path</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.array_path ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, array_path: e.target.value },
                      });
                    }}
                    placeholder="e.g. identifier[*], telecom, or coding"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Element Sub-Path (Optional)</label>
                    <input
                      type="text"
                      value={modalLineState.transform_params?.element_path ?? ''}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, element_path: e.target.value },
                        });
                      }}
                      placeholder="e.g. value, code, or display"
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Delimiter (Optional)</label>
                    <input
                      type="text"
                      value={modalLineState.transform_params?.delimiter ?? ', '}
                      onChange={(e) => {
                        setModalLineState({
                          ...modalLineState,
                          transform_params: { ...modalLineState.transform_params, delimiter: e.target.value },
                        });
                      }}
                      placeholder=", "
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                    />
                  </div>
                </div>
              </div>
            )}

            {modalLineState.transform_type === 'UNNEST' && (
              <div className="space-y-3 p-3 bg-slate-950 border border-slate-800 rounded-lg">
                <span className="text-[10px] font-mono text-cyan-400 uppercase font-bold">UNNEST Parameters</span>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Structure Path</label>
                  <input
                    type="text"
                    value={modalLineState.transform_params?.path ?? ''}
                    onChange={(e) => {
                      setModalLineState({
                        ...modalLineState,
                        transform_params: { ...modalLineState.transform_params, path: e.target.value },
                      });
                    }}
                    placeholder="e.g. patient.address or subject"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-white"
                  />
                </div>
              </div>
            )}

            {/* Interactive Transform Tester Panel */}
            <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Play className="w-3.5 h-3.5 text-emerald-400" />
                  Test Transform with Sample JSON
                </span>
                <button
                  type="button"
                  onClick={handleRunStructuralTest}
                  disabled={runningStructuralTest}
                  className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-bold transition flex items-center gap-1"
                >
                  {runningStructuralTest ? 'Testing...' : 'Execute Test'}
                </button>
              </div>
              <textarea
                rows={3}
                value={structuralTestInput}
                onChange={(e) => setStructuralTestInput(e.target.value)}
                placeholder="Enter sample JSON record"
                className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-800 rounded text-[11px] font-mono text-slate-200"
              />
              {structuralTestResult && (
                <div className={`p-2 rounded border text-[11px] font-mono ${
                  structuralTestResult.success ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300' : 'bg-rose-950/60 border-rose-800 text-rose-300'
                }`}>
                  {structuralTestResult.success ? (
                    <div>
                      <span className="text-[10px] text-slate-400">Extracted Result ({structuralTestResult.result_type}):</span>
                      <pre className="mt-1 overflow-x-auto">{JSON.stringify(structuralTestResult.result, null, 2)}</pre>
                    </div>
                  ) : (
                    <div>Error: {structuralTestResult.error}</div>
                  )}
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-between pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => {
                  setMappingLines(mappingLines.filter((l) => l.canonical_field_id !== modalTargetField.id));
                  setModalTargetField(null);
                  setModalLineState(null);
                }}
                className="text-xs text-rose-400 hover:text-rose-300 flex items-center gap-1"
              >
                <Trash2 className="w-3.5 h-3.5" /> Remove Mapping
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setModalTargetField(null);
                    setModalLineState(null);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={saveTransformModal}
                  className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition"
                >
                  Apply Transform
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* RULE BUILDER / EDITOR MODAL */}
      {ruleModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Scale className="w-4 h-4 text-blue-400" />
                  {ruleModalMode === 'create' ? 'Create Data Quality Rule' : ruleModalMode === 'edit' ? `Edit Rule: ${ruleForm.name}` : `View Rule: ${ruleForm.name}`}
                </h3>
                <p className="text-[11px] text-slate-400">
                  Target Field: <span className="text-cyan-300 font-mono">{ruleForm.target_field}</span> | Type: <span className="font-mono text-white">{ruleForm.rule_type}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => setRuleModalOpen(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                Close
              </button>
            </div>

            {/* Validation alert if present */}
            {ruleValidationRep && (
              <div className={`p-3 rounded-lg text-xs border ${
                ruleValidationRep.is_valid ? 'bg-emerald-950/80 border-emerald-800 text-emerald-300' : 'bg-rose-950/80 border-rose-800 text-rose-300'
              }`}>
                <p className="font-bold">{ruleValidationRep.is_valid ? 'Validation Passed' : 'Validation Errors:'}</p>
                {ruleValidationRep.errors.map((e: string, i: number) => (
                  <p key={i} className="text-[11px] mt-0.5">• {e}</p>
                ))}
              </div>
            )}

            {/* Rule Config Form */}
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Rule Name</label>
                  <input
                    type="text"
                    disabled={ruleModalMode !== 'create'}
                    value={ruleForm.name}
                    onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })}
                    placeholder="e.g. claim_amount_positive"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Target Field</label>
                  <select
                    disabled={ruleModalMode === 'view'}
                    value={ruleForm.target_field}
                    onChange={(e) => setRuleForm({ ...ruleForm, target_field: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-cyan-300 font-mono text-xs"
                  >
                    {schemaFields.map((f) => (
                      <option key={f.field_name} value={f.field_name}>
                        {f.field_name} ({f.data_type})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Rule Type</label>
                  <select
                    disabled={ruleModalMode === 'view'}
                    value={ruleForm.rule_type}
                    onChange={(e) => setRuleForm({ ...ruleForm, rule_type: e.target.value, rule_config: {} })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs"
                  >
                    {RULE_TYPES.map((rt) => (
                      <option key={rt} value={rt}>{rt}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Severity</label>
                  <select
                    disabled={ruleModalMode === 'view'}
                    value={ruleForm.severity}
                    onChange={(e) => setRuleForm({ ...ruleForm, severity: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs"
                  >
                    {SEVERITIES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Dynamic Type Config Panels */}
              {ruleForm.rule_type === 'RANGE' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                  <p className="font-semibold text-slate-300">RANGE Parameters</p>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] text-slate-400">Min Boundary</label>
                      <input
                        type="number"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.min ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, min: e.target.value ? parseFloat(e.target.value) : null },
                        })}
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-slate-400">Max Boundary</label>
                      <input
                        type="number"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.max ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, max: e.target.value ? parseFloat(e.target.value) : null },
                        })}
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                    <div className="flex items-center gap-2 pt-4">
                      <input
                        type="checkbox"
                        disabled={ruleModalMode === 'view'}
                        checked={ruleForm.rule_config?.inclusive ?? true}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, inclusive: e.target.checked },
                        })}
                        className="rounded bg-slate-900 border-slate-700"
                      />
                      <label className="text-[11px] text-slate-300">Inclusive [min, max]</label>
                    </div>
                  </div>
                </div>
              )}

              {ruleForm.rule_type === 'REGEX' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-2">
                  <label className="block font-semibold text-slate-300">Regular Expression Pattern</label>
                  <input
                    type="text"
                    disabled={ruleModalMode === 'view'}
                    value={ruleForm.rule_config?.pattern ?? ''}
                    onChange={(e) => setRuleForm({
                      ...ruleForm,
                      rule_config: { ...ruleForm.rule_config, pattern: e.target.value },
                    })}
                    placeholder="e.g. ^[0-9]{3}-[0-9]{2}-[0-9]{4}$"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                  />
                </div>
              )}

              {ruleForm.rule_type === 'ENUM' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-2">
                  <label className="block font-semibold text-slate-300">Allowed Values (Comma-separated)</label>
                  <input
                    type="text"
                    disabled={ruleModalMode === 'view'}
                    value={Array.isArray(ruleForm.rule_config?.allowed_values) ? ruleForm.rule_config.allowed_values.join(', ') : ''}
                    onChange={(e) => setRuleForm({
                      ...ruleForm,
                      rule_config: {
                        ...ruleForm.rule_config,
                        allowed_values: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                      },
                    })}
                    placeholder="e.g. ACTIVE, INACTIVE, PENDING"
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                  />
                  <div className="flex items-center gap-2 pt-1">
                    <input
                      type="checkbox"
                      disabled={ruleModalMode === 'view'}
                      checked={ruleForm.rule_config?.case_sensitive ?? true}
                      onChange={(e) => setRuleForm({
                        ...ruleForm,
                        rule_config: { ...ruleForm.rule_config, case_sensitive: e.target.checked },
                      })}
                      className="rounded bg-slate-900 border-slate-700"
                    />
                    <label className="text-[11px] text-slate-300">Case Sensitive</label>
                  </div>
                </div>
              )}

              {ruleForm.rule_type === 'LENGTH' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                  <p className="font-semibold text-slate-300">String Length Limits</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[11px] text-slate-400">Min Length</label>
                      <input
                        type="number"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.min_length ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, min_length: e.target.value ? parseInt(e.target.value, 10) : null },
                        })}
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-slate-400">Max Length</label>
                      <input
                        type="number"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.max_length ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, max_length: e.target.value ? parseInt(e.target.value, 10) : null },
                        })}
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}

              {ruleForm.rule_type === 'DATE_RANGE' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                  <p className="font-semibold text-slate-300">Date Range & Format</p>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] text-slate-400">Format Pattern</label>
                      <select
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.format ?? 'YYYY-MM-DD'}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, format: e.target.value },
                        })}
                        className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      >
                        <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                        <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                        <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                        <option value="YYYY/MM/DD">YYYY/MM/DD</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[11px] text-slate-400">Min Date</label>
                      <input
                        type="text"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.min_date ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, min_date: e.target.value || null },
                        })}
                        placeholder="e.g. 1900-01-01"
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-slate-400">Max Date</label>
                      <input
                        type="text"
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.max_date ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, max_date: e.target.value || null },
                        })}
                        placeholder="e.g. 2099-12-31"
                        className="w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}

              {ruleForm.rule_type === 'CROSS_FIELD' && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                  <p className="font-semibold text-slate-300">Cross-Field Comparison</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[11px] text-slate-400">Comparison Field</label>
                      <select
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.compare_field ?? ''}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, compare_field: e.target.value },
                        })}
                        className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-cyan-300 font-mono"
                      >
                        <option value="">Select field...</option>
                        {schemaFields
                          .filter((f) => f.field_name !== ruleForm.target_field)
                          .map((f) => (
                            <option key={f.field_name} value={f.field_name}>
                              {f.field_name} ({f.data_type})
                            </option>
                          ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-[11px] text-slate-400">Comparison Operator</label>
                      <select
                        disabled={ruleModalMode === 'view'}
                        value={ruleForm.rule_config?.operator ?? 'EQ'}
                        onChange={(e) => setRuleForm({
                          ...ruleForm,
                          rule_config: { ...ruleForm.rule_config, operator: e.target.value },
                        })}
                        className="w-full px-2 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white font-mono"
                      >
                        <option value="EQ">== (Equal)</option>
                        <option value="NE">!= (Not Equal)</option>
                        <option value="GT">&gt; (Greater Than)</option>
                        <option value="GTE">&gt;= (Greater Than or Equal)</option>
                        <option value="LT">&lt; (Less Than)</option>
                        <option value="LTE">&lt;= (Less Than or Equal)</option>
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Needs Review & Custom Template */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Error Message Template</label>
                  <input
                    type="text"
                    disabled={ruleModalMode === 'view'}
                    value={ruleForm.error_message_template}
                    onChange={(e) => setRuleForm({ ...ruleForm, error_message_template: e.target.value })}
                    placeholder="e.g. Invalid value {value}"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-xs"
                  />
                </div>
                <div className="flex items-center gap-2 pt-6">
                  <input
                    type="checkbox"
                    disabled={ruleModalMode === 'view'}
                    checked={ruleForm.needs_review}
                    onChange={(e) => setRuleForm({ ...ruleForm, needs_review: e.target.checked })}
                    className="rounded bg-slate-950 border-slate-800"
                  />
                  <label className="text-xs text-slate-300">Flag for Technical Review (Needs Review)</label>
                </div>
              </div>

              {/* Test Run Results in Modal */}
              {testRunResult && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="font-bold text-white text-xs">Latest Sample Test Result</p>
                    <span className="font-mono text-emerald-400 font-bold">{testRunResult.pass_rate}% Passed</span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    Tested {testRunResult.total_rows} rows: {testRunResult.passed_rows} passed, {testRunResult.failed_rows} failed.
                  </p>
                  {testRunResult.failed_row_details && testRunResult.failed_row_details.length > 0 && (
                    <div className="overflow-x-auto border border-slate-800 rounded-lg max-h-36 overflow-y-auto">
                      <table className="w-full text-left text-[11px]">
                        <thead className="bg-slate-900 text-slate-400 font-mono">
                          <tr>
                            <th className="p-2">Row #</th>
                            <th className="p-2">Field</th>
                            <th className="p-2">Reason</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800">
                          {testRunResult.failed_row_details.slice(0, 5).map((f: any, idx: number) => (
                            <tr key={idx} className="hover:bg-slate-900/30">
                              <td className="p-2 font-mono text-slate-400">{f.row_number}</td>
                              <td className="p-2 font-mono text-cyan-300">{f.field_name}</td>
                              <td className="p-2 text-rose-300">{f.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="text-[10px] text-slate-500 italic">
                    Note: Actual cell/sample values are transiently reviewed in session and never persisted to the database.
                  </p>
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-between pt-3 border-t border-slate-800">
              <div className="flex items-center gap-2">
                {editingRule && editingRule.version && (
                  <>
                    <button
                      type="button"
                      onClick={() => handleValidateRule(editingRule.rule.id, editingRule.version.id)}
                      disabled={validatingRule}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs font-medium"
                    >
                      {validatingRule ? 'Validating...' : 'Validate'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleTestRule(editingRule.rule.id, editingRule.version.id)}
                      disabled={testingRule}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-xs font-medium flex items-center gap-1"
                    >
                      <Play className="w-3 h-3 text-cyan-400" />
                      {testingRule ? 'Testing...' : 'Test Against Sample'}
                    </button>
                  </>
                )}
              </div>

              <div className="flex items-center gap-2">
                {ruleModalMode === 'view' && editingRule?.version?.status === 'PUBLISHED' && (
                  <button
                    type="button"
                    onClick={() => handleSpawnRuleVersion(editingRule.rule.id)}
                    disabled={spawningRuleVersion}
                    className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition flex items-center gap-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    {spawningRuleVersion ? 'Spawning...' : 'New Draft Version'}
                  </button>
                )}

                {ruleModalMode !== 'view' && (
                  <>
                    <button
                      type="button"
                      onClick={handleSaveRule}
                      disabled={savingRule || !ruleForm.name || !ruleForm.target_field}
                      className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold transition border border-slate-700"
                    >
                      {savingRule ? 'Saving...' : 'Save Draft'}
                    </button>

                    {editingRule && editingRule.version?.status === 'DRAFT' && (
                      <button
                        type="button"
                        onClick={() => handlePublishRule(editingRule.rule.id, editingRule.version.id)}
                        disabled={publishingRule}
                        className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition flex items-center gap-1 shadow-lg shadow-emerald-950/40"
                      >
                        <ShieldCheck className="w-3.5 h-3.5" />
                        {publishingRule ? 'Publishing...' : 'Publish Rule'}
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* STEP 5: SUBMIT FOR APPROVAL MODAL */}
      {submitModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Send className="w-4 h-4 text-blue-400" />
                Submit Feed for Governed Activation Review
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Submitting places the feed into PENDING_APPROVAL status. Under the Four-Eyes Principle, an independent Engineer must review and approve this feed for production.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Submission Notes & Context (Optional)
              </label>
              <textarea
                value={submissionNotes}
                onChange={(e) => setSubmissionNotes(e.target.value)}
                placeholder="e.g. All 7 transforms configured, 100% balanced reconciliation, ready for nightly batch ingestion."
                rows={3}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-xs placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setSubmitModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmitApproval}
                disabled={submittingApproval}
                className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-blue-950/50"
              >
                <Send className="w-3.5 h-3.5" />
                {submittingApproval ? 'Submitting...' : 'Confirm Submission'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 5: APPROVE ACTIVATION MODAL */}
      {approveModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                Approve Feed Activation (Four-Eyes Sign-off)
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Certify that the evidence pack, contract alignments, and data quality rules have been independently reviewed.
              </p>
            </div>

            <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-xl text-xs text-emerald-200">
              <p className="font-semibold text-white">Immutable Ledger Guarantee:</p>
              <p className="text-[11px] text-emerald-300 mt-0.5">
                Activation pins the exact schema version, mapping version, and active rule version IDs in the FeedActivationRecord ledger.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Decision Notes & Sign-off Remarks (Optional)
              </label>
              <textarea
                value={decisionNotes}
                onChange={(e) => setDecisionNotes(e.target.value)}
                placeholder="e.g. Verified reconciliation metrics and schema alignment. Approved for live production ingestion."
                rows={3}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-xs placeholder:text-slate-600 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setApproveModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleApproveActivation}
                disabled={approvingFeed}
                className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-emerald-950/50"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                {approvingFeed ? 'Activating...' : 'Approve & Activate Feed'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 5: REJECT ACTIVATION MODAL */}
      {rejectModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <XCircle className="w-5 h-5 text-rose-400" />
                Reject Activation Request
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Rejection reverts the activation request and records an immutable audit record. A mandatory reason is required.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Mandatory Rejection Reason <span className="text-rose-400">*</span>
              </label>
              <textarea
                value={decisionNotes}
                onChange={(e) => setDecisionNotes(e.target.value)}
                placeholder="Explain why this activation cannot proceed (minimum 3 characters)..."
                rows={3}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-xs placeholder:text-slate-600 focus:outline-none focus:border-rose-500"
              />
              {decisionNotes.trim().length < 3 && (
                <p className="text-[11px] text-rose-400 mt-1">Minimum 3 characters required.</p>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRejectActivation}
                disabled={rejectingFeed || decisionNotes.trim().length < 3}
                className="px-5 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:opacity-40 disabled:hover:bg-rose-600 text-white text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-rose-950/50"
              >
                <XCircle className="w-3.5 h-3.5" />
                {rejectingFeed ? 'Rejecting...' : 'Confirm Rejection'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

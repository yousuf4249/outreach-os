import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { useNotify } from '../context/NotificationContext';
import { useConfirm } from '../context/ConfirmContext';
import { useLoading } from '../context/LoadingContext';
import { cn } from '../utils/cn';
import {
  RiUserAddLine,
  RiUploadCloud2Line,
  RiDownload2Line,
  RiDeleteBinLine,
  RiFilter3Line,
  RiSearchLine,
  RiCloseLine,
  RiCheckLine,
  RiFolderUserLine,
  RiBuildingLine,
  RiMapPinLine,
  RiGlobalLine,
  RiPhoneLine,
  RiPriceTag3Line,
} from 'react-icons/ri';

const PIPELINE_STATUSES = [
  { value: 'all', label: 'All Stages' },
  { value: 'new', label: 'New' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'follow_up_scheduled', label: 'Follow-up Scheduled' },
  { value: 'replied', label: 'Replied' },
  { value: 'interested', label: 'Interested' },
  { value: 'meeting_scheduled', label: 'Meeting Scheduled' },
  { value: 'proposal_sent', label: 'Proposal Sent' },
  { value: 'won', label: 'Won' },
  { value: 'lost', label: 'Lost' },
  { value: 'not_interested', label: 'Not Interested' },
];

function pipelineBadge(status) {
  const s = (status || 'new').toLowerCase();
  switch (s) {
    case 'new':
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-300';
    case 'contacted':
      return 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 border-blue-300';
    case 'follow_up_scheduled':
      return 'bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300 border-amber-300';
    case 'replied':
      return 'bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300 border-teal-300';
    case 'interested':
      return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border-emerald-300 font-semibold';
    case 'meeting_scheduled':
      return 'bg-purple-50 text-purple-700 dark:bg-purple-950/50 dark:text-purple-300 border-purple-300 font-semibold';
    case 'proposal_sent':
      return 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300 border-indigo-300';
    case 'won':
      return 'bg-green-100 text-green-800 dark:bg-green-950/70 dark:text-green-300 border-green-500 font-bold';
    case 'lost':
    case 'not_interested':
      return 'bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300 border-rose-300';
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
  }
}

export default function Leads() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [leads, setLeads] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [search, setSearch] = useState('');
  const [pipelineFilter, setPipelineFilter] = useState('all');
  const [selected, setSelected] = useState(() => new Set());
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Modals state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [leadFormData, setLeadFormData] = useState({
    email: '',
    name: '',
    company: '',
    phone: '',
    website: '',
    industry: '',
    city: '',
    country: '',
    lead_source: 'Cold Outreach',
    notes: '',
    pipeline_status: 'new',
    tags: '',
  });

  // Bulk operation states
  const [bulkCampaignId, setBulkCampaignId] = useState('');
  const [bulkPipelineTarget, setBulkPipelineTarget] = useState('contacted');

  // File Import state
  const [importFile, setImportFile] = useState(null);
  const [importColumns, setImportColumns] = useState([]);
  const [importMapping, setImportMapping] = useState({
    email: '',
    name: '',
    company: '',
    phone: '',
    website: '',
    industry: '',
    city: '',
    country: '',
    lead_source: '',
    notes: '',
  });
  const [duplicateAction, setDuplicateAction] = useState('skip');
  const [importCampaignId, setImportCampaignId] = useState('');
  const [importResult, setImportResult] = useState(null);

  const notify = useNotify();
  const confirm = useConfirm();
  const loading = useLoading();

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Fetch campaigns for assignment
  useEffect(() => {
    api.get('/campaigns').then((res) => setCampaigns(res || [])).catch(() => {});
  }, []);

  const loadLeads = useCallback(async () => {
    loading.start();
    try {
      const params = new URLSearchParams();
      if (debouncedSearch) params.set('q', debouncedSearch);
      const qs = params.toString();
      const data = await api.get('/leads' + (qs ? `?${qs}` : ''));
      setLeads(Array.isArray(data) ? data : []);
      setSelected(new Set());
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to load prospects' });
    } finally {
      loading.stop();
    }
  }, [debouncedSearch, loading, notify]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads]);

  const visibleLeads = useMemo(() => {
    return leads.filter((l) => {
      if (pipelineFilter === 'all') return true;
      return (l.pipeline_status || 'new').toLowerCase() === pipelineFilter;
    });
  }, [leads, pipelineFilter]);

  const visibleIds = useMemo(() => visibleLeads.map((l) => l.id), [visibleLeads]);

  const toggleOne = (id) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const toggleAll = () => {
    if (selected.size === visibleIds.length && visibleIds.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleIds));
    }
  };

  // Add Single Prospect
  const handleCreateLead = async (e) => {
    e.preventDefault();
    if (!leadFormData.email || !leadFormData.email.includes('@')) {
      notify({ type: 'error', message: 'Valid email address is required.' });
      return;
    }

    loading.start();
    try {
      const payload = {
        ...leadFormData,
        tags: leadFormData.tags ? leadFormData.tags.split(',').map((t) => t.trim()).filter(Boolean) : [],
      };
      await api.post('/leads', payload);
      notify({ type: 'success', message: 'Prospect added successfully!' });
      setCreateModalOpen(false);
      setLeadFormData({
        email: '',
        name: '',
        company: '',
        phone: '',
        website: '',
        industry: '',
        city: '',
        country: '',
        lead_source: 'Cold Outreach',
        notes: '',
        pipeline_status: 'new',
        tags: '',
      });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to create prospect' });
    } finally {
      loading.stop();
    }
  };

  // Parse Header Columns on File Select
  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportFile(file);
    setImportResult(null);

    // Read first few lines of CSV to suggest column mapping
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target?.result;
      if (typeof text === 'string') {
        const firstLine = text.split(/\r\n|\n/)[0];
        const cols = firstLine.split(',').map((c) => c.replace(/["\r]/g, '').trim()).filter(Boolean);
        setImportColumns(cols);

        // Auto-detect mappings
        const mapping = { email: '', name: '', company: '', phone: '', website: '', industry: '', city: '', country: '', lead_source: '', notes: '' };
        cols.forEach((col) => {
          const lower = col.toLowerCase();
          if (lower.includes('email')) mapping.email = col;
          else if (lower.includes('name') || lower.includes('founder') || lower.includes('contact')) mapping.name = col;
          else if (lower.includes('comp') || lower.includes('business')) mapping.company = col;
          else if (lower.includes('phone') || lower.includes('tel')) mapping.phone = col;
          else if (lower.includes('web') || lower.includes('url') || lower.includes('site')) mapping.website = col;
          else if (lower.includes('indus') || lower.includes('sector')) mapping.industry = col;
          else if (lower.includes('city')) mapping.city = col;
          else if (lower.includes('countr')) mapping.country = col;
          else if (lower.includes('source')) mapping.lead_source = col;
          else if (lower.includes('note')) mapping.notes = col;
        });
        setImportMapping(mapping);
      }
    };
    reader.readAsText(file.slice(0, 4096));
  };

  // Execute Import
  const handleExecuteImport = async (e) => {
    e.preventDefault();
    if (!importFile) return;

    loading.start();
    try {
      const formData = new FormData();
      formData.append('file', importFile);
      formData.append('column_mapping', JSON.stringify(importMapping));
      formData.append('duplicate_action', duplicateAction);
      if (importCampaignId) {
        formData.append('campaign_id', importCampaignId);
      }

      const res = await api.upload('/leads/import', formData);
      setImportResult(res);
      notify({
        type: 'success',
        message: `Imported ${res.imported} new prospects (${res.duplicates_skipped} skipped, ${res.duplicates_updated} updated).`,
      });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Import failed' });
    } finally {
      loading.stop();
    }
  };

  // Bulk Delete
  const handleBulkDelete = async () => {
    if (!selected.size) return;
    const ok = await confirm(`Permanently delete ${selected.size} prospect(s)?`);
    if (!ok) return;
    loading.start();
    try {
      const res = await api.post('/leads/bulk-delete', { lead_ids: [...selected] });
      notify({ type: 'success', message: `Deleted ${res.deleted ?? selected.size} prospects.` });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Delete failed' });
    } finally {
      loading.stop();
    }
  };

  // Bulk Assign to Campaign
  const handleBulkAssignCampaign = async () => {
    if (!selected.size || !bulkCampaignId) {
      notify({ type: 'error', message: 'Select prospects and choose an active campaign.' });
      return;
    }
    loading.start();
    try {
      const res = await api.post('/leads/bulk-assign-campaign', {
        lead_ids: [...selected],
        campaign_id: parseInt(bulkCampaignId, 10),
      });
      notify({ type: 'success', message: `Assigned ${res.assigned} prospects to campaign.` });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Assignment failed' });
    } finally {
      loading.stop();
    }
  };

  // Bulk Pipeline Status
  const handleBulkPipelineStatus = async () => {
    if (!selected.size || !bulkPipelineTarget) return;
    loading.start();
    try {
      const res = await api.post('/leads/bulk-pipeline-status', {
        lead_ids: [...selected],
        pipeline_status: bulkPipelineTarget,
      });
      notify({ type: 'success', message: `Updated pipeline status for ${res.updated} prospects.` });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Status update failed' });
    } finally {
      loading.stop();
    }
  };

  // Export CSV
  const exportCsv = async () => {
    loading.start();
    try {
      const res = await api.download('/leads/export');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `weblinx-prospects-${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      notify({ type: 'success', message: 'Prospect CSV export downloaded.' });
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Export failed' });
    } finally {
      loading.stop();
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
              Prospect Database
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
              {leads.length} contacts
            </span>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Manage your qualified target accounts, import verified lists, and monitor sales pipeline progression.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={exportCsv} variant="secondary" className="flex items-center gap-2">
            <RiDownload2Line size={16} />
            <span>Export CSV</span>
          </Button>

          <Button onClick={() => setImportModalOpen(true)} variant="secondary" className="flex items-center gap-2">
            <RiUploadCloud2Line size={16} />
            <span>Import CSV / Excel</span>
          </Button>

          <Button onClick={() => setCreateModalOpen(true)} variant="primary" className="flex items-center gap-2">
            <RiUserAddLine size={16} />
            <span>Add Prospect</span>
          </Button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="relative w-full sm:w-80">
          <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <input
            type="text"
            placeholder="Search email, name, company, city..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        {/* Pipeline Stage Pills */}
        <div className="flex items-center gap-1.5 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 mr-1 flex items-center gap-1">
            <RiFilter3Line size={14} /> Stage:
          </span>
          {PIPELINE_STATUSES.map((st) => (
            <button
              key={st.value}
              onClick={() => setPipelineFilter(st.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors whitespace-nowrap capitalize ${
                pipelineFilter === st.value
                  ? 'bg-primary-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {st.label}
            </button>
          ))}
        </div>
      </div>

      {/* Bulk Action Bar */}
      {selected.size > 0 && (
        <div className="bg-primary-50 dark:bg-primary-950/40 p-4 rounded-xl border border-primary-200 dark:border-primary-900 flex flex-wrap items-center justify-between gap-4 animate-fade-in shadow-sm">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-primary-900 dark:text-primary-100">
              {selected.size} prospect{selected.size > 1 ? 's' : ''} selected
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Assign Campaign */}
            <div className="flex items-center gap-2">
              <select
                value={bulkCampaignId}
                onChange={(e) => setBulkCampaignId(e.target.value)}
                className="text-xs rounded-lg border border-primary-300 dark:border-primary-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-slate-900 dark:text-white"
              >
                <option value="">Choose Campaign...</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <Button size="sm" variant="primary" onClick={handleBulkAssignCampaign} disabled={!bulkCampaignId}>
                Assign
              </Button>
            </div>

            {/* Set Pipeline Status */}
            <div className="flex items-center gap-2">
              <select
                value={bulkPipelineTarget}
                onChange={(e) => setBulkPipelineTarget(e.target.value)}
                className="text-xs rounded-lg border border-primary-300 dark:border-primary-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-slate-900 dark:text-white capitalize"
              >
                {PIPELINE_STATUSES.filter((p) => p.value !== 'all').map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <Button size="sm" variant="secondary" onClick={handleBulkPipelineStatus}>
                Update Stage
              </Button>
            </div>

            <Button size="sm" variant="destructive" onClick={handleBulkDelete}>
              <RiDeleteBinLine size={14} className="mr-1 inline" /> Delete
            </Button>
          </div>
        </div>
      )}

      {/* Prospects Data Table */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 uppercase font-semibold">
                <th className="py-3 px-3 w-10 text-center">
                  <input
                    type="checkbox"
                    className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                    checked={visibleIds.length > 0 && selected.size === visibleIds.length}
                    onChange={toggleAll}
                  />
                </th>
                <th className="py-3 px-3">Prospect</th>
                <th className="py-3 px-3">Company & Role</th>
                <th className="py-3 px-3">Location</th>
                <th className="py-3 px-3">Pipeline Stage</th>
                <th className="py-3 px-3">Campaign Enrollments</th>
                <th className="py-3 px-3">Tags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {visibleLeads.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    No prospects match the current filter or search query.
                  </td>
                </tr>
              ) : (
                visibleLeads.map((lead) => (
                  <tr key={lead.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-3 text-center">
                      <input
                        type="checkbox"
                        className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                        checked={selected.has(lead.id)}
                        onChange={() => toggleOne(lead.id)}
                      />
                    </td>
                    <td className="py-3 px-3">
                      <Link to={`/leads/${lead.id}`} className="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
                        {lead.name || lead.email}
                      </Link>
                      <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">
                        {lead.email}
                      </div>
                      {lead.phone && (
                        <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                          <RiPhoneLine size={10} /> {lead.phone}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <div className="font-medium text-slate-800 dark:text-slate-200">
                        {lead.company || '—'}
                      </div>
                      <div className="text-[11px] text-slate-400 flex items-center gap-1 mt-0.5">
                        {lead.industry && <span>{lead.industry}</span>}
                        {lead.website && (
                          <a
                            href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary-500 hover:underline ml-1"
                          >
                            <RiGlobalLine size={12} className="inline" />
                          </a>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-slate-600 dark:text-slate-300">
                      {lead.city || lead.country ? (
                        <div className="flex items-center gap-1">
                          <RiMapPinLine size={12} className="text-slate-400" />
                          <span>{[lead.city, lead.country].filter(Boolean).join(', ')}</span>
                        </div>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <span className={`inline-block px-2.5 py-1 text-[11px] rounded-full border ${pipelineBadge(lead.pipeline_status)}`}>
                        {(lead.pipeline_status || 'new').replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {(lead.campaigns || []).length === 0 ? (
                          <span className="text-slate-400 text-[11px]">Not enrolled</span>
                        ) : (
                          (lead.campaigns || []).map((c) => (
                            <Link
                              key={c.campaign_id}
                              to={`/campaigns/${c.campaign_id}`}
                              className="px-2 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 font-medium"
                            >
                              {c.campaign_name || `Camp #${c.campaign_id}`}
                            </Link>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex flex-wrap gap-1">
                        {Array.isArray(lead.tags) && lead.tags.length > 0 ? (
                          lead.tags.map((tg, i) => (
                            <span key={i} className="px-1.5 py-0.5 text-[10px] rounded bg-primary-50 dark:bg-primary-950/40 text-primary-600 dark:text-primary-300 border border-primary-100 dark:border-primary-900">
                              {tg}
                            </span>
                          ))
                        ) : (
                          <span className="text-slate-400 text-[10px]">—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Manual Prospect Creation Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
              <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <RiUserAddLine className="text-primary-500" size={20} /> Add New Prospect
              </h2>
              <button onClick={() => setCreateModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <RiCloseLine size={24} />
              </button>
            </div>

            <form onSubmit={handleCreateLead} className="p-6 space-y-4 overflow-y-auto flex-1">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Email Address *
                  </label>
                  <Input
                    type="email"
                    placeholder="founder@company.com"
                    value={leadFormData.email}
                    onChange={(e) => setLeadFormData({ ...leadFormData, email: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Contact / Founder Name
                  </label>
                  <Input
                    placeholder="Alex Vance"
                    value={leadFormData.name}
                    onChange={(e) => setLeadFormData({ ...leadFormData, name: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Business / Company Name
                  </label>
                  <Input
                    placeholder="Acme Corp"
                    value={leadFormData.company}
                    onChange={(e) => setLeadFormData({ ...leadFormData, company: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Phone Number
                  </label>
                  <Input
                    placeholder="+1 (555) 019-2831"
                    value={leadFormData.phone}
                    onChange={(e) => setLeadFormData({ ...leadFormData, phone: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Website URL
                  </label>
                  <Input
                    placeholder="https://company.com"
                    value={leadFormData.website}
                    onChange={(e) => setLeadFormData({ ...leadFormData, website: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Industry
                  </label>
                  <Input
                    placeholder="SaaS / FinTech"
                    value={leadFormData.industry}
                    onChange={(e) => setLeadFormData({ ...leadFormData, industry: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    City / Country
                  </label>
                  <Input
                    placeholder="San Francisco, USA"
                    value={leadFormData.city}
                    onChange={(e) => setLeadFormData({ ...leadFormData, city: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Pipeline Stage
                  </label>
                  <select
                    value={leadFormData.pipeline_status}
                    onChange={(e) => setLeadFormData({ ...leadFormData, pipeline_status: e.target.value })}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white capitalize"
                  >
                    {PIPELINE_STATUSES.filter((p) => p.value !== 'all').map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Tags (comma separated)
                  </label>
                  <Input
                    placeholder="vip, enterprise, q4-target"
                    value={leadFormData.tags}
                    onChange={(e) => setLeadFormData({ ...leadFormData, tags: e.target.value })}
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Notes
                </label>
                <textarea
                  rows={3}
                  placeholder="Key background context, decision maker details, etc."
                  value={leadFormData.notes}
                  onChange={(e) => setLeadFormData({ ...leadFormData, notes: e.target.value })}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button type="button" variant="ghost" onClick={() => setCreateModalOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary">
                  Save Prospect
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* CSV / Excel Import Modal with Column Mapping */}
      {importModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
              <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <RiUploadCloud2Line className="text-primary-500" size={20} />
                Import Prospects (CSV / Excel)
              </h2>
              <button onClick={() => setImportModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <RiCloseLine size={24} />
              </button>
            </div>

            <form onSubmit={handleExecuteImport} className="p-6 space-y-5 overflow-y-auto flex-1">
              {/* File Dropzone */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Select CSV or Excel (.xlsx) file
                </label>
                <input
                  type="file"
                  accept=".csv, .xlsx, .xls"
                  onChange={handleFileSelect}
                  className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-primary-50 dark:file:bg-primary-950/60 file:text-primary-700 dark:file:text-primary-300 hover:file:bg-primary-100"
                />
              </div>

              {/* Column Mapping Section */}
              {importColumns.length > 0 && (
                <div className="bg-slate-50 dark:bg-slate-800/60 p-4 rounded-xl border border-slate-200 dark:border-slate-700 space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                    Column Mapping
                  </h3>
                  <p className="text-xs text-slate-400">
                    Match fields from your uploaded file to the Weblinx prospect database.
                  </p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div>
                      <span className="font-semibold block mb-1">Email Address *</span>
                      <select
                        value={importMapping.email}
                        onChange={(e) => setImportMapping({ ...importMapping, email: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                        required
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>

                    <div>
                      <span className="font-semibold block mb-1">Full / Contact Name</span>
                      <select
                        value={importMapping.name}
                        onChange={(e) => setImportMapping({ ...importMapping, name: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>

                    <div>
                      <span className="font-semibold block mb-1">Business / Company Name</span>
                      <select
                        value={importMapping.company}
                        onChange={(e) => setImportMapping({ ...importMapping, company: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>

                    <div>
                      <span className="font-semibold block mb-1">Industry</span>
                      <select
                        value={importMapping.industry}
                        onChange={(e) => setImportMapping({ ...importMapping, industry: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>

                    <div>
                      <span className="font-semibold block mb-1">City</span>
                      <select
                        value={importMapping.city}
                        onChange={(e) => setImportMapping({ ...importMapping, city: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>

                    <div>
                      <span className="font-semibold block mb-1">Website URL</span>
                      <select
                        value={importMapping.website}
                        onChange={(e) => setImportMapping({ ...importMapping, website: e.target.value })}
                        className="w-full p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                      >
                        <option value="">-- Choose Column --</option>
                        {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Duplicate Handling and Campaign Assignment */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Duplicate Email Handling
                  </label>
                  <select
                    value={duplicateAction}
                    onChange={(e) => setDuplicateAction(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                  >
                    <option value="skip">Skip duplicates (Recommended)</option>
                    <option value="update">Update existing prospect details</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Enroll in Campaign (Optional)
                  </label>
                  <select
                    value={importCampaignId}
                    onChange={(e) => setImportCampaignId(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                  >
                    <option value="">Do not assign yet (Safe Mode)</option>
                    {campaigns.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {importResult && (
                <div className="p-3 text-xs rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-200 border border-emerald-200">
                  Import summary: {importResult.imported} added, {importResult.duplicates_skipped} duplicates skipped, {importResult.duplicates_updated} updated.
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button type="button" variant="ghost" onClick={() => setImportModalOpen(false)}>
                  Close
                </Button>
                <Button type="submit" variant="primary" disabled={!importFile || !importMapping.email}>
                  Run Import
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

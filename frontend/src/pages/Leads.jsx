import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import { useNotify } from '../context/NotificationContext';
import { useConfirm } from '../context/ConfirmContext';
import { useLoading } from '../context/LoadingContext';
import { cn } from '../utils/cn';
import ComposeModal from '../components/ComposeModal';
import LeadVerificationModal, { getVerificationBadge } from '../components/LeadVerificationModal';
import AssignCampaignModal from '../components/AssignCampaignModal';
import {
  RiShieldCheckLine,
  RiCheckDoubleLine,
  RiProgress3Line,
  RiCheckboxCircleLine,
  RiStopCircleLine,
} from 'react-icons/ri';
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
  RiMailSendLine,
  RiArrowDownSLine,
  RiArrowLeftLine,
  RiArrowRightLine,
  RiFileCopyLine,
  RiExternalLinkLine,
  RiEyeLine,
  RiLayoutColumnLine,
  RiRefreshLine,
  RiAlertLine,
  RiLoader4Line,
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
  const notify = useNotify();
  const confirm = useConfirm();
  const loading = useLoading();

  const DEFAULT_COLUMNS = useMemo(() => ({
    company: true,       // 1. Company Name with Website Link
    contact: true,       // 2. Contact / Founder Name
    email: true,         // 3. Email Address with Copy Action
    phone: true,         // 4. Phone Number with Copy Action
    verification: true,  // 5. Email Verification Status
    pipeline: true,      // 6. Sales / Pipeline Status
    actions: true,       // 7. Actions: View, Send Email, Add to Campaign
    // Optional columns (hidden by default in Show/Hide Columns menu):
    location: false,
    industry: false,
    tags: false,
    campaigns: false,
    lead_source: false,
    created_at: false,
  }), []);

  const [columns, setColumns] = useState(() => {
    try {
      const saved = localStorage.getItem('weblinx_prospect_columns');
      if (saved) {
        return {
          company: true,
          contact: true,
          email: true,
          phone: true,
          verification: true,
          pipeline: true,
          actions: true,
          location: false,
          industry: false,
          tags: false,
          campaigns: false,
          lead_source: false,
          created_at: false,
          ...JSON.parse(saved)
        };
      }
    } catch {}
    return {
      company: true,
      contact: true,
      email: true,
      phone: true,
      verification: true,
      pipeline: true,
      actions: true,
      location: false,
      industry: false,
      tags: false,
      campaigns: false,
      lead_source: false,
      created_at: false,
    };
  });

  const [columnsMenuOpen, setColumnsMenuOpen] = useState(false);
  const columnsMenuRef = useRef(null);

  const toggleColumn = (colKey) => {
    setColumns((prev) => {
      const updated = { ...prev, [colKey]: !prev[colKey] };
      try {
        localStorage.setItem('weblinx_prospect_columns', JSON.stringify(updated));
      } catch {}
      return updated;
    });
  };

  const resetColumnsToDefault = () => {
    const defaults = {
      company: true,
      contact: true,
      email: true,
      phone: true,
      verification: true,
      pipeline: true,
      actions: true,
      location: false,
      industry: false,
      tags: false,
      campaigns: false,
      lead_source: false,
      created_at: false,
    };
    setColumns(defaults);
    try {
      localStorage.setItem('weblinx_prospect_columns', JSON.stringify(defaults));
    } catch {}
  };

  const [leads, setLeads] = useState([]);
  const [campaigns, setCampaigns] = useState([]);

  // Filter states initialized from URL searchParams to preserve state on navigation
  const [search, setSearch] = useState(() => searchParams.get('q') || '');
  const [debouncedSearch, setDebouncedSearch] = useState(() => searchParams.get('q') || '');
  const [industryFilter, setIndustryFilter] = useState(() => searchParams.get('industry') || 'all');
  const [locationFilter, setLocationFilter] = useState(() => searchParams.get('location') || 'all');
  const [verifFilter, setVerifFilter] = useState(() => searchParams.get('verif') || 'all');
  const [campaignFilter, setCampaignFilter] = useState(() => searchParams.get('campaign') || 'all');
  const [pipelineFilter, setPipelineFilter] = useState(() => searchParams.get('stage') || 'all');
  const [selected, setSelected] = useState(() => new Set());
  const [assignTargetLeadIds, setAssignTargetLeadIds] = useState([]);

  // Pagination & responsive table states
  const [pageSize, setPageSize] = useState(50);
  const [currentPage, setCurrentPage] = useState(() => {
    const p = parseInt(searchParams.get('page') || '1', 10);
    return isNaN(p) || p < 1 ? 1 : p;
  });

  // Dynamic filter options from actual database records
  const [filterOptions, setFilterOptions] = useState({
    industries: [],
    industry_counts: {},
    total_leads: null,
    cities: [],
    states: [],
    countries: [],
  });
  const tableContainerRef = useRef(null);

  // Export dropdown state
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const exportMenuRef = useRef(null);

  // Modals state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [showAdvancedCreate, setShowAdvancedCreate] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [leadFormData, setLeadFormData] = useState({
    company: '',
    email: '',
    name: '',
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
  const [assignCampaignModalOpen, setAssignCampaignModalOpen] = useState(false);

  // File Import state
  const [importFile, setImportFile] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [importColumns, setImportColumns] = useState([]);
  const [importMapping, setImportMapping] = useState({
    email: '',
    name: '',
    first_name: '',
    last_name: '',
    company: '',
    phone: '',
    website: '',
    industry: '',
    city: '',
    state: '',
    country: '',
    lead_source: '',
    tags: '',
    notes: '',
  });
  const [duplicateAction, setDuplicateAction] = useState('skip');
  const [fillMissingDetails, setFillMissingDetails] = useState(false);
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const [selectedDetailTab, setSelectedDetailTab] = useState('skipped');
  const [importCampaignId, setImportCampaignId] = useState('');
  const [importExecuting, setImportExecuting] = useState(false);
  const [importError, setImportError] = useState(null);
  const [importResult, setImportResult] = useState(null);

  // Direct compose state
  const [composeModalOpen, setComposeModalOpen] = useState(false);
  const [composeTargetLead, setComposeTargetLead] = useState(null);

  // Email Verification States
  const [verifModalLead, setVerifModalLead] = useState(null);
  const [autoVerifyImport, setAutoVerifyImport] = useState(true);
  const [verifyingSelected, setVerifyingSelected] = useState(false);
  const [verifJob, setVerifJob] = useState(null);
  const [verifRunning, setVerifRunning] = useState(false);

  // Search debounce
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Click outside to close export dropdown menu
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target)) {
        setExportMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Fetch campaigns for assignment
  useEffect(() => {
    api.get('/campaigns').then((res) => setCampaigns(res || [])).catch(() => {});
  }, []);

  // Fetch dynamic filter options from backend
  useEffect(() => {
    api.get('/leads/filter-options')
      .then((res) => {
        if (res) {
          setFilterOptions({
            industries: res.industries || [],
            industry_counts: res.industry_counts || {},
            total_leads: typeof res.total_leads === 'number' ? res.total_leads : null,
            cities: res.cities || [],
            states: res.states || [],
            countries: res.countries || [],
          });
        }
      })
      .catch(() => {});
  }, []);

  // Merge loaded leads with filter options and industry counts
  const dynamicIndustries = useMemo(() => {
    const counts = { ...(filterOptions.industry_counts || {}) };
    const set = new Set(filterOptions.industries || []);

    leads.forEach((l) => {
      if (l.industry && l.industry.trim()) {
        const ind = l.industry.trim();
        set.add(ind);
        if (counts[ind] === undefined) {
          counts[ind] = 1;
        }
      }
    });

    return Array.from(set).sort((a, b) => a.localeCompare(b)).map((name) => ({
      name,
      count: counts[name] ?? 0,
    }));
  }, [filterOptions.industries, filterOptions.industry_counts, leads]);

  const totalIndustryCount = useMemo(() => {
    if (typeof filterOptions.total_leads === 'number') {
      return filterOptions.total_leads;
    }
    return leads.length;
  }, [filterOptions.total_leads, leads.length]);

  const dynamicLocations = useMemo(() => {
    const cities = new Set(filterOptions.cities);
    const states = new Set(filterOptions.states);
    const countries = new Set(filterOptions.countries);
    leads.forEach((l) => {
      if (l.city && l.city.trim()) cities.add(l.city.trim());
      if (l.country && l.country.trim()) countries.add(l.country.trim());
      if (l.custom_data?.state && typeof l.custom_data.state === 'string' && l.custom_data.state.trim()) {
        states.add(l.custom_data.state.trim());
      }
    });
    return {
      cities: Array.from(cities).sort((a, b) => a.localeCompare(b)),
      states: Array.from(states).sort((a, b) => a.localeCompare(b)),
      countries: Array.from(countries).sort((a, b) => a.localeCompare(b)),
    };
  }, [filterOptions, leads]);

  // Synchronize filter states to URL search parameters to preserve filters across navigation
  useEffect(() => {
    const params = new URLSearchParams();
    if (debouncedSearch) params.set('q', debouncedSearch);
    if (industryFilter !== 'all') params.set('industry', industryFilter);
    if (locationFilter !== 'all') params.set('location', locationFilter);
    if (verifFilter !== 'all') params.set('verif', verifFilter);
    if (campaignFilter !== 'all') params.set('campaign', campaignFilter);
    if (pipelineFilter !== 'all') params.set('stage', pipelineFilter);
    if (currentPage > 1) params.set('page', String(currentPage));
    setSearchParams(params, { replace: true });
  }, [debouncedSearch, industryFilter, locationFilter, verifFilter, campaignFilter, pipelineFilter, currentPage, setSearchParams]);

  // Primary lead loading routine
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

  const handleOpenCompose = (lead) => {
    setComposeTargetLead(lead);
    setComposeModalOpen(true);
  };

  const loadVerificationJobStatus = useCallback(async () => {
    try {
      const res = await api.get('/leads/verify-status');
      if (res && res.job) {
        setVerifJob(res.job);
        setVerifRunning(!!res.job.is_running);
      }
    } catch {}
  }, []);

  useEffect(() => {
    loadVerificationJobStatus();
  }, [loadVerificationJobStatus]);

  useEffect(() => {
    let interval = null;
    if (verifRunning) {
      interval = setInterval(async () => {
        try {
          const res = await api.get('/leads/verify-status');
          if (res && res.job) {
            setVerifJob(res.job);
            if (!res.job.is_running) {
              setVerifRunning(false);
              loadLeads();
            }
          }
        } catch {}
      }, 2000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [verifRunning, loadLeads]);

  const handleVerifySelected = async () => {
    if (!selected.size) return;
    setVerifyingSelected(true);
    try {
      const res = await api.post('/leads/verify-selected', {
        lead_ids: Array.from(selected),
        check_smtp: false,
      });
      notify({
        type: 'success',
        message: `Verified ${res.total} prospects (Valid: ${res.counts?.valid || 0}, Domain Validated: ${res.counts?.domain_validated || 0}, Invalid: ${res.counts?.invalid || 0}).`,
      });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Verification failed' });
    } finally {
      setVerifyingSelected(false);
    }
  };

  const handleApproveSelected = async () => {
    if (!selected.size) return;
    loading.start();
    try {
      const res = await api.post('/leads/approve-selected', {
        lead_ids: Array.from(selected),
        note: 'Approved for sending via prospects bulk action',
      });
      notify({ type: 'success', message: `Approved ${res.approved_count} prospects for sending.` });
      await loadLeads();
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Approval failed' });
    } finally {
      loading.stop();
    }
  };

  const handleVerifyAll = async () => {
    try {
      const res = await api.post('/leads/verify-all', { reverify: false, check_smtp: false });
      if (res.ok) {
        notify({ type: 'success', message: res.message || 'Verification started' });
        setVerifRunning(true);
        loadVerificationJobStatus();
      } else {
        notify({ type: 'info', message: res.message || 'Job already running' });
      }
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to start verification' });
    }
  };

  const handleCancelVerifyJob = async () => {
    try {
      await api.post('/leads/verify-cancel');
      notify({ type: 'info', message: 'Cancellation requested' });
      setTimeout(loadVerificationJobStatus, 500);
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to cancel' });
    }
  };

  const visibleLeads = useMemo(() => {
    return leads.filter((l) => {
      // 1. Search filter: company, contact name, email, phone
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase();
        const comp = (l.company || '').toLowerCase();
        const nm = (l.name || '').toLowerCase();
        const em = (l.email || '').toLowerCase();
        const ph = (l.phone || '').toLowerCase();
        if (!comp.includes(q) && !nm.includes(q) && !em.includes(q) && !ph.includes(q)) {
          return false;
        }
      }

      // 2. Industry filter
      if (industryFilter !== 'all') {
        const ind = (l.industry || '').toLowerCase();
        if (ind !== industryFilter.toLowerCase()) {
          return false;
        }
      }

      // 3. Location filter (country, state, city)
      if (locationFilter !== 'all') {
        const cty = (l.city || '').toLowerCase();
        const ctry = (l.country || '').toLowerCase();
        const st = (l.custom_data?.state || '').toLowerCase();

        if (locationFilter.startsWith('city:')) {
          const val = locationFilter.slice(5).toLowerCase();
          if (cty !== val && !cty.includes(val)) return false;
        } else if (locationFilter.startsWith('state:')) {
          const val = locationFilter.slice(6).toLowerCase();
          if (st !== val && !cty.includes(val)) return false;
        } else if (locationFilter.startsWith('country:')) {
          const val = locationFilter.slice(8).toLowerCase();
          if (ctry !== val && !ctry.includes(val)) return false;
        } else {
          const val = locationFilter.toLowerCase();
          if (!cty.includes(val) && !ctry.includes(val) && !st.includes(val)) return false;
        }
      }

      // 4. Verification status filter
      if (verifFilter !== 'all') {
        const st = (l.email_verification_status || 'unverified').toLowerCase();
        if (verifFilter === 'unverified') {
          if (l.email_verification_status && l.email_verification_status !== 'not_verified' && l.email_verification_status !== 'unverified') {
            return false;
          }
        } else if (verifFilter === 'review_needed') {
          if (!['unknown', 'catch_all', 'risky', 'not_verified', 'unverified'].includes(st)) {
            return false;
          }
        } else if (st !== verifFilter.toLowerCase()) {
          return false;
        }
      }

      // 5. Campaign filter
      if (campaignFilter !== 'all') {
        const cid = Number(campaignFilter);
        const inCamp = (l.campaigns || []).some((c) => c.campaign_id === cid) ||
          (l.campaign_leads || []).some((cl) => cl.campaign_id === cid);
        if (!inCamp) return false;
      }

      // 6. Pipeline stage filter
      if (pipelineFilter !== 'all') {
        const stage = (l.pipeline_status || 'new').toLowerCase();
        if (stage !== pipelineFilter.toLowerCase()) {
          return false;
        }
      }

      return true;
    });
  }, [leads, debouncedSearch, industryFilter, locationFilter, verifFilter, campaignFilter, pipelineFilter]);

  // Check if any filter is active
  const hasActiveFilters = Boolean(
    search ||
    industryFilter !== 'all' ||
    locationFilter !== 'all' ||
    verifFilter !== 'all' ||
    campaignFilter !== 'all' ||
    pipelineFilter !== 'all'
  );

  const handleClearFilters = () => {
    setSearch('');
    setDebouncedSearch('');
    setIndustryFilter('all');
    setLocationFilter('all');
    setVerifFilter('all');
    setCampaignFilter('all');
    setPipelineFilter('all');
    setCurrentPage(1);
  };

  // Reset page when filters change (preserves page during in-page navigation)
  const prevFiltersRef = useRef({ debouncedSearch, industryFilter, locationFilter, verifFilter, campaignFilter, pipelineFilter });
  useEffect(() => {
    const prev = prevFiltersRef.current;
    if (
      prev.debouncedSearch !== debouncedSearch ||
      prev.industryFilter !== industryFilter ||
      prev.locationFilter !== locationFilter ||
      prev.verifFilter !== verifFilter ||
      prev.campaignFilter !== campaignFilter ||
      prev.pipelineFilter !== pipelineFilter
    ) {
      setCurrentPage(1);
      prevFiltersRef.current = { debouncedSearch, industryFilter, locationFilter, verifFilter, campaignFilter, pipelineFilter };
    }
  }, [debouncedSearch, industryFilter, locationFilter, verifFilter, campaignFilter, pipelineFilter]);

  const totalItems = visibleLeads.length;
  const totalPages = pageSize === 'all' ? 1 : Math.max(1, Math.ceil(totalItems / Number(pageSize)));

  const paginatedLeads = useMemo(() => {
    if (pageSize === 'all') return visibleLeads;
    const start = (currentPage - 1) * Number(pageSize);
    return visibleLeads.slice(start, start + Number(pageSize));
  }, [visibleLeads, currentPage, pageSize]);

  const currentPageIds = useMemo(() => paginatedLeads.map((l) => l.id), [paginatedLeads]);
  const allVisibleIds = useMemo(() => visibleLeads.map((l) => l.id), [visibleLeads]);

  const isAllCurrentPageSelected = currentPageIds.length > 0 && currentPageIds.every((id) => selected.has(id));
  const isAllFilteredSelected = allVisibleIds.length > 0 && selected.size === allVisibleIds.length;

  const toggleOne = (id) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const toggleAllCurrentPage = () => {
    if (isAllCurrentPageSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        currentPageIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        currentPageIds.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  const selectAllFiltered = () => {
    setSelected(new Set(allVisibleIds));
  };

  const scrollTable = (direction) => {
    if (!tableContainerRef.current) return;
    const scrollAmount = direction === 'left' ? -350 : 350;
    tableContainerRef.current.scrollBy({ left: scrollAmount, behavior: 'smooth' });
  };

  // Add Single Prospect
  const handleCreateLead = async (e) => {
    e.preventDefault();
    if (!leadFormData.company?.trim()) {
      notify({ type: 'error', message: 'Company Name is required.' });
      return;
    }
    if (!leadFormData.email?.trim() || !leadFormData.email.includes('@')) {
      notify({ type: 'error', message: 'Valid email address is required.' });
      return;
    }

    loading.start();
    try {
      const payload = {
        company: leadFormData.company.trim(),
        email: leadFormData.email.trim(),
        name: leadFormData.name?.trim() || '',
        phone: leadFormData.phone?.trim() || '',
        website: leadFormData.website?.trim() || '',
        industry: leadFormData.industry?.trim() || '',
        city: leadFormData.city?.trim() || '',
        country: leadFormData.country?.trim() || '',
        lead_source: leadFormData.lead_source?.trim() || 'Cold Outreach',
        notes: leadFormData.notes?.trim() || '',
        pipeline_status: leadFormData.pipeline_status || 'new',
        tags: leadFormData.tags ? leadFormData.tags.split(',').map((t) => t.trim()).filter(Boolean) : [],
      };
      await api.post('/leads', payload);
      notify({ type: 'success', message: 'Prospect added successfully!' });
      setCreateModalOpen(false);
      setShowAdvancedCreate(false);
      setLeadFormData({
        company: '',
        email: '',
        name: '',
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

  // Handle File Selection with instant backend analysis & preview
  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportFile(file);
    setImportResult(null);
    setImportError(null);
    setPreviewError(null);
    setPreviewLoading(true);
    setPreviewData(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await api.upload('/leads/import-preview', formData);
      setPreviewData(res);
      setImportColumns(res.headers || []);
      setImportMapping(res.detected_mapping || {});
    } catch (err) {
      setPreviewError(err.message || 'Failed to inspect file. Please ensure it is a valid CSV or Excel spreadsheet.');
      setImportColumns([]);
      setImportMapping({});
    } finally {
      setPreviewLoading(false);
    }
  };

  // Execute Import
  const handleExecuteImport = async (e) => {
    e.preventDefault();
    if (!importFile || !importMapping.email || importExecuting) return;

    setImportExecuting(true);
    setImportError(null);
    loading.start();
    try {
      const formData = new FormData();
      formData.append('file', importFile);
      formData.append('column_mapping', JSON.stringify(importMapping));
      formData.append('duplicate_action', fillMissingDetails ? 'update' : 'skip');
      formData.append('fill_missing', fillMissingDetails ? 'true' : 'false');
      if (importCampaignId) {
        formData.append('campaign_id', importCampaignId);
      }

      const res = await api.upload(`/leads/import?auto_verify=${autoVerifyImport}`, formData);
      if (res.auto_verify_queued) {
        setVerifRunning(true);
        loadVerificationJobStatus();
      }
      setImportResult(res);
      notify({
        type: 'success',
        message: `Import complete: ${res.added ?? res.imported ?? 0} added, ${res.skipped_duplicates ?? res.duplicates_skipped ?? 0} skipped, ${res.updated ?? res.duplicates_updated ?? 0} updated.`,
      });
      await loadLeads();
    } catch (e) {
      setImportError(e.message || 'Import failed. Please check your column mappings and file contents.');
      notify({ type: 'error', message: e.message || 'Import failed' });
    } finally {
      setImportExecuting(false);
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
  const handleBulkAssignCampaign = () => {
    if (!selected.size) {
      notify({ type: 'error', message: 'Select at least one prospect to assign.' });
      return;
    }
    setAssignCampaignModalOpen(true);
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
  const handleExport = async (scope = 'all') => {
    setExportMenuOpen(false);
    loading.start();
    try {
      const today = new Date().toISOString().split('T')[0];
      let res;
      let countDesc = leads.length;

      if (scope === 'selected' && selected.size > 0) {
        countDesc = selected.size;
        res = await api.downloadPost('/leads/export', {
          scope: 'selected',
          lead_ids: Array.from(selected),
        });
      } else if (scope === 'filtered') {
        countDesc = totalItems;
        res = await api.downloadPost('/leads/export', {
          scope: 'filtered',
          q: debouncedSearch || null,
          pipeline_status: pipelineFilter !== 'all' ? pipelineFilter : null,
          email_verification_status: verifFilter !== 'all' ? verifFilter : null,
        });
      } else {
        countDesc = leads.length;
        res = await api.downloadPost('/leads/export', {
          scope: 'all',
        });
      }

      if (!res.ok) {
        throw new Error(`Export failed (HTTP ${res.status})`);
      }

      const exportedHeaderCount = res.headers?.get('x-exported-count');
      const actualCount = exportedHeaderCount != null ? Number(exportedHeaderCount) : countDesc;

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `weblinx-prospects-${scope}-${actualCount}-${today}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      notify({
        type: 'success',
        message: `Exported ${actualCount} prospect${actualCount === 1 ? '' : 's'} to CSV.`,
      });
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Export failed' });
    } finally {
      loading.stop();
    }
  };

  return (
    <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-5">
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

        <div className="flex flex-wrap sm:flex-nowrap items-center gap-2 shrink-0">
          {/* Export Dropdown with All / Filtered / Selected Options */}
          <div className="relative" ref={exportMenuRef}>
            <Button
              onClick={() => setExportMenuOpen((prev) => !prev)}
              variant="secondary"
              className="flex items-center gap-1.5"
              title="Export prospects to Excel/Google Sheets compatible CSV"
            >
              <RiDownload2Line size={16} />
              <span>Export CSV</span>
              <RiArrowDownSLine size={14} className={`transition-transform duration-150 ${exportMenuOpen ? 'rotate-180' : ''}`} />
            </Button>

            {exportMenuOpen && (
              <div className="absolute left-0 sm:left-auto sm:right-0 mt-1 w-64 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-xl z-50 py-1.5 text-xs animate-fade-in">
                {/* Option 1: All Prospects */}
                <button
                  type="button"
                  onClick={() => handleExport('all')}
                  className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200 cursor-pointer transition-colors"
                >
                  <div>
                    <div className="font-semibold">Export All Prospects</div>
                    <div className="text-[11px] text-slate-400">Entire database ({leads.length} total)</div>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-mono font-medium">
                    {leads.length}
                  </span>
                </button>

                {/* Option 2: Filtered Prospects */}
                {(hasActiveFilters) && (
                  <button
                    type="button"
                    onClick={() => handleExport('filtered')}
                    className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200 border-t border-slate-100 dark:border-slate-800 cursor-pointer transition-colors"
                  >
                    <div>
                      <div className="font-semibold text-teal-600 dark:text-teal-400">Export Filtered Prospects</div>
                      <div className="text-[11px] text-slate-400">Matching current filters ({totalItems} records)</div>
                    </div>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-teal-50 dark:bg-teal-950 text-teal-700 dark:text-teal-300 font-mono font-bold">
                      {totalItems}
                    </span>
                  </button>
                )}

                {/* Option 3: Selected Prospects */}
                {selected.size > 0 && (
                  <button
                    type="button"
                    onClick={() => handleExport('selected')}
                    className="w-full text-left px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between text-slate-800 dark:text-slate-200 border-t border-slate-100 dark:border-slate-800 cursor-pointer transition-colors"
                  >
                    <div>
                      <div className="font-semibold text-emerald-600 dark:text-emerald-400">Export Selected Prospects</div>
                      <div className="text-[11px] text-slate-400">Checked rows ({selected.size} records)</div>
                    </div>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-mono font-bold">
                      {selected.size}
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>

          <Button
            onClick={handleVerifyAll}
            variant="secondary"
            className="flex items-center gap-2"
            disabled={verifRunning}
            title="Run self-hosted deliverability verification across all unverified prospects"
          >
            <RiShieldCheckLine size={16} className={verifRunning ? 'animate-spin text-teal-500' : 'text-teal-600'} />
            <span>{verifRunning ? 'Verifying...' : 'Verify All'}</span>
          </Button>

          <Button onClick={() => setImportModalOpen(true)} variant="secondary" className="flex items-center gap-2">
            <RiUploadCloud2Line size={16} />
            <span>Import CSV / Excel</span>
          </Button>

          <Button onClick={() => { setShowAdvancedCreate(false); setCreateModalOpen(true); }} variant="primary" className="flex items-center gap-2">
            <RiUserAddLine size={16} />
            <span>Add Prospect</span>
          </Button>
        </div>
      </div>

      {/* Verification Job Progress Banner */}
      {verifJob && (verifJob.is_running || (verifJob.processed > 0 && verifJob.total > 0)) && (
        <div className="p-4 rounded-xl border border-teal-200 dark:border-teal-900 bg-teal-50/50 dark:bg-teal-950/30 flex flex-wrap items-center justify-between gap-4 animate-fade-in shadow-xs">
          <div className="space-y-1.5 flex-1 min-w-[280px]">
            <div className="flex items-center gap-2">
              {verifJob.is_running ? (
                <>
                  <RiProgress3Line size={18} className="animate-spin text-teal-600 shrink-0" />
                  <span className="font-semibold text-xs text-teal-900 dark:text-teal-200">
                    Bulk Verification in Progress: {verifJob.processed} / {verifJob.total} ({Math.round((verifJob.processed / (verifJob.total || 1)) * 100)}%)
                  </span>
                </>
              ) : (
                <>
                  <RiCheckboxCircleLine size={18} className="text-teal-600 shrink-0" />
                  <span className="font-semibold text-xs text-teal-900 dark:text-teal-200">
                    Verification Complete: {verifJob.processed} prospects evaluated
                  </span>
                </>
              )}
              {verifJob.current_email && (
                <span className="text-[11px] font-mono text-teal-700 dark:text-teal-300 truncate max-w-xs">
                  ({verifJob.current_email})
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2 text-[11px]">
              <span className="text-emerald-700 dark:text-emerald-400 font-medium">Valid: {verifJob.valid || 0}</span>
              <span className="text-sky-700 dark:text-sky-400 font-medium">Domain Validated: {verifJob.domain_validated || 0}</span>
              <span className="text-amber-700 dark:text-amber-400 font-medium">Risky: {verifJob.risky || 0}</span>
              <span className="text-purple-700 dark:text-purple-400 font-medium">Catch-All: {verifJob.catch_all || 0}</span>
              <span className="text-rose-700 dark:text-rose-400 font-medium">Invalid (Blocked): {verifJob.invalid || 0}</span>
              <span className="text-slate-600 dark:text-slate-400 font-medium">Unknown: {verifJob.unknown || 0}</span>
            </div>
          </div>
          {verifJob.is_running && (
            <Button size="sm" variant="destructive" onClick={handleCancelVerifyJob} className="text-xs">
              Stop Job
            </Button>
          )}
        </div>
      )}

      {/* Compact Search & Filter Toolbar - Single Horizontal Row on Desktop */}
      <div className="bg-white dark:bg-slate-900 p-2.5 sm:p-3 rounded-xl border border-slate-200 dark:border-slate-800 shadow-xs flex flex-wrap items-center gap-2 sm:gap-2.5">
        {/* 1. Prominent Search Bar */}
        <div className="relative flex-1 min-w-[220px]">
          <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" size={15} />
          <input
            type="text"
            placeholder="Search company, contact, email, phone..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-8 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors"
          />
          {search && (
            <button
              type="button"
              onClick={() => { setSearch(''); setDebouncedSearch(''); }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-0.5 rounded cursor-pointer"
              title="Clear search"
            >
              <RiCloseLine size={14} />
            </button>
          )}
        </div>

        {/* 2. Industry Filter */}
        <select
          value={industryFilter}
          onChange={(e) => setIndustryFilter(e.target.value)}
          className="w-[145px] sm:w-[165px] text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer truncate shrink-0"
          title="Filter by industry"
        >
          <option value="all">All Industries ({totalIndustryCount})</option>
          {dynamicIndustries.map(({ name, count }) => (
            <option key={name} value={name}>{name} ({count})</option>
          ))}
        </select>

        {/* 3. Location Filter (Country, State, City) */}
        <select
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
          className="w-[125px] sm:w-[135px] text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer truncate shrink-0"
          title="Filter by location (country, state, city)"
        >
          <option value="all">All Locations</option>
          {dynamicLocations.cities.length > 0 && (
            <optgroup label="Cities">
              {dynamicLocations.cities.map((ct) => (
                <option key={'city:' + ct} value={'city:' + ct}>{ct}</option>
              ))}
            </optgroup>
          )}
          {dynamicLocations.states.length > 0 && (
            <optgroup label="States">
              {dynamicLocations.states.map((st) => (
                <option key={'state:' + st} value={'state:' + st}>{st}</option>
              ))}
            </optgroup>
          )}
          {dynamicLocations.countries.length > 0 && (
            <optgroup label="Countries">
              {dynamicLocations.countries.map((cntry) => (
                <option key={'country:' + cntry} value={'country:' + cntry}>{cntry}</option>
              ))}
            </optgroup>
          )}
        </select>

        {/* 4. Verification Status Filter */}
        <select
          value={verifFilter}
          onChange={(e) => setVerifFilter(e.target.value)}
          className="w-[130px] sm:w-[140px] text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer truncate shrink-0"
          title="Filter by deliverability verification status"
        >
          <option value="all">All Verification</option>
          <option value="valid">Valid (Mailbox Confirmed)</option>
          <option value="domain_validated">Domain Validated</option>
          <option value="review_needed">Review Needed</option>
          <option value="risky">Risky</option>
          <option value="catch_all">Catch-All</option>
          <option value="unknown">Unknown</option>
          <option value="invalid">Invalid (Blocked)</option>
          <option value="unverified">Unverified</option>
        </select>

        {/* 5. Campaign Filter */}
        <select
          value={campaignFilter}
          onChange={(e) => setCampaignFilter(e.target.value)}
          className="w-[125px] sm:w-[135px] text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer truncate shrink-0"
          title="Filter by enrolled campaign"
        >
          <option value="all">All Campaigns</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        {/* 6. Pipeline Stage Filter */}
        <select
          value={pipelineFilter}
          onChange={(e) => setPipelineFilter(e.target.value)}
          className="w-[120px] sm:w-[130px] text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer truncate capitalize shrink-0"
          title="Filter by sales pipeline stage"
        >
          {PIPELINE_STATUSES.map((st) => (
            <option key={st.value} value={st.value}>{st.label}</option>
          ))}
        </select>

        {/* 7. Clear Filters Action Button */}
        {hasActiveFilters && (
          <button
            type="button"
            onClick={handleClearFilters}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 rounded-lg border border-rose-200 dark:border-rose-900/60 transition-colors whitespace-nowrap cursor-pointer shrink-0"
            title="Reset search and all active filters"
          >
            <RiCloseLine size={14} />
            <span>Clear Filters</span>
          </button>
        )}
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
              <Button size="sm" variant="primary" onClick={handleBulkAssignCampaign} className="flex items-center gap-1.5">
                <RiFolderUserLine size={14} />
                Assign to Campaign
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

            <Button
              size="sm"
              variant="secondary"
              onClick={handleVerifySelected}
              disabled={verifyingSelected}
              className="text-xs"
            >
              <RiShieldCheckLine size={14} className={`mr-1 inline ${verifyingSelected ? 'animate-spin' : ''}`} />
              {verifyingSelected ? 'Verifying...' : 'Verify Selected'}
            </Button>

            <Button
              size="sm"
              variant="secondary"
              onClick={handleApproveSelected}
              className="text-xs"
            >
              <RiCheckDoubleLine size={14} className="mr-1 inline" />
              Approve for Sending
            </Button>

            <Button
              size="sm"
              variant="secondary"
              onClick={() => handleExport('selected')}
              className="text-xs"
              title="Export only selected prospects to CSV"
            >
              <RiDownload2Line size={14} className="mr-1 inline" />
              Export Selected ({selected.size})
            </Button>

            <Button size="sm" variant="destructive" onClick={handleBulkDelete}>
              <RiDeleteBinLine size={14} className="mr-1 inline" /> Delete
            </Button>
          </div>
        </div>
      )}

      {/* Selection Matching Banner (when current page is selected but more matching records exist) */}
      {isAllCurrentPageSelected && totalItems > currentPageIds.length && !isAllFilteredSelected && (
        <div className="bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 px-4 py-2.5 rounded-xl text-xs flex items-center justify-between gap-3 text-teal-900 dark:text-teal-200 animate-fade-in shadow-2xs">
          <div>
            All <span className="font-bold">{currentPageIds.length}</span> prospects on this page are selected.
          </div>
          <button
            type="button"
            onClick={selectAllFiltered}
            className="font-bold underline hover:text-teal-700 dark:hover:text-teal-100 transition-colors cursor-pointer"
          >
            Select all {totalItems} matching prospects in database
          </button>
        </div>
      )}

      {/* Prospects Data Table Card */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col min-h-0 overflow-hidden">
        {/* Table Controls & Display Settings Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-700 dark:text-slate-300">Prospect Records</span>
            <span className="text-slate-400">·</span>
            <span className="text-slate-500">{totalItems} total</span>
            {selected.size > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-teal-100 dark:bg-teal-950/60 text-teal-800 dark:text-teal-300 font-semibold text-[11px]">
                {selected.size} selected
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Table Setting: Customizable Show/Hide Columns Menu */}
            <div className="relative" ref={columnsMenuRef}>
              <button
                type="button"
                onClick={() => setColumnsMenuOpen(!columnsMenuOpen)}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition-colors cursor-pointer"
                title="Customize table column visibility"
              >
                <RiLayoutColumnLine size={13} className="text-teal-600 dark:text-teal-400" />
                <span>Columns ({Object.values(columns).filter(Boolean).length}/13)</span>
                <RiArrowDownSLine size={12} className={`transition-transform duration-200 ${columnsMenuOpen ? 'rotate-180' : ''}`} />
              </button>

              {columnsMenuOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-64 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-slate-200 dark:border-slate-800 z-40 p-2 animate-fade-in text-xs">
                  <div className="px-2 py-1.5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wider text-[10px]">
                    <span>Visible Columns</span>
                    <button
                      type="button"
                      onClick={resetColumnsToDefault}
                      className="text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1 font-semibold capitalize"
                    >
                      <RiRefreshLine size={10} /> Reset Default
                    </button>
                  </div>

                  <div className="py-1 space-y-0.5 max-h-60 overflow-y-auto">
                    <div className="text-[10px] font-bold text-slate-400 px-2 pt-1 uppercase">Core Columns (Default 7)</div>
                    {[
                      { key: 'company', label: '1. Company Name & Website' },
                      { key: 'contact', label: '2. Contact / Founder Name' },
                      { key: 'email', label: '3. Email Address (Copy)' },
                      { key: 'phone', label: '4. Phone Number (Copy)' },
                      { key: 'verification', label: '5. Email Verification Status' },
                      { key: 'pipeline', label: '6. Pipeline Stage' },
                      { key: 'actions', label: '7. Actions (View/Email/Add)' },
                    ].map(({ key, label }) => (
                      <label key={key} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer text-slate-700 dark:text-slate-300">
                        <input
                          type="checkbox"
                          checked={!!columns[key]}
                          onChange={() => toggleColumn(key)}
                          className="rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                        />
                        <span>{label}</span>
                      </label>
                    ))}

                    <div className="text-[10px] font-bold text-slate-400 px-2 pt-2 border-t border-slate-100 dark:border-slate-800 uppercase">Optional Columns</div>
                    {[
                      { key: 'location', label: 'Location (City, Country)' },
                      { key: 'industry', label: 'Industry / Vertical' },
                      { key: 'tags', label: 'Tags' },
                      { key: 'campaigns', label: 'Campaign Enrollments' },
                      { key: 'lead_source', label: 'Lead Source' },
                      { key: 'created_at', label: 'Date Added' },
                    ].map(({ key, label }) => (
                      <label key={key} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer text-slate-700 dark:text-slate-300">
                        <input
                          type="checkbox"
                          checked={!!columns[key]}
                          onChange={() => toggleColumn(key)}
                          className="rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Horizontal Scroll Controls */}
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-slate-400 hidden sm:inline mr-1">Scroll:</span>
              <button
                type="button"
                onClick={() => scrollTable('left')}
                title="Scroll table left"
                className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors cursor-pointer"
              >
                <RiArrowLeftLine size={14} />
              </button>
              <button
                type="button"
                onClick={() => scrollTable('right')}
                title="Scroll table right"
                className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors cursor-pointer"
              >
                <RiArrowRightLine size={14} />
              </button>
            </div>
          </div>
        </div>

        {/* Scrollable responsive table wrapper */}
        <div
          ref={tableContainerRef}
          tabIndex={0}
          role="region"
          aria-label="Prospects Database Table"
          className="relative flex-1 min-h-[350px] max-h-[calc(100dvh-280px)] sm:max-h-[calc(100dvh-260px)] overflow-x-auto overflow-y-auto overscroll-contain table-scrollbar focus:outline-none"
        >
          <table className="w-full min-w-[950px] text-left border-collapse text-xs">
            <thead className="sticky top-0 z-20 bg-slate-50 dark:bg-slate-800/95 backdrop-blur-xs border-b border-slate-200 dark:border-slate-700 shadow-2xs">
              <tr className="text-slate-600 dark:text-slate-300 uppercase font-semibold text-[11px] tracking-wider">
                {/* Select All Checkbox (Sticky Left) */}
                <th className="py-2.5 px-3 w-10 min-w-[40px] max-w-[40px] text-center sticky top-0 left-0 z-30 bg-slate-50 dark:bg-slate-800 border-b border-r border-slate-200 dark:border-slate-700 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                  <input
                    type="checkbox"
                    className="rounded border-slate-300 text-teal-600 focus:ring-teal-500 cursor-pointer"
                    checked={isAllCurrentPageSelected}
                    onChange={toggleAllCurrentPage}
                    title="Select all on this page"
                  />
                </th>

                {/* 1. Company Name & Website Link */}
                {columns.company && (
                  <th className="py-2.5 px-3 min-w-[170px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Company Name
                  </th>
                )}

                {/* 2. Contact / Founder Name */}
                {columns.contact && (
                  <th className="py-2.5 px-3 min-w-[130px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Contact / Founder
                  </th>
                )}

                {/* 3. Email Address with Copy Action */}
                {columns.email && (
                  <th className="py-2.5 px-3 min-w-[200px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Email Address
                  </th>
                )}

                {/* 4. Phone Number with Copy Action */}
                {columns.phone && (
                  <th className="py-2.5 px-3 min-w-[130px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Phone Number
                  </th>
                )}

                {/* 5. Email Verification Status */}
                {columns.verification && (
                  <th className="py-2.5 px-3 min-w-[160px] whitespace-nowrap sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Verification Status
                  </th>
                )}

                {/* 6. Sales / Pipeline Status */}
                {columns.pipeline && (
                  <th className="py-2.5 px-3 min-w-[140px] whitespace-nowrap sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Pipeline Stage
                  </th>
                )}

                {/* Optional Columns */}
                {columns.location && (
                  <th className="py-2.5 px-3 min-w-[140px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Location
                  </th>
                )}
                {columns.industry && (
                  <th className="py-2.5 px-3 min-w-[140px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Industry
                  </th>
                )}
                {columns.tags && (
                  <th className="py-2.5 px-3 min-w-[130px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Tags
                  </th>
                )}
                {columns.campaigns && (
                  <th className="py-2.5 px-3 min-w-[150px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Campaigns
                  </th>
                )}
                {columns.lead_source && (
                  <th className="py-2.5 px-3 min-w-[120px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Source
                  </th>
                )}
                {columns.created_at && (
                  <th className="py-2.5 px-3 min-w-[100px] sticky top-0 z-20 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                    Date Added
                  </th>
                )}

                {/* 7. Actions: View, Send Email, Add to Campaign (Sticky Right) */}
                {columns.actions && (
                  <th className="py-2.5 px-3 min-w-[110px] text-right sticky top-0 right-0 z-30 bg-slate-50 dark:bg-slate-800 border-b border-l border-slate-200 dark:border-slate-700 shadow-[-2px_0_4px_-2px_rgba(0,0,0,0.06)] whitespace-nowrap">
                    Actions
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {paginatedLeads.length === 0 ? (
                <tr>
                  <td colSpan={14} className="py-14 text-center text-slate-400">
                    <p className="font-semibold text-sm">No prospects found.</p>
                    <p className="text-xs text-slate-400 mt-1">Try clearing filters or search query, or import a spreadsheet above.</p>
                  </td>
                </tr>
              ) : (
                paginatedLeads.map((lead) => (
                  <tr key={lead.id} className="group/row hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors border-b border-slate-100 dark:border-slate-800/80">
                    {/* Checkbox (Sticky Left) */}
                    <td className="py-2.5 px-3 w-10 min-w-[40px] max-w-[40px] text-center sticky left-0 z-10 bg-white dark:bg-slate-900 group-hover/row:bg-slate-50 dark:group-hover/row:bg-slate-800/70 border-r border-slate-200/60 dark:border-slate-800 transition-colors shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)]">
                      <input
                        type="checkbox"
                        className="rounded border-slate-300 text-teal-600 focus:ring-teal-500 cursor-pointer"
                        checked={selected.has(lead.id)}
                        onChange={() => toggleOne(lead.id)}
                      />
                    </td>

                    {/* 1. Company Name with Website Link */}
                    {columns.company && (
                      <td className="py-2.5 px-3 min-w-[200px]">
                        <div className="flex items-center gap-1.5 font-medium text-slate-900 dark:text-slate-100">
                          <span className="truncate max-w-[170px]" title={lead.company || ''}>
                            {lead.company || '—'}
                          </span>
                          {lead.website && (
                            <a
                              href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`}
                              target="_blank"
                              rel="noreferrer"
                              title={`Visit ${lead.website}`}
                              className="text-primary-500 hover:text-primary-600 dark:hover:text-primary-400 p-0.5 rounded transition-colors shrink-0"
                            >
                              <RiExternalLinkLine size={13} />
                            </a>
                          )}
                        </div>
                      </td>
                    )}

                    {/* 2. Contact / Founder Name */}
                    {columns.contact && (
                      <td className="py-2.5 px-3 min-w-[130px]">
                        {lead.name ? (
                          <Link to={`/leads/${lead.id}`} className="font-semibold text-teal-600 dark:text-teal-400 hover:underline truncate max-w-[120px] block" title={lead.name}>
                            {lead.name}
                          </Link>
                        ) : (
                          <span className="text-slate-400 dark:text-slate-500">—</span>
                        )}
                      </td>
                    )}

                    {/* 3. Email Address with Copy Action */}
                    {columns.email && (
                      <td className="py-2.5 px-3 min-w-[220px]">
                        <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-700 dark:text-slate-300">
                          <span className="truncate max-w-[170px]" title={lead.email}>{lead.email}</span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              copyToClipboard(lead.email, `Copied: ${lead.email}`);
                            }}
                            title="Copy email address"
                            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer shrink-0"
                          >
                            <RiFileCopyLine size={13} />
                          </button>
                        </div>
                      </td>
                    )}

                    {/* 4. Phone Number with Copy Action */}
                    {columns.phone && (
                      <td className="py-2.5 px-3 min-w-[160px]">
                        {lead.phone ? (
                          <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-600 dark:text-slate-300">
                            <span className="truncate max-w-[125px]">{lead.phone}</span>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                copyToClipboard(lead.phone, `Copied: ${lead.phone}`);
                              }}
                              title="Copy phone number"
                              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer shrink-0"
                            >
                              <RiFileCopyLine size={13} />
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                    )}

                    {/* 5. Email Verification Status */}
                    {columns.verification && (
                      <td className="py-2.5 px-3 min-w-[160px] whitespace-nowrap cursor-pointer" onClick={() => setVerifModalLead(lead)}>
                        {getVerificationBadge(
                          lead.email_verification_status,
                          lead.email_verification_result?.role_based?.is_role_account,
                          lead.email_verification_result?.role_based?.role_category,
                          lead.email_verification_result?.approved
                        )}
                      </td>
                    )}

                    {/* 6. Sales / Pipeline Status */}
                    {columns.pipeline && (
                      <td className="py-2.5 px-3 min-w-[140px] whitespace-nowrap">
                        <span className={`inline-block px-2.5 py-0.5 text-[11px] rounded-full border ${pipelineBadge(lead.pipeline_status)}`}>
                          {(lead.pipeline_status || 'new').replace(/_/g, ' ')}
                        </span>
                      </td>
                    )}

                    {/* Optional Columns */}
                    {columns.location && (
                      <td className="py-2.5 px-3 min-w-[150px] text-slate-600 dark:text-slate-300 whitespace-nowrap">
                        {lead.city || lead.country ? (
                          <div className="flex items-center gap-1">
                            <RiMapPinLine size={12} className="text-slate-400 shrink-0" />
                            <span>{[lead.city, lead.country].filter(Boolean).join(', ')}</span>
                          </div>
                        ) : '—'}
                      </td>
                    )}

                    {columns.industry && (
                      <td className="py-2.5 px-3 min-w-[140px] text-slate-600 dark:text-slate-300">
                        {lead.industry || '—'}
                      </td>
                    )}

                    {columns.tags && (
                      <td className="py-2.5 px-3 min-w-[140px]">
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {(lead.tags || []).length === 0 ? (
                            <span className="text-slate-400">—</span>
                          ) : (
                            (lead.tags || []).map((t) => (
                              <span key={t} className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                                {t}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                    )}

                    {columns.campaigns && (
                      <td className="py-2.5 px-3 min-w-[170px]">
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {(lead.campaigns || []).length === 0 ? (
                            <span className="text-slate-400 text-[11px]">Not enrolled</span>
                          ) : (
                            (lead.campaigns || []).map((c) => (
                              <Link
                                key={c.campaign_id}
                                to={`/campaigns/${c.campaign_id}`}
                                className="px-1.5 py-0.5 rounded text-[10px] bg-teal-50 dark:bg-teal-950/60 text-teal-700 dark:text-teal-300 font-medium hover:underline"
                              >
                                {c.campaign_name || `Camp #${c.campaign_id}`}
                              </Link>
                            ))
                          )}
                        </div>
                      </td>
                    )}

                    {columns.lead_source && (
                      <td className="py-2.5 px-3 min-w-[130px] text-slate-600 dark:text-slate-300">
                        {lead.lead_source || '—'}
                      </td>
                    )}

                    {columns.created_at && (
                      <td className="py-2.5 px-3 min-w-[130px] text-slate-500 font-mono text-[11px]">
                        {lead.created_at ? lead.created_at.slice(0, 10) : '—'}
                      </td>
                    )}

                    {/* 7. Actions: View, Send Email, Add to Campaign (Sticky Right) */}
                    {columns.actions && (
                      <td className="py-2.5 px-3 min-w-[110px] text-right sticky right-0 z-10 bg-white dark:bg-slate-900 group-hover/row:bg-slate-50 dark:group-hover/row:bg-slate-800/70 border-l border-slate-200/60 dark:border-slate-800 shadow-[-2px_0_4px_-2px_rgba(0,0,0,0.06)] whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1">
                          <Link
                            to={`/leads/${lead.id}`}
                            title="View Prospect Profile"
                            className="p-1.5 rounded-lg text-slate-500 hover:text-teal-600 hover:bg-teal-50 dark:hover:bg-teal-950/50 transition-colors"
                          >
                            <RiEyeLine size={15} />
                          </Link>
                          <button
                            type="button"
                            onClick={() => handleOpenCompose(lead)}
                            title="Send Direct Email"
                            className="p-1.5 rounded-lg text-slate-500 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-950/50 transition-colors cursor-pointer"
                          >
                            <RiMailSendLine size={15} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleAssignSingleLead(lead)}
                            title="Add to Campaign"
                            className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 transition-colors cursor-pointer"
                          >
                            <RiUserAddLine size={15} />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {/* Accessible Pagination & Navigation Controls Footer */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-3 bg-slate-50 dark:bg-slate-800/60 border-t border-slate-200 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex items-center gap-3">
            <span>
              Showing <span className="font-semibold text-slate-800 dark:text-slate-200">{totalItems === 0 ? 0 : (currentPage - 1) * (pageSize === 'all' ? totalItems : Number(pageSize)) + 1}</span> to{' '}
              <span className="font-semibold text-slate-800 dark:text-slate-200">{pageSize === 'all' ? totalItems : Math.min(currentPage * Number(pageSize), totalItems)}</span> of{' '}
              <span className="font-semibold text-slate-800 dark:text-slate-200">{totalItems}</span> prospects
            </span>
            {selected.size > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-teal-100 dark:bg-teal-950/60 text-teal-800 dark:text-teal-300 font-semibold text-[11px]">
                {selected.size} selected
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span>Per page:</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(e.target.value === 'all' ? 'all' : Number(e.target.value));
                  setCurrentPage(1);
                }}
                className="text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2 py-1 focus:ring-1 focus:ring-teal-500"
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
                <option value="all">All</option>
              </select>
            </div>

            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="outline"
                disabled={currentPage <= 1}
                onClick={() => {
                  setCurrentPage((p) => Math.max(1, p - 1));
                  tableContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
                }}
                className="px-2.5 py-1 text-xs"
              >
                Previous
              </Button>
              <span className="px-2 font-medium text-slate-700 dark:text-slate-300">
                {currentPage} / {totalPages}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={currentPage >= totalPages}
                onClick={() => {
                  setCurrentPage((p) => Math.min(totalPages, p + 1));
                  tableContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
                }}
                className="px-2.5 py-1 text-xs"
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Manual Prospect Creation Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
              <div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <RiUserAddLine className="text-teal-600 dark:text-teal-400" size={18} /> Add New Prospect
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Fast prospect entry. Only company and email are required to begin outreach.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
              >
                <RiCloseLine size={20} />
              </button>
            </div>

            <form onSubmit={handleCreateLead} className="p-6 space-y-4 overflow-y-auto flex-1">
              {/* 5 Main Fields */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* 1. Company Name (Required) */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                    <RiBuildingLine className="text-slate-400" size={14} />
                    Company Name <span className="text-rose-500 font-bold">*</span>
                  </label>
                  <Input
                    placeholder="Acme Innovations"
                    value={leadFormData.company}
                    onChange={(e) => setLeadFormData({ ...leadFormData, company: e.target.value })}
                    required
                    autoFocus
                  />
                </div>

                {/* 2. Email Address (Required) */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                    <RiMailSendLine className="text-slate-400" size={14} />
                    Email Address <span className="text-rose-500 font-bold">*</span>
                  </label>
                  <Input
                    type="email"
                    placeholder="founder@company.com"
                    value={leadFormData.email}
                    onChange={(e) => setLeadFormData({ ...leadFormData, email: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {/* 3. Founder / Contact Name (Optional) */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                    <RiUserAddLine className="text-slate-400" size={14} />
                    Founder / Contact Name <span className="text-slate-400 text-[10px] font-normal">(optional)</span>
                  </label>
                  <Input
                    placeholder="Alex Vance"
                    value={leadFormData.name}
                    onChange={(e) => setLeadFormData({ ...leadFormData, name: e.target.value })}
                  />
                </div>

                {/* 4. Phone Number (Optional) */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                    <RiPhoneLine className="text-slate-400" size={14} />
                    Phone Number <span className="text-slate-400 text-[10px] font-normal">(optional)</span>
                  </label>
                  <Input
                    type="tel"
                    placeholder="+1 (555) 019-2831"
                    value={leadFormData.phone}
                    onChange={(e) => setLeadFormData({ ...leadFormData, phone: e.target.value })}
                  />
                </div>

                {/* 5. Website URL (Optional) */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                    <RiGlobalLine className="text-slate-400" size={14} />
                    Website URL <span className="text-slate-400 text-[10px] font-normal">(optional)</span>
                  </label>
                  <Input
                    type="url"
                    placeholder="https://company.com"
                    value={leadFormData.website}
                    onChange={(e) => setLeadFormData({ ...leadFormData, website: e.target.value })}
                  />
                </div>
              </div>

              {/* Automated Systems Indicator */}
              <div className="py-2.5 px-3 bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-slate-200/60 dark:border-slate-800 text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-500 shrink-0" />
                <span>
                  Verification status, pipeline stage (<strong className="text-slate-700 dark:text-slate-300">{leadFormData.pipeline_status || 'new'}</strong>), communication history, and campaign activity are automatically initialized and managed.
                </span>
              </div>

              {/* Collapsed Advanced Details Section */}
              <div className="pt-2 border-t border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAdvancedCreate((prev) => !prev)}
                  className="w-full flex items-center justify-between py-2 px-3 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
                >
                  <span className="flex items-center gap-1.5">
                    <span>Advanced Details</span>
                    <span className="text-[10px] font-normal text-slate-400">
                      (Industry, Location, Pipeline Stage, Tags, Notes)
                    </span>
                  </span>
                  <RiArrowDownSLine
                    size={16}
                    className={cn('transition-transform duration-200', showAdvancedCreate && 'rotate-180')}
                  />
                </button>

                {showAdvancedCreate && (
                  <div className="mt-3.5 space-y-3.5 pt-1 animate-fade-in">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                          City
                        </label>
                        <Input
                          placeholder="San Francisco"
                          value={leadFormData.city}
                          onChange={(e) => setLeadFormData({ ...leadFormData, city: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                          Country
                        </label>
                        <Input
                          placeholder="United States"
                          value={leadFormData.country}
                          onChange={(e) => setLeadFormData({ ...leadFormData, country: e.target.value })}
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div>
                        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                          Pipeline Stage
                        </label>
                        <select
                          value={leadFormData.pipeline_status}
                          onChange={(e) => setLeadFormData({ ...leadFormData, pipeline_status: e.target.value })}
                          className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white capitalize focus:ring-2 focus:ring-teal-500 focus:outline-none"
                        >
                          {PIPELINE_STATUSES.filter((p) => p.value !== 'all').map((p) => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                          Lead Source
                        </label>
                        <Input
                          placeholder="Cold Outreach"
                          value={leadFormData.lead_source}
                          onChange={(e) => setLeadFormData({ ...leadFormData, lead_source: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                          Tags (comma separated)
                        </label>
                        <Input
                          placeholder="vip, enterprise, q4"
                          value={leadFormData.tags}
                          onChange={(e) => setLeadFormData({ ...leadFormData, tags: e.target.value })}
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                        Internal Notes
                      </label>
                      <textarea
                        rows={2}
                        placeholder="Key background context, decision maker notes, pain points..."
                        value={leadFormData.notes}
                        onChange={(e) => setLeadFormData({ ...leadFormData, notes: e.target.value })}
                        className="w-full px-3 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-teal-500 focus:outline-none"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Actions Footer */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button type="button" variant="ghost" onClick={() => setCreateModalOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm flex items-center gap-1.5">
                  <RiCheckLine size={16} />
                  Save Prospect
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* CSV / Excel Import Modal with Column Mapping & Live Preview */}
      {importModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-4xl w-full max-h-[92vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-primary-100 dark:bg-primary-950/60 flex items-center justify-center text-primary-600 dark:text-primary-400">
                  <RiUploadCloud2Line size={20} />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900 dark:text-white">
                    Import Prospects (CSV / Excel)
                  </h2>
                  <p className="text-xs text-slate-500">
                    Smart auto-mapping for Austin agency prospect spreadsheets, contact lists, and CRM exports.
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setImportModalOpen(false);
                  setPreviewData(null);
                  setPreviewError(null);
                  setImportError(null);
                  setImportResult(null);
                  setImportFile(null);
                }}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded-lg"
              >
                <RiCloseLine size={22} />
              </button>
            </div>

            <form onSubmit={handleExecuteImport} className="p-6 space-y-5 overflow-y-auto flex-1">
              {/* File Dropzone */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Select CSV or Excel (.xlsx / .xls) File
                </label>
                <input
                  type="file"
                  accept=".csv, .xlsx, .xls"
                  onChange={handleFileSelect}
                  className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-primary-50 dark:file:bg-primary-950/60 file:text-primary-700 dark:file:text-primary-300 hover:file:bg-primary-100 dark:hover:file:bg-primary-900/60 cursor-pointer border border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-2 bg-slate-50/30 dark:bg-slate-800/20"
                />
              </div>

              {/* Loading State */}
              {previewLoading && (
                <div className="p-8 text-center bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-slate-200 dark:border-slate-700">
                  <RiLoader4Line className="animate-spin text-primary-500 mx-auto mb-2" size={32} />
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                    Analyzing spreadsheet structure & validating records...
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Auto-detecting agency fields, checking email syntax, and scanning for duplicates.
                  </p>
                </div>
              )}

              {/* Error Alert */}
              {previewError && (
                <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/60 text-rose-800 dark:text-rose-200 text-xs flex items-start gap-3">
                  <RiAlertLine className="text-rose-500 shrink-0 mt-0.5" size={18} />
                  <div className="flex-1">
                    <p className="font-semibold text-sm">Cannot Import File</p>
                    <p className="mt-1 leading-relaxed">{previewError}</p>
                    <p className="mt-2 text-rose-600 dark:text-rose-400 font-medium">
                      Tip: Ensure your spreadsheet contains a header row and at least 1 valid row of prospect data.
                    </p>
                  </div>
                </div>
              )}

              {/* Pre-Import Data Health & Stats Badges */}
              {previewData && (
                <div className="space-y-5 animate-fade-in">
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 text-xs">
                    <div className="bg-slate-100 dark:bg-slate-800 p-3 rounded-xl border border-slate-200 dark:border-slate-700 text-center">
                      <span className="block text-slate-400 font-medium text-[11px] mb-0.5">Total Records</span>
                      <span className="text-lg font-bold text-slate-800 dark:text-slate-100">{previewData.total_rows}</span>
                    </div>
                    <div className="bg-emerald-50 dark:bg-emerald-950/40 p-3 rounded-xl border border-emerald-200 dark:border-emerald-800 text-center">
                      <span className="block text-emerald-600 dark:text-emerald-400 font-medium text-[11px] mb-0.5">Ready to Import</span>
                      <span className="text-lg font-bold text-emerald-700 dark:text-emerald-300">{previewData.estimated_import}</span>
                    </div>
                    <div className="bg-amber-50 dark:bg-amber-950/40 p-3 rounded-xl border border-amber-200 dark:border-amber-800 text-center">
                      <span className="block text-amber-600 dark:text-amber-400 font-medium text-[11px] mb-0.5">Duplicates</span>
                      <span className="text-lg font-bold text-amber-700 dark:text-amber-300">{previewData.duplicate_count}</span>
                    </div>
                    <div className="bg-rose-50 dark:bg-rose-950/40 p-3 rounded-xl border border-rose-200 dark:border-rose-800 text-center">
                      <span className="block text-rose-600 dark:text-rose-400 font-medium text-[11px] mb-0.5">Invalid Format</span>
                      <span className="text-lg font-bold text-rose-700 dark:text-rose-300">{previewData.invalid_count}</span>
                    </div>
                    <div className="bg-slate-50 dark:bg-slate-800/60 p-3 rounded-xl border border-slate-200 dark:border-slate-700 text-center col-span-2 sm:col-span-1">
                      <span className="block text-slate-500 font-medium text-[11px] mb-0.5">Missing Email</span>
                      <span className="text-lg font-bold text-slate-600 dark:text-slate-400">{previewData.missing_email_count}</span>
                    </div>
                  </div>

                  {/* Column Mapping Grid */}
                  <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-xl border border-slate-200 dark:border-slate-700 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 flex items-center gap-2">
                        <span>Smart Column Mapping</span>
                        <span className="text-[10px] font-normal px-2 py-0.5 bg-primary-100 dark:bg-primary-950 text-primary-700 dark:text-primary-300 rounded-full">
                          Auto-Detected
                        </span>
                      </h3>
                      <span className="text-[11px] text-slate-400">Only Email is required; all other fields optional</span>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">
                          Email Address <span className="text-rose-500">*</span>
                        </span>
                        <select
                          value={importMapping.email || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, email: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                          required
                        >
                          <option value="">-- Choose Column --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Contact / Founder Name</span>
                        <select
                          value={importMapping.name || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, name: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Agency / Business Name</span>
                        <select
                          value={importMapping.company || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, company: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Phone Number</span>
                        <select
                          value={importMapping.phone || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, phone: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Website / Domain URL</span>
                        <select
                          value={importMapping.website || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, website: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">City / Metro</span>
                        <select
                          value={importMapping.city || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, city: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">State / Region</span>
                        <select
                          value={importMapping.state || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, state: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Country</span>
                        <select
                          value={importMapping.country || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, country: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Industry / Vertical</span>
                        <select
                          value={importMapping.industry || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, industry: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Lead Source / Channel</span>
                        <select
                          value={importMapping.lead_source || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, lead_source: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Tags / Keywords</span>
                        <select
                          value={importMapping.tags || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, tags: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>

                      <div>
                        <span className="font-semibold block mb-1 text-slate-700 dark:text-slate-300">Notes / Bio</span>
                        <select
                          value={importMapping.notes || ''}
                          onChange={(e) => setImportMapping({ ...importMapping, notes: e.target.value })}
                          className="w-full p-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        >
                          <option value="">-- Ignore / None --</option>
                          {importColumns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* First 10 Rows Data Preview */}
                  {previewData.preview_rows && previewData.preview_rows.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs text-slate-500">
                        <span className="font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider text-[11px]">
                          Data Preview (First 10 Rows)
                        </span>
                        <span>Showing mapped view of uploaded records</span>
                      </div>
                      <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700 max-h-48 overflow-y-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 sticky top-0 border-b border-slate-200 dark:border-slate-700">
                            <tr>
                              <th className="px-3 py-2 font-semibold">#</th>
                              <th className="px-3 py-2 font-semibold">Status</th>
                              <th className="px-3 py-2 font-semibold">Email</th>
                              <th className="px-3 py-2 font-semibold">Contact</th>
                              <th className="px-3 py-2 font-semibold">Agency / Company</th>
                              <th className="px-3 py-2 font-semibold">Phone</th>
                              <th className="px-3 py-2 font-semibold">Website</th>
                              <th className="px-3 py-2 font-semibold">Location</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100 dark:divide-slate-800 bg-white dark:bg-slate-900">
                            {previewData.preview_rows.map((row) => (
                              <tr key={row.row_index} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/40">
                                <td className="px-3 py-2 text-slate-400 font-mono text-[11px]">{row.row_index}</td>
                                <td className="px-3 py-2 whitespace-nowrap">
                                  {row.status === 'ready' && (
                                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                                      Ready
                                    </span>
                                  )}
                                  {row.status === 'duplicate' && (
                                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300">
                                      Duplicate
                                    </span>
                                  )}
                                  {row.status === 'invalid_format' && (
                                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300">
                                      Invalid
                                    </span>
                                  )}
                                  {row.status === 'missing_email' && (
                                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                                      No Email
                                    </span>
                                  )}
                                </td>
                                <td className="px-3 py-2 font-medium text-slate-900 dark:text-slate-100 max-w-[180px] truncate">
                                  {row.email || '<empty>'}
                                </td>
                                <td className="px-3 py-2 text-slate-600 dark:text-slate-300 max-w-[140px] truncate">
                                  {row.name || '—'}
                                </td>
                                <td className="px-3 py-2 text-slate-600 dark:text-slate-300 max-w-[160px] truncate font-medium">
                                  {row.company || '—'}
                                </td>
                                <td className="px-3 py-2 text-slate-500 font-mono text-[11px]">
                                  {row.phone || '—'}
                                </td>
                                <td className="px-3 py-2 text-slate-500 max-w-[140px] truncate">
                                  {row.website || '—'}
                                </td>
                                <td className="px-3 py-2 text-slate-500">
                                  {[row.city, row.state].filter(Boolean).join(', ') || '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Campaign Assignment and Fill Missing Details */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
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

                <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 flex flex-col justify-center">
                  <label className="flex items-start gap-2.5 cursor-pointer text-xs font-medium text-slate-700 dark:text-slate-300">
                    <input
                      type="checkbox"
                      checked={fillMissingDetails}
                      onChange={(e) => setFillMissingDetails(e.target.checked)}
                      className="mt-0.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                    />
                    <div>
                      <span className="font-semibold text-slate-800 dark:text-slate-200">Fill Missing Details</span>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">
                        Existing prospects are skipped by default. Check this to fill empty fields. Conflicting values are never overwritten.
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700">
                <label className="flex items-center gap-2.5 cursor-pointer text-xs font-medium text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={autoVerifyImport}
                    onChange={(e) => setAutoVerifyImport(e.target.checked)}
                    className="rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                  />
                  <span>Automatically verify email deliverability in background after import</span>
                </label>
              </div>

              {/* Import Error Banner */}
              {importError && (
                <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-200 text-xs flex items-start gap-2.5">
                  <RiAlertLine className="text-rose-500 shrink-0 mt-0.5" size={16} />
                  <div>
                    <p className="font-semibold text-xs">Import Execution Error</p>
                    <p className="mt-0.5">{importError}</p>
                  </div>
                </div>
              )}

              {/* Compact Import Execution Summary with Optional View Details */}
              {importResult && (
                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 space-y-3 animate-fade-in">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-bold uppercase tracking-wider text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                      <RiCheckLine className="text-emerald-500" size={16} />
                      Import Execution Summary
                    </span>
                    <span className="text-[11px] font-mono text-slate-500">
                      {importResult.filename || 'Spreadsheet'}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
                    <div className="bg-emerald-50 dark:bg-emerald-950/40 p-2.5 rounded-lg border border-emerald-200 dark:border-emerald-800 text-center">
                      <span className="block text-emerald-600 dark:text-emerald-400 text-[10px] uppercase font-semibold">Added</span>
                      <span className="text-base font-bold text-emerald-700 dark:text-emerald-300">{importResult.added ?? importResult.imported ?? 0}</span>
                    </div>
                    <div className="bg-amber-50 dark:bg-amber-950/40 p-2.5 rounded-lg border border-amber-200 dark:border-amber-800 text-center">
                      <span className="block text-amber-600 dark:text-amber-400 text-[10px] uppercase font-semibold">Skipped Duplicates</span>
                      <span className="text-base font-bold text-amber-700 dark:text-amber-300">
                        {importResult.skipped_duplicates ?? importResult.duplicates_skipped ?? 0}
                      </span>
                    </div>
                    <div className="bg-blue-50 dark:bg-blue-950/40 p-2.5 rounded-lg border border-blue-200 dark:border-blue-800 text-center">
                      <span className="block text-blue-600 dark:text-blue-400 text-[10px] uppercase font-semibold">Updated</span>
                      <span className="text-base font-bold text-blue-700 dark:text-blue-300">{importResult.updated ?? importResult.duplicates_updated ?? 0}</span>
                    </div>
                    <div className="bg-rose-50 dark:bg-rose-950/40 p-2.5 rounded-lg border border-rose-200 dark:border-rose-800 text-center">
                      <span className="block text-rose-600 dark:text-rose-400 text-[10px] uppercase font-semibold">Invalid</span>
                      <span className="text-base font-bold text-rose-700 dark:text-rose-300">{importResult.invalid || 0}</span>
                    </div>
                    <div className="bg-slate-100 dark:bg-slate-800 p-2.5 rounded-lg border border-slate-200 dark:border-slate-700 text-center">
                      <span className="block text-slate-500 text-[10px] uppercase font-semibold">Failed</span>
                      <span className="text-base font-bold text-slate-700 dark:text-slate-300">{importResult.failed || 0}</span>
                    </div>
                  </div>

                  {/* Optional View Details Action */}
                  {importResult.details && (
                    (importResult.details.skipped?.length > 0 ||
                     importResult.details.updated?.length > 0 ||
                     importResult.details.conflicts?.length > 0 ||
                     importResult.details.invalid?.length > 0) && (
                      <div className="pt-2 border-t border-slate-200 dark:border-slate-700">
                        <div className="flex items-center justify-between">
                          <button
                            type="button"
                            onClick={() => setDetailsExpanded(!detailsExpanded)}
                            className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 flex items-center gap-1.5 transition-colors"
                          >
                            <span>{detailsExpanded ? '▾ Hide Details' : '▸ View Details'}</span>
                            <span className="text-[11px] font-normal text-slate-500">
                              ({(importResult.details.skipped?.length || 0)} skipped, {(importResult.details.updated?.length || 0)} updated, {(importResult.details.conflicts?.length || 0)} conflicts, {(importResult.details.invalid?.length || 0)} invalid)
                            </span>
                          </button>
                        </div>

                        {detailsExpanded && (
                          <div className="mt-2.5 space-y-2">
                            {/* Detail Sub-Tabs */}
                            <div className="flex items-center gap-1 border-b border-slate-200 dark:border-slate-700 text-xs">
                              {importResult.details.skipped?.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setSelectedDetailTab('skipped')}
                                  className={`px-2.5 py-1 font-medium rounded-t border-b-2 -mb-px transition-colors ${
                                    selectedDetailTab === 'skipped'
                                      ? 'border-amber-500 text-amber-700 dark:text-amber-400 font-semibold'
                                      : 'border-transparent text-slate-500 hover:text-slate-700'
                                  }`}
                                >
                                  Skipped ({importResult.details.skipped.length})
                                </button>
                              )}
                              {importResult.details.updated?.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setSelectedDetailTab('updated')}
                                  className={`px-2.5 py-1 font-medium rounded-t border-b-2 -mb-px transition-colors ${
                                    selectedDetailTab === 'updated'
                                      ? 'border-blue-500 text-blue-700 dark:text-blue-400 font-semibold'
                                      : 'border-transparent text-slate-500 hover:text-slate-700'
                                  }`}
                                >
                                  Updated ({importResult.details.updated.length})
                                </button>
                              )}
                              {importResult.details.conflicts?.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setSelectedDetailTab('conflicts')}
                                  className={`px-2.5 py-1 font-medium rounded-t border-b-2 -mb-px transition-colors ${
                                    selectedDetailTab === 'conflicts'
                                      ? 'border-orange-500 text-orange-700 dark:text-orange-400 font-semibold'
                                      : 'border-transparent text-slate-500 hover:text-slate-700'
                                  }`}
                                >
                                  Conflicts Retained ({importResult.details.conflicts.length})
                                </button>
                              )}
                              {importResult.details.invalid?.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setSelectedDetailTab('invalid')}
                                  className={`px-2.5 py-1 font-medium rounded-t border-b-2 -mb-px transition-colors ${
                                    selectedDetailTab === 'invalid'
                                      ? 'border-rose-500 text-rose-700 dark:text-rose-400 font-semibold'
                                      : 'border-transparent text-slate-500 hover:text-slate-700'
                                  }`}
                                >
                                  Invalid ({importResult.details.invalid.length})
                                </button>
                              )}
                            </div>

                            {/* Details Table */}
                            <div className="max-h-48 overflow-y-auto border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-900 text-xs">
                              <table className="w-full text-left">
                                <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 text-[10px] uppercase font-semibold sticky top-0 border-b border-slate-200 dark:border-slate-700">
                                  <tr>
                                    <th className="px-3 py-1.5 w-12">Row</th>
                                    <th className="px-3 py-1.5">Email</th>
                                    {selectedDetailTab === 'conflicts' ? (
                                      <>
                                        <th className="px-3 py-1.5">Field</th>
                                        <th className="px-3 py-1.5">Kept Value (DB)</th>
                                        <th className="px-3 py-1.5">Ignored (Import)</th>
                                      </>
                                    ) : selectedDetailTab === 'updated' ? (
                                      <>
                                        <th className="px-3 py-1.5">Company</th>
                                        <th className="px-3 py-1.5">Fields Filled</th>
                                      </>
                                    ) : (
                                      <>
                                        <th className="px-3 py-1.5">Company</th>
                                        <th className="px-3 py-1.5">Reason</th>
                                      </>
                                    )}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                  {(importResult.details[selectedDetailTab] || []).map((item, idx) => (
                                    <tr key={idx} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/50">
                                      <td className="px-3 py-1 text-slate-400 font-mono text-[11px]">{item.row || idx + 1}</td>
                                      <td className="px-3 py-1 font-medium text-slate-800 dark:text-slate-200 font-mono text-[11px] truncate max-w-[160px]">{item.email}</td>
                                      {selectedDetailTab === 'conflicts' ? (
                                        <>
                                          <td className="px-3 py-1 font-semibold text-slate-700 dark:text-slate-300">{item.field}</td>
                                          <td className="px-3 py-1 text-emerald-700 dark:text-emerald-400">{item.existing}</td>
                                          <td className="px-3 py-1 text-slate-400 line-through">{item.imported}</td>
                                        </>
                                      ) : selectedDetailTab === 'updated' ? (
                                        <>
                                          <td className="px-3 py-1 text-slate-600 dark:text-slate-400 truncate max-w-[120px]">{item.company || '—'}</td>
                                          <td className="px-3 py-1 text-blue-600 dark:text-blue-400 font-mono text-[10px]">
                                            {(item.fields_filled || []).join(', ')}
                                          </td>
                                        </>
                                      ) : (
                                        <>
                                          <td className="px-3 py-1 text-slate-600 dark:text-slate-400 truncate max-w-[120px]">{item.company || '—'}</td>
                                          <td className="px-3 py-1 text-slate-500 text-[11px]">{item.reason || '—'}</td>
                                        </>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  )}
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setImportModalOpen(false);
                    setPreviewData(null);
                    setPreviewError(null);
                    setImportFile(null);
                    setImportResult(null);
                  }}
                >
                  Close
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={!importFile || !importMapping.email || previewLoading || importExecuting}
                  className="flex items-center gap-1.5"
                >
                  {importExecuting && <RiLoader4Line className="animate-spin" size={14} />}
                  <span>
                    {importExecuting
                      ? 'Importing...'
                      : previewData
                      ? `Import ${previewData.estimated_import || 0} Prospects`
                      : 'Run Import'}
                  </span>
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Direct Email Compose Modal */}
      <ComposeModal
        isOpen={composeModalOpen}
        onClose={() => {
          setComposeModalOpen(false);
          setComposeTargetLead(null);
        }}
        onSent={() => loadLeads()}
        initialTo={composeTargetLead?.email || ''}
        initialRecipientName={composeTargetLead?.name || ''}
        initialLeadId={composeTargetLead?.id || null}
      />

      <LeadVerificationModal
        lead={verifModalLead}
        isOpen={!!verifModalLead}
        onClose={() => setVerifModalLead(null)}
        onUpdated={(updated) => {
          const merged = {
            ...(verifModalLead || {}),
            ...updated,
            email_verification_status: updated.status || updated.email_verification_status || verifModalLead?.email_verification_status,
            email_verification_result: updated.result || updated.email_verification_result || verifModalLead?.email_verification_result,
          };
          setVerifModalLead(merged);
          setLeads((prev) =>
            prev.map((l) =>
              l.id === (updated.lead_id || updated.id)
                ? {
                    ...l,
                    ...merged,
                  }
                : l
            )
          );
        }}
      />

      {/* Bulk Assign to Campaign Modal */}
      <AssignCampaignModal
        isOpen={assignCampaignModalOpen}
        onClose={() => {
          setAssignCampaignModalOpen(false);
          setAssignTargetLeadIds([]);
        }}
        selectedLeadIds={assignTargetLeadIds.length > 0 ? assignTargetLeadIds : [...selected]}
        campaigns={campaigns}
        initialCampaignId={bulkCampaignId}
        onAssigned={() => {
          setSelected(new Set());
          setAssignTargetLeadIds([]);
          loadLeads();
        }}
      />
    </div>
  );
}

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RiCompassDiscoverLine,
  RiSearchLine,
  RiBuildingLine,
  RiUserLine,
  RiMailLine,
  RiPhoneLine,
  RiGlobalLine,
  RiMapPinLine,
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiAlertLine,
  RiPlayLine,
  RiPauseLine,
  RiStopLine,
  RiUserAddLine,
  RiExternalLinkLine,
  RiCheckLine,
  RiCloseLine,
  RiInformationLine,
  RiRefreshLine,
  RiFilter3Line,
  RiArrowRightLine,
  RiShieldCheckLine,
  RiFileTextLine,
  RiLinkedinBoxLine,
  RiTwitterXLine,
  RiInstagramLine,
} from 'react-icons/ri';
import { api } from '../api';
import { useNotify } from '../context/NotificationContext';
import { useConfirm } from '../context/ConfirmContext';

export default function ProspectResearch() {
  const notify = useNotify();
  const confirm = useConfirm();

  // Navigation tab state
  const [activeTab, setActiveTab] = useState(() => {
    const hash = typeof window !== 'undefined' ? window.location.hash.replace('#', '') : '';
    if (['dashboard', 'new-job', 'results', 'jobs', 'imported'].includes(hash)) return hash;
    const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
    const tabParam = params?.get('tab');
    if (['dashboard', 'new-job', 'results', 'jobs', 'imported'].includes(tabParam)) return tabParam;
    return 'dashboard';
  });

  useEffect(() => {
    const syncFromUrl = () => {
      const hash = (window.location.hash || '').replace('#', '');
      const params = new URLSearchParams(window.location.search);
      const target = hash || params.get('tab');
      if (['dashboard', 'new-job', 'results', 'jobs', 'imported'].includes(target)) {
        setActiveTab(target);
      }
    };
    window.addEventListener('hashchange', syncFromUrl);
    return () => window.removeEventListener('hashchange', syncFromUrl);
  }, []);

  // Dashboard Stats
  const [stats, setStats] = useState({
    total_jobs: 0,
    running_jobs: 0,
    total_companies: 0,
    total_contacts: 0,
    emails_discovered: 0,
    verified_valid: 0,
    approved_companies: 0,
    imported_to_crm: 0,
  });
  const [loadingStats, setLoadingStats] = useState(false);

  // New Research Job Form
  const [jobForm, setJobForm] = useState({
    name: 'Austin Web Design & Creative Agencies',
    country: 'United States',
    state: 'Texas',
    city: 'Austin',
    industry: 'Web Design Agencies',
    keywords: 'web design, digital agency, branding, ux',
    target_count: 50,
    assigned_to: 'admin',
  });
  const [creatingJob, setCreatingJob] = useState(false);

  // Results State
  const [results, setResults] = useState([]);
  const [totalResults, setTotalResults] = useState(0);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const limit = 25;

  // Results Filter
  const [search, setSearch] = useState('');
  const [filterCity, setFilterCity] = useState('');
  const [filterIndustry, setFilterIndustry] = useState('');
  const [filterEmailStatus, setFilterEmailStatus] = useState('all'); // 'all' | 'has_email' | 'missing'
  const [filterVerification, setFilterVerification] = useState('all');
  const [filterMinIcp, setFilterMinIcp] = useState('all');
  const [filterReviewStatus, setFilterReviewStatus] = useState('all');
  const [selectedJobFilter, setSelectedJobFilter] = useState(null);

  // Bulk Selection
  const [selectedContactIds, setSelectedContactIds] = useState([]);

  // Jobs List State
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);

  // Detail Modal
  const [detailCompany, setDetailCompany] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // ── Load Stats ─────────────────────────────────────────────────────────────
  const loadStats = useCallback(async () => {
    try {
      setLoadingStats(true);
      const res = await api.get('/research/stats');
      setStats(res);
    } catch (err) {
      console.error('Failed to load research stats:', err);
    } finally {
      setLoadingStats(false);
    }
  }, []);

  // ── Load Jobs ──────────────────────────────────────────────────────────────
  const loadJobs = useCallback(async () => {
    try {
      setJobsLoading(true);
      const res = await api.get('/research/jobs');
      setJobs(res || []);
    } catch (err) {
      console.error('Failed to load research jobs:', err);
    } finally {
      setJobsLoading(false);
    }
  }, []);

  // ── Load Results ───────────────────────────────────────────────────────────
  const loadResults = useCallback(async () => {
    try {
      setResultsLoading(true);
      const params = new URLSearchParams({
        page: String(page),
        limit: String(limit),
      });

      if (search.trim()) params.append('search', search.trim());
      if (filterCity.trim()) params.append('city', filterCity.trim());
      if (filterIndustry.trim()) params.append('industry', filterIndustry.trim());
      if (filterReviewStatus !== 'all') params.append('review_status', filterReviewStatus);
      if (filterVerification !== 'all') params.append('verification_status', filterVerification);
      if (filterMinIcp !== 'all') params.append('min_icp', filterMinIcp);
      if (filterEmailStatus === 'has_email') params.append('has_email', 'true');
      if (filterEmailStatus === 'missing') params.append('has_email', 'false');
      if (selectedJobFilter) params.append('job_id', String(selectedJobFilter));

      const res = await api.get(`/research/results?${params.toString()}`);
      setResults(res.results || []);
      setTotalResults(res.total || 0);
    } catch (err) {
      console.error('Failed to load research results:', err);
    } finally {
      setResultsLoading(false);
    }
  }, [page, search, filterCity, filterIndustry, filterReviewStatus, filterVerification, filterMinIcp, filterEmailStatus, selectedJobFilter]);

  // Initial load
  useEffect(() => {
    loadStats();
    loadJobs();
  }, [loadStats, loadJobs]);

  useEffect(() => {
    if (activeTab === 'results' || activeTab === 'imported') {
      loadResults();
    }
  }, [activeTab, loadResults]);

  // Periodic polling when any job is running
  useEffect(() => {
    if (stats.running_jobs > 0 || jobs.some(j => j.status === 'running')) {
      const interval = setInterval(() => {
        loadStats();
        loadJobs();
        if (activeTab === 'results') {
          loadResults();
        }
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [stats.running_jobs, jobs, activeTab, loadStats, loadJobs, loadResults]);

  // ── Handle Start Research Job ──────────────────────────────────────────────
  const handleCreateJob = async (e) => {
    e.preventDefault();
    if (!jobForm.name.trim()) {
      notify?.error('Please enter a research job name');
      return;
    }

    try {
      setCreatingJob(true);
      const keywordsList = jobForm.keywords
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean);

      const payload = {
        name: jobForm.name.trim(),
        country: jobForm.country.trim(),
        state: jobForm.state.trim(),
        city: jobForm.city.trim(),
        industry: jobForm.industry.trim(),
        keywords: keywordsList,
        target_count: Number(jobForm.target_count),
        assigned_to: jobForm.assigned_to.trim() || 'admin',
      };

      const res = await api.post('/research/jobs', payload);
      notify?.success(`Research Job '${res.name}' started in background!`);
      loadStats();
      loadJobs();
      setActiveTab('jobs');
    } catch (err) {
      notify?.error(err.response?.data?.detail || 'Failed to start research job');
    } finally {
      setCreatingJob(false);
    }
  };

  // ── Job Controls ───────────────────────────────────────────────────────────
  const handlePauseJob = async (jobId) => {
    try {
      await api.post(`/research/jobs/${jobId}/pause`);
      notify?.info(`Job #${jobId} paused`);
      loadJobs();
    } catch (err) {
      notify?.error('Failed to pause job');
    }
  };

  const handleResumeJob = async (jobId) => {
    try {
      await api.post(`/research/jobs/${jobId}/resume`);
      notify?.success(`Job #${jobId} resumed`);
      loadJobs();
    } catch (err) {
      notify?.error('Failed to resume job');
    }
  };

  const handleCancelJob = async (jobId) => {
    const ok = await confirm?.({
      title: 'Cancel Research Job',
      message: `Are you sure you want to cancel research job #${jobId}? In-progress extractions will stop.`,
      confirmLabel: 'Cancel Job',
      destructive: true,
    });
    if (!ok) return;

    try {
      await api.post(`/research/jobs/${jobId}/cancel`);
      notify?.info(`Job #${jobId} cancelled`);
      loadJobs();
      loadStats();
    } catch (err) {
      notify?.error('Failed to cancel job');
    }
  };

  // ── Status Updates ─────────────────────────────────────────────────────────
  const handleUpdateStatus = async (companyId, newStatus) => {
    try {
      await api.patch(`/research/results/${companyId}/status`, { review_status: newStatus });
      notify?.success(`Marked as ${newStatus}`);
      // Update locally
      setResults((prev) =>
        prev.map((c) => (c.id === companyId ? { ...c, review_status: newStatus } : c))
      );
      if (detailCompany && detailCompany.id === companyId) {
        setDetailCompany((prev) => ({ ...prev, review_status: newStatus }));
      }
      loadStats();
    } catch (err) {
      notify?.error('Failed to update status');
    }
  };

  // ── Promote Single Contact to Lead (Phase 8) ───────────────────────────────
  const handlePromoteContact = async (contactId) => {
    try {
      const res = await api.post(`/research/results/${contactId}/promote`);
      if (res.imported) {
        notify?.success(res.message || 'Successfully added to Prospects!');
      } else if (res.already_exists) {
        notify?.info(res.message || 'Already exists in Prospects');
      }
      loadResults();
      loadStats();
      if (detailCompany) {
        openCompanyDetail(detailCompany.id);
      }
    } catch (err) {
      notify?.error(err.response?.data?.detail || 'Failed to add contact to prospects');
    }
  };

  // ── Bulk Actions ───────────────────────────────────────────────────────────
  const handleBulkPromote = async () => {
    if (selectedContactIds.length === 0) return;
    const ok = await confirm?.({
      title: `Add ${selectedContactIds.length} Prospects`,
      message: `Promote ${selectedContactIds.length} selected contacts into the active CRM Prospect Database? Verified emails and metadata will be preserved.`,
      confirmLabel: `Add ${selectedContactIds.length} to Prospects`,
    });
    if (!ok) return;

    try {
      const res = await api.post('/research/results/bulk-promote', {
        contact_ids: selectedContactIds,
      });
      notify?.success(
        `Imported: ${res.imported} new, Already existing: ${res.already_exists}, Skipped/Missing email: ${res.missing_email}`
      );
      setSelectedContactIds([]);
      loadResults();
      loadStats();
    } catch (err) {
      notify?.error('Bulk promotion failed');
    }
  };

  const handleBulkStatus = async (status) => {
    const selectedCompanies = results
      .filter((r) => r.primary_contact && selectedContactIds.includes(r.primary_contact.id))
      .map((r) => r.id);

    if (selectedCompanies.length === 0) return;

    try {
      await api.post('/research/results/bulk-status', {
        company_ids: selectedCompanies,
        review_status: status,
      });
      notify?.success(`Updated ${selectedCompanies.length} companies to ${status}`);
      setSelectedContactIds([]);
      loadResults();
      loadStats();
    } catch (err) {
      notify?.error('Failed to update statuses');
    }
  };

  // ── Open Detail Modal ──────────────────────────────────────────────────────
  const openCompanyDetail = async (companyId) => {
    try {
      setLoadingDetail(true);
      const res = await api.get(`/research/results/${companyId}`);
      setDetailCompany(res.company);
    } catch (err) {
      notify?.error('Failed to load company details');
    } finally {
      setLoadingDetail(false);
    }
  };

  // ── Checkbox Selection ─────────────────────────────────────────────────────
  const toggleSelectContact = (cid) => {
    setSelectedContactIds((prev) =>
      prev.includes(cid) ? prev.filter((id) => id !== cid) : [...prev, cid]
    );
  };

  const toggleSelectAll = () => {
    const pageContactIds = results
      .filter((r) => r.primary_contact && r.primary_contact.email)
      .map((r) => r.primary_contact.id);

    if (pageContactIds.every((id) => selectedContactIds.includes(id))) {
      setSelectedContactIds((prev) => prev.filter((id) => !pageContactIds.includes(id)));
    } else {
      setSelectedContactIds((prev) => [...new Set([...prev, ...pageContactIds])]);
    }
  };

  // Status Badge Helper
  const renderVerificationBadge = (st) => {
    switch (st) {
      case 'valid':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/60">
            <RiShieldCheckLine className="w-3.5 h-3.5" /> Valid
          </span>
        );
      case 'domain_validated':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-teal-950/60 text-teal-300 border border-teal-800/60">
            <RiShieldCheckLine className="w-3.5 h-3.5" /> Domain Validated
          </span>
        );
      case 'risky':
      case 'catch_all':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-950/60 text-amber-300 border border-amber-800/60">
            <RiAlertLine className="w-3.5 h-3.5" /> Catch-All / Risky
          </span>
        );
      case 'invalid':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-rose-950/60 text-rose-300 border border-rose-800/60">
            <RiCloseCircleLine className="w-3.5 h-3.5" /> Invalid
          </span>
        );
      case 'missing':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
            Email Missing
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
            Untested
          </span>
        );
    }
  };

  const renderReviewBadge = (st, promotedId) => {
    if (promotedId) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-950/70 text-blue-300 border border-blue-800/60">
          <RiCheckboxCircleLine className="w-3.5 h-3.5" /> Lead #{promotedId}
        </span>
      );
    }
    switch (st) {
      case 'approved':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/60">
            Approved
          </span>
        );
      case 'rejected':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-950/60 text-rose-300 border border-rose-800/60">
            Rejected
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-950/60 text-amber-300 border border-amber-800/60">
            Pending Review
          </span>
        );
    }
  };

  const renderIcpBadge = (score) => {
    let color = 'bg-slate-800 text-slate-300 border-slate-700';
    if (score >= 90) color = 'bg-teal-950/70 text-teal-300 border-teal-800/70 font-semibold';
    else if (score >= 75) color = 'bg-blue-950/70 text-blue-300 border-blue-800/70';
    else if (score >= 50) color = 'bg-amber-950/70 text-amber-300 border-amber-800/70';

    return (
      <span className={`inline-flex items-center justify-center px-2 py-0.5 rounded text-xs border ${color}`}>
        {score} / 100
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-8 py-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-teal-500/10 text-teal-400 rounded-lg border border-teal-500/20">
              <RiCompassDiscoverLine className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Prospect Research Engine
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-teal-950 text-teal-300 border border-teal-800/60">
                  Open-Source Discovery & Enrichment
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Discover businesses via Overture Maps & OpenStreetMap, crawl official websites, extract leadership contacts, and verify deliverability.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              loadStats();
              loadJobs();
              if (activeTab === 'results') loadResults();
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-800 hover:border-slate-700 bg-slate-900 text-slate-300 text-xs font-medium transition"
          >
            <RiRefreshLine className="w-3.5 h-3.5" /> Refresh
          </button>
          <button
            onClick={() => setActiveTab('new-job')}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold shadow-sm transition"
          >
            <RiCompassDiscoverLine className="w-3.5 h-3.5" /> Start New Research
          </button>
        </div>
      </div>

      {/* ── Navigation Tabs ─────────────────────────────────────────────────── */}
      <div className="border-b border-slate-800 bg-slate-900/30 px-8 flex items-center gap-6 text-sm font-medium">
        {[
          { id: 'dashboard', label: 'Research Dashboard' },
          { id: 'new-job', label: 'New Research' },
          { id: 'results', label: `Research Results (${totalResults || stats.total_companies})` },
          { id: 'jobs', label: `Research Jobs (${jobs.length})` },
          { id: 'imported', label: `Approved & Imported (${stats.imported_to_crm})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveTab(tab.id);
              if (tab.id === 'imported') {
                setFilterReviewStatus('approved');
              } else if (tab.id === 'results') {
                setFilterReviewStatus('all');
              }
            }}
            className={`py-3 relative font-medium transition text-xs tracking-wide uppercase ${
              activeTab === tab.id
                ? 'text-teal-400 font-semibold'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-teal-400 rounded-t" />
            )}
          </button>
        ))}
      </div>

      {/* ── Main Content Area ───────────────────────────────────────────────── */}
      <div className="p-8 flex-1 overflow-auto">
        {/* ── VIEW 1: RESEARCH DASHBOARD ────────────────────────────────────── */}
        {activeTab === 'dashboard' && (
          <div className="space-y-6 max-w-7xl mx-auto">
            {/* Metric Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between text-slate-400 text-xs">
                  <span>DISCOVERED ENTITIES</span>
                  <RiBuildingLine className="w-4 h-4 text-teal-400" />
                </div>
                <div className="text-2xl font-bold text-white mt-2">
                  {stats.total_companies.toLocaleString()}
                </div>
                <div className="text-xs text-slate-400 mt-1">Staged in research DB</div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between text-slate-400 text-xs">
                  <span>CONTACTS EXTRACTED</span>
                  <RiUserLine className="w-4 h-4 text-blue-400" />
                </div>
                <div className="text-2xl font-bold text-white mt-2">
                  {stats.total_contacts.toLocaleString()}
                </div>
                <div className="text-xs text-slate-400 mt-1">Founders & Leadership</div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between text-slate-400 text-xs">
                  <span>PUBLIC EMAILS</span>
                  <RiMailLine className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold text-white mt-2">
                  {stats.emails_discovered.toLocaleString()}
                </div>
                <div className="text-xs text-emerald-400/90 mt-1 font-medium">
                  {stats.verified_valid} active verified
                </div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between text-slate-400 text-xs">
                  <span>APPROVED ENTITIES</span>
                  <RiCheckboxCircleLine className="w-4 h-4 text-purple-400" />
                </div>
                <div className="text-2xl font-bold text-white mt-2">
                  {stats.approved_companies.toLocaleString()}
                </div>
                <div className="text-xs text-slate-400 mt-1">Passed researcher review</div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <div className="flex items-center justify-between text-slate-400 text-xs">
                  <span>IMPORTED TO CRM</span>
                  <RiUserAddLine className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="text-2xl font-bold text-white mt-2">
                  {stats.imported_to_crm.toLocaleString()}
                </div>
                <div className="text-xs text-cyan-400/90 mt-1 font-medium">Active CRM Leads</div>
              </div>
            </div>

            {/* Quick Actions & Recent Jobs Banner */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left 2 cols: Recent Jobs */}
              <div className="lg:col-span-2 bg-slate-900/60 border border-slate-800/80 rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-white tracking-wide uppercase flex items-center gap-2">
                    <RiCompassDiscoverLine className="text-teal-400" /> Recent Research Jobs
                  </h3>
                  <button
                    onClick={() => setActiveTab('jobs')}
                    className="text-xs text-teal-400 hover:text-teal-300 font-medium flex items-center gap-1"
                  >
                    View All Jobs <RiArrowRightLine />
                  </button>
                </div>

                {jobs.length === 0 ? (
                  <div className="text-center py-10 text-slate-500 text-sm">
                    No research jobs created yet. Click "Start New Research" to run your first discovery batch!
                  </div>
                ) : (
                  <div className="divide-y divide-slate-800/70">
                    {jobs.slice(0, 4).map((j) => (
                      <div key={j.id} className="py-3.5 flex items-center justify-between">
                        <div>
                          <div className="text-sm font-medium text-white flex items-center gap-2">
                            {j.name}
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase ${
                                j.status === 'completed'
                                  ? 'bg-emerald-950 text-emerald-300 border border-emerald-800/50'
                                  : j.status === 'running'
                                  ? 'bg-blue-950 text-blue-300 border border-blue-800/50 animate-pulse'
                                  : 'bg-slate-800 text-slate-300'
                              }`}
                            >
                              {j.status}
                            </span>
                          </div>
                          <div className="text-xs text-slate-400 mt-0.5">
                            Target: {j.query_params?.city}, {j.query_params?.state} • {j.query_params?.industry}
                          </div>
                        </div>

                        <div className="flex items-center gap-4 text-xs text-right">
                          <div>
                            <span className="text-white font-semibold">{j.unique_companies}</span>
                            <span className="text-slate-400"> companies</span>
                          </div>
                          <div>
                            <span className="text-emerald-400 font-semibold">{j.verified_valid}</span>
                            <span className="text-slate-400"> verified</span>
                          </div>
                          <button
                            onClick={() => {
                              setSelectedJobFilter(j.id);
                              setActiveTab('results');
                            }}
                            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs transition"
                          >
                            Explore Results
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Right Col: Guided Pilot Callout */}
              <div className="bg-gradient-to-br from-slate-900 to-slate-900/40 border border-slate-800/80 rounded-xl p-6 flex flex-col justify-between">
                <div>
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-teal-950/80 text-teal-300 border border-teal-800/60 text-xs font-semibold mb-3">
                    <RiShieldCheckLine /> 100% Permitted Open Data
                  </div>
                  <h3 className="text-base font-bold text-white mb-2">
                    Austin Agency Discovery Engine
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Discovers genuine local businesses using Overture Maps Places, OpenStreetMap, and official website metadata. Strict extraction rules ensure <strong>zero hallucinated emails</strong>.
                  </p>
                  <div className="mt-4 space-y-2 text-xs text-slate-300">
                    <div className="flex items-center gap-2">
                      <RiCheckLine className="text-teal-400" /> Explainable 0–100 ICP Scoring
                    </div>
                    <div className="flex items-center gap-2">
                      <RiCheckLine className="text-teal-400" /> Native DNS, MX & Role Validation
                    </div>
                    <div className="flex items-center gap-2">
                      <RiCheckLine className="text-teal-400" /> Staging Area & Dedup Protection
                    </div>
                    <div className="flex items-center gap-2">
                      <RiCheckLine className="text-teal-400" /> One-Click Selective CRM Import
                    </div>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800">
                  <button
                    onClick={() => setActiveTab('new-job')}
                    className="w-full py-2 px-3 bg-teal-600 hover:bg-teal-500 text-white rounded text-xs font-semibold flex items-center justify-center gap-2 transition"
                  >
                    Configure New Discovery <RiArrowRightLine />
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── VIEW 2: NEW RESEARCH JOB FORM ─────────────────────────────────── */}
        {activeTab === 'new-job' && (
          <div className="max-w-3xl mx-auto bg-slate-900/60 border border-slate-800/80 rounded-xl p-8">
            <div className="mb-6">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <RiCompassDiscoverLine className="text-teal-400" /> Launch Prospect Discovery Job
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Configure your geographic target and vertical parameters. The research worker will discover companies, crawl official pages, verify emails, and stage results for review.
              </p>
            </div>

            <form onSubmit={handleCreateJob} className="space-y-5">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Research Job Name *
                </label>
                <input
                  type="text"
                  required
                  value={jobForm.name}
                  onChange={(e) => setJobForm({ ...jobForm, name: e.target.value })}
                  placeholder="e.g. Austin Web Design & Creative Agencies"
                  className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Country *</label>
                  <input
                    type="text"
                    required
                    value={jobForm.country}
                    onChange={(e) => setJobForm({ ...jobForm, country: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">State / Region</label>
                  <input
                    type="text"
                    value={jobForm.state}
                    onChange={(e) => setJobForm({ ...jobForm, state: e.target.value })}
                    placeholder="e.g. Texas"
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">City / Metro *</label>
                  <input
                    type="text"
                    required
                    value={jobForm.city}
                    onChange={(e) => setJobForm({ ...jobForm, city: e.target.value })}
                    placeholder="e.g. Austin"
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Industry / Vertical
                  </label>
                  <input
                    type="text"
                    value={jobForm.industry}
                    onChange={(e) => setJobForm({ ...jobForm, industry: e.target.value })}
                    placeholder="e.g. Web Design Agencies"
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Target Company Count
                  </label>
                  <input
                    type="number"
                    min="5"
                    max="1000"
                    value={jobForm.target_count}
                    onChange={(e) => setJobForm({ ...jobForm, target_count: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Business Keywords (comma-separated)
                </label>
                <input
                  type="text"
                  value={jobForm.keywords}
                  onChange={(e) => setJobForm({ ...jobForm, keywords: e.target.value })}
                  placeholder="e.g. web design, branding, digital agency, custom development"
                  className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded px-3 py-2 text-sm text-white outline-none"
                />
              </div>

              <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-3 text-xs text-slate-400 space-y-1">
                <div className="flex items-center gap-1.5 font-medium text-slate-300">
                  <RiInformationLine className="text-teal-400" /> Research Rules & Compliance
                </div>
                <p>
                  • Businesses are discovered from permitted open datasets (Overture Maps Places, OpenStreetMap).
                </p>
                <p>
                  • Official websites are crawled to extract public leadership contacts. <strong>No email addresses are ever invented.</strong>
                </p>
                <p>
                  • Extracted emails undergo native DNS/MX deliverability verification before review.
                </p>
              </div>

              <div className="pt-4 flex items-center justify-end gap-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setActiveTab('dashboard')}
                  className="px-4 py-2 border border-slate-800 hover:border-slate-700 bg-slate-900 text-slate-300 rounded text-xs font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingJob}
                  className="px-5 py-2 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white rounded text-xs font-semibold flex items-center gap-2 transition"
                >
                  {creatingJob ? (
                    'Launching Worker...'
                  ) : (
                    <>
                      <RiPlayLine /> Launch Research Job
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* ── VIEW 3 & 5: RESEARCH RESULTS & IMPORTED TABLE ─────────────────── */}
        {(activeTab === 'results' || activeTab === 'imported') && (
          <div className="space-y-4">
            {/* Filter Bar */}
            <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2 flex-1 min-w-[240px]">
                <div className="relative w-full max-w-sm">
                  <RiSearchLine className="absolute left-3 top-2.5 text-slate-500" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search company, contact, domain..."
                    className="w-full bg-slate-950 border border-slate-800 focus:border-teal-500 rounded pl-9 pr-3 py-1.5 text-xs text-white outline-none"
                  />
                </div>
              </div>

              <div className="flex items-center flex-wrap gap-2">
                {/* Email Filter */}
                <select
                  value={filterEmailStatus}
                  onChange={(e) => setFilterEmailStatus(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 outline-none"
                >
                  <option value="all">Email: All</option>
                  <option value="has_email">Has Verified Email</option>
                  <option value="missing">Missing Email</option>
                </select>

                {/* Verification Filter */}
                <select
                  value={filterVerification}
                  onChange={(e) => setFilterVerification(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 outline-none"
                >
                  <option value="all">Verification: All</option>
                  <option value="domain_validated">Domain Validated</option>
                  <option value="valid">Mailbox Valid</option>
                  <option value="risky">Risky / Catch-All</option>
                  <option value="invalid">Invalid</option>
                  <option value="missing">Missing</option>
                </select>

                {/* Min ICP Score */}
                <select
                  value={filterMinIcp}
                  onChange={(e) => setFilterMinIcp(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 outline-none"
                >
                  <option value="all">ICP: All Scores</option>
                  <option value="90">ICP: 90+ Top Tier</option>
                  <option value="80">ICP: 80+ Strong Match</option>
                  <option value="70">ICP: 70+ Moderate</option>
                </select>

                {/* Review Status (if not on 'imported' tab) */}
                {activeTab !== 'imported' && (
                  <select
                    value={filterReviewStatus}
                    onChange={(e) => setFilterReviewStatus(e.target.value)}
                    className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 outline-none"
                  >
                    <option value="all">Status: All</option>
                    <option value="pending">Pending Review</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                  </select>
                )}

                {/* Clear filters */}
                {(search || filterCity || filterEmailStatus !== 'all' || filterVerification !== 'all' || filterMinIcp !== 'all' || selectedJobFilter) && (
                  <button
                    onClick={() => {
                      setSearch('');
                      setFilterCity('');
                      setFilterIndustry('');
                      setFilterEmailStatus('all');
                      setFilterVerification('all');
                      setFilterMinIcp('all');
                      setFilterReviewStatus('all');
                      setSelectedJobFilter(null);
                    }}
                    className="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded font-medium transition"
                  >
                    Clear Filters
                  </button>
                )}
              </div>
            </div>

            {/* Bulk Action Bar (when selected) */}
            {selectedContactIds.length > 0 && (
              <div className="bg-teal-950/60 border border-teal-800/80 rounded-xl px-4 py-3 flex items-center justify-between text-xs animate-fadeIn">
                <div className="flex items-center gap-2 text-teal-300 font-medium">
                  <RiCheckboxCircleLine className="w-4 h-4" />
                  <span>{selectedContactIds.length} contacts selected for action</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleBulkStatus('approved')}
                    className="px-3 py-1.5 bg-slate-900 border border-slate-700 hover:bg-slate-800 text-slate-200 rounded font-medium transition"
                  >
                    Approve Selected
                  </button>
                  <button
                    onClick={() => handleBulkStatus('rejected')}
                    className="px-3 py-1.5 bg-slate-900 border border-slate-700 hover:bg-slate-800 text-rose-300 rounded font-medium transition"
                  >
                    Reject Selected
                  </button>
                  <button
                    onClick={handleBulkPromote}
                    className="px-4 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded font-semibold shadow-sm transition flex items-center gap-1.5"
                  >
                    <RiUserAddLine /> Add {selectedContactIds.length} to Prospects
                  </button>
                </div>
              </div>
            )}

            {/* Results Table */}
            <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold tracking-wider uppercase">
                      <th className="py-3 px-3 w-10 text-center">
                        <input
                          type="checkbox"
                          onChange={toggleSelectAll}
                          checked={
                            results.length > 0 &&
                            results
                              .filter((r) => r.primary_contact && r.primary_contact.email)
                              .every((r) => selectedContactIds.includes(r.primary_contact.id))
                          }
                          className="rounded border-slate-700 bg-slate-900 text-teal-500 focus:ring-0 cursor-pointer"
                        />
                      </th>
                      <th className="py-3 px-3">Company</th>
                      <th className="py-3 px-3">Contact</th>
                      <th className="py-3 px-3">Email</th>
                      <th className="py-3 px-3">Phone</th>
                      <th className="py-3 px-3">Location</th>
                      <th className="py-3 px-3">Industry</th>
                      <th className="py-3 px-3">Verification</th>
                      <th className="py-3 px-3 text-center">ICP Score</th>
                      <th className="py-3 px-3">Status</th>
                      <th className="py-3 px-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {resultsLoading ? (
                      <tr>
                        <td colSpan="11" className="text-center py-12 text-slate-400">
                          Loading research records...
                        </td>
                      </tr>
                    ) : results.length === 0 ? (
                      <tr>
                        <td colSpan="11" className="text-center py-12 text-slate-500">
                          No research results found matching your filters.
                        </td>
                      </tr>
                    ) : (
                      results.map((c) => {
                        const pc = c.primary_contact || {};
                        const isSelected = pc.id && selectedContactIds.includes(pc.id);

                        return (
                          <tr
                            key={c.id}
                            className={`hover:bg-slate-800/30 transition ${
                              isSelected ? 'bg-teal-950/20' : ''
                            }`}
                          >
                            <td className="py-3 px-3 text-center">
                              {pc.email ? (
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleSelectContact(pc.id)}
                                  className="rounded border-slate-700 bg-slate-900 text-teal-500 focus:ring-0 cursor-pointer"
                                />
                              ) : (
                                <span className="text-slate-600">-</span>
                              )}
                            </td>

                            {/* Company */}
                            <td className="py-3 px-3 font-medium text-white max-w-[180px]">
                              <div className="truncate font-semibold">{c.name}</div>
                              {c.website ? (
                                <a
                                  href={c.website}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-[11px] text-teal-400/90 hover:text-teal-300 flex items-center gap-1 truncate"
                                >
                                  {c.domain || 'website'} <RiExternalLinkLine className="w-2.5 h-2.5" />
                                </a>
                              ) : (
                                <span className="text-[11px] text-slate-500">No website</span>
                              )}
                            </td>

                            {/* Contact */}
                            <td className="py-3 px-3 max-w-[160px]">
                              <div className="font-medium text-slate-200 truncate">
                                {pc.name || 'Unknown Contact'}
                              </div>
                              <div className="text-[11px] text-slate-400 truncate">
                                {pc.role || 'Representative'}
                              </div>
                            </td>

                            {/* Email */}
                            <td className="py-3 px-3 max-w-[180px]">
                              {pc.email ? (
                                <span className="text-slate-200 font-mono text-[11px] truncate block select-all">
                                  {pc.email}
                                </span>
                              ) : (
                                <span className="text-slate-500 text-[11px] italic">Missing</span>
                              )}
                            </td>

                            {/* Phone */}
                            <td className="py-3 px-3 text-slate-300 text-[11px] whitespace-nowrap">
                              {c.phone || pc.phone || '-'}
                            </td>

                            {/* Location */}
                            <td className="py-3 px-3 text-slate-300 text-[11px] whitespace-nowrap">
                              {c.city}, {c.state}
                            </td>

                            {/* Industry */}
                            <td className="py-3 px-3 text-slate-300 text-[11px] max-w-[140px] truncate">
                              {c.category || '-'}
                            </td>

                            {/* Verification */}
                            <td className="py-3 px-3 whitespace-nowrap">
                              {renderVerificationBadge(pc.email_verification_status)}
                            </td>

                            {/* ICP Score */}
                            <td className="py-3 px-3 text-center whitespace-nowrap">
                              {renderIcpBadge(c.icp_score)}
                            </td>

                            {/* Review Status */}
                            <td className="py-3 px-3 whitespace-nowrap">
                              {renderReviewBadge(c.review_status, c.promoted_to_lead_id)}
                            </td>

                            {/* Actions */}
                            <td className="py-3 px-3 text-right whitespace-nowrap space-x-1">
                              <button
                                onClick={() => openCompanyDetail(c.id)}
                                className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-[11px] font-medium transition"
                              >
                                Review
                              </button>

                              {pc.email && !c.promoted_to_lead_id && (
                                <button
                                  onClick={() => handlePromoteContact(pc.id)}
                                  className="px-2.5 py-1 bg-teal-600/90 hover:bg-teal-500 text-white rounded text-[11px] font-semibold transition"
                                >
                                  Add to Prospects
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="border-t border-slate-800 px-4 py-3 flex items-center justify-between text-xs text-slate-400">
                <div>
                  Showing {results.length} of {totalResults} staged entities
                </div>
                <div className="flex items-center gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="px-3 py-1 bg-slate-900 border border-slate-800 hover:bg-slate-800 disabled:opacity-40 rounded text-slate-300"
                  >
                    Previous
                  </button>
                  <span className="text-slate-300 font-medium">Page {page}</span>
                  <button
                    disabled={results.length < limit}
                    onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 bg-slate-900 border border-slate-800 hover:bg-slate-800 disabled:opacity-40 rounded text-slate-300"
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── VIEW 4: RESEARCH JOBS ─────────────────────────────────────────── */}
        {activeTab === 'jobs' && (
          <div className="space-y-4 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <RiCompassDiscoverLine className="text-teal-400" /> Research Jobs & Background Pipelines
              </h2>
              <button
                onClick={() => setActiveTab('new-job')}
                className="px-3 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded text-xs font-semibold flex items-center gap-1.5 transition"
              >
                <RiPlayLine /> Launch New Job
              </button>
            </div>

            <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden shadow-sm">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-950/70 border-b border-slate-800 text-slate-400 font-semibold tracking-wider uppercase">
                    <th className="py-3 px-4">Job Name</th>
                    <th className="py-3 px-4">Target Parameters</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Discovered</th>
                    <th className="py-3 px-4">Unique Companies</th>
                    <th className="py-3 px-4">Emails Extracted</th>
                    <th className="py-3 px-4">Verified Valid</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {jobs.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="text-center py-12 text-slate-500">
                        No research jobs recorded yet.
                      </td>
                    </tr>
                  ) : (
                    jobs.map((j) => (
                      <tr key={j.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3.5 px-4 font-semibold text-white">
                          <div>{j.name}</div>
                          <div className="text-[11px] text-slate-400 font-normal">
                            Job #{j.id} • {j.created_at ? new Date(j.created_at).toLocaleDateString() : ''}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-slate-300">
                          <div>
                            {j.query_params?.city}, {j.query_params?.state} ({j.query_params?.country})
                          </div>
                          <div className="text-[11px] text-slate-400">
                            {j.query_params?.industry} • Target: {j.query_params?.target_count}
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase ${
                              j.status === 'completed'
                                ? 'bg-emerald-950/70 text-emerald-300 border border-emerald-800/60'
                                : j.status === 'running'
                                ? 'bg-blue-950/70 text-blue-300 border border-blue-800/60 animate-pulse'
                                : j.status === 'paused'
                                ? 'bg-amber-950/70 text-amber-300 border border-amber-800/60'
                                : 'bg-slate-800 text-slate-300'
                            }`}
                          >
                            {j.status}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-slate-200">
                          {j.total_discovered}
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-white">
                          {j.unique_companies}
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-emerald-400">
                          {j.emails_found}
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-teal-300">
                          {j.verified_valid}
                        </td>
                        <td className="py-3.5 px-4 text-right space-x-1.5">
                          {j.status === 'running' && (
                            <button
                              onClick={() => handlePauseJob(j.id)}
                              className="px-2 py-1 bg-amber-900/60 hover:bg-amber-800 text-amber-200 rounded text-[11px] font-medium transition"
                            >
                              Pause
                            </button>
                          )}
                          {j.status === 'paused' && (
                            <button
                              onClick={() => handleResumeJob(j.id)}
                              className="px-2 py-1 bg-emerald-900/60 hover:bg-emerald-800 text-emerald-200 rounded text-[11px] font-medium transition"
                            >
                              Resume
                            </button>
                          )}
                          {['running', 'paused'].includes(j.status) && (
                            <button
                              onClick={() => handleCancelJob(j.id)}
                              className="px-2 py-1 bg-rose-900/60 hover:bg-rose-800 text-rose-200 rounded text-[11px] font-medium transition"
                            >
                              Cancel
                            </button>
                          )}
                          <button
                            onClick={() => {
                              setSelectedJobFilter(j.id);
                              setActiveTab('results');
                            }}
                            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-[11px] font-medium transition"
                          >
                            View Results
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* ── COMPANY & CONTACT DETAIL MODAL ──────────────────────────────────── */}
      {detailCompany && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-3xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-fadeIn">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  {detailCompany.name}
                  {renderIcpBadge(detailCompany.icp_score)}
                  {renderReviewBadge(detailCompany.review_status, detailCompany.promoted_to_lead_id)}
                </h3>
                <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-3">
                  {detailCompany.website && (
                    <a
                      href={detailCompany.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-teal-400 hover:underline flex items-center gap-1"
                    >
                      {detailCompany.domain || detailCompany.website} <RiExternalLinkLine className="w-3 h-3" />
                    </a>
                  )}
                  <span>•</span>
                  <span>{detailCompany.city}, {detailCompany.state}</span>
                  <span>•</span>
                  <span>Source: {detailCompany.source}</span>
                </div>
              </div>

              <button
                onClick={() => setDetailCompany(null)}
                className="p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <RiCloseLine className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-6 text-xs text-slate-300">
              {/* Description */}
              {detailCompany.description && (
                <div>
                  <h4 className="font-semibold text-slate-400 uppercase tracking-wider text-[11px] mb-1">
                    Company Overview
                  </h4>
                  <p className="bg-slate-950/60 p-3 rounded border border-slate-800 text-slate-300 leading-relaxed">
                    {detailCompany.description}
                  </p>
                </div>
              )}

              {/* Explainable ICP Reasons */}
              <div>
                <h4 className="font-semibold text-slate-400 uppercase tracking-wider text-[11px] mb-1.5 flex items-center gap-1.5">
                  <RiShieldCheckLine className="text-teal-400" /> Explainable ICP Targeting Criteria
                </h4>
                <div className="bg-slate-950/60 p-3 rounded border border-slate-800 space-y-1.5">
                  {(detailCompany.icp_reasons || []).map((reason, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      <RiCheckLine className="text-teal-400 shrink-0 mt-0.5" />
                      <span>{reason}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Contacts Roster */}
              <div>
                <h4 className="font-semibold text-slate-400 uppercase tracking-wider text-[11px] mb-2 flex items-center justify-between">
                  <span>Discovered Leadership Contacts ({detailCompany.contacts?.length || 0})</span>
                  <span className="text-slate-500 font-normal">Strict: No synthetic / guessed emails</span>
                </h4>

                <div className="space-y-3">
                  {(detailCompany.contacts || []).map((ct) => (
                    <div
                      key={ct.id}
                      className="bg-slate-950 border border-slate-800 rounded-lg p-3.5 flex flex-col md:flex-row md:items-center justify-between gap-3"
                    >
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm text-white">{ct.name}</span>
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                            {ct.role}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-3 text-slate-400">
                          {ct.email ? (
                            <span className="font-mono text-teal-300 flex items-center gap-1">
                              <RiMailLine className="w-3 h-3" /> {ct.email}
                            </span>
                          ) : (
                            <span className="text-slate-500 italic">No email discovered</span>
                          )}
                          {ct.phone && (
                            <span className="flex items-center gap-1">
                              <RiPhoneLine className="w-3 h-3" /> {ct.phone}
                            </span>
                          )}
                          {ct.linkedin_url && (
                            <a
                              href={ct.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-400 hover:underline flex items-center gap-1"
                            >
                              <RiLinkedinBoxLine className="w-3.5 h-3.5" /> LinkedIn
                            </a>
                          )}
                        </div>

                        {/* Verification & Provenance details */}
                        <div className="pt-1.5 flex flex-wrap items-center gap-2">
                          {renderVerificationBadge(ct.email_verification_status)}
                          {ct.field_provenance?.email?.snippet && (
                            <span className="text-[10px] text-slate-500">
                              Provenance: {ct.field_provenance.email.snippet}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Action */}
                      <div className="shrink-0">
                        {ct.email && !detailCompany.promoted_to_lead_id ? (
                          <button
                            onClick={() => handlePromoteContact(ct.id)}
                            className="w-full md:w-auto px-3.5 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded font-semibold text-xs shadow-sm flex items-center justify-center gap-1.5 transition"
                          >
                            <RiUserAddLine /> Add to Prospects
                          </button>
                        ) : detailCompany.promoted_to_lead_id ? (
                          <span className="text-xs text-blue-400 font-medium">
                            Imported as Lead #{detailCompany.promoted_to_lead_id}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3.5 border-t border-slate-800 bg-slate-950/70 flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <span className="text-slate-400">Review Status:</span>
                <button
                  onClick={() => handleUpdateStatus(detailCompany.id, 'approved')}
                  className={`px-3 py-1 rounded font-medium transition ${
                    detailCompany.review_status === 'approved'
                      ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  Approve
                </button>
                <button
                  onClick={() => handleUpdateStatus(detailCompany.id, 'rejected')}
                  className={`px-3 py-1 rounded font-medium transition ${
                    detailCompany.review_status === 'rejected'
                      ? 'bg-rose-950 text-rose-300 border border-rose-800'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  Reject
                </button>
              </div>

              <button
                onClick={() => setDetailCompany(null)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded font-medium transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

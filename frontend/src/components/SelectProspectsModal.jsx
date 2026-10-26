import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';
import { useNotify } from '../context/NotificationContext';
import ErrorBoundary from './ErrorBoundary';
import { getVerificationBadge } from './LeadVerificationModal';
import {
  RiCloseLine,
  RiSearchLine,
  RiFilterLine,
  RiUserSharedLine,
  RiArrowLeftLine,
  RiArrowRightLine,
  RiBuildingLine,
  RiMapPinLine,
  RiGlobalLine,
  RiCompass3Line,
  RiBriefcaseLine,
  RiAlertLine,
  RiRefreshLine,
} from 'react-icons/ri';

export default function SelectProspectsModal({
  isOpen,
  onClose,
  campaignId,
  campaignName = '',
  isCampaignPaused = false,
  onEnrolled,
}) {
  const notify = useNotify();

  // Step 1 = select prospects, Step 2 = review & confirmation summary
  const [step, setStep] = useState(1);

  // Filter values
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [country, setCountry] = useState('');
  const [state, setState] = useState('');
  const [industry, setIndustry] = useState('');
  const [verificationStatus, setVerificationStatus] = useState('');
  const [pipelineStatus, setPipelineStatus] = useState('');
  const [excludeCurrentCampaign, setExcludeCurrentCampaign] = useState(true);

  // Debounce search input by 250ms to prevent excessive queries
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(search);
    }, 250);
    return () => clearTimeout(handler);
  }, [search]);

  // Dynamic Facets & Counts from backend
  const [facets, setFacets] = useState({
    total_matching: 0,
    all_countries_count: 0,
    state_all_count: 0,
    industry_all_count: 0,
    countries: [],
    states: [],
    industries: [],
  });
  const [facetsLoading, setFacetsLoading] = useState(false);

  // Pipeline statuses from filter-options for secondary dropdown
  const [pipelineStatuses, setPipelineStatuses] = useState([]);

  // Prospects list
  const [prospects, setProspects] = useState([]);
  const [loading, setLoading] = useState(false);

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Selection (Maintained across pagination and filter changes)
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selectAllFiltered, setSelectAllFiltered] = useState(false);

  // Step 2 Summary State
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summary, setSummary] = useState(null);
  const [skipOtherActive, setSkipOtherActive] = useState(false);
  const [enrolling, setEnrolling] = useState(false);

  // Initial reset on modal open
  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setSelectedIds(new Set());
      setSelectAllFiltered(false);
      setSummary(null);
      setPage(1);

      api
        .get('/leads/filter-options')
        .then((res) => {
          if (res?.pipeline_statuses) {
            setPipelineStatuses(res.pipeline_statuses);
          }
        })
        .catch(() => {});
    }
  }, [isOpen]);

  // Fetch dynamic facet counts from backend
  const loadFacets = useCallback(async () => {
    if (!isOpen) return;
    setFacetsLoading(true);
    try {
      const params = new URLSearchParams();
      if (debouncedSearch.trim()) params.set('q', debouncedSearch.trim());
      if (country) params.set('country', country);
      if (state) params.set('state', state);
      if (industry) params.set('industry', industry);
      if (pipelineStatus) params.set('pipeline_status', pipelineStatus);
      if (verificationStatus) params.set('email_verification_status', verificationStatus);
      if (excludeCurrentCampaign && campaignId) params.set('exclude_campaign_id', String(campaignId));

      const res = await api.get(`/leads/facet-counts?${params.toString()}`);
      if (res) {
        setFacets(res);
      }
    } catch (err) {
      console.error('Failed to load facet counts:', err);
    } finally {
      setFacetsLoading(false);
    }
  }, [isOpen, debouncedSearch, country, state, industry, pipelineStatus, verificationStatus, excludeCurrentCampaign, campaignId]);

  // Fetch prospects list from backend
  const loadProspects = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (debouncedSearch.trim()) params.set('q', debouncedSearch.trim());
      if (country) params.set('country', country);
      if (state) params.set('state', state);
      if (industry) params.set('industry', industry);
      if (pipelineStatus) params.set('pipeline_status', pipelineStatus);
      if (verificationStatus) params.set('email_verification_status', verificationStatus);
      if (excludeCurrentCampaign && campaignId) params.set('exclude_campaign_id', String(campaignId));

      const res = await api.get(`/leads?${params.toString()}`);
      setProspects(Array.isArray(res) ? res : []);
      setPage(1);
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to load prospects' });
    } finally {
      setLoading(false);
    }
  }, [isOpen, debouncedSearch, country, state, industry, pipelineStatus, verificationStatus, excludeCurrentCampaign, campaignId, notify]);

  // Load facets and prospects whenever active filters change
  useEffect(() => {
    if (isOpen) {
      loadFacets();
      loadProspects();
    }
  }, [isOpen, loadFacets, loadProspects]);

  // Handle Country selection change: automatically reset State
  const handleCountryChange = (newCountry) => {
    setCountry(newCountry);
    setState(''); // Reset selected state when country changes
  };

  // Reset all filters
  const handleResetFilters = () => {
    setSearch('');
    setDebouncedSearch('');
    setCountry('');
    setState('');
    setIndustry('');
    setVerificationStatus('');
    setPipelineStatus('');
  };

  const hasActiveFilters = Boolean(
    debouncedSearch || country || state || industry || verificationStatus || pipelineStatus
  );

  // Total matching count
  const totalMatching = facets.total_matching ?? prospects.length;

  // Pagination calculation
  const totalPages = Math.ceil(prospects.length / pageSize) || 1;
  const paginatedProspects = useMemo(() => {
    const start = (page - 1) * pageSize;
    return prospects.slice(start, start + pageSize);
  }, [prospects, page, pageSize]);

  // Check if all rows on current page are selected
  const allCurrentPageSelected = useMemo(() => {
    if (!paginatedProspects.length) return false;
    return paginatedProspects.every((p) => selectedIds.has(p.id));
  }, [paginatedProspects, selectedIds]);

  // Handle single row toggle
  const toggleSelectOne = (id) => {
    setSelectAllFiltered(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Toggle select all on current page
  const toggleSelectCurrentPage = () => {
    setSelectAllFiltered(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allCurrentPageSelected) {
        paginatedProspects.forEach((p) => next.delete(p.id));
      } else {
        paginatedProspects.forEach((p) => next.add(p.id));
      }
      return next;
    });
  };

  // Select all filtered prospects across all pages
  const handleSelectAllFiltered = () => {
    const allIds = new Set(prospects.map((p) => p.id));
    setSelectedIds(allIds);
    setSelectAllFiltered(true);
  };

  // Clear selections
  const handleClearSelection = () => {
    setSelectedIds(new Set());
    setSelectAllFiltered(false);
  };

  // Proceed to Step 2: Confirmation Summary & Safeguards Check (Dry Run)
  const handleProceedToReview = async () => {
    if (!selectedIds.size && !selectAllFiltered) return;

    setSummaryLoading(true);
    setStep(2);
    try {
      const payload = {
        campaign_id: campaignId,
        lead_ids: [...selectedIds],
        select_all_filtered: selectAllFiltered,
        filters: selectAllFiltered
          ? {
              q: debouncedSearch.trim() || undefined,
              country: country || undefined,
              state: state || undefined,
              industry: industry || undefined,
              pipeline_status: pipelineStatus || undefined,
              email_verification_status: verificationStatus || undefined,
              exclude_campaign_id: excludeCurrentCampaign ? campaignId : undefined,
            }
          : undefined,
        dry_run: true,
      };

      const res = await api.post('/leads/bulk-campaign-assign', payload);
      if (res && res.summary) {
        setSummary(res.summary);
      }
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to generate enrollment preview' });
      setStep(1);
    } finally {
      setSummaryLoading(false);
    }
  };

  // Confirm and enroll prospects
  const handleConfirmEnroll = async () => {
    setEnrolling(true);
    try {
      const payload = {
        campaign_id: campaignId,
        lead_ids: [...selectedIds],
        select_all_filtered: selectAllFiltered,
        filters: selectAllFiltered
          ? {
              q: debouncedSearch.trim() || undefined,
              country: country || undefined,
              state: state || undefined,
              industry: industry || undefined,
              pipeline_status: pipelineStatus || undefined,
              email_verification_status: verificationStatus || undefined,
              exclude_campaign_id: excludeCurrentCampaign ? campaignId : undefined,
            }
          : undefined,
        dry_run: false,
        skip_other_active: skipOtherActive,
      };

      const res = await api.post('/leads/bulk-campaign-assign', payload);

      notify({
        type: 'success',
        message: `Successfully enrolled ${res.assigned} prospect(s) into campaign "${campaignName || 'Campaign'}".`,
      });

      if (onEnrolled) {
        onEnrolled(res);
      }
      onClose();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to enroll prospects' });
    } finally {
      setEnrolling(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-5xl rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col max-h-[92vh] overflow-hidden">
        <ErrorBoundary
          title="Prospect Selection Error"
          description="Could not render the prospect selection list. Your prospects data is safe."
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-800">
                <RiUserSharedLine size={20} />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white">
                  {step === 1 ? 'Select Existing Prospects' : 'Review & Confirm Enrollment'}
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Target Campaign: <span className="font-semibold text-teal-600 dark:text-teal-400">{campaignName}</span>
                  {isCampaignPaused && (
                    <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                      Paused Campaign (Safe Mode)
                    </span>
                  )}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <RiCloseLine size={20} />
            </button>
          </div>

          {/* STEP 1: BROWSE & SELECT PROSPECTS */}
          {step === 1 && (
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Filter Section */}
              <div className="p-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-3 shrink-0">
                {/* 1. Full-width Search Input */}
                <div className="relative">
                  <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search prospects by company, contact name, or email..."
                    className="w-full pl-9 pr-8 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors"
                  />
                  {search && (
                    <button
                      onClick={() => {
                        setSearch('');
                        setDebouncedSearch('');
                      }}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-0.5 rounded"
                      title="Clear search"
                    >
                      <RiCloseLine size={14} />
                    </button>
                  )}
                </div>

                {/* 2. Primary Dropdown Filters Row: Country, Dependent State, Industry */}
                <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
                  {/* Country Dropdown with Dynamic Prospect Counts */}
                  <div className="relative">
                    <select
                      value={country}
                      onChange={(e) => handleCountryChange(e.target.value)}
                      className="w-full py-1.5 pl-2.5 pr-6 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 font-medium truncate cursor-pointer"
                      title="Filter by country"
                    >
                      <option value="">
                        All Countries ({facets.all_countries_count || prospects.length})
                      </option>
                      {facets.countries.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name} ({c.count})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Dependent State / Region Dropdown with Dynamic Counts */}
                  <div className="relative">
                    <select
                      value={state}
                      onChange={(e) => setState(e.target.value)}
                      disabled={Boolean(country && facets.states.length === 0)}
                      className="w-full py-1.5 pl-2.5 pr-6 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 font-medium truncate cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      title={
                        country && facets.states.length === 0
                          ? 'No states available for this country'
                          : 'Filter by state / region'
                      }
                    >
                      {country && facets.states.length === 0 ? (
                        <option value="">No states available</option>
                      ) : (
                        <>
                          <option value="">
                            All States ({facets.state_all_count || prospects.length})
                          </option>
                          {facets.states.map((s) => (
                            <option key={s.name} value={s.name}>
                              {s.name} ({s.count})
                            </option>
                          ))}
                        </>
                      )}
                    </select>
                  </div>

                  {/* Industry Dropdown with Dynamic Counts */}
                  <div className="relative">
                    <select
                      value={industry}
                      onChange={(e) => setIndustry(e.target.value)}
                      className="w-full py-1.5 pl-2.5 pr-6 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 font-medium truncate cursor-pointer"
                      title="Filter by industry"
                    >
                      <option value="">
                        All Industries ({facets.industry_all_count || prospects.length})
                      </option>
                      {facets.industries.map((ind) => (
                        <option key={ind.name} value={ind.name}>
                          {ind.name} ({ind.count})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Compact Verification Status Dropdown */}
                  <div className="relative">
                    <select
                      value={verificationStatus}
                      onChange={(e) => setVerificationStatus(e.target.value)}
                      className="w-full py-1.5 pl-2.5 pr-6 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 truncate cursor-pointer"
                      title="Filter by email verification status"
                    >
                      <option value="">Verification: All Statuses</option>
                      <option value="valid">Valid (Pass)</option>
                      <option value="domain_validated">Domain Validated (Pass)</option>
                      <option value="risky">Risky (Needs Review)</option>
                      <option value="unknown">Unknown (Needs Review)</option>
                      <option value="catch_all">Catch-All (Needs Review)</option>
                      <option value="invalid">Invalid (Blocked)</option>
                      <option value="unverified">Unverified (Null)</option>
                    </select>
                  </div>
                </div>

                {/* Exclude Toggle & Reset Controls */}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 text-xs">
                  <div className="flex items-center gap-3">
                    {pipelineStatuses.length > 0 && (
                      <select
                        value={pipelineStatus}
                        onChange={(e) => setPipelineStatus(e.target.value)}
                        className="py-1 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 capitalize"
                      >
                        <option value="">Pipeline: All Stages</option>
                        {pipelineStatuses.map((p) => (
                          <option key={p} value={p}>
                            {p.replace(/_/g, ' ')}
                          </option>
                        ))}
                      </select>
                    )}

                    {hasActiveFilters && (
                      <button
                        type="button"
                        onClick={handleResetFilters}
                        className="inline-flex items-center gap-1 text-[11px] text-teal-600 dark:text-teal-400 hover:underline font-medium cursor-pointer"
                      >
                        <RiRefreshLine size={12} />
                        Reset filters
                      </button>
                    )}
                  </div>

                  <label className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-300 select-none cursor-pointer">
                    <input
                      type="checkbox"
                      checked={excludeCurrentCampaign}
                      onChange={(e) => setExcludeCurrentCampaign(e.target.checked)}
                      className="rounded text-teal-600 focus:ring-teal-500"
                    >
                    </input>
                    <span>Exclude already enrolled in this campaign</span>
                  </label>
                </div>

                {/* 3. Combined Matching Prospects Count Banner */}
                <div className="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-100/90 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 dark:text-white">
                      Showing {totalMatching} matching prospect{totalMatching !== 1 ? 's' : ''}
                    </span>
                    {facetsLoading && (
                      <span className="w-3 h-3 border border-teal-500 border-t-transparent rounded-full animate-spin ml-1" />
                    )}
                  </div>

                  {/* Multi-selection Summary on Banner */}
                  <div className="flex items-center gap-2">
                    {selectedIds.size > 0 ? (
                      <span className="inline-flex items-center gap-1 font-medium text-teal-600 dark:text-teal-400">
                        {selectedIds.size} prospect{selectedIds.size !== 1 ? 's' : ''} selected
                      </span>
                    ) : (
                      <span className="text-slate-400 text-[11px]">0 selected</span>
                    )}
                  </div>
                </div>

                {/* Select All Filtered Banner */}
                {allCurrentPageSelected && totalMatching > paginatedProspects.length && (
                  <div className="bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 px-3 py-2 rounded-lg flex items-center justify-between text-xs text-teal-800 dark:text-teal-200 animate-fade-in">
                    <span>
                      All <strong>{paginatedProspects.length}</strong> prospects on this page are selected.
                    </span>
                    {!selectAllFiltered ? (
                      <button
                        onClick={handleSelectAllFiltered}
                        className="font-semibold underline hover:text-teal-900 dark:hover:text-teal-100 ml-2 cursor-pointer"
                      >
                        Select all {totalMatching} prospects matching current filters
                      </button>
                    ) : (
                      <span className="font-semibold text-teal-700 dark:text-teal-300">
                        ✓ All {totalMatching} filtered prospects selected
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Prospects Table */}
              <div className="flex-1 overflow-y-auto">
                {loading ? (
                  <div className="p-12 text-center text-slate-400 text-xs flex flex-col items-center gap-2">
                    <div className="w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                    Loading prospects...
                  </div>
                ) : prospects.length === 0 ? (
                  <div className="p-12 text-center text-slate-400 text-xs">
                    No prospects found matching your search and filter criteria.
                  </div>
                ) : (
                  <table className="w-full text-left text-xs border-collapse">
                    <thead className="sticky top-0 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-xs text-slate-600 dark:text-slate-300 font-semibold border-b border-slate-200 dark:border-slate-700 z-10">
                      <tr>
                        <th className="py-2.5 px-3 w-10 text-center">
                          <input
                            type="checkbox"
                            checked={allCurrentPageSelected}
                            onChange={toggleSelectCurrentPage}
                            className="rounded text-teal-600 focus:ring-teal-500 cursor-pointer"
                          />
                        </th>
                        <th className="py-2.5 px-3">Prospect</th>
                        <th className="py-2.5 px-3">Company & Industry</th>
                        <th className="py-2.5 px-3">Location (City, State, Country)</th>
                        <th className="py-2.5 px-3">Verification</th>
                        <th className="py-2.5 px-3">Campaign Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {paginatedProspects.map((lead) => {
                        const isSelected = selectedIds.has(lead.id);

                        // Check if already in THIS campaign
                        const inThisCampaign = lead.campaigns?.some((c) => String(c.campaign_id) === String(campaignId));

                        // Check if active in OTHER campaigns
                        const otherActiveCampaigns = (lead.campaigns || []).filter(
                          (c) =>
                            String(c.campaign_id) !== String(campaignId) &&
                            !c.campaign_paused &&
                            ['active', 'contacted'].includes(c.status)
                        );

                        // Get verification badge config
                        const isRole = Boolean(lead.email_verification_result?.is_role_account);
                        const isApproved = Boolean(
                          lead.email_verification_result?.approved || lead.email_verification_result?.review_approved
                        );

                        // Format state
                        const leadState = lead.custom_data?.state || '';
                        const locationParts = [lead.city, leadState, lead.country].filter(Boolean);

                        return (
                          <tr
                            key={lead.id}
                            className={`hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors ${
                              isSelected ? 'bg-teal-50/40 dark:bg-teal-950/20' : ''
                            }`}
                          >
                            <td className="py-2 px-3 text-center">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelectOne(lead.id)}
                                className="rounded text-teal-600 focus:ring-teal-500 cursor-pointer"
                              />
                            </td>
                            <td className="py-2 px-3">
                              <div className="font-medium text-slate-800 dark:text-slate-100">
                                {lead.name || 'Unnamed Prospect'}
                              </div>
                              <div className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                                {lead.email}
                              </div>
                            </td>
                            <td className="py-2 px-3">
                              <div className="text-slate-700 dark:text-slate-200">
                                {lead.company ? (
                                  <span className="inline-flex items-center gap-1 font-medium">
                                    <RiBuildingLine size={12} className="text-slate-400" />
                                    {lead.company}
                                  </span>
                                ) : (
                                  <span className="text-slate-400">—</span>
                                )}
                              </div>
                              {lead.industry && (
                                <div className="text-[10px] text-teal-600 dark:text-teal-400 font-medium truncate max-w-[200px]">
                                  {lead.industry}
                                </div>
                              )}
                            </td>
                            <td className="py-2 px-3">
                              <div className="text-[11px] text-slate-600 dark:text-slate-300">
                                {locationParts.length > 0 ? (
                                  <span className="inline-flex items-center gap-1">
                                    <RiMapPinLine size={11} className="text-slate-400" />
                                    {locationParts.join(', ')}
                                  </span>
                                ) : (
                                  <span className="text-slate-400">—</span>
                                )}
                              </div>
                            </td>
                            <td className="py-2 px-3">
                              {getVerificationBadge(lead.email_verification_status, isRole, null, isApproved)}
                            </td>
                            <td className="py-2 px-3">
                              <div className="flex flex-wrap gap-1 items-center">
                                {inThisCampaign && (
                                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                                    Already Enrolled
                                  </span>
                                )}
                                {otherActiveCampaigns.map((c) => (
                                  <span
                                    key={c.campaign_id}
                                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                                    title={`Enrolled in active campaign "${c.campaign_name}"`}
                                  >
                                    <RiAlertLine size={10} />
                                    Active in: {c.campaign_name}
                                  </span>
                                ))}
                                {!inThisCampaign && otherActiveCampaigns.length === 0 && (
                                  <span className="text-slate-400 text-[11px]">No active campaigns</span>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Pagination & Selection Bar */}
              <div className="px-6 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/60 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {selectedIds.size} prospect{selectedIds.size !== 1 ? 's' : ''} selected
                  </span>
                  {selectedIds.size > 0 && (
                    <button
                      onClick={handleClearSelection}
                      className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 underline cursor-pointer"
                    >
                      Clear selection
                    </button>
                  )}
                </div>

                {/* Page navigation */}
                <div className="flex items-center gap-2">
                  <span className="text-slate-500">
                    Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, prospects.length)} of {prospects.length}
                  </span>
                  <select
                    value={pageSize}
                    onChange={(e) => {
                      setPageSize(Number(e.target.value));
                      setPage(1);
                    }}
                    className="py-1 px-2 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 cursor-pointer"
                  >
                    <option value={25}>25 / page</option>
                    <option value={50}>50 / page</option>
                    <option value={100}>100 / page</option>
                  </select>

                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40 cursor-pointer"
                  >
                    <RiArrowLeftLine size={14} />
                  </button>
                  <span className="text-slate-600 dark:text-slate-300">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40 cursor-pointer"
                  >
                    <RiArrowRightLine size={14} />
                  </button>
                </div>

                {/* Actions: Cancel & Add Selected Prospects */}
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={onClose}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={handleProceedToReview}
                    disabled={selectedIds.size === 0 && !selectAllFiltered}
                    className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm flex items-center gap-1.5"
                  >
                    Add Selected Prospects ({selectAllFiltered ? totalMatching : selectedIds.size})
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: CONFIRMATION SUMMARY & SAFEGUARDS */}
          {step === 2 && (
            <div className="flex-1 flex flex-col overflow-y-auto p-6 space-y-6">
              {summaryLoading ? (
                <div className="p-12 text-center text-slate-400 text-xs flex flex-col items-center gap-2">
                  <div className="w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                  Analyzing selected prospects and checking campaign enrollment safeguards...
                </div>
              ) : summary ? (
                <>
                  {/* Campaign Status Banner */}
                  {isCampaignPaused ? (
                    <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl text-xs text-amber-800 dark:text-amber-200 flex items-start gap-3">
                      <RiAlertLine size={18} className="shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
                      <div>
                        <div className="font-semibold">Campaign is Currently Paused</div>
                        <div>
                          Enrolled prospects will be added safely in draft/staged mode. No emails will be sent until
                          you manually resume the campaign.
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="p-4 bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 rounded-xl text-xs text-teal-800 dark:text-teal-200 flex items-start gap-3">
                      <RiAlertLine size={18} className="shrink-0 text-teal-600 dark:text-teal-400 mt-0.5" />
                      <div>
                        <div className="font-semibold">Active Campaign Enrollment</div>
                        <div>
                          Eligible prospects will begin following this campaign schedule according to sending limits and working hours.
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Summary Breakdown Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                    <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700">
                      <div className="text-2xl font-bold text-slate-900 dark:text-white">
                        {summary.total_selected}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">Total Selected</div>
                    </div>

                    <div className="p-4 rounded-xl bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800">
                      <div className="text-2xl font-bold text-teal-600 dark:text-teal-400">
                        {summary.eligible}
                      </div>
                      <div className="text-xs text-teal-800 dark:text-teal-200 mt-1">Eligible to Enroll</div>
                    </div>

                    <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800">
                      <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                        {summary.needs_review}
                      </div>
                      <div className="text-xs text-amber-800 dark:text-amber-200 mt-1">Needs Review (Risky/Unknown)</div>
                    </div>

                    <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800">
                      <div className="text-2xl font-bold text-rose-600 dark:text-rose-400">
                        {summary.blocked + summary.already_enrolled}
                      </div>
                      <div className="text-xs text-rose-800 dark:text-rose-200 mt-1">
                        Blocked / Duplicate
                      </div>
                    </div>
                  </div>

                  {/* Other Active Campaigns Warning */}
                  {summary.other_active_campaigns > 0 && (
                    <div className="p-4 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30 space-y-3">
                      <div className="flex items-center justify-between text-xs font-semibold text-amber-800 dark:text-amber-200">
                        <span>
                          {summary.other_active_campaigns} prospect(s) are already active in another campaign
                        </span>
                        <label className="inline-flex items-center gap-1.5 cursor-pointer font-normal text-amber-900 dark:text-amber-100">
                          <input
                            type="checkbox"
                            checked={skipOtherActive}
                            onChange={(e) => setSkipOtherActive(e.target.checked)}
                            className="rounded text-amber-600 focus:ring-amber-500"
                          />
                          <span>Skip these prospects (Recommended)</span>
                        </label>
                      </div>

                      {summary.other_active_details?.length > 0 && (
                        <div className="max-h-36 overflow-y-auto space-y-1 text-[11px] pr-2">
                          {summary.other_active_details.map((d) => (
                            <div
                              key={d.lead_id}
                              className="flex items-center justify-between py-1 px-2 rounded bg-amber-100/60 dark:bg-amber-900/30 text-amber-900 dark:text-amber-200"
                            >
                              <span className="font-mono">{d.email}</span>
                              <span className="text-amber-700 dark:text-amber-300">
                                Active in: {d.campaign_name}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Blocked Prospect Details */}
                  {summary.blocked_details?.length > 0 && (
                    <div className="p-4 rounded-xl border border-rose-200 dark:border-rose-800 bg-rose-50/60 dark:bg-rose-950/30 space-y-2">
                      <div className="text-xs font-semibold text-rose-800 dark:text-rose-200">
                        {summary.blocked_details.length} prospect(s) blocked by deliverability safeguards:
                      </div>
                      <div className="max-h-32 overflow-y-auto space-y-1 text-[11px] pr-2">
                        {summary.blocked_details.map((d) => (
                          <div
                            key={d.lead_id}
                            className="flex items-center justify-between py-1 px-2 rounded bg-rose-100/60 dark:bg-rose-900/30 text-rose-900 dark:text-rose-200"
                          >
                            <span className="font-mono">{d.email}</span>
                            <span className="text-rose-700 dark:text-rose-300 capitalize">{d.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : null}

              {/* Footer Buttons for Step 2 */}
              <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-800 mt-auto">
                <Button size="sm" variant="outline" onClick={() => setStep(1)} disabled={enrolling}>
                  <RiArrowLeftLine size={14} className="mr-1" /> Back to Selection
                </Button>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={onClose} disabled={enrolling}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={handleConfirmEnroll}
                    disabled={enrolling || !summary || summary.eligible === 0}
                    className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm"
                  >
                    {enrolling ? 'Enrolling...' : `Confirm & Enroll ${summary ? summary.eligible : ''} Prospects`}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </ErrorBoundary>
      </div>
    </div>
  );
}

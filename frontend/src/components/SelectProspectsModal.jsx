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
  RiCheckDoubleLine,
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiAlertLine,
  RiUserSharedLine,
  RiArrowLeftLine,
  RiArrowRightLine,
  RiInformationLine,
  RiBuildingLine,
  RiMapPinLine,
  RiPriceTag3Line,
  RiShieldCheckLine,
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

  // Filter options from backend
  const [filterOptions, setFilterOptions] = useState({
    countries: [],
    cities: [],
    industries: [],
    tags: [],
    pipeline_statuses: [],
    verification_statuses: [],
  });

  // Filter values
  const [search, setSearch] = useState('');
  const [country, setCountry] = useState('');
  const [city, setCity] = useState('');
  const [industry, setIndustry] = useState('');
  const [tag, setTag] = useState('');
  const [pipelineStatus, setPipelineStatus] = useState('');
  const [verificationStatus, setVerificationStatus] = useState('');
  const [excludeCurrentCampaign, setExcludeCurrentCampaign] = useState(true);

  // Prospects data
  const [prospects, setProspects] = useState([]);
  const [loading, setLoading] = useState(false);

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Selection
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selectAllFiltered, setSelectAllFiltered] = useState(false);

  // Summary / Preview (Step 2)
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summary, setSummary] = useState(null);
  const [skipOtherActive, setSkipOtherActive] = useState(false);
  const [enrolling, setEnrolling] = useState(false);

  // Load filter options on modal open
  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setSelectedIds(new Set());
      setSelectAllFiltered(false);
      setSummary(null);
      api
        .get('/leads/filter-options')
        .then((res) => {
          if (res) setFilterOptions(res);
        })
        .catch(() => {});
    }
  }, [isOpen]);

  // Load prospects based on filters
  const loadProspects = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('q', search.trim());
      if (country) params.set('country', country);
      if (city) params.set('city', city);
      if (industry) params.set('industry', industry);
      if (tag) params.set('tag', tag);
      if (pipelineStatus) params.set('pipeline_status', pipelineStatus);
      if (verificationStatus) params.set('email_verification_status', verificationStatus);
      if (excludeCurrentCampaign && campaignId) params.set('exclude_campaign_id', campaignId);

      const qs = params.toString();
      const res = await api.get(`/leads${qs ? `?${qs}` : ''}`);
      setProspects(Array.isArray(res) ? res : []);
      setPage(1);
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to load prospects' });
    } finally {
      setLoading(false);
    }
  }, [isOpen, search, country, city, industry, tag, pipelineStatus, verificationStatus, excludeCurrentCampaign, campaignId, notify]);

  useEffect(() => {
    if (isOpen) {
      loadProspects();
    }
  }, [isOpen, loadProspects]);

  // Pagination slice
  const totalProspects = prospects.length;
  const totalPages = Math.ceil(totalProspects / pageSize) || 1;
  const paginatedProspects = useMemo(() => {
    const start = (page - 1) * pageSize;
    return prospects.slice(start, start + pageSize);
  }, [prospects, page, pageSize]);

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

  // Check if all visible rows are selected
  const allCurrentPageSelected = useMemo(() => {
    if (!paginatedProspects.length) return false;
    return paginatedProspects.every((p) => selectedIds.has(p.id));
  }, [paginatedProspects, selectedIds]);

  // Toggle select current page
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

  // Select all filtered prospects
  const handleSelectAllFiltered = () => {
    const allIds = new Set(prospects.map((p) => p.id));
    setSelectedIds(allIds);
    setSelectAllFiltered(true);
  };

  // Clear all selections
  const handleClearSelection = () => {
    setSelectedIds(new Set());
    setSelectAllFiltered(false);
  };

  // Proceed to Step 2: Confirmation Summary (runs dry_run preview)
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
              q: search.trim() || undefined,
              country: country || undefined,
              city: city || undefined,
              industry: industry || undefined,
              tag: tag || undefined,
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
              q: search.trim() || undefined,
              country: country || undefined,
              city: city || undefined,
              industry: industry || undefined,
              tag: tag || undefined,
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
            {/* Filter Bar */}
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-3 shrink-0">
              {/* Search & Main Status */}
              <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
                <div className="relative sm:col-span-2">
                  <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search prospects by name, email, or company..."
                    className="w-full pl-9 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  />
                  {search && (
                    <button
                      onClick={() => setSearch('')}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                    >
                      <RiCloseLine size={14} />
                    </button>
                  )}
                </div>

                {/* Email Verification Status Filter */}
                <div>
                  <select
                    value={verificationStatus}
                    onChange={(e) => setVerificationStatus(e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
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

                {/* Pipeline Status Filter */}
                <div>
                  <select
                    value={pipelineStatus}
                    onChange={(e) => setPipelineStatus(e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 capitalize"
                  >
                    <option value="">Pipeline: All Stages</option>
                    {filterOptions.pipeline_statuses.map((p) => (
                      <option key={p} value={p}>
                        {p.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Secondary Filters: Country, Industry, Tag, Exclude Toggle */}
              <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
                {filterOptions.countries.length > 0 && (
                  <select
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    className="py-1 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  >
                    <option value="">Country: All</option>
                    {filterOptions.countries.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                )}

                {filterOptions.industries.length > 0 && (
                  <select
                    value={industry}
                    onChange={(e) => setIndustry(e.target.value)}
                    className="py-1 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  >
                    <option value="">Industry: All</option>
                    {filterOptions.industries.map((ind) => (
                      <option key={ind} value={ind}>
                        {ind}
                      </option>
                    ))}
                  </select>
                )}

                {filterOptions.tags.length > 0 && (
                  <select
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                    className="py-1 px-2.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  >
                    <option value="">Tag: All</option>
                    {filterOptions.tags.map((t) => (
                      <option key={t} value={t}>
                        #{t}
                      </option>
                    ))}
                  </select>
                )}

                <label className="inline-flex items-center gap-1.5 ml-auto text-slate-600 dark:text-slate-300 select-none cursor-pointer">
                  <input
                    type="checkbox"
                    checked={excludeCurrentCampaign}
                    onChange={(e) => setExcludeCurrentCampaign(e.target.checked)}
                    className="rounded text-teal-600 focus:ring-teal-500"
                  />
                  <span>Exclude already enrolled in this campaign</span>
                </label>
              </div>

              {/* Select All Filtered Banner */}
              {allCurrentPageSelected && totalProspects > paginatedProspects.length && (
                <div className="bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 px-3 py-2 rounded-lg flex items-center justify-between text-xs text-teal-800 dark:text-teal-200 animate-fade-in">
                  <span>
                    All <strong>{paginatedProspects.length}</strong> prospects on this page are selected.
                  </span>
                  {!selectAllFiltered ? (
                    <button
                      onClick={handleSelectAllFiltered}
                      className="font-semibold underline hover:text-teal-900 dark:hover:text-teal-100 ml-2"
                    >
                      Select all {totalProspects} prospects matching current filters
                    </button>
                  ) : (
                    <span className="font-semibold text-teal-700 dark:text-teal-300">
                      ✓ All {totalProspects} filtered prospects selected
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
                          className="rounded text-teal-600 focus:ring-teal-500"
                        />
                      </th>
                      <th className="py-2.5 px-3">Prospect</th>
                      <th className="py-2.5 px-3">Company & Location</th>
                      <th className="py-2.5 px-3">Verification</th>
                      <th className="py-2.5 px-3">Existing Campaigns</th>
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
                              className="rounded text-teal-600 focus:ring-teal-500"
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
                            <div className="text-[11px] text-slate-400">
                              {[lead.city, lead.country].filter(Boolean).join(', ') || 'No location'}
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
                    className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 underline"
                  >
                    Clear selection
                  </button>
                )}
              </div>

              {/* Page navigation */}
              <div className="flex items-center gap-2">
                <span className="text-slate-500">
                  Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalProspects)} of {totalProspects}
                </span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="py-1 px-2 text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
                >
                  <option value={10}>10 / page</option>
                  <option value={25}>25 / page</option>
                  <option value={50}>50 / page</option>
                </select>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40"
                >
                  <RiArrowLeftLine size={14} />
                </button>
                <span className="text-slate-600 dark:text-slate-300 font-medium">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40"
                >
                  <RiArrowRightLine size={14} />
                </button>
              </div>

              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={handleProceedToReview}
                  disabled={selectedIds.size === 0}
                  className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm flex items-center gap-1.5"
                >
                  Review & Enroll ({selectedIds.size})
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
                    <RiInformationLine size={18} className="shrink-0 mt-0.5 text-amber-600" />
                    <div>
                      <p className="font-semibold text-sm">Campaign is currently PAUSED</p>
                      <p className="mt-1">
                        Enrolling these prospects will attach them safely to this campaign, but will <strong>not</strong>{' '}
                        activate the campaign or trigger any email sending. Outbound scheduling will remain disabled until you explicitly resume the campaign.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-xl text-xs text-emerald-800 dark:text-emerald-200 flex items-start gap-3">
                    <RiCheckboxCircleLine size={18} className="shrink-0 mt-0.5 text-emerald-600" />
                    <div>
                      <p className="font-semibold text-sm">Campaign is ACTIVE</p>
                      <p className="mt-1">
                        Eligible verified prospects will be assigned queue slots according to your sending schedules and inbox capacity.
                      </p>
                    </div>
                  </div>
                )}

                {/* 4 Stat Breakdown Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40">
                    <div className="text-xs text-slate-500">Total Selected</div>
                    <div className="text-2xl font-bold text-slate-900 dark:text-white mt-1">
                      {summary.total_selected}
                    </div>
                  </div>

                  <div className="p-4 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/30">
                    <div className="text-xs font-medium text-emerald-700 dark:text-emerald-300 flex items-center gap-1">
                      <RiShieldCheckLine size={14} /> Ready to Send
                    </div>
                    <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">
                      {summary.eligible}
                    </div>
                    <div className="text-[10px] text-emerald-600/80 mt-1">Valid / Domain Validated</div>
                  </div>

                  <div className="p-4 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30">
                    <div className="text-xs font-medium text-amber-700 dark:text-amber-300 flex items-center gap-1">
                      <RiAlertLine size={14} /> Needs Review
                    </div>
                    <div className="text-2xl font-bold text-amber-600 dark:text-amber-400 mt-1">
                      {summary.needs_review}
                    </div>
                    <div className="text-[10px] text-amber-600/80 mt-1">Paused until review</div>
                  </div>

                  <div className="p-4 rounded-xl border border-rose-200 dark:border-rose-800 bg-rose-50/50 dark:bg-rose-950/30">
                    <div className="text-xs font-medium text-rose-700 dark:text-rose-300 flex items-center gap-1">
                      <RiCloseCircleLine size={14} /> Blocked / Excluded
                    </div>
                    <div className="text-2xl font-bold text-rose-600 dark:text-rose-400 mt-1">
                      {summary.blocked}
                    </div>
                    <div className="text-[10px] text-rose-600/80 mt-1">Invalid / Suppressed / Unsub</div>
                  </div>
                </div>

                {/* Duplicates & Existing Campaign Notice */}
                {summary.already_enrolled > 0 && (
                  <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg text-xs text-slate-600 dark:text-slate-300 flex items-center justify-between">
                    <span>
                      ℹ️ <strong>{summary.already_enrolled}</strong> prospect(s) are already enrolled in this campaign and will be skipped to prevent duplicate outreach.
                    </span>
                  </div>
                )}

                {/* Overlapping Outreach Warning (Requirement 9) */}
                {summary.other_active_campaigns > 0 && (
                  <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl space-y-3">
                    <div className="flex items-start gap-2.5">
                      <RiAlertLine size={18} className="text-amber-600 shrink-0 mt-0.5" />
                      <div>
                        <p className="text-xs font-bold text-amber-900 dark:text-amber-200">
                          Overlapping Active Outreach Warning
                        </p>
                        <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
                          <strong>{summary.other_active_campaigns}</strong> of the selected prospects are already enrolled in other currently ACTIVE campaigns.
                        </p>
                      </div>
                    </div>

                    <label className="flex items-center gap-2 text-xs font-medium text-amber-900 dark:text-amber-200 cursor-pointer pt-1">
                      <input
                        type="checkbox"
                        checked={skipOtherActive}
                        onChange={(e) => setSkipOtherActive(e.target.checked)}
                        className="rounded text-amber-600 focus:ring-amber-500"
                      />
                      <span>Skip prospects already in active campaigns (prevent duplicate outreach)</span>
                    </label>

                    {summary.other_active_details?.length > 0 && (
                      <div className="max-h-24 overflow-y-auto text-[11px] bg-white/70 dark:bg-slate-900/60 p-2 rounded border border-amber-200 dark:border-amber-900 font-mono text-slate-600 dark:text-slate-300">
                        {summary.other_active_details.map((d, i) => (
                          <div key={i}>
                            {d.email}: Active in {d.campaigns?.join(', ')}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Blocked details */}
                {summary.blocked > 0 && summary.blocked_details?.length > 0 && (
                  <div className="p-3 bg-rose-50/60 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-900 rounded-lg text-xs space-y-1">
                    <p className="font-semibold text-rose-800 dark:text-rose-200">
                      Excluded Contacts ({summary.blocked}):
                    </p>
                    <p className="text-[11px] text-rose-600 dark:text-rose-300">
                      These contacts will be enrolled in a blocked state without queue slots to protect sender reputation.
                    </p>
                  </div>
                )}

                {/* Step 2 Actions */}
                <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                  <Button size="sm" variant="outline" onClick={() => setStep(1)} disabled={enrolling}>
                    <RiArrowLeftLine size={14} className="mr-1" /> Back to Selection
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={handleConfirmEnroll}
                    disabled={enrolling || summary.total_selected === 0}
                    className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm flex items-center gap-1.5"
                  >
                    {enrolling ? (
                      <>Enrolling prospects...</>
                    ) : (
                      <>
                        <RiCheckboxCircleLine size={16} /> Confirm & Enroll Prospects
                      </>
                    )}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        )}
        </ErrorBoundary>
      </div>
    </div>
  );
}

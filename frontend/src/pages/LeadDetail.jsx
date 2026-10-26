import { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import ComposeModal from '../components/ComposeModal';
import LeadVerificationModal, { getVerificationBadge } from '../components/LeadVerificationModal';
import AssignCampaignModal from '../components/AssignCampaignModal';
import EmailTrackingCard from '../components/EmailTrackingCard';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import ErrorBoundary from '../components/ErrorBoundary';
import { useNotify } from '../context/NotificationContext';
import { useLoading } from '../context/LoadingContext';
import { cn } from '../utils/cn';
import {
  RiMailSendLine,
  RiShieldCheckLine,
  RiInformationLine,
  RiEditLine,
  RiBuildingLine,
  RiPhoneLine,
  RiGlobalLine,
  RiFolderUserLine,
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiCheckLine,
  RiCloseLine,
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiAlertLine,
  RiTimeLine,
  RiExternalLinkLine,
  RiRefreshLine,
  RiErrorWarningLine,
} from 'react-icons/ri';

function formatDt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const PIPELINE_STAGES = [
  { value: 'new', label: 'New', dot: 'bg-blue-400' },
  { value: 'contacted', label: 'Contacted', dot: 'bg-indigo-400' },
  { value: 'follow_up_scheduled', label: 'Follow-up Scheduled', dot: 'bg-sky-400' },
  { value: 'replied', label: 'Replied', dot: 'bg-purple-400' },
  { value: 'interested', label: 'Interested', dot: 'bg-emerald-400' },
  { value: 'meeting_scheduled', label: 'Meeting Scheduled', dot: 'bg-teal-400' },
  { value: 'proposal_sent', label: 'Proposal Sent', dot: 'bg-amber-400' },
  { value: 'won', label: 'Won', dot: 'bg-emerald-500' },
  { value: 'lost', label: 'Lost', dot: 'bg-rose-400' },
  { value: 'not_interested', label: 'Not Interested', dot: 'bg-slate-400' },
];

export default function LeadDetail() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const notify = useNotify();
  const loading = useLoading();

  const [lead, setLead] = useState(null);
  const [error, setError] = useState(null);
  const [campaigns, setCampaigns] = useState([]);

  // Stage dropdown custom state
  const [stageDropdownOpen, setStageDropdownOpen] = useState(false);
  const stageDropdownRef = useRef(null);

  useEffect(() => {
    if (searchParams.get('open_stage') === 'true') {
      const timer = setTimeout(() => setStageDropdownOpen(true), 350);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  // Quick reverification state
  const [reverifying, setReverifying] = useState(false);

  // Modals state
  const [composeOpen, setComposeOpen] = useState(false);
  const [verifModalOpen, setVerifModalOpen] = useState(false);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);

  // Edit form state (only 5 essential fields)
  const [editForm, setEditForm] = useState({
    company: '',
    email: '',
    name: '',
    phone: '',
    website: '',
  });

  // Expandable interaction messages
  const [expandedInteractions, setExpandedInteractions] = useState(new Set());

  const toggleExpand = (idx) => {
    setExpandedInteractions((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const load = useCallback(async () => {
    loading.start();
    setError(null);
    try {
      const l = await api.get(`/leads/${id}`);
      setLead(l);
    } catch (e) {
      setError(e.message || 'Failed to load lead');
      notify({ type: 'error', message: 'Could not load lead' });
    } finally {
      loading.stop();
    }
  }, [id, loading, notify]);

  useEffect(() => {
    load();
    // Load campaigns for assignment
    api
      .get('/campaigns')
      .then((res) => {
        const list = Array.isArray(res) ? res : res?.items || [];
        setCampaigns(list);
      })
      .catch(() => {});
  }, [load]);

  // Open Edit Modal with current values
  const handleOpenEdit = () => {
    if (!lead) return;
    setEditForm({
      company: lead.company || '',
      email: lead.email || '',
      name: lead.name || '',
      phone: lead.phone || '',
      website: lead.website || '',
    });
    setEditModalOpen(true);
  };

  // Submit Edit form
  const handleSaveEdit = async (e) => {
    e.preventDefault();
    if (!editForm.company?.trim()) {
      notify({ type: 'error', message: 'Company Name is required.' });
      return;
    }
    if (!editForm.email?.trim() || !editForm.email.includes('@')) {
      notify({ type: 'error', message: 'Valid Email Address is required.' });
      return;
    }

    loading.start();
    try {
      const updated = await api.patch(`/leads/${id}`, {
        company: editForm.company.trim(),
        email: editForm.email.trim(),
        name: editForm.name.trim(),
        phone: editForm.phone.trim(),
        website: editForm.website.trim(),
      });
      setLead(updated);
      setEditModalOpen(false);
      notify({ type: 'success', message: 'Prospect updated successfully!' });
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to update prospect' });
    } finally {
      loading.stop();
    }
  };

  // Change Lead Status dropdown
  const handleStageChange = async (newStage) => {
    try {
      const updated = await api.patch(`/leads/${id}`, { pipeline_status: newStage });
      setLead((prev) => ({ ...prev, pipeline_status: newStage, ...updated }));
      notify({
        type: 'success',
        message: `Status updated to ${newStage.replace(/_/g, ' ')}.`,
      });
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to update status' });
    }
  };

  // Close stage dropdown on outside click or escape
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (stageDropdownRef.current && !stageDropdownRef.current.contains(e.target)) {
        setStageDropdownOpen(false);
      }
    };
    const handleEsc = (e) => {
      if (e.key === 'Escape') setStageDropdownOpen(false);
    };
    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleEsc);
    };
  }, []);

  // Quick reverification action
  const handleQuickReverify = async () => {
    setReverifying(true);
    try {
      const res = await api.post(`/leads/${id}/verify`);
      notify({
        type: 'success',
        message: `Deliverability check completed: ${res.status?.replace(/_/g, ' ')}`,
      });
      await load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Verification failed' });
    } finally {
      setReverifying(false);
    }
  };

  // Pre-fill edit modal with suggested email
  const handleApplySuggestedEmail = (suggestedEmail) => {
    if (!suggestedEmail) return;
    setEditForm({
      company: lead?.company || '',
      email: suggestedEmail,
      name: lead?.name || '',
      phone: lead?.phone || '',
      website: lead?.website || '',
    });
    setEditModalOpen(true);
  };

  if (error && !lead) {
    return (
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-8">
        <h1 className="text-2xl font-semibold mb-4">Prospect</h1>
        <p className="text-red-600">{error}</p>
        <Button as={Link} to="/leads" variant="outline">
          Back to Prospects
        </Button>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-8">
        <p className="text-gray-500">Loading prospect details…</p>
      </div>
    );
  }

  const customEntries = Object.entries(lead.custom_data || {});
  const currentStage = (lead.pipeline_status || 'new').toLowerCase();
  const activeStageObj = PIPELINE_STAGES.find((s) => s.value === currentStage) || {
    value: currentStage,
    label: currentStage.replace(/_/g, ' '),
    dot: 'bg-teal-400',
  };

  return (
    <ErrorBoundary
      title="Prospect Details Error"
      description="An unexpected error occurred while displaying this prospect profile. Please refresh or try again."
    >
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6 md:p-8">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-slate-800">
        <div>
          <div className="text-xs text-slate-500 mb-1 flex items-center gap-1.5">
            <Link to="/leads" className="text-teal-600 dark:text-teal-400 hover:underline">
              Prospects
            </Link>
            <span>/</span>
            <span className="font-mono text-[11px] bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              #{lead.id}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              {lead.company || lead.name || lead.email}
            </h1>
            {lead.name && lead.company && (
              <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                ({lead.name})
              </span>
            )}
          </div>
          <p className="text-slate-600 dark:text-slate-400 mt-0.5 font-mono text-xs">
            {lead.email}
          </p>
        </div>

        {/* Action Buttons & Status Selector */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Custom Pipeline Stage Dropdown */}
          <div className="relative inline-block" ref={stageDropdownRef}>
            <button
              type="button"
              onClick={() => setStageDropdownOpen((prev) => !prev)}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold shadow-2xs transition-all cursor-pointer focus:outline-none focus:ring-2 focus:ring-teal-500/30",
                stageDropdownOpen
                  ? "bg-slate-100 dark:bg-slate-800 border-teal-500/50 text-teal-700 dark:text-teal-300 ring-2 ring-teal-500/20"
                  : "bg-white dark:bg-slate-800/90 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 text-slate-800 dark:text-slate-100"
              )}
              aria-haspopup="true"
              aria-expanded={stageDropdownOpen}
              title="Change pipeline stage"
            >
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Stage:
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn("w-2 h-2 rounded-full shrink-0", activeStageObj.dot || "bg-teal-400")} />
                <span className="capitalize">{activeStageObj.label}</span>
              </span>
              <RiArrowDownSLine
                size={14}
                className={cn("text-slate-400 transition-transform duration-200", stageDropdownOpen && "rotate-180")}
              />
            </button>

            {stageDropdownOpen && (
              <div
                className="absolute right-0 mt-1.5 w-56 sm:w-60 z-50 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-xl py-1 backdrop-blur-md animate-in fade-in zoom-in-95"
                style={{ animationDuration: '120ms' }}
              >
                <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100 dark:border-slate-800">
                  Update Pipeline Stage
                </div>
                <div className="max-h-60 overflow-y-auto py-1">
                  {PIPELINE_STAGES.map((s) => {
                    const isSelected = currentStage === s.value;
                    return (
                      <button
                        key={s.value}
                        type="button"
                        onClick={() => {
                          handleStageChange(s.value);
                          setStageDropdownOpen(false);
                        }}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 text-xs transition-colors text-left cursor-pointer",
                          isSelected
                            ? "bg-teal-500/10 text-teal-600 dark:text-teal-300 font-semibold"
                            : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/80"
                        )}
                      >
                        <span className="flex items-center gap-2">
                          <span className={cn("w-2 h-2 rounded-full shrink-0", s.dot || "bg-slate-400")} />
                          <span>{s.label}</span>
                        </span>
                        {isSelected && <RiCheckLine size={15} className="text-teal-600 dark:text-teal-400" />}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleOpenEdit}
            className="flex items-center gap-1.5 text-xs text-slate-700 dark:text-slate-300"
          >
            <RiEditLine size={14} /> Edit Prospect
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setAssignModalOpen(true)}
            className="flex items-center gap-1.5 text-xs text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800 hover:bg-teal-50 dark:hover:bg-teal-950/40"
          >
            <RiFolderUserLine size={14} /> Add to Campaign
          </Button>

          <Button
            type="button"
            size="sm"
            onClick={() => setComposeOpen(true)}
            className="bg-teal-600 hover:bg-teal-700 text-white flex items-center gap-1.5 text-xs shadow-sm"
          >
            <RiMailSendLine size={15} /> Send Email
          </Button>

          <Button as={Link} to="/unibox" variant="outline" size="sm" className="text-xs">
            Open Unibox
          </Button>
        </div>
      </div>

      {/* Main Grid: Details & Deliverability */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Left Column (2 cols): Essential Details */}
        <Card className="p-5 md:col-span-2 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <RiBuildingLine className="text-teal-600" size={16} /> Essential Details
            </h2>
            <button
              onClick={handleOpenEdit}
              className="text-xs text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1"
            >
              <RiEditLine size={13} /> Edit
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800">
              <span className="text-slate-400 text-[11px] block mb-1">Company Name</span>
              <span className="font-semibold text-slate-900 dark:text-white text-sm">
                {lead.company || '—'}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800">
              <span className="text-slate-400 text-[11px] block mb-1">Email Address</span>
              <span className="font-semibold text-slate-900 dark:text-white text-sm font-mono break-all">
                {lead.email}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800">
              <span className="text-slate-400 text-[11px] block mb-1">Founder / Contact Name</span>
              <span className="font-medium text-slate-800 dark:text-slate-200 text-sm">
                {lead.name || '—'}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800">
              <span className="text-slate-400 text-[11px] block mb-1">Phone Number</span>
              {lead.phone ? (
                <a
                  href={`tel:${lead.phone}`}
                  className="font-medium text-teal-600 dark:text-teal-400 hover:underline text-sm"
                >
                  {lead.phone}
                </a>
              ) : (
                <span className="text-slate-400">—</span>
              )}
            </div>

            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800 sm:col-span-2">
              <span className="text-slate-400 text-[11px] block mb-1">Website URL</span>
              {lead.website ? (
                <a
                  href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1.5 text-sm"
                >
                  <RiGlobalLine size={14} />
                  {lead.website}
                  <RiExternalLinkLine size={12} className="opacity-70" />
                </a>
              ) : (
                <span className="text-slate-400">—</span>
              )}
            </div>
          </div>
        </Card>

        {/* Right Column (1 col): Deliverability & Verification Health */}
        <Card className="p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
            <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <RiShieldCheckLine className="text-teal-600 dark:text-teal-400" size={17} /> Deliverability Health
            </h2>
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleQuickReverify}
                disabled={reverifying}
                title="Re-verify DNS, MX, and syntax"
                className="text-[11px] px-2 py-1 flex items-center gap-1 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                <RiRefreshLine size={13} className={cn("text-slate-500", reverifying && "animate-spin text-teal-600")} />
                {reverifying ? 'Checking...' : 'Re-verify'}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setVerifModalOpen(true)}
                className="text-[11px] px-2 py-1 flex items-center gap-1 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                Inspect
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            {/* Status & Confidence Badge Row */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Deliverability Classification
                </span>
                {lead.email_verification_result?.confidence && (
                  <span className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                    {lead.email_verification_result.confidence} Confidence
                  </span>
                )}
              </div>
              <div>
                {getVerificationBadge(
                  lead.email_verification_status,
                  lead.email_verification_result?.role_based?.is_role_account,
                  lead.email_verification_result?.role_based?.role_category,
                  lead.email_verification_result?.approved
                )}
              </div>
            </div>

            {/* Diagnostic Message Box */}
            <div className={cn(
              "p-3 rounded-xl border text-xs leading-relaxed space-y-1.5",
              lead.email_verification_status === 'valid'
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-900 dark:text-emerald-200"
                : lead.email_verification_status === 'domain_validated'
                ? "bg-sky-500/10 border-sky-500/30 text-sky-900 dark:text-sky-200"
                : lead.email_verification_status === 'risky'
                ? "bg-amber-500/10 border-amber-500/30 text-amber-900 dark:text-amber-200"
                : lead.email_verification_status === 'catch_all'
                ? "bg-purple-500/10 border-purple-500/30 text-purple-900 dark:text-purple-200"
                : lead.email_verification_status === 'invalid'
                ? "bg-rose-500/10 border-rose-500/30 text-rose-900 dark:text-rose-200"
                : "bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700/80 text-slate-700 dark:text-slate-300"
            )}>
              {lead.email_verification_status === 'valid' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiCheckboxCircleLine size={15} className="shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                  <span><strong>Mailbox Verified:</strong> Recipient existence confirmed via SMTP probe response.</span>
                </p>
              )}
              {lead.email_verification_status === 'domain_validated' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiInformationLine size={15} className="shrink-0 mt-0.5 text-sky-600 dark:text-sky-400" />
                  <span><strong>Domain Validated:</strong> DNS and MX servers are confirmed active. Safe for outreach.</span>
                </p>
              )}
              {lead.email_verification_status === 'risky' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiAlertLine size={15} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                  <span><strong>Risky Deliverability:</strong> Potential deliverability risk or domain typo detected.</span>
                </p>
              )}
              {lead.email_verification_status === 'catch_all' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiInformationLine size={15} className="shrink-0 mt-0.5 text-purple-600 dark:text-purple-400" />
                  <span><strong>Catch-All Domain:</strong> Server accepts all emails. Individual inbox existence unconfirmed.</span>
                </p>
              )}
              {lead.email_verification_status === 'unknown' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiAlertLine size={15} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                  <span><strong>Review Needed:</strong> Mail server timed out or greylisted. Requires manual check before sending.</span>
                </p>
              )}
              {lead.email_verification_status === 'invalid' && (
                <p className="flex items-start gap-1.5 font-medium">
                  <RiCloseCircleLine size={15} className="shrink-0 mt-0.5 text-rose-600 dark:text-rose-400" />
                  <span><strong>Invalid Email:</strong> Nonexistent domain, syntax error, or dead MX. Blocked from sending.</span>
                </p>
              )}
              {(!lead.email_verification_status ||
                lead.email_verification_status === 'not_verified' ||
                lead.email_verification_status === 'unverified') && (
                <p className="flex items-start gap-1.5 text-slate-500 dark:text-slate-400">
                  <RiTimeLine size={15} className="shrink-0 mt-0.5" />
                  <span><strong>Unscanned:</strong> DNS and mailbox validation have not been performed yet.</span>
                </p>
              )}

              {lead.email_verification_result?.reason && (
                <p className="text-[11px] pt-1.5 border-t border-current/10 font-sans">
                  <span className="font-semibold">Diagnostic Finding:</span> {lead.email_verification_result.reason}
                </p>
              )}
            </div>

            {/* Domain Mismatch Advisory Banner (if website domain differs from email domain) */}
            {lead.email_verification_result?.domain_mismatch?.has_mismatch && (
              <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/40 dark:bg-amber-950/30 dark:border-amber-800/60 space-y-2">
                <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-xs">
                  <RiAlertLine size={16} className="text-amber-500 shrink-0" />
                  <span>Website Domain Mismatch Advisory</span>
                </div>
                <p className="text-[11px] leading-relaxed text-amber-900 dark:text-amber-200">
                  {lead.email_verification_result.domain_mismatch.advisory}
                </p>
                {lead.email_verification_result.domain_mismatch.suggested_email && (
                  <div className="pt-2 flex flex-wrap items-center justify-between gap-2 border-t border-amber-500/20">
                    <span className="text-[11px] text-amber-800 dark:text-amber-200 font-mono">
                      Suggested: <strong>{lead.email_verification_result.domain_mismatch.suggested_email}</strong>
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        handleApplySuggestedEmail(
                          lead.email_verification_result.domain_mismatch.suggested_email
                        )
                      }
                      className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-amber-600 hover:bg-amber-700 text-white transition-colors flex items-center gap-1 shadow-xs cursor-pointer"
                    >
                      <RiEditLine size={12} />
                      Review & Update Email
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Quick Metadata: Provider & MX */}
            <div className="grid grid-cols-2 gap-2 pt-1 text-[11px] text-slate-500 dark:text-slate-400">
              <div className="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800 truncate">
                <span className="block text-[10px] uppercase font-bold text-slate-400">Provider</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200 truncate block">
                  {lead.provider || lead.email_verification_result?.domain?.detected_provider || 'Unknown'}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800 truncate">
                <span className="block text-[10px] uppercase font-bold text-slate-400">MX Routing</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200 truncate block">
                  {lead.email_verification_result?.domain?.has_mx ? 'Active' : lead.email_verification_result?.domain?.is_null_mx ? 'Null MX' : 'Unchecked'}
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Campaigns Card */}
      <Card className="p-5 space-y-3">
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <RiFolderUserLine className="text-teal-600" size={16} /> Campaign Enrollments
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Active campaigns this prospect is assigned to. Duplicate assignments are automatically prevented.
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setAssignModalOpen(true)}
            className="flex items-center gap-1.5 text-xs text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800 hover:bg-teal-50 dark:hover:bg-teal-950/40"
          >
            <RiFolderUserLine size={14} /> Add to Campaign
          </Button>
        </div>

        {lead.campaigns?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-[11px] text-slate-400 uppercase bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200/60 dark:border-slate-800">
                <tr>
                  <th className="py-2.5 px-3">Campaign</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Engagement</th>
                  <th className="py-2.5 px-3">Enrolled At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {lead.campaigns.map((c) => (
                  <tr key={c.campaign_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                    <td className="py-3 px-3 font-medium">
                      <Link
                        to={`/campaigns/${c.campaign_id}#leads`}
                        className="text-teal-600 dark:text-teal-400 hover:underline font-semibold"
                      >
                        {c.campaign_name}
                      </Link>
                      {c.campaign_paused && (
                        <span className="ml-2 text-[10px] bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 px-1.5 py-0.5 rounded">
                          Campaign Paused
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <span className="rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5">
                        {c.status || 'active'}
                      </span>
                      {c.sending_paused && (
                        <span className="ml-1.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-200 px-2 py-0.5">
                          Sending Paused
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3 text-slate-500">
                      Opened: {c.opened ? 'Yes' : 'No'} · Clicked: {c.clicked ? 'Yes' : 'No'} · Replied:{' '}
                      {c.replied ? 'Yes' : 'No'}
                    </td>
                    <td className="py-3 px-3 text-slate-400">{formatDt(c.enrolled_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-slate-500 text-xs py-4 text-center">
            This prospect is not enrolled in any campaign yet.
          </p>
        )}
      </Card>

      {/* Expandable Communication History */}
      <Card className="p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <RiMailSendLine className="text-teal-600" size={16} /> Communication History
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Personalized emails delivered, direct messages, and client replies with full message inspection.
            </p>
          </div>
          <span className="text-xs text-slate-400">
            {lead.interactions?.length || 0} interaction{lead.interactions?.length !== 1 ? 's' : ''}
          </span>
        </div>

        {lead.interactions?.length ? (
          <div className="space-y-3">
            {lead.interactions.map((msg, idx) => {
              const isExpanded = expandedInteractions.has(idx);
              const isOutbound = msg.direction === 'outbound';
              const isSent = (msg.status || '').toLowerCase() === 'sent';
              const isFailed = (msg.status || '').toLowerCase() === 'failed';

              return (
                <div
                  key={idx}
                  className={cn(
                    'rounded-xl border transition-all text-xs overflow-hidden',
                    isOutbound
                      ? 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900'
                      : 'border-violet-200 dark:border-violet-900/60 bg-violet-50/30 dark:bg-violet-950/20'
                  )}
                >
                  {/* Collapsed Header Line */}
                  <div
                    onClick={() => toggleExpand(idx)}
                    className="p-3.5 flex flex-wrap items-center justify-between gap-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40 select-none"
                  >
                    <div className="flex items-center gap-2.5 flex-1 min-w-[260px]">
                      {/* Direction & Status Badge */}
                      <span
                        className={cn(
                          'text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 uppercase tracking-wider',
                          isOutbound
                            ? isFailed
                              ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-200'
                              : 'bg-teal-100 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
                            : 'bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-200'
                        )}
                      >
                        {isOutbound ? (isFailed ? 'Send Failed' : 'Sent Email') : 'Received'}
                      </span>

                      {/* Channel Pill */}
                      {msg.campaign_name && (
                        <span className="text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-full">
                          Campaign: {msg.campaign_name}
                        </span>
                      )}
                      {msg.channel === 'direct_email' && (
                        <span className="text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-full">
                          Direct Email
                        </span>
                      )}

                      {/* Tracking Engagement Pill */}
                      {isOutbound && msg.tracking?.status_label && (
                        <span
                          className={cn(
                            'text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0 border',
                            msg.tracking.tracking_status === 'open_detected'
                              ? 'bg-teal-50 text-teal-800 border-teal-200'
                              : msg.tracking.tracking_status === 'clicked'
                              ? 'bg-indigo-50 text-indigo-800 border-indigo-200'
                              : msg.tracking.tracking_status === 'replied'
                              ? 'bg-purple-50 text-purple-800 border-purple-200'
                              : msg.tracking.tracking_status === 'no_open_detected'
                              ? 'bg-blue-50 text-blue-700 border-blue-200'
                              : 'bg-slate-100 text-slate-600 border-slate-300'
                          )}
                        >
                          {msg.tracking.status_label}
                        </span>
                      )}

                      {/* Subject */}
                      <span className="font-bold text-slate-900 dark:text-white truncate max-w-md">
                        {msg.subject || '(no subject)'}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-slate-400 text-[11px]">{formatDt(msg.at)}</span>
                      <button
                        type="button"
                        className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                        title={isExpanded ? 'Collapse' : 'Expand full message'}
                      >
                        {isExpanded ? <RiArrowUpSLine size={16} /> : <RiArrowDownSLine size={16} />}
                      </button>
                    </div>
                  </div>

                  {/* Snippet (when collapsed) */}
                  {!isExpanded && msg.snippet && (
                    <div
                      onClick={() => toggleExpand(idx)}
                      className="px-3.5 pb-3 text-slate-500 dark:text-slate-400 truncate cursor-pointer"
                    >
                      {msg.snippet}
                    </div>
                  )}

                  {/* Expanded Full Message Body & Headers */}
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-3 bg-slate-50/50 dark:bg-slate-800/20">
                      {/* Sender & Recipient Metadata */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] text-slate-600 dark:text-slate-400 pb-2 border-b border-slate-200/60 dark:border-slate-800">
                        <div>
                          <strong className="text-slate-700 dark:text-slate-300">From:</strong>{' '}
                          <span className="font-mono">{msg.from_email || 'Outreach OS Sending Inbox'}</span>
                        </div>
                        <div>
                          <strong className="text-slate-700 dark:text-slate-300">To:</strong>{' '}
                          <span className="font-mono">{msg.to_email || lead.email}</span>
                        </div>
                        <div>
                          <strong className="text-slate-700 dark:text-slate-300">Delivered At:</strong>{' '}
                          <span>{formatDt(msg.at)}</span>
                        </div>
                        <div>
                          <strong className="text-slate-700 dark:text-slate-300">Sending Status:</strong>{' '}
                          <span className="capitalize font-semibold text-slate-800 dark:text-slate-200">
                            {msg.status || (isOutbound ? 'sent' : 'received')}
                          </span>
                        </div>
                      </div>

                      {/* Error Banner if send failed */}
                      {msg.error_message && (
                        <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
                          <strong>Delivery Error:</strong> {msg.error_message}
                        </div>
                      )}

                      {/* Full Message Body */}
                      <div className="p-3.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 whitespace-pre-wrap font-sans text-xs text-slate-800 dark:text-slate-200 leading-relaxed max-h-96 overflow-y-auto">
                        {msg.body || msg.snippet || '(Empty body)'}
                      </div>

                      {/* Engagement & Tracking Card */}
                      {isOutbound && msg.tracking && (
                        <EmailTrackingCard tracking={msg.tracking} isSent={true} />
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-slate-500 text-xs py-4 text-center">
            No communication history recorded for this prospect yet.
          </p>
        )}
      </Card>

      {/* Custom Data Card (if any custom fields exist) */}
      {customEntries.length > 0 && (
        <Card className="p-5">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider mb-3 border-b border-slate-100 dark:border-slate-800 pb-2">
            Custom Fields
          </h2>
          <table className="w-full table-auto border-collapse text-xs">
            <tbody>
              {customEntries.map(([k, v]) => (
                <tr key={k} className="even:bg-slate-50 dark:even:bg-slate-800/40">
                  <td className="border border-slate-200 dark:border-slate-700 px-3 py-1.5 font-medium text-slate-700 dark:text-slate-300 w-1/3">
                    {k}
                  </td>
                  <td className="border border-slate-200 dark:border-slate-700 px-3 py-1.5 font-mono text-[11px] text-slate-600 dark:text-slate-400 break-all">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Edit Lead Modal (Only 5 Essential Fields) */}
      {editModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 w-full max-w-lg flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
              <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <RiEditLine className="text-teal-600" size={18} /> Edit Prospect
              </h2>
              <button
                type="button"
                onClick={() => setEditModalOpen(false)}
                className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <RiCloseLine size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Company Name <span className="text-rose-500">*</span>
                </label>
                <Input
                  value={editForm.company}
                  onChange={(e) => setEditForm({ ...editForm, company: e.target.value })}
                  placeholder="Acme Innovations"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Email Address <span className="text-rose-500">*</span>
                </label>
                <Input
                  type="email"
                  value={editForm.email}
                  onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                  placeholder="founder@company.com"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Founder / Contact Name
                </label>
                <Input
                  value={editForm.name}
                  onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  placeholder="Alex Vance"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Phone Number
                  </label>
                  <Input
                    type="tel"
                    value={editForm.phone}
                    onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                    placeholder="+1 (555) 019-2831"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Website URL
                  </label>
                  <Input
                    type="url"
                    value={editForm.website}
                    onChange={(e) => setEditForm({ ...editForm, website: e.target.value })}
                    placeholder="https://company.com"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button type="button" variant="ghost" size="sm" onClick={() => setEditModalOpen(false)}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  className="bg-teal-600 hover:bg-teal-700 text-white flex items-center gap-1.5"
                >
                  <RiCheckLine size={15} /> Save Changes
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add to Campaign Modal */}
      <AssignCampaignModal
        isOpen={assignModalOpen}
        onClose={() => setAssignModalOpen(false)}
        selectedLeadIds={[Number(id)]}
        campaigns={campaigns}
        onAssigned={() => load()}
      />

      {/* Compose Direct Email Modal */}
      <ComposeModal
        isOpen={composeOpen}
        onClose={() => setComposeOpen(false)}
        onSent={() => load()}
        initialTo={lead?.email || ''}
        initialRecipientName={lead?.name || ''}
        initialLeadId={lead?.id || null}
      />

      {/* Lead Deliverability Inspector Modal */}
      <LeadVerificationModal
        lead={lead}
        isOpen={verifModalOpen}
        onClose={() => setVerifModalOpen(false)}
        onUpdated={(updated) => {
          if (updated) setLead((prev) => ({ ...prev, ...updated }));
          load();
        }}
      />
    </div>
    </ErrorBoundary>
  );
}

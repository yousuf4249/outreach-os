import { useState, useEffect } from 'react';
import { api } from '../api';
import { useNotify } from '../context/NotificationContext';
import { Button } from './ui/Button';
import {
  RiShieldCheckLine,
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiErrorWarningLine,
  RiGlobalLine,
  RiInboxArchiveLine,
  RiQuestionLine,
  RiTimeLine,
  RiCheckDoubleLine,
  RiRefreshLine,
  RiInformationLine,
  RiCloseLine,
  RiFileShield2Line,
  RiAlertLine,
} from 'react-icons/ri';

export function getVerificationBadge(status, isRoleAccount = false, roleCategory = null, approved = false) {
  const norm = (status || 'unverified').toLowerCase();

  let config = {
    label: 'Unverified',
    color: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
    icon: RiTimeLine,
  };

  if (norm === 'valid') {
    config = {
      label: 'Valid',
      color: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
      icon: RiCheckboxCircleLine,
    };
  } else if (norm === 'domain_validated') {
    config = {
      label: 'Domain Validated',
      color: 'bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800',
      icon: RiGlobalLine,
    };
  } else if (norm === 'invalid') {
    config = {
      label: 'Invalid (Blocked)',
      color: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800',
      icon: RiCloseCircleLine,
    };
  } else if (norm === 'risky') {
    config = {
      label: 'Risky',
      color: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
      icon: RiErrorWarningLine,
    };
  } else if (norm === 'catch_all') {
    config = {
      label: 'Catch-All',
      color: 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800',
      icon: RiInboxArchiveLine,
    };
  } else if (norm === 'unknown') {
    config = {
      label: 'Unknown',
      color: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700',
      icon: RiQuestionLine,
    };
  }

  const Icon = config.icon;

  return (
    <div className="inline-flex flex-wrap items-center gap-1.5">
      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${config.color}`}>
        <Icon size={13} />
        {config.label}
      </span>
      {isRoleAccount && (
        <span
          title="Role-based business address (e.g. sales, support, info). Deliverability score is not penalized."
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800"
        >
          Role: {roleCategory || 'business'}
        </span>
      )}
      {approved && (
        <span
          title="Explicitly reviewed and approved for outreach campaigns"
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-200 border border-emerald-300 dark:border-emerald-700"
        >
          <RiCheckDoubleLine size={11} /> Approved
        </span>
      )}
    </div>
  );
}

export default function LeadVerificationModal({ lead: initialLead, isOpen, onClose, onUpdated }) {
  const notify = useNotify();
  const [currentLead, setCurrentLead] = useState(initialLead);
  const [verifying, setVerifying] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [overrideStatus, setOverrideStatus] = useState(initialLead?.email_verification_status || 'domain_validated');
  const [overrideNote, setOverrideNote] = useState('');
  const [showOverrideForm, setShowOverrideForm] = useState(false);

  useEffect(() => {
    setCurrentLead(initialLead);
    setOverrideStatus(initialLead?.email_verification_status || 'domain_validated');
  }, [initialLead]);

  if (!isOpen || !currentLead) return null;

  const lead = currentLead;
  const result = lead.email_verification_result || {};
  const status = lead.email_verification_status || 'not_verified';
  const syntax = result.syntax || {};
  const domain = result.domain || {};
  const disposable = result.disposable || {};
  const roleBased = result.role_based || {};
  const typo = result.typo || {};
  const smtp = result.smtp || {};
  const overrideAudit = result.override || {};
  const approvalAudit = result.approval_audit || {};

  const handleVerify = async (checkSmtp = false) => {
    setVerifying(true);
    try {
      const res = await api.post(`/leads/${lead.id}/verify?check_smtp=${checkSmtp}`);
      notify({ type: 'success', message: `Verification complete: ${res.status}` });
      const updatedLead = {
        ...lead,
        email_verification_status: res.status,
        email_verification_result: res.result || res,
      };
      setCurrentLead(updatedLead);
      if (onUpdated) onUpdated(updatedLead);
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Verification failed' });
    } finally {
      setVerifying(false);
    }
  };

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    setOverriding(true);
    try {
      const res = await api.post(`/leads/${lead.id}/override-verification`, {
        status: overrideStatus,
        note: overrideNote,
      });
      notify({ type: 'success', message: `Status updated to ${res.status}` });
      setShowOverrideForm(false);
      setOverrideNote('');
      const updatedLead = {
        ...lead,
        email_verification_status: res.status,
        email_verification_result: {
          ...(lead.email_verification_result || {}),
          status: res.status,
          override: res.override,
          approved: res.status === 'valid' || res.status === 'domain_validated',
        },
      };
      setCurrentLead(updatedLead);
      if (onUpdated) onUpdated(updatedLead);
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to update status' });
    } finally {
      setOverriding(false);
    }
  };

  const handleDirectApprove = async () => {
    setOverriding(true);
    try {
      const res = await api.post('/leads/approve-selected', {
        lead_ids: [lead.id],
        note: 'Approved directly via verification inspector',
      });
      notify({ type: 'success', message: 'Prospect approved for sending' });
      const updatedLead = {
        ...lead,
        email_verification_result: { ...(lead.email_verification_result || {}), approved: true },
      };
      setCurrentLead(updatedLead);
      if (onUpdated) onUpdated(updatedLead);
    } catch (e) {
      notify({ type: 'error', message: e.message || 'Failed to approve' });
    } finally {
      setOverriding(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-2xl w-full max-h-[92vh] flex flex-col overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <div>
            <div className="flex items-center gap-2">
              <RiShieldCheckLine className="text-teal-600 dark:text-teal-400" size={22} />
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                Email Deliverability Inspector
              </h2>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-mono">
              {lead.email} {lead.name ? `(${lead.name})` : ''}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <RiCloseLine size={22} />
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-6 space-y-6 overflow-y-auto flex-1">
          {/* Main Status Banner */}
          <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800">
            <div>
              <span className="text-xs uppercase font-semibold text-slate-400 tracking-wider block mb-1">
                Classification
              </span>
              <div className="flex items-center gap-2">
                {getVerificationBadge(
                  status,
                  roleBased.is_role_account,
                  roleBased.role_category,
                  result.approved
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleVerify(false)}
                disabled={verifying}
                className="flex items-center gap-1.5 text-xs"
              >
                <RiRefreshLine size={14} className={verifying ? 'animate-spin' : ''} />
                {verifying ? 'Verifying...' : 'Verify DNS/MX'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => handleVerify(true)}
                disabled={verifying}
                title="Runs DNS check plus direct SMTP RCPT TO mailbox probe"
                className="flex items-center gap-1.5 text-xs"
              >
                <RiShieldCheckLine size={14} />
                Deep SMTP Probe
              </Button>
            </div>
          </div>

          {/* Reason & Explanation */}
          {result.reason && (
            <div className="p-3.5 rounded-lg bg-teal-50/60 dark:bg-teal-950/20 border border-teal-200/60 dark:border-teal-900/40 text-xs text-teal-900 dark:text-teal-200 flex items-start gap-2.5">
              <RiInformationLine size={16} className="text-teal-600 dark:text-teal-400 mt-0.5 shrink-0" />
              <div>
                <span className="font-semibold block mb-0.5">Diagnostic Finding:</span>
                <span>{result.reason}</span>
                {result.confidence && (
                  <span className="block mt-1 text-[11px] text-teal-700 dark:text-teal-300">
                    Confidence level: <strong className="capitalize">{result.confidence}</strong>
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Domain Mismatch Advisory Banner */}
          {result.domain_mismatch?.has_mismatch && (
            <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/40 dark:bg-amber-950/30 dark:border-amber-800/60 text-xs space-y-2">
              <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold">
                <RiAlertLine size={17} className="text-amber-500 shrink-0" />
                <span>Website Domain Mismatch Advisory</span>
              </div>
              <p className="text-amber-900 dark:text-amber-200 leading-relaxed text-[11px]">
                {result.domain_mismatch.advisory}
              </p>
              {result.domain_mismatch.suggested_email && (
                <div className="pt-2 flex flex-wrap items-center justify-between gap-2 border-t border-amber-500/20 text-[11px]">
                  <span className="text-amber-800 dark:text-amber-200 font-mono">
                    Suggested alternate email: <strong>{result.domain_mismatch.suggested_email}</strong>
                  </span>
                  <span className="text-amber-700/80 dark:text-amber-400/80 italic text-[10px]">
                    (Verify with prospect before updating)
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Detailed Verification Checks */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            {/* Syntax Check */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">1. Syntax & Format</span>
                {syntax.valid === true ? (
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <RiCheckboxCircleLine size={13} /> RFC 5322 Valid
                  </span>
                ) : syntax.valid === false ? (
                  <span className="text-rose-600 dark:text-rose-400 font-medium flex items-center gap-1">
                    <RiCloseCircleLine size={13} /> Invalid
                  </span>
                ) : (
                  <span className="text-slate-400 font-medium flex items-center gap-1">
                    <RiTimeLine size={13} /> Not Scanned
                  </span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                {syntax.normalized || syntax.normalized_email || lead.email}
              </p>
              {syntax.error && (
                <p className="text-rose-600 dark:text-rose-400 text-[11px] mt-1 font-sans">
                  {syntax.error}
                </p>
              )}
            </div>

            {/* Domain & MX */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">2. Mail Exchange (MX)</span>
                {domain.has_mx ? (
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <RiCheckboxCircleLine size={13} /> Active
                  </span>
                ) : domain.is_null_mx ? (
                  <span className="text-rose-600 dark:text-rose-400 font-medium flex items-center gap-1">
                    <RiCloseCircleLine size={13} /> RFC 7505 Null MX
                  </span>
                ) : domain.dns_checked ? (
                  <span className="text-rose-600 dark:text-rose-400 font-medium flex items-center gap-1">
                    <RiCloseCircleLine size={13} /> No MX
                  </span>
                ) : (
                  <span className="text-slate-400 font-medium">Not scanned</span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-[11px] truncate">
                {domain.primary_mx || domain.name || 'Domain unverified'}
                {domain.detected_provider && ` (${domain.detected_provider})`}
              </p>
            </div>

            {/* Disposable Email Check */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">3. Disposable / Burner</span>
                {disposable.is_disposable ? (
                  <span className="text-rose-600 dark:text-rose-400 font-medium flex items-center gap-1">
                    <RiCloseCircleLine size={13} /> Disposable
                  </span>
                ) : (
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <RiCheckboxCircleLine size={13} /> Clean
                  </span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-[11px]">
                {disposable.is_disposable
                  ? 'Matched in 97,000+ disposable domain database'
                  : 'Domain is not in disposable temporary email list'}
              </p>
            </div>

            {/* Role-based Account Check */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">4. Role Business Account</span>
                {roleBased.is_role_account ? (
                  <span className="text-indigo-600 dark:text-indigo-400 font-medium capitalize">
                    {roleBased.role_category || 'Role'} Address
                  </span>
                ) : (
                  <span className="text-slate-400 font-medium">Personal / Direct</span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-[11px]">
                {roleBased.is_role_account
                  ? 'Business department address; kept deliverable without penalty'
                  : 'Direct individual contact address'}
              </p>
            </div>

            {/* Typo Suggestion */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">5. Typo Suggestion</span>
                {typo.has_typo_risk ? (
                  <span className="text-amber-600 dark:text-amber-400 font-medium">
                    Did you mean {typo.suggestion}?
                  </span>
                ) : (
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium">None detected</span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-[11px]">
                {typo.has_typo_risk
                  ? `Known common typo for ${typo.suggestion}`
                  : 'Standard domain spelling verified'}
              </p>
            </div>

            {/* SMTP Mailbox Verification */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-slate-700 dark:text-slate-300">6. SMTP Mailbox Probe</span>
                {smtp.mailbox_verified ? (
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <RiCheckboxCircleLine size={13} /> 250 Accepted
                  </span>
                ) : smtp.port_25_blocked ? (
                  <span className="text-amber-600 dark:text-amber-400 font-medium">Port 25 Restricted</span>
                ) : smtp.checked ? (
                  <span className="text-slate-500 font-medium">{smtp.response_message || 'Unconfirmed'}</span>
                ) : (
                  <span className="text-slate-400 font-medium">Not probed</span>
                )}
              </div>
              <p className="text-slate-500 dark:text-slate-400 text-[11px]">
                {smtp.is_catch_all
                  ? 'Domain is catch-all (accepts any mailbox probe)'
                  : smtp.mailbox_verified
                  ? 'Recipient accepted by destination mail exchange'
                  : 'Subject to remote mail-server anti-abuse limits'}
              </p>
            </div>
          </div>

          {/* Audit Trail (if overridden) */}
          {(overrideAudit.by_user || approvalAudit.approved_by) && (
            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 text-xs text-slate-600 dark:text-slate-300 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold text-slate-700 dark:text-slate-200">
                <RiFileShield2Line size={15} /> Audit Trail
              </div>
              {overrideAudit.by_user && (
                <p>
                  Status manually overridden to <strong>{overrideAudit.new_status}</strong> by{' '}
                  <span className="font-mono">{overrideAudit.by_user}</span> on{' '}
                  {new Date(overrideAudit.overridden_at).toLocaleString()}.
                  {overrideAudit.note && <span className="block italic">Note: "{overrideAudit.note}"</span>}
                </p>
              )}
              {approvalAudit.approved_by && (
                <p>
                  Approved by <span className="font-mono">{approvalAudit.approved_by}</span> on{' '}
                  {new Date(approvalAudit.approved_at).toLocaleString()}.
                </p>
              )}
            </div>
          )}

          {/* Campaign Gate Protection Notice */}
          <div className="p-3 rounded-lg bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-900/30 text-xs text-amber-900 dark:text-amber-200">
            <span className="font-semibold block mb-0.5">Campaign Verification Gate Policy:</span>
            <span>
              Invalid addresses are strictly blocked from sequence dispatch. Unknown, Catch-All, Risky, and
              Unverified contacts require explicit review & approval before emails can be scheduled.
            </span>
          </div>

          {/* Manual Override & Approval Section */}
          <div className="border-t border-slate-200 dark:border-slate-800 pt-4">
            {!showOverrideForm ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  Need to adjust this prospect's deliverability status or approve for sending?
                </div>
                <div className="flex items-center gap-2">
                  {!result.approved && status !== 'invalid' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={handleDirectApprove}
                      disabled={overriding}
                      className="text-xs flex items-center gap-1"
                    >
                      <RiCheckDoubleLine size={13} />
                      Approve for Campaigns
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowOverrideForm(true)}
                    className="text-xs"
                  >
                    Manual Override
                  </Button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleOverrideSubmit} className="space-y-3 p-4 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider">
                    Manual Verification Override
                  </h4>
                  <button
                    type="button"
                    onClick={() => setShowOverrideForm(false)}
                    className="text-xs text-slate-400 hover:text-slate-600"
                  >
                    Cancel
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Target Status
                    </label>
                    <select
                      value={overrideStatus}
                      onChange={(e) => setOverrideStatus(e.target.value)}
                      className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 text-slate-900 dark:text-white"
                    >
                      <option value="valid">Valid (Mailbox Verified)</option>
                      <option value="domain_validated">Domain Validated (DNS/MX Active)</option>
                      <option value="invalid">Invalid (Blocked)</option>
                      <option value="risky">Risky</option>
                      <option value="catch_all">Catch-All</option>
                      <option value="unknown">Unknown</option>
                      <option value="not_verified">Not Verified</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Audit Note / Justification
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Verified manually via direct phone contact"
                      value={overrideNote}
                      onChange={(e) => setOverrideNote(e.target.value)}
                      className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 text-slate-900 dark:text-white"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setShowOverrideForm(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    size="sm"
                    variant="primary"
                    disabled={overriding}
                  >
                    {overriding ? 'Saving...' : 'Apply Status Override'}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

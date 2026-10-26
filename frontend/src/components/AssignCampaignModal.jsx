import { useState, useEffect } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';
import { useNotify } from '../context/NotificationContext';
import {
  RiCloseLine,
  RiCheckDoubleLine,
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiAlertLine,
  RiShieldCheckLine,
  RiInformationLine,
} from 'react-icons/ri';

export default function AssignCampaignModal({
  isOpen,
  onClose,
  selectedLeadIds = [],
  campaigns = [],
  initialCampaignId = '',
  onAssigned,
}) {
  const notify = useNotify();

  const [campaignId, setCampaignId] = useState(initialCampaignId ? String(initialCampaignId) : '');
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState(null);
  const [skipOtherActive, setSkipOtherActive] = useState(false);
  const [enrolling, setEnrolling] = useState(false);

  useEffect(() => {
    if (initialCampaignId) {
      setCampaignId(String(initialCampaignId));
    } else if (campaigns.length > 0 && !campaignId) {
      setCampaignId(String(campaigns[0].id));
    }
  }, [initialCampaignId, campaigns]);

  // Whenever campaignId changes and modal is open, load dry_run preview summary
  useEffect(() => {
    if (!isOpen || !campaignId || !selectedLeadIds.length) {
      setSummary(null);
      return;
    }

    let isMounted = true;
    setLoading(true);

    api
      .post('/leads/bulk-campaign-assign', {
        campaign_id: parseInt(campaignId, 10),
        lead_ids: selectedLeadIds,
        dry_run: true,
      })
      .then((res) => {
        if (isMounted && res && res.summary) {
          setSummary(res.summary);
        }
      })
      .catch((err) => {
        if (isMounted) {
          notify({ type: 'error', message: err.message || 'Failed to analyze campaign assignment' });
          setSummary(null);
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, campaignId, selectedLeadIds]);

  if (!isOpen) return null;

  const selectedCampaign = campaigns.find((c) => String(c.id) === String(campaignId));
  const isCampaignPaused = summary ? summary.campaign_paused : selectedCampaign?.paused;

  const handleConfirm = async () => {
    if (!campaignId || !selectedLeadIds.length) return;
    setEnrolling(true);
    try {
      const res = await api.post('/leads/bulk-campaign-assign', {
        campaign_id: parseInt(campaignId, 10),
        lead_ids: selectedLeadIds,
        dry_run: false,
        skip_other_active: skipOtherActive,
      });

      notify({
        type: 'success',
        message: `Assigned ${res.assigned} prospect(s) to campaign "${res.summary?.campaign_name || selectedCampaign?.name || 'Campaign'}".`,
      });

      if (onAssigned) {
        onAssigned(res);
      }
      onClose();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to assign prospects to campaign' });
    } finally {
      setEnrolling(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 w-full max-w-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <RiCheckDoubleLine className="text-teal-600" size={18} />
              Assign Prospects to Campaign
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Review eligibility, existing enrollments, and delivery safety rules before assigning.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
          >
            <RiCloseLine size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto space-y-5">
          {/* Campaign Selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Select Target Campaign:
            </label>
            <select
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              className="w-full text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2 text-slate-900 dark:text-white font-medium focus:ring-2 focus:ring-teal-500 focus:outline-none"
            >
              <option value="">-- Choose a Campaign --</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.paused ? '(Paused)' : '(Active)'}
                </option>
              ))}
            </select>
          </div>

          {loading ? (
            <div className="py-12 text-center text-slate-400 text-xs flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
              Checking prospects against campaign rules and deliverability safeguards...
            </div>
          ) : summary ? (
            <>
              {/* Campaign status indicator */}
              {isCampaignPaused ? (
                <div className="p-3.5 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl text-xs text-amber-800 dark:text-amber-200 flex items-start gap-2.5">
                  <RiInformationLine size={18} className="shrink-0 mt-0.5 text-amber-600" />
                  <div>
                    <p className="font-semibold">Target campaign is PAUSED</p>
                    <p className="mt-0.5 text-amber-700 dark:text-amber-300">
                      Prospects will be enrolled safely without activating sending. No emails will be scheduled or sent until you resume the campaign.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="p-3.5 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-xl text-xs text-emerald-800 dark:text-emerald-200 flex items-start gap-2.5">
                  <RiCheckboxCircleLine size={18} className="shrink-0 mt-0.5 text-emerald-600" />
                  <div>
                    <p className="font-semibold">Target campaign is ACTIVE</p>
                    <p className="mt-0.5 text-emerald-700 dark:text-emerald-300">
                      Eligible verified prospects will be assigned sequence queue slots based on your sending schedules.
                    </p>
                  </div>
                </div>
              )}

              {/* 4 Stat Breakdown Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40">
                  <div className="text-[11px] text-slate-500">Selected</div>
                  <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">
                    {summary.total_selected}
                  </div>
                </div>

                <div className="p-3.5 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/30">
                  <div className="text-[11px] font-medium text-emerald-700 dark:text-emerald-300 flex items-center gap-1">
                    <RiShieldCheckLine size={13} /> Ready to Send
                  </div>
                  <div className="text-xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">
                    {summary.eligible}
                  </div>
                  <div className="text-[10px] text-emerald-600/80">Valid / Domain Validated</div>
                </div>

                <div className="p-3.5 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30">
                  <div className="text-[11px] font-medium text-amber-700 dark:text-amber-300 flex items-center gap-1">
                    <RiAlertLine size={13} /> Needs Review
                  </div>
                  <div className="text-xl font-bold text-amber-600 dark:text-amber-400 mt-1">
                    {summary.needs_review}
                  </div>
                  <div className="text-[10px] text-amber-600/80">Added paused for review</div>
                </div>

                <div className="p-3.5 rounded-xl border border-rose-200 dark:border-rose-800 bg-rose-50/50 dark:bg-rose-950/30">
                  <div className="text-[11px] font-medium text-rose-700 dark:text-rose-300 flex items-center gap-1">
                    <RiCloseCircleLine size={13} /> Blocked
                  </div>
                  <div className="text-xl font-bold text-rose-600 dark:text-rose-400 mt-1">
                    {summary.blocked}
                  </div>
                  <div className="text-[10px] text-rose-600/80">Invalid / Suppressed</div>
                </div>
              </div>

              {/* Already enrolled notice */}
              {summary.already_enrolled > 0 && (
                <div className="p-3 bg-slate-100 dark:bg-slate-800 rounded-lg text-xs text-slate-600 dark:text-slate-300 flex items-center gap-2">
                  <RiInformationLine size={15} className="shrink-0 text-slate-400" />
                  <span>
                    <strong>{summary.already_enrolled}</strong> prospect(s) are already in this campaign and will be skipped to prevent duplicate enrollment.
                  </span>
                </div>
              )}

              {/* Overlapping active campaigns warning */}
              {summary.other_active_campaigns > 0 && (
                <div className="p-4 bg-orange-50 dark:bg-orange-950/40 border border-orange-200 dark:border-orange-800 rounded-xl space-y-3">
                  <div className="flex items-start gap-2.5">
                    <RiAlertLine size={18} className="shrink-0 text-orange-600 mt-0.5" />
                    <div className="text-xs">
                      <p className="font-semibold text-orange-900 dark:text-orange-200">
                        Overlapping Campaign Outreach Detected ({summary.other_active_campaigns} prospect{summary.other_active_campaigns > 1 ? 's' : ''})
                      </p>
                      <p className="text-orange-800 dark:text-orange-300 mt-0.5">
                        These prospects are actively receiving emails from another running campaign. Enrolling them in this campaign may cause overlapping outreach.
                      </p>
                    </div>
                  </div>

                  {summary.other_active_details && summary.other_active_details.length > 0 && (
                    <div className="max-h-24 overflow-y-auto space-y-1 bg-white/70 dark:bg-slate-900/60 p-2.5 rounded-lg border border-orange-200/60 text-[11px]">
                      {summary.other_active_details.map((item, idx) => (
                        <div key={idx} className="flex items-center justify-between">
                          <span className="font-medium text-slate-800 dark:text-slate-200">{item.email}</span>
                          <span className="text-orange-700 dark:text-orange-400 font-mono text-[10px]">
                            {item.campaigns.join(', ')}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  <label className="flex items-center gap-2 text-xs font-semibold text-orange-950 dark:text-orange-200 cursor-pointer pt-1">
                    <input
                      type="checkbox"
                      checked={skipOtherActive}
                      onChange={(e) => setSkipOtherActive(e.target.checked)}
                      className="rounded border-orange-300 text-orange-600 focus:ring-orange-500"
                    />
                    Skip these {summary.other_active_campaigns} prospect(s) to protect from overlapping outreach
                  </label>
                </div>
              )}

              {/* Blocked contacts details */}
              {summary.blocked > 0 && summary.blocked_details && summary.blocked_details.length > 0 && (
                <div className="p-3.5 bg-rose-50/60 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 rounded-xl space-y-2">
                  <div className="text-xs font-semibold text-rose-800 dark:text-rose-200 flex items-center gap-1.5">
                    <RiCloseCircleLine size={14} /> Excluded Contacts ({summary.blocked}):
                  </div>
                  <div className="max-h-24 overflow-y-auto space-y-1 text-[11px]">
                    {summary.blocked_details.map((b, idx) => (
                      <div key={idx} className="flex items-center justify-between text-rose-700 dark:text-rose-300">
                        <span className="font-mono">{b.email}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-100 dark:bg-rose-900/60 text-rose-800 dark:text-rose-200">
                          {b.reason}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-500 text-center py-6">
              Please choose a target campaign to review enrollment details.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <Button size="sm" variant="outline" onClick={onClose} disabled={enrolling}>
            Cancel
          </Button>

          <Button
            size="sm"
            variant="primary"
            onClick={handleConfirm}
            disabled={!summary || enrolling || (summary.eligible === 0 && summary.needs_review === 0)}
            className="bg-teal-600 hover:bg-teal-700 text-white shadow-sm flex items-center gap-1.5"
          >
            {enrolling ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Assigning...
              </>
            ) : (
              <>
                <RiCheckDoubleLine size={15} />
                Confirm & Assign ({(summary ? summary.eligible + summary.needs_review : 0) - (skipOtherActive ? summary?.other_active_campaigns || 0 : 0)})
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

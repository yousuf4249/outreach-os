import { useState, useRef, useEffect } from 'react';
import {
  RiEyeLine,
  RiEyeOffLine,
  RiCursorLine,
  RiReplyLine,
  RiCheckLine,
  RiCloseLine,
  RiAlertLine,
  RiSendPlaneLine,
  RiInformationLine,
} from 'react-icons/ri';

function formatDateTime(value) {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * Clean, compact, single-line tracking indicator for Unified Inbox & Prospect Details.
 * Displays subtle status pills (Sent, Open Detected, Clicked, Replied, Not Tracked)
 * with an interactive popover for detailed telemetry on demand.
 */
export default function EmailTrackingCard({ tracking, isSent = true }) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const containerRef = useRef(null);

  // Close popover on click outside or Escape key
  useEffect(() => {
    if (!popoverOpen) return;

    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setPopoverOpen(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setPopoverOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [popoverOpen]);

  if (!isSent || !tracking) {
    return null;
  }

  const isTracked = tracking.tracked !== false && tracking.tracking_status !== 'not_tracked';
  const openCount = Number(tracking.open_count || 0);
  const clickCount = Number(tracking.click_count || 0);
  const isReplied = Boolean(tracking.replied);
  const isFailed = tracking.tracking_status === 'failed';

  return (
    <div className="relative mt-2 inline-block max-w-full" ref={containerRef}>
      {/* Single-Line Compact Indicator Row */}
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-medium leading-none select-none">
        {/* If tracking is disabled or plain text */}
        {!isTracked ? (
          <button
            type="button"
            onClick={() => setPopoverOpen(!popoverOpen)}
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-slate-200/80 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400 dark:hover:bg-slate-800 transition-colors cursor-pointer"
            title="Click to view tracking details"
          >
            <RiEyeOffLine size={13} className="text-slate-400 shrink-0" />
            <span>Not Tracked</span>
          </button>
        ) : isFailed ? (
          <button
            type="button"
            onClick={() => setPopoverOpen(!popoverOpen)}
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300 transition-colors cursor-pointer"
            title="Click to view delivery details"
          >
            <RiAlertLine size={13} className="text-rose-500 shrink-0" />
            <span>Delivery Failed</span>
          </button>
        ) : (
          <>
            {/* Sent Indicator (Base status) */}
            <button
              type="button"
              onClick={() => setPopoverOpen(!popoverOpen)}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border transition-colors cursor-pointer ${
                openCount === 0 && !isReplied && clickCount === 0
                  ? 'border-slate-200 bg-slate-100/90 text-slate-600 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300'
                  : 'border-slate-200/60 bg-slate-50/70 text-slate-500 hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400'
              }`}
              title="Click for full tracking details"
            >
              <RiCheckLine size={13} className="text-slate-400 shrink-0" />
              <span>Sent</span>
            </button>

            {/* Open Detected Indicator */}
            {openCount > 0 && (
              <button
                type="button"
                onClick={() => setPopoverOpen(!popoverOpen)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-emerald-200/80 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300 transition-colors cursor-pointer font-semibold"
                title={`Open detected (${openCount} event${openCount > 1 ? 's' : ''}). Click for details.`}
              >
                <RiEyeLine size={13} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
                <span>Open Detected{openCount > 1 ? ` (${openCount})` : ''}</span>
              </button>
            )}

            {/* Clicked Indicator */}
            {clickCount > 0 && (
              <button
                type="button"
                onClick={() => setPopoverOpen(!popoverOpen)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-indigo-200/80 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 dark:border-indigo-900/50 dark:bg-indigo-950/40 dark:text-indigo-300 transition-colors cursor-pointer font-semibold"
                title={`Link clicked (${clickCount} time${clickCount > 1 ? 's' : ''}). Click for details.`}
              >
                <RiCursorLine size={12} className="text-indigo-600 dark:text-indigo-400 shrink-0" />
                <span>Clicked{clickCount > 1 ? ` (${clickCount})` : ''}</span>
              </button>
            )}

            {/* Replied Indicator */}
            {isReplied && (
              <button
                type="button"
                onClick={() => setPopoverOpen(!popoverOpen)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-purple-200/80 bg-purple-50 text-purple-700 hover:bg-purple-100 dark:border-purple-900/50 dark:bg-purple-950/40 dark:text-purple-300 transition-colors cursor-pointer font-semibold"
                title="Prospect replied to this message. Click for details."
              >
                <RiReplyLine size={13} className="text-purple-600 dark:text-purple-400 shrink-0" />
                <span>Replied</span>
              </button>
            )}
          </>
        )}
      </div>

      {/* Floating Detailed Popover on Click */}
      {popoverOpen && (
        <div className="absolute left-0 top-full mt-2 z-30 w-72 sm:w-80 rounded-xl border border-slate-200 bg-white p-3.5 shadow-xl text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 animate-fade-in">
          {/* Popover Header */}
          <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2.5 dark:border-slate-800">
            <span className="font-bold text-[11px] uppercase tracking-wider text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
              <RiInformationLine size={14} className="text-primary-500" />
              Email Telemetry
            </span>
            <button
              type="button"
              onClick={() => setPopoverOpen(false)}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-0.5 rounded"
            >
              <RiCloseLine size={16} />
            </button>
          </div>

          {/* Details List */}
          <div className="space-y-2 text-[11px]">
            {/* Sent Status */}
            <div className="flex items-start justify-between gap-2">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                <RiSendPlaneLine size={12} className="text-slate-400" /> Sent:
              </span>
              <span className="font-mono text-slate-800 dark:text-slate-200 text-right">
                {formatDateTime(tracking.sent_at)}
              </span>
            </div>

            {/* Opens */}
            <div className="flex items-start justify-between gap-2">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                <RiEyeLine size={12} className={openCount > 0 ? 'text-emerald-500' : 'text-slate-400'} /> Opens:
              </span>
              <div className="text-right">
                <span className={`font-semibold ${openCount > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-600 dark:text-slate-400'}`}>
                  {openCount > 0 ? `${openCount} event${openCount > 1 ? 's' : ''} detected` : isTracked ? 'None detected yet' : 'Not tracked'}
                </span>
                {tracking.first_opened_at && (
                  <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                    1st: {formatDateTime(tracking.first_opened_at)}
                  </div>
                )}
              </div>
            </div>

            {/* Clicks */}
            <div className="flex items-start justify-between gap-2">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                <RiCursorLine size={12} className={clickCount > 0 ? 'text-indigo-500' : 'text-slate-400'} /> Link Clicks:
              </span>
              <div className="text-right">
                <span className={`font-semibold ${clickCount > 0 ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-600 dark:text-slate-400'}`}>
                  {clickCount > 0 ? `${clickCount} click${clickCount > 1 ? 's' : ''}` : 'None recorded'}
                </span>
                {tracking.first_clicked_at && (
                  <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                    1st: {formatDateTime(tracking.first_clicked_at)}
                  </div>
                )}
              </div>
            </div>

            {/* Replies */}
            <div className="flex items-start justify-between gap-2">
              <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                <RiReplyLine size={12} className={isReplied ? 'text-purple-500' : 'text-slate-400'} /> Reply:
              </span>
              <div className="text-right">
                <span className={`font-semibold ${isReplied ? 'text-purple-600 dark:text-purple-400' : 'text-slate-500'}`}>
                  {isReplied ? 'Replied' : 'Awaiting reply'}
                </span>
                {tracking.replied_at && (
                  <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                    {formatDateTime(tracking.replied_at)}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Privacy & Deliverability Note */}
          <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 text-[10px] leading-tight text-slate-400 dark:text-slate-500">
            Open events are registered via a 1x1 image pixel. Privacy features (such as Apple Mail Protection) and mail proxies may fetch images automatically.
          </div>
        </div>
      )}
    </div>
  );
}

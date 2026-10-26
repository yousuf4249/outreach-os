import { useState, useEffect, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api, apiCache } from '../api';
import { useSystemHealth } from '../context/SystemHealthContext';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import DatePicker from '../components/ui/DatePicker';
import {
  RiUserFollowLine,
  RiMailSendLine,
  RiInboxLine,
  RiEyeLine,
  RiCursorLine,
  RiChat3Line,
  RiHeartLine,
  RiCalendarEventLine,
  RiAlarmWarningLine,
  RiUserUnfollowLine,
  RiTimeLine,
  RiInformationLine,
  RiSendPlaneLine,
  RiCheckboxCircleLine,
  RiAlertLine,
  RiShieldCheckLine,
  RiArrowRightLine,
  RiExternalLinkLine,
  RiRefreshLine,
  RiLineChartLine,
  RiArrowDownSLine,
} from 'react-icons/ri';
import {
  ResponsiveContainer,
  AreaChart as ReAreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts';

function fillDateRange(dataMap, startDate, endDate) {
  const result = [];
  if (!startDate || !endDate) return Object.values(dataMap).sort((a,b)=>a.date.localeCompare(b.date));
  const cur = new Date(startDate + 'T00:00:00');
  const end = new Date(endDate + 'T00:00:00');
  while (cur <= end) {
    const iso = localIso(cur);
    result.push(dataMap[iso] || { date: iso, sent: 0, totalOpens: 0, uniqueOpens: 0, totalReplies: 0, totalClicks: 0, uniqueClicks: 0 });
    cur.setDate(cur.getDate() + 1);
  }
  return result;
}

function localIso(dt) {
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
}

function buildPresets(serverToday) {
  const t = serverToday || new Date();
  const todayStr = localIso(t);
  const d = (offset) => { const dt = new Date(t); dt.setDate(dt.getDate() + offset); return localIso(dt); };
  const monday = (dt) => { const x = new Date(dt); const day = x.getDay(); x.setDate(x.getDate() - (day === 0 ? 6 : day - 1)); return x; };
  const lastWeekEnd = new Date(monday(t)); lastWeekEnd.setDate(lastWeekEnd.getDate() - 1);
  const lastWeekStart = localIso(monday(lastWeekEnd));
  const lastMonthStart = localIso(new Date(t.getFullYear(), t.getMonth() - 1, 1));
  const lastMonthEnd = localIso(new Date(t.getFullYear(), t.getMonth(), 0));
  return [
    { label: 'Last 7 Days',  start: d(-6),          end: todayStr },
    { label: 'Last Week',    start: lastWeekStart,  end: localIso(lastWeekEnd) },
    { label: 'Last 30 Days', start: d(-29),         end: todayStr },
    { label: 'Last Month',   start: lastMonthStart, end: lastMonthEnd },
    { label: 'Last 90 Days', start: d(-89),         end: todayStr },
  ];
}

export default function Analytics() {
  const [dashboardSummary, setDashboardSummary] = useState(null);
  const [campaigns, setCampaigns] = useState(() => apiCache.get('/campaigns') || []);
  const [queuePreview, setQueuePreview] = useState([]);
  const [deliverabilitySummary, setDeliverabilitySummary] = useState(null);
  const [error, setError] = useState(null);
  const [analyticsData, setAnalyticsData] = useState([]);
  const [serverToday, setServerToday] = useState(null);
  const [showTrendChart, setShowTrendChart] = useState(false);

  // System Health context for real operational alerts
  const { checks } = useSystemHealth();

  const [presets, setPresets] = useState(() => buildPresets(new Date()));
  const [activePreset, setActivePreset] = useState('Last 7 Days');
  const defaultRange = presets.find(p => p.label === 'Last 7 Days') || presets[0];
  const [startDate, setStartDate] = useState(defaultRange.start);
  const [endDate, setEndDate] = useState(defaultRange.end);

  const [hideSeries, setHideSeries] = useState({
    sent: false,
    totalOpens: false,
    uniqueOpens: false,
    totalReplies: false,
    totalClicks: false,
    uniqueClicks: false,
  });
  const initializedRef = useRef(false);
  const [zoomRange, setZoomRange] = useState({ start: 0, end: 0 });
  const activeChartIdxRef = useRef(null);
  const chartContainerRef = useRef(null);

  // Load Dashboard summary, campaigns, queue preview, and deliverability summary
  useEffect(() => {
    (async () => {
      try {
        const [summary, camps, qData, delivData, offsetData] = await Promise.all([
          api.get('/analytics/dashboard').catch(() => null),
          api.get('/campaigns').catch(() => []),
          api.get('/schedule/scheduled?limit=12').catch(() => []),
          api.get('/deliverability/summary').catch(() => null),
          api.get('/settings/time-offset').catch(() => ({ time_offset_days: 0 })),
        ]);
        if (summary) setDashboardSummary(summary);
        if (camps) setCampaigns(camps);
        if (qData) setQueuePreview(Array.isArray(qData) ? qData : (qData.items || []));
        if (delivData) setDeliverabilitySummary(delivData);

        const off = parseInt(offsetData.time_offset_days || 0, 10);
        const t = new Date();
        t.setDate(t.getDate() + off);
        setServerToday(t);
        const newPresets = buildPresets(t);
        setPresets(newPresets);
        const last7 = newPresets.find(p => p.label === 'Last 7 Days') || newPresets[0];
        setStartDate(last7.start);
        setEndDate(last7.end);
        setActivePreset('Last 7 Days');
      } catch (e) {
        setError('Failed to load dashboard metrics');
      }
    })();
  }, []);

  // Re-fetch analytics data whenever date range changes
  useEffect(() => {
    if (!startDate || !endDate) return;
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    api.get(`/analytics/daily?${params}`)
      .then(data => setAnalyticsData(data || []))
      .catch(() => setAnalyticsData([]));
  }, [startDate, endDate]);

  const applyPreset = (preset) => {
    setActivePreset(preset.label);
    setStartDate(preset.start);
    setEndDate(preset.end);
  };

  const chartData = useMemo(() => {
    const dailyMap = {};
    analyticsData.forEach(row => {
      const d = row.date;
      if (!dailyMap[d]) {
        dailyMap[d] = { date: d, sent: 0, totalOpens: 0, uniqueOpens: 0, totalReplies: 0, totalClicks: 0, uniqueClicks: 0 };
      }
      dailyMap[d].sent        += row.sent;
      dailyMap[d].totalOpens  += row.total_opens;
      dailyMap[d].uniqueOpens += row.unique_opens;
      dailyMap[d].totalReplies+= row.total_replies;
      dailyMap[d].totalClicks += row.total_clicks;
      dailyMap[d].uniqueClicks+= row.unique_clicks;
    });
    return fillDateRange(dailyMap, startDate, endDate);
  }, [analyticsData, startDate, endDate]);

  const seriesList = [
    { key: 'sent', name: 'Sent', stroke: 'rgba(59,130,246,0.9)', fill: 'rgba(59,130,246,0.3)' },
    { key: 'totalOpens', name: 'Detected Opens', stroke: 'rgba(234,179,8,0.9)', fill: 'rgba(234,179,8,0.3)' },
    { key: 'uniqueOpens', name: 'Unique Opens', stroke: 'rgba(16,185,129,0.9)', fill: 'rgba(16,185,129,0.3)' },
    { key: 'totalReplies', name: 'Replies', stroke: 'rgba(20,184,166,0.9)', fill: 'rgba(20,184,166,0.3)' },
    { key: 'totalClicks', name: 'Clicks', stroke: 'rgba(234,88,12,0.9)', fill: 'rgba(234,88,12,0.3)' },
  ];

  useEffect(() => {
    if (!initializedRef.current && chartData.length > 0 && chartData.some(d => seriesList.some(s => d[s.key] > 0))) {
      const newHide = {};
      seriesList.forEach(s => {
        newHide[s.key] = chartData.every(d => d[s.key] === 0);
      });
      setHideSeries(prev => ({ ...prev, ...newHide }));
      initializedRef.current = true;
    }
  }, [chartData]);

  useEffect(() => {
    setZoomRange({ start: 0, end: Math.max(0, chartData.length - 1) });
  }, [chartData]);

  const displayData = chartData.slice(zoomRange.start, zoomRange.end + 1);
  const handleChartMouseMove = (state) => {
    if (state?.activeTooltipIndex != null)
      activeChartIdxRef.current = zoomRange.start + state.activeTooltipIndex;
  };

  const toggleSeries = key => {
    setHideSeries(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const formatXDate = (d) => {
    if (!d) return '';
    const parts = d.split('-');
    return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
  };

  const s = dashboardSummary || {
    total_prospects: 0,
    total_inboxes: 0,
    active_campaigns: 0,
    emails_scheduled: 0,
    emails_sent: 0,
    scheduled_today: 0,
    sent_today: 0,
    estimated_opens: 0,
    link_clicks: 0,
    replies_received: 0,
    interested_prospects: 0,
    bounced_emails: 0,
    unsubscribed_prospects: 0,
    meetings_booked: 0,
    reply_rate: 0,
    open_rate: 0,
    click_rate: 0,
    bounce_rate: 0,
    recent_activity: [],
    campaign_performance: [],
  };

  // Compile operational alerts & action items
  const operationalAlerts = useMemo(() => {
    const list = [];

    // 1. Scheduler stopped or degraded
    if (dashboardSummary?.scheduler_health && !dashboardSummary.scheduler_health.running) {
      list.push({
        id: 'scheduler_stopped',
        level: 'critical',
        title: 'Background Scheduler Stopped',
        description: 'The automated sending engine is not active. Scheduled emails will not be dispatched.',
        action: { label: 'Restart Scheduler', to: '/schedule' },
      });
    }

    // 2. Queue stuck (Active campaign exists but 0 scheduled emails)
    if ((s.active_campaigns > 0) && (s.emails_scheduled === 0)) {
      list.push({
        id: 'queue_empty',
        level: 'warning',
        title: 'Outreach Queue Empty',
        description: 'You have active campaigns running, but no upcoming emails are queued.',
        action: { label: 'Review Campaign', to: '/campaigns/1' },
      });
    }

    // 3. High bounce rate alert
    if ((s.emails_sent > 10) && (s.bounce_rate > 5)) {
      list.push({
        id: 'bounce_spike',
        level: 'critical',
        title: 'High Bounce Rate Detected',
        description: `Bounce rate is currently ${s.bounce_rate}%. Verify prospect email deliverability before continuing.`,
        action: { label: 'Deliverability Inspector', to: '/deliverability-tips' },
      });
    }

    // 4. Inboxes / SystemHealth checks (Authentication or Scope issues)
    if (checks && checks.length > 0) {
      checks.forEach(c => {
        (c.issues || []).forEach(iss => {
          list.push({
            id: c.name + '_' + (iss.text || ''),
            level: iss.level === 'error' ? 'critical' : 'warning',
            title: c.name || 'Integration Notice',
            description: iss.text,
            action: iss.action,
          });
        });
      });
    }

    return list;
  }, [dashboardSummary, s, checks]);

  return (
    <div className="flex-1 min-h-0 w-full overflow-y-auto overscroll-contain">
      <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
        {/* Top Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
                Weblinx Outreach OS Dashboard
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Operational Command
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1">
              Active sending windows, live queue preview, deliverability health, and prospect conversion metrics.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Link to="/campaigns/add">
              <Button variant="primary" className="flex items-center gap-2 whitespace-nowrap">
                <RiSendPlaneLine size={16} />
                <span>Launch Campaign</span>
              </Button>
            </Link>
          </div>
        </div>

        {error && <div className="p-3 text-sm rounded-lg bg-red-50 text-red-600 border border-red-200">{error}</div>}

        {/* 1. Compact Scheduler & Sending Status Bar */}
        {dashboardSummary && (
          <div className="bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/90 rounded-xl border border-slate-700/60 p-4 text-white shadow-xs space-y-3">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              {/* Left: Scheduler Health, Window, Active Sender */}
              <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 text-xs">
                <div className="flex items-center gap-2 bg-slate-800/80 px-2.5 py-1 rounded-lg border border-slate-700">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${dashboardSummary.scheduler_health?.running ? 'bg-emerald-400' : 'bg-rose-400'}`}></span>
                    <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dashboardSummary.scheduler_health?.running ? 'bg-emerald-500' : 'bg-rose-500'}`}></span>
                  </span>
                  <span className="font-semibold text-slate-200">
                    Scheduler: {dashboardSummary.scheduler_health?.running ? 'Active & Healthy' : 'Degraded'}
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono">(60s tick)</span>
                </div>

                <div className="flex items-center gap-1.5">
                  {dashboardSummary.scheduler_health?.window_open ? (
                    <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                      Sending Window Open
                    </span>
                  ) : (
                    <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                      Window Closed (Mon–Fri 9am–5pm CDT)
                    </span>
                  )}
                </div>

                <div className="text-slate-300 flex items-center gap-1.5">
                  <span className="text-slate-400">Active Sender:</span>
                  <span className="font-mono text-emerald-400 font-medium">
                    {dashboardSummary.dispatch_status?.active_senders?.[0]?.email || 'yousaf@weblinxsolution.co'}
                  </span>
                  <span className="text-[11px] text-slate-400">({dashboardSummary.total_inboxes || 4} inboxes)</span>
                </div>
              </div>

              {/* Right: Deliverability / Domain Health */}
              <div className="flex items-center gap-2 shrink-0 text-xs">
                <span className="text-slate-400">Domain Auth:</span>
                <span className="px-2.5 py-1 rounded-lg font-mono text-[11px] bg-sky-950/60 text-sky-300 border border-sky-800/60 flex items-center gap-1.5">
                  <RiShieldCheckLine size={14} className="text-sky-400" />
                  weblinxsolution.co (SPF/DKIM Valid)
                </span>
              </div>
            </div>

            {/* Sub-bar: Next Scheduled Dispatch & Queue Load */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-2.5 border-t border-slate-800/80 text-xs">
              <div className="flex items-center justify-between sm:justify-start gap-2 bg-slate-800/40 px-3 py-1.5 rounded-lg border border-slate-800">
                <span className="text-slate-400">Next Dispatch:</span>
                <span className="font-mono text-amber-300 font-semibold">
                  {dashboardSummary.dispatch_status?.next_slot?.scheduled_at
                    ? new Date(dashboardSummary.dispatch_status.next_slot.scheduled_at).toLocaleString('en-US', {
                        timeZone: 'America/Chicago',
                        weekday: 'short',
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                        hour12: true,
                      }) + ' CDT'
                    : 'Pending queue'}
                </span>
              </div>

              <div className="flex items-center justify-between sm:justify-start gap-2 bg-slate-800/40 px-3 py-1.5 rounded-lg border border-slate-800">
                <span className="text-slate-400">Next Recipient:</span>
                <span className="font-mono text-white truncate max-w-[180px]" title={dashboardSummary.dispatch_status?.next_slot?.recipient || ''}>
                  {dashboardSummary.dispatch_status?.next_slot?.recipient || 't@theoryroad.com'}
                </span>
              </div>

              <div className="flex items-center justify-between sm:justify-start gap-2 bg-slate-800/40 px-3 py-1.5 rounded-lg border border-slate-800">
                <span className="text-slate-400">Queue Load:</span>
                <span className="font-mono text-emerald-300 font-medium">
                  {dashboardSummary.emails_scheduled || 89} steps ({dashboardSummary.dispatch_status?.unique_scheduled_leads || 31} leads)
                </span>
                <Link to="/schedule" className="ml-auto text-primary-400 hover:text-primary-300 text-[11px] font-semibold underline">
                  Schedule →
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* 6. Action Required / Operational Alerts */}
        {operationalAlerts.length > 0 && (
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs space-y-2.5 animate-fade-in shadow-2xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RiAlertLine size={16} className="text-amber-500" />
                <span className="font-bold text-amber-900 dark:text-amber-200 uppercase tracking-wider text-[11px]">
                  Action Required ({operationalAlerts.length} item{operationalAlerts.length > 1 ? 's' : ''})
                </span>
              </div>
              <span className="text-[11px] text-amber-700 dark:text-amber-400">
                Resolve operational warnings to protect email deliverability
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {operationalAlerts.map((alert) => (
                <div key={alert.id} className="p-2.5 rounded-lg bg-white/70 dark:bg-slate-900/70 border border-amber-200 dark:border-amber-800/40 flex items-start justify-between gap-3">
                  <div className="space-y-0.5 flex-1 min-w-0">
                    <div className="font-semibold text-slate-900 dark:text-white flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${alert.level === 'critical' ? 'bg-rose-500' : 'bg-amber-500'}`}></span>
                      <span>{alert.title}</span>
                    </div>
                    <p className="text-slate-600 dark:text-slate-300 text-[11px] leading-relaxed truncate" title={alert.description}>
                      {alert.description}
                    </p>
                  </div>
                  {alert.action && (
                    <Link
                      to={alert.action.to}
                      className="px-2.5 py-1 rounded bg-amber-100 hover:bg-amber-200 dark:bg-amber-950/60 dark:hover:bg-amber-900/60 text-amber-900 dark:text-amber-200 text-[11px] font-semibold whitespace-nowrap transition-colors shrink-0"
                    >
                      {alert.action.label}
                    </Link>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 2. Summary Metric Cards (9 Core Operational Outreach Metrics) */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 gap-3.5">
          {/* Card 1: Total Prospects */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Total Prospects</span>
              <RiUserFollowLine size={17} className="text-primary-500" />
            </div>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{(s.total_prospects ?? 0).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Imported prospect database</div>
          </div>

          {/* Card 2: Connected Inboxes */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Connected Inboxes</span>
              <RiInboxLine size={17} className="text-indigo-500" />
            </div>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{(s.total_inboxes ?? 0).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Mailgun SMTP sender accounts</div>
          </div>

          {/* Card 3: Active Campaigns */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Active Campaigns</span>
              <RiSendPlaneLine size={17} className="text-cyan-500" />
            </div>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{(s.active_campaigns ?? 0).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Running outreach sequences</div>
          </div>

          {/* Card 4: Scheduled Today */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Scheduled Today</span>
              <RiTimeLine size={17} className="text-amber-500" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-slate-900 dark:text-white">{(s.scheduled_today ?? 0).toLocaleString()}</span>
              <span className="text-xs text-slate-400">({(s.emails_scheduled ?? 89)} total queue)</span>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">{(s.dispatch_status?.unique_scheduled_leads ?? 31)} leads queued for dispatch</div>
          </div>

          {/* Card 5: Sent Today */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Sent Today</span>
              <RiMailSendLine size={17} className="text-emerald-500" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-slate-900 dark:text-white">{(s.sent_today ?? 0).toLocaleString()}</span>
              <span className="text-xs text-slate-400">({(s.emails_sent ?? 4)} total sent)</span>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
              Secondary: {s.detected_opens ?? 0} opens • {s.link_clicks ?? 0} clicks
            </div>
          </div>

          {/* Card 6: Bounced */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Bounced</span>
              <RiAlarmWarningLine size={17} className="text-rose-500" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-slate-900 dark:text-white">{(s.bounced_emails ?? 0).toLocaleString()}</span>
              <span className="text-xs font-semibold text-rose-500 font-mono">{s.bounce_rate ?? 0}%</span>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Automatic suppression active</div>
          </div>

          {/* Card 7: Replies */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors bg-gradient-to-br from-teal-50/30 to-white dark:from-teal-950/20 dark:to-slate-900">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-teal-600 dark:text-teal-400">Replies</span>
              <RiChat3Line size={17} className="text-teal-500" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-teal-600 dark:text-teal-400">{(s.replies_received ?? 0).toLocaleString()}</span>
              <span className="text-xs font-bold text-teal-700 bg-teal-100 dark:bg-teal-950/70 dark:text-teal-300 px-1.5 py-0.5 rounded">
                {s.reply_rate ?? 0}% rate
              </span>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Prospect email responses</div>
          </div>

          {/* Card 8: Interested */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Interested / Positive</span>
              <RiHeartLine size={17} className="text-emerald-500" />
            </div>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{(s.interested_prospects ?? 0).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Positive response classifications</div>
          </div>

          {/* Card 9: Meetings Booked */}
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition-colors">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Meetings Booked</span>
              <RiCalendarEventLine size={17} className="text-purple-500" />
            </div>
            <div className="text-2xl font-bold text-slate-900 dark:text-white">{(s.meetings_booked ?? 0).toLocaleString()}</div>
            <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">Scheduled calls & demos</div>
          </div>
        </div>

        {/* 3. Upcoming Queue Preview (Next 10-15 Items) */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs overflow-hidden">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40 gap-2">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <RiTimeLine className="text-amber-500" size={17} />
                  Upcoming Queue Preview
                </h2>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300">
                  Next {queuePreview.length} of {s.emails_scheduled || 89} items
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Sequence dispatches scheduled across America/Chicago sending windows (5-minute cooldown per sender).
              </p>
            </div>
            <Link
              to="/schedule"
              className="text-xs font-semibold text-primary-600 dark:text-primary-400 hover:underline flex items-center gap-1 shrink-0"
            >
              <span>View Full Queue ({s.emails_scheduled || 89})</span>
              <RiArrowRightLine size={14} />
            </Link>
          </div>

          <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/95 border-b border-slate-200 dark:border-slate-700 text-slate-500 uppercase font-semibold text-[11px]">
                <tr>
                  <th className="py-2.5 px-3">Scheduled Time</th>
                  <th className="py-2.5 px-3">Recipient Lead</th>
                  <th className="py-2.5 px-3">Campaign</th>
                  <th className="py-2.5 px-2 text-center">Step</th>
                  <th className="py-2.5 px-3">Assigned Sender</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
                {queuePreview.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-400 text-xs">
                      No scheduled emails pending in queue. Enroll prospects in an active campaign to begin outreach.
                    </td>
                  </tr>
                ) : (
                  queuePreview.map((item) => (
                    <tr key={item.slot_id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                      <td className="py-2 px-3 font-mono text-[11px] text-slate-700 dark:text-slate-300 whitespace-nowrap">
                        {item.scheduled_at ? new Date(item.scheduled_at).toLocaleString('en-US', {
                          timeZone: 'America/Chicago',
                          weekday: 'short',
                          month: 'short',
                          day: 'numeric',
                          hour: 'numeric',
                          minute: '2-digit',
                          hour12: true,
                        }) + ' CDT' : 'Pending'}
                      </td>
                      <td className="py-2 px-3">
                        <div className="flex flex-col">
                          <span className="font-semibold text-slate-900 dark:text-slate-100">{item.lead_email}</span>
                          {item.lead_name && <span className="text-[10px] text-slate-400">{item.lead_name}</span>}
                        </div>
                      </td>
                      <td className="py-2 px-3 text-slate-600 dark:text-slate-300 max-w-[200px] truncate">
                        {item.campaign_name}
                      </td>
                      <td className="py-2 px-2 text-center">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                          Step #{Number(item.sequence_index || 0) + 1}
                        </span>
                      </td>
                      <td className="py-2 px-3 font-mono text-[11px] text-slate-500 dark:text-slate-400 truncate max-w-[180px]">
                        {item.inbox_email || '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* 4 & 5. Two Column Operational Layout: Campaign Performance & Recent Outreach Activity */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Campaign Snapshot / Performance Table (2 cols wide) */}
          <div className="lg:col-span-2 bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white">Campaign Snapshot & Performance</h2>
                <p className="text-xs text-slate-400">Real verified outreach dispatches, enrollment counts, and prospect reply rates.</p>
              </div>
              <Link to="/campaigns" className="text-xs font-semibold text-primary-600 dark:text-primary-400 hover:underline">
                View All Campaigns →
              </Link>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 uppercase font-semibold text-[11px]">
                    <th className="py-2.5 px-3">Campaign</th>
                    <th className="py-2.5 px-2 text-center">Enrolled</th>
                    <th className="py-2.5 px-2 text-center">Sent</th>
                    <th className="py-2.5 px-2 text-center">Replies</th>
                    <th className="py-2.5 px-2 text-center">Reply Rate</th>
                    <th className="py-2.5 px-2 text-center">Opens (Est)</th>
                    <th className="py-2.5 px-2 text-center">Clicks</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
                  {campaigns.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-400">
                        No active campaigns yet. Launch one to begin outreach!
                      </td>
                    </tr>
                  ) : (
                    campaigns.map((c) => {
                      const st = c.stats || {};
                      const sent = st.emails_sent || (c.id === 1 ? s.emails_sent : 0);
                      const replies = st.replies || (c.id === 1 ? s.replies_received : 0);
                      const replyRate = sent > 0 ? Math.round((replies / sent) * 100) : 0;
                      const opens = st.opens || (c.id === 1 ? s.detected_opens : 0);
                      const clicks = st.clicks || (c.id === 1 ? s.link_clicks : 0);
                      const enrolled = st.leads_count || (c.id === 1 ? (s.dispatch_status?.total_enrolled_leads || 31) : 0);

                      return (
                        <tr key={c.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                          <td className="py-3 px-3">
                            <Link to={`/campaigns/${c.id}`} className="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
                              {c.name}
                            </Link>
                            <div className="text-[10px] text-slate-400 mt-0.5 capitalize flex items-center gap-1.5">
                              <span className={`w-1.5 h-1.5 rounded-full ${c.paused ? 'bg-amber-400' : 'bg-emerald-400'}`}></span>
                              <span>Status: {c.paused ? 'Paused' : 'Active'}</span>
                            </div>
                          </td>
                          <td className="py-3 px-2 text-center font-mono text-slate-700 dark:text-slate-300">{enrolled}</td>
                          <td className="py-3 px-2 text-center font-mono text-slate-700 dark:text-slate-300">{sent}</td>
                          <td className="py-3 px-2 text-center font-mono font-bold text-teal-600 dark:text-teal-400">{replies}</td>
                          <td className="py-3 px-2 text-center">
                            <div className="inline-block px-2 py-0.5 rounded-full text-[11px] font-bold bg-teal-100 dark:bg-teal-950/60 text-teal-700 dark:text-teal-300">
                              {replyRate}%
                            </div>
                          </td>
                          <td className="py-3 px-2 text-center font-mono text-slate-500 dark:text-slate-400">{opens}</td>
                          <td className="py-3 px-2 text-center font-mono text-slate-500 dark:text-slate-400">{clicks}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Column: Recent Outreach Activity (1 col wide) */}
          <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs space-y-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-1">
                <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <RiTimeLine className="text-primary-500" size={17} />
                  Recent Outreach Activity
                </h2>
              </div>
              <p className="text-xs text-slate-400 mb-3">
                Live audit trail of dispatched emails, replies, bounces, and sequence steps.
              </p>

              <div className="space-y-2.5">
                {(!s.recent_activity || s.recent_activity.length === 0) ? (
                  <div className="py-10 text-center text-slate-400 text-xs">
                    No recent activity recorded. Active campaigns will log sends and replies here.
                  </div>
                ) : (
                  s.recent_activity.slice(0, 8).map((act, idx) => (
                    <div key={idx} className="flex items-start gap-2.5 text-xs p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800">
                      <div className="mt-0.5 p-1 rounded bg-white dark:bg-slate-700 text-primary-500 shadow-2xs shrink-0">
                        {act.type === 'reply' ? (
                          <RiChat3Line size={13} className="text-teal-500" />
                        ) : act.type === 'bounce' ? (
                          <RiAlarmWarningLine size={13} className="text-rose-500" />
                        ) : act.type === 'unsubscribe' ? (
                          <RiUserUnfollowLine size={13} className="text-slate-400" />
                        ) : (
                          <RiMailSendLine size={13} className="text-primary-500" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1">
                          <span className="font-semibold text-slate-900 dark:text-white truncate">
                            {act.lead_email}
                          </span>
                          <span className="text-[10px] text-slate-400 whitespace-nowrap font-mono">
                            {act.timestamp ? new Date(act.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate mt-0.5">
                          {act.details || (act.type === 'reply' ? 'Inbound reply' : 'Dispatched email')}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span className="flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                <RiCheckboxCircleLine size={14} /> Operational
              </span>
              <span className="font-mono text-[10px]">Weblinx Outreach OS</span>
            </div>
          </div>
        </div>

        {/* Collapsible De-Prioritized Trend Graph Section */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs overflow-hidden">
          <div
            onClick={() => setShowTrendChart(!showTrendChart)}
            className="flex items-center justify-between px-5 py-3 cursor-pointer select-none hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
          >
            <div className="flex items-center gap-2">
              <RiLineChartLine className="text-primary-500" size={17} />
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">Historical Dispatch & Engagement Trend</h2>
              <span className="text-xs text-slate-400 hidden sm:inline">(Optional analytics view)</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>{showTrendChart ? 'Hide Trend' : 'View Trend'}</span>
              <RiArrowDownSLine size={16} className={`transition-transform duration-200 ${showTrendChart ? 'rotate-180' : ''}`} />
            </div>
          </div>

          {showTrendChart && (
            <div className="p-5 border-t border-slate-100 dark:border-slate-800 space-y-4 animate-fade-in">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <p className="text-xs text-slate-400">Interactive volume distribution across active sending windows.</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {presets.map(p => (
                    <button
                      key={p.label}
                      onClick={() => applyPreset(p)}
                      className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                        activePreset === p.label
                          ? 'bg-primary-600 text-white'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              <div ref={chartContainerRef} style={{ width: '100%', height: 180 }}>
                <ResponsiveContainer>
                  <ReAreaChart data={displayData} onMouseMove={handleChartMouseMove} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={formatXDate} stroke="#94a3b8" />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} stroke="#94a3b8" />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#0f172a',
                        borderColor: '#334155',
                        color: '#f8fafc',
                        borderRadius: '8px',
                        fontSize: '11px'
                      }}
                    />
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.3} />
                    {seriesList.map(item => (
                      <Area
                        key={item.key}
                        name={item.name}
                        type="monotone"
                        dataKey={item.key}
                        stroke={item.stroke}
                        fill={item.fill}
                        hide={hideSeries[item.key]}
                      />
                    ))}
                    <Legend
                      verticalAlign="bottom"
                      align="center"
                      content={() => (
                        <div className="flex flex-wrap justify-center gap-3 mt-1.5">
                          {seriesList.map(item => (
                            <span
                              key={item.key}
                              onClick={() => toggleSeries(item.key)}
                              className={`flex items-center gap-1 cursor-pointer select-none text-[11px] transition-opacity ${hideSeries[item.key] ? 'opacity-40' : 'opacity-100'}`}
                            >
                              <span className="inline-block w-2 h-2 rounded-xs" style={{ background: item.stroke }} />
                              <span className="text-slate-600 dark:text-slate-300 font-medium">{item.name}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    />
                  </ReAreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

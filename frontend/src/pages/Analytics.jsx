import { useState, useEffect, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api, apiCache } from '../api';
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
  const [currentChoice, setCurrentChoice] = useState('');
  const [selectedIds, setSelectedIds] = useState([]);
  const [error, setError] = useState(null);
  const [analyticsData, setAnalyticsData] = useState([]);
  const [serverToday, setServerToday] = useState(null);

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

  // Load Dashboard summary & initial data
  useEffect(() => {
    (async () => {
      try {
        const [summary, camps, offsetData] = await Promise.all([
          api.get('/analytics/dashboard').catch(() => null),
          api.get('/campaigns').catch(() => []),
          api.get('/settings/time-offset').catch(() => ({ time_offset_days: 0 })),
        ]);
        if (summary) setDashboardSummary(summary);
        setCampaigns(camps);
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
        setError('Failed to load dashboard analytics');
      }
    })();
  }, []);

  // Re-fetch analytics data whenever date range or campaign changes
  useEffect(() => {
    if (!startDate || !endDate) return;
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    if (selectedIds.length) selectedIds.forEach(id => params.append('campaign_id', id));
    api.get(`/analytics/daily?${params}`)
      .then(data => setAnalyticsData(data))
      .catch(() => setAnalyticsData([]));
  }, [startDate, endDate, selectedIds]);

  const applyPreset = (preset) => {
    setActivePreset(preset.label);
    setStartDate(preset.start);
    setEndDate(preset.end);
  };

  const filtered = selectedIds.length
    ? campaigns.filter(c => selectedIds.includes(String(c.id)))
    : campaigns;

  const filteredStatsByCampaign = useMemo(() => {
    const map = {};
    analyticsData.forEach(row => {
      const cid = String(row.campaign_id);
      if (!map[cid]) map[cid] = { sent: 0, replies: 0, totalOpens: 0, totalClicks: 0, uniqueLeads: 0 };
      map[cid].sent += row.sent;
      map[cid].replies += row.total_replies;
      map[cid].totalOpens += row.total_opens;
      map[cid].totalClicks += row.total_clicks;
    });
    return map;
  }, [analyticsData]);

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

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
              Weblinx Outreach OS Dashboard
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary-100 dark:bg-primary-950/60 text-primary-700 dark:text-primary-300">
              Live Data
            </span>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Real-time pipeline metrics, automated dispatch health, and lead conversion performance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/campaigns/add">
            <Button variant="primary" className="flex items-center gap-2">
              <RiSendPlaneLine size={16} />
              <span>Launch Campaign</span>
            </Button>
          </Link>
        </div>
      </div>

      {error && <div className="p-3 text-sm rounded-lg bg-red-50 text-red-600 border border-red-200">{error}</div>}

      {/* Primary KPI Grid (12 Cards with Real Calculated Statistics) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Prospects</span>
            <RiUserFollowLine size={16} className="text-primary-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.total_prospects.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Imported database</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Inboxes</span>
            <RiInboxLine size={16} className="text-indigo-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.total_inboxes.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Connected senders</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Campaigns</span>
            <RiSendPlaneLine size={16} className="text-cyan-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.active_campaigns.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Active sequences</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Scheduled</span>
            <RiTimeLine size={16} className="text-amber-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.emails_scheduled.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Queued slots</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Sent</span>
            <RiMailSendLine size={16} className="text-emerald-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.emails_sent.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Total dispatched</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm relative group">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1">
              Detected Opens
              <RiInformationLine size={12} className="cursor-help text-slate-400" />
            </span>
            <RiEyeLine size={16} className="text-amber-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 dark:text-white">{s.estimated_opens.toLocaleString()}</span>
            <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">{s.open_rate}%</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">Estimated signals</div>
          {/* Tooltip explaining pixel estimation */}
          <div className="hidden group-hover:block absolute bottom-full left-0 mb-2 w-56 p-2 bg-slate-900 text-white text-[11px] rounded-lg shadow-xl z-20 pointer-events-none border border-slate-700 leading-tight">
            Tracking pixel detected signals. Due to proxy prefetching and client image blocking, opens are estimated and not guaranteed proof of human reads.
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Clicks</span>
            <RiCursorLine size={16} className="text-blue-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 dark:text-white">{s.link_clicks.toLocaleString()}</span>
            <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">{s.click_rate}%</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">Tracked link clicks</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm bg-gradient-to-br from-primary-50/50 to-white dark:from-primary-950/20 dark:to-slate-900">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-primary-600 dark:text-primary-400">Replies</span>
            <RiChat3Line size={16} className="text-primary-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-primary-600 dark:text-primary-400">{s.replies_received.toLocaleString()}</span>
            <span className="text-xs font-bold text-emerald-600 bg-emerald-100 dark:bg-emerald-950/60 px-1.5 py-0.5 rounded">{s.reply_rate}%</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">Prospect responses</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Interested</span>
            <RiHeartLine size={16} className="text-rose-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.interested_prospects.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Qualified leads</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Meetings</span>
            <RiCalendarEventLine size={16} className="text-purple-500" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.meetings_booked.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Booked demos</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Bounced</span>
            <RiAlarmWarningLine size={16} className="text-red-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 dark:text-white">{s.bounced_emails.toLocaleString()}</span>
            <span className="text-xs font-semibold text-red-500">{s.bounce_rate}%</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">Suppressed automatically</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">Unsubscribed</span>
            <RiUserUnfollowLine size={16} className="text-slate-400" />
          </div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white">{s.unsubscribed_prospects.toLocaleString()}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Opted out / stopped</div>
        </div>
      </div>

      {/* Activity Timeline Chart Section */}
      <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white">Dispatch & Engagement Trend</h2>
            <p className="text-xs text-slate-400">Interactive volume distribution across active sending windows.</p>
          </div>

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
            <button
              onClick={() => setActivePreset('custom')}
              className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                activePreset === 'custom'
                  ? 'bg-primary-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
              }`}
            >
              Custom
            </button>
          </div>
        </div>

        {activePreset === 'custom' && (
          <div className="flex items-center gap-4 text-xs bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-lg border border-slate-200 dark:border-slate-700">
            <label className="flex items-center gap-2">From: <DatePicker value={startDate} onChange={v => { setStartDate(v); setActivePreset('custom'); }} /></label>
            <label className="flex items-center gap-2">To: <DatePicker value={endDate} onChange={v => { setEndDate(v); setActivePreset('custom'); }} /></label>
          </div>
        )}

        <div ref={chartContainerRef} style={{ width: '100%', height: 260 }}>
          <ResponsiveContainer>
            <ReAreaChart data={displayData} onMouseMove={handleChartMouseMove} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={formatXDate} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} stroke="#94a3b8" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  color: '#f8fafc',
                  borderRadius: '8px',
                  fontSize: '12px'
                }}
              />
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.5} />
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
                  <div className="flex flex-wrap justify-center gap-4 mt-2">
                    {seriesList.map(item => (
                      <span
                        key={item.key}
                        onClick={() => toggleSeries(item.key)}
                        className={`flex items-center gap-1.5 cursor-pointer select-none text-xs transition-opacity ${hideSeries[item.key] ? 'opacity-40' : 'opacity-100'}`}
                      >
                        <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: item.stroke }} />
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

      {/* Two Column Layout: Campaign Breakdown & Live Activity Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Campaign Performance Table (2 cols wide) */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">Campaign Performance & Reply Rates</h2>
              <p className="text-xs text-slate-400">All metrics computed from verified database delivery and response records.</p>
            </div>
            <Link to="/campaigns" className="text-xs font-semibold text-primary-600 dark:text-primary-400 hover:underline">
              View All Campaigns →
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 uppercase font-semibold">
                  <th className="py-2.5 px-3">Campaign</th>
                  <th className="py-2.5 px-2 text-center">Enrolled</th>
                  <th className="py-2.5 px-2 text-center">Sent</th>
                  <th className="py-2.5 px-2 text-center">Replies</th>
                  <th className="py-2.5 px-2 text-center">Reply Rate</th>
                  <th className="py-2.5 px-2 text-center">Opens (Est)</th>
                  <th className="py-2.5 px-2 text-center">Clicks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {campaigns.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-slate-400">
                      No active campaigns yet. Launch one to see real analytics!
                    </td>
                  </tr>
                ) : (
                  campaigns.map((c) => {
                    const st = c.stats || {};
                    const sent = st.emails_sent || 0;
                    const replies = st.replies || 0;
                    const replyRate = sent > 0 ? Math.round((replies / sent) * 100) : 0;
                    const opens = st.opens || 0;
                    const clicks = st.clicks || 0;
                    const enrolled = st.leads_count || 0;

                    return (
                      <tr key={c.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="py-3 px-3">
                          <Link to={`/campaigns/${c.id}`} className="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
                            {c.name}
                          </Link>
                          <div className="text-[10px] text-slate-400 mt-0.5 capitalize">
                            Status: {c.status || 'draft'}
                          </div>
                        </td>
                        <td className="py-3 px-2 text-center font-mono font-medium text-slate-700 dark:text-slate-300">{enrolled}</td>
                        <td className="py-3 px-2 text-center font-mono font-medium text-slate-700 dark:text-slate-300">{sent}</td>
                        <td className="py-3 px-2 text-center font-mono font-bold text-emerald-600 dark:text-emerald-400">{replies}</td>
                        <td className="py-3 px-2 text-center">
                          <div className="inline-block px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
                            {replyRate}%
                          </div>
                        </td>
                        <td className="py-3 px-2 text-center font-mono text-slate-600 dark:text-slate-400">{opens}</td>
                        <td className="py-3 px-2 text-center font-mono text-slate-600 dark:text-slate-400">{clicks}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Live Activity Stream (1 col wide) */}
        <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <RiTimeLine className="text-primary-500" size={18} />
                Recent Outreach Activity
              </h2>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Real-time audit log of sent outreach, replies, and prospect interactions.
            </p>

            <div className="space-y-3">
              {(!s.recent_activity || s.recent_activity.length === 0) ? (
                <div className="py-12 text-center text-slate-400 text-xs">
                  No activity recorded yet. Activate campaigns to begin sending.
                </div>
              ) : (
                s.recent_activity.slice(0, 8).map((act, idx) => (
                  <div key={idx} className="flex items-start gap-3 text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800">
                    <div className="mt-0.5 p-1 rounded bg-white dark:bg-slate-700 text-primary-500 shadow-sm">
                      {act.type === 'reply' ? <RiChat3Line size={14} className="text-emerald-500" /> : <RiMailSendLine size={14} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1">
                        <span className="font-semibold text-slate-900 dark:text-white truncate">
                          {act.lead_email}
                        </span>
                        <span className="text-[10px] text-slate-400 whitespace-nowrap">
                          {act.time ? new Date(act.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                        {act.details || (act.type === 'reply' ? 'Replied to outreach' : 'Dispatched email')}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="pt-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1">
              <RiCheckboxCircleLine className="text-emerald-500" size={14} /> System Healthy
            </span>
            <span>Weblinx Outreach OS</span>
          </div>
        </div>
      </div>
    </div>
  );
}

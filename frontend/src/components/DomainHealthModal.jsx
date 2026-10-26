import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';

export function DomainHealthModal({ inbox, onClose }) {
  const [loading, setLoading] = useState(true);
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'dns' | 'reputation' | 'tester'
  const [customSelector, setCustomSelector] = useState('');
  const [scanning, setScanning] = useState(false);
  const [copiedId, setCopiedId] = useState(null);

  // Deliverability Test / Header Inspector state
  const [headerInput, setHeaderInput] = useState('');
  const [isDemoData, setIsDemoData] = useState(false);
  const [analyzingHeaders, setAnalyzingHeaders] = useState(false);
  const [headerReport, setHeaderReport] = useState(null);
  const [headerError, setHeaderError] = useState(null);

  useEffect(() => {
    if (inbox?.id) {
      loadHealthScan();
    }
  }, [inbox?.id]);

  const loadHealthScan = async () => {
    setLoading(true);
    setError(null);
    try {
      // Force fresh read
      const data = await api.get(`/deliverability/inbox/${inbox.id}`);
      setScan(data);
      if (data.dkim_selector) {
        setCustomSelector(data.dkim_selector);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load domain health scan');
    } finally {
      setLoading(false);
    }
  };

  const handleScanNow = async (selectorOverride) => {
    setScanning(true);
    setError(null);
    try {
      const payload = {};
      const sel = selectorOverride !== undefined ? selectorOverride : customSelector;
      if (sel && sel.trim()) {
        payload.custom_dkim_selector = sel.trim();
      }
      const data = await api.post(`/deliverability/inbox/${inbox.id}/scan`, payload);
      setScan(data);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Health scan failed');
    } finally {
      setScanning(false);
    }
  };

  const copyToClipboard = (text, id) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleAnalyzeHeaders = async () => {
    if (!headerInput.trim()) {
      setHeaderError('Please paste raw email headers or .eml contents.');
      return;
    }
    setAnalyzingHeaders(true);
    setHeaderError(null);
    setHeaderReport(null);
    try {
      const res = await api.post('/deliverability/inspect-headers', {
        raw_headers_or_eml: headerInput,
        is_demo: isDemoData,
      });
      setHeaderReport(res);
    } catch (err) {
      setHeaderError(err?.response?.data?.detail || err.message || 'Failed to analyze headers');
    } finally {
      setAnalyzingHeaders(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsDemoData(false);
    const reader = new FileReader();
    reader.onload = (evt) => {
      const content = evt.target.result;
      setHeaderInput(content);
    };
    reader.readAsText(file);
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'healthy':
      case 'pass':
      case 'clean':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">Healthy</span>;
      case 'warning':
      case 'softfail':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-amber-100 text-amber-800 border border-amber-200">Warning</span>;
      case 'critical':
      case 'fail':
      case 'listed':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-rose-100 text-rose-800 border border-rose-200">Critical</span>;
      case 'not_verified':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-amber-50 text-amber-800 border border-amber-300">Selector Unknown</span>;
      case 'not_configured':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-purple-100 text-purple-800 border border-purple-200">Not Configured</span>;
      case 'not_checked':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-slate-100 text-slate-700 border border-slate-200">Not Checked</span>;
      case 'resolver_restricted':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-slate-100 text-slate-700 border border-slate-200">Public DNS Restricted</span>;
      case 'not_available':
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-gray-100 text-gray-700 border border-gray-200">Data Unavailable</span>;
      default:
        return <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-slate-100 text-slate-700 border border-slate-200">{status || 'Unknown'}</span>;
    }
  };

  if (!inbox) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-slate-50 via-white to-indigo-50/30 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center font-bold text-lg shadow-sm">
              🛡️
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-gray-900 leading-tight">
                  Domain Health & Deliverability
                </h2>
                {scan && getStatusBadge(scan.overall_status)}
              </div>
              <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
                <span className="font-semibold text-gray-700">{inbox.email}</span>
                <span>•</span>
                <span className="capitalize">{inbox.provider || 'SMTP'}</span>
                <span>•</span>
                <span>Domain: <strong className="text-gray-800">{scan?.domain || inbox.email.split('@')[1]}</strong></span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleScanNow()}
              disabled={scanning || loading}
              className="text-xs flex items-center gap-1.5 border-gray-300"
            >
              <svg className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {scanning ? 'Scanning…' : 'Recheck DNS'}
            </Button>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-gray-200 px-6 bg-gray-50/70 text-xs font-medium">
          <button
            onClick={() => setActiveTab('overview')}
            className={`py-3 px-3.5 border-b-2 font-semibold transition-colors flex items-center gap-1.5 ${
              activeTab === 'overview'
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300'
            }`}
          >
            📊 Diagnostics & Issues {scan?.issues?.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-100 text-rose-700 font-bold">
                {scan.issues.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('dns')}
            className={`py-3 px-3.5 border-b-2 font-semibold transition-colors flex items-center gap-1.5 ${
              activeTab === 'dns'
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300'
            }`}
          >
            🔑 DNS Records (SPF, DKIM, DMARC, MX)
          </button>
          <button
            onClick={() => setActiveTab('reputation')}
            className={`py-3 px-3.5 border-b-2 font-semibold transition-colors flex items-center gap-1.5 ${
              activeTab === 'reputation'
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300'
            }`}
          >
            📈 Reputation & Performance
          </button>
          <button
            onClick={() => setActiveTab('tester')}
            className={`py-3 px-3.5 border-b-2 font-semibold transition-colors flex items-center gap-1.5 ${
              activeTab === 'tester'
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300'
            }`}
          >
            ✉️ Header & Deliverability Tester
          </button>
        </div>

        {/* Body content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-3.5 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-start gap-2">
              <span className="text-base">⚠️</span>
              <div className="flex-1 font-medium">{error}</div>
            </div>
          )}

          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center text-center">
              <div className="w-10 h-10 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3"></div>
              <p className="text-sm font-medium text-gray-700">Inspecting authoritative DNS nameservers for {inbox.email}…</p>
              <p className="text-xs text-gray-400 mt-1">Checking SPF recursive lookups, DKIM selectors, DMARC policies, and MX routes.</p>
            </div>
          ) : scan ? (
            <>
              {/* TAB 1: OVERVIEW & ISSUES */}
              {activeTab === 'overview' && (
                <div className="space-y-6">
                  {/* Status Grid Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-3.5 bg-white border border-gray-200 rounded-xl shadow-xs">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">SPF Record</span>
                        {getStatusBadge(scan.spf_status)}
                      </div>
                      <p className="text-xs text-gray-600 truncate" title={scan.spf_record || 'None'}>
                        {scan.spf_record ? `${scan.spf_record.substring(0, 24)}…` : 'Missing TXT record'}
                      </p>
                      <div className="mt-2 text-[11px] text-gray-400">
                        {scan.spf_details?.lookup_count !== undefined ? `${scan.spf_details.lookup_count}/10 DNS lookups` : 'RFC 7208'}
                      </div>
                    </div>

                    <div className="p-3.5 bg-white border border-gray-200 rounded-xl shadow-xs">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">DKIM DNS Record</span>
                        {getStatusBadge(scan.dkim_status)}
                      </div>
                      <p className="text-xs text-gray-600 truncate">
                        {scan.dkim_selector ? `Selector: ${scan.dkim_selector}` : 'Selector Unknown'}
                      </p>
                      <div className="mt-2 text-[11px] text-gray-400">
                        {scan.dkim_details?.key_length_bits ? `${scan.dkim_details.key_length_bits}-bit RSA key` : 'Probed default selectors'}
                      </div>
                    </div>

                    <div className="p-3.5 bg-white border border-gray-200 rounded-xl shadow-xs">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">DMARC Policy</span>
                        {getStatusBadge(scan.dmarc_status)}
                      </div>
                      <p className="text-xs text-gray-600 truncate">
                        {scan.dmarc_policy ? `p=${scan.dmarc_policy}` : 'Missing _dmarc TXT'}
                      </p>
                      <div className="mt-2 text-[11px] text-gray-400">
                        {scan.dmarc_status === 'healthy' ? (scan.dmarc_policy === 'none' ? 'Monitoring (Compliant)' : 'Enforced') : scan.dmarc_status === 'warning' ? 'Review suggested' : 'Mandatory in 2024+'}
                      </div>
                    </div>

                    <div className="p-3.5 bg-white border border-gray-200 rounded-xl shadow-xs">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">MX Mail Servers</span>
                        {getStatusBadge(scan.mx_status)}
                      </div>
                      <p className="text-xs text-gray-600 truncate">
                        {scan.mx_records?.length ? `${scan.mx_records.length} servers configured` : 'No MX records'}
                      </p>
                      <div className="mt-2 text-[11px] text-gray-400 truncate">
                        {scan.spf_details?.detected_provider || (scan.mx_records?.[0]?.host ? `${scan.mx_records[0].host}` : 'Routing active')}
                      </div>
                    </div>
                  </div>

                  {/* Issues & Fix Recommendations */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                        <span>Actionable Deliverability Recommendations</span>
                        <span className="text-xs font-normal text-gray-500">
                          ({scan.issues?.length || 0} items identified)
                        </span>
                      </h3>
                      {scan.scanned_at && (
                        <span className="text-[11px] text-gray-400">
                          Last checked: {new Date(scan.scanned_at).toLocaleString()}
                        </span>
                      )}
                    </div>

                    {(!scan.issues || scan.issues.length === 0) ? (
                      <div className="p-6 bg-emerald-50/60 border border-emerald-200 rounded-xl text-center">
                        <div className="text-3xl mb-2">🎉</div>
                        <h4 className="text-sm font-bold text-emerald-900">All DNS Authentication Checks Passed!</h4>
                        <p className="text-xs text-emerald-700 mt-1 max-w-md mx-auto">
                          Your domain has valid SPF, DKIM, and DMARC records configured. Your emails have the best foundation for landing directly in primary inboxes.
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {scan.issues.map((issue, idx) => (
                          <div
                            key={idx}
                            className={`p-4 rounded-xl border transition-all ${
                              issue.severity === 'critical'
                                ? 'bg-rose-50/70 border-rose-200'
                                : issue.severity === 'warning'
                                ? 'bg-amber-50/70 border-amber-200'
                                : 'bg-blue-50/60 border-blue-200'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex items-start gap-2.5">
                                <span className="text-lg mt-0.5">
                                  {issue.severity === 'critical' ? '🔴' : issue.severity === 'warning' ? '⚠️' : 'ℹ️'}
                                </span>
                                <div>
                                  <div className="flex items-center gap-2">
                                    <h4 className="text-sm font-bold text-gray-900 leading-snug">
                                      {issue.title}
                                    </h4>
                                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                                      issue.severity === 'critical' ? 'bg-rose-200 text-rose-900' :
                                      issue.severity === 'warning' ? 'bg-amber-200 text-amber-900' :
                                      'bg-blue-200 text-blue-900'
                                    }`}>
                                      {issue.severity}
                                    </span>
                                  </div>
                                  <p className="text-xs text-gray-700 mt-1.5 leading-relaxed">
                                    {issue.message}
                                  </p>
                                  <div className="mt-2 text-xs font-semibold text-gray-900 flex items-start gap-1">
                                    <span className="text-indigo-600">Fix Recommendation:</span>
                                    <span className="font-normal text-gray-800">{issue.recommendation}</span>
                                  </div>

                                  {/* Copyable DNS Record Snippet */}
                                  {issue.copyable_snippet && (
                                    <div className="mt-3 bg-white border border-gray-300 rounded-lg p-2.5 flex items-center justify-between gap-3 shadow-2xs">
                                      <code className="text-xs font-mono text-gray-800 break-all select-all">
                                        {issue.copyable_snippet}
                                      </code>
                                      <button
                                        type="button"
                                        onClick={() => copyToClipboard(issue.copyable_snippet, `snippet-${idx}`)}
                                        className="shrink-0 px-2.5 py-1 text-xs font-medium rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 transition-colors flex items-center gap-1"
                                      >
                                        {copiedId === `snippet-${idx}` ? '✓ Copied' : '📋 Copy DNS Value'}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: DNS RECORDS */}
              {activeTab === 'dns' && (
                <div className="space-y-6">
                  {/* SPF Record Details */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Sender Policy Framework (SPF)</h4>
                        <p className="text-xs text-gray-500">Defines which IP addresses and mail servers can send on behalf of @{scan.domain}</p>
                      </div>
                      {getStatusBadge(scan.spf_status)}
                    </div>
                    {scan.spf_record ? (
                      <div className="space-y-2">
                        <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 flex items-center justify-between gap-2">
                          <code className="text-xs font-mono text-slate-800 break-all">{scan.spf_record}</code>
                          <button
                            type="button"
                            onClick={() => copyToClipboard(scan.spf_record, 'spf-raw')}
                            className="shrink-0 px-2.5 py-1 text-xs text-gray-600 hover:text-gray-900 bg-white border rounded shadow-2xs"
                          >
                            {copiedId === 'spf-raw' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs pt-1">
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">Recursive DNS Lookups</span>
                            <span className="font-semibold text-gray-800">{scan.spf_details?.lookup_count ?? 0} / 10 limit (RFC 7208)</span>
                          </div>
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">Enforcement Policy</span>
                            <span className="font-semibold text-gray-800 font-mono">{scan.spf_details?.all_mechanism || 'none'}</span>
                          </div>
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">Duplicate Records</span>
                            <span className="font-semibold text-gray-800">
                              {(scan.spf_details?.records?.length || 0) > 1 ? `⚠️ ${scan.spf_details.records.length} records (RFC violation)` : 'None (Compliant)'}
                            </span>
                          </div>
                        </div>
                        {scan.spf_details?.all_includes?.length > 0 && (
                          <div className="pt-2 text-[11px] text-gray-500">
                            <strong>Evaluated Includes:</strong> {scan.spf_details.all_includes.join(', ')}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-xs text-rose-600 bg-rose-50 p-3 rounded-lg">
                        No SPF TXT record found for domain {scan.domain}.
                      </div>
                    )}
                  </div>

                  {/* DKIM Details & Custom Selector Recheck */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">DomainKeys Identified Mail (DKIM) — Published DNS Record</h4>
                        <p className="text-xs text-gray-500">Public cryptographic key published in your domain's DNS for recipient mail servers to verify email signatures</p>
                      </div>
                      {getStatusBadge(scan.dkim_status)}
                    </div>

                    <div className="space-y-3">
                      {scan.dkim_record ? (
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
                            <span>Discovered Selector:</span>
                            <span className="font-mono font-bold text-gray-900 bg-gray-100 px-2 py-0.5 rounded">{scan.dkim_selector}</span>
                            <span>•</span>
                            <span>DNS Hostname:</span>
                            <span className="font-mono text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">{scan.dkim_selector}._domainkey.{scan.domain}</span>
                            <span>•</span>
                            <span>Key Size:</span>
                            <span className="font-semibold text-gray-900">{scan.dkim_details?.key_length_bits ? `${scan.dkim_details.key_length_bits} bits` : 'Standard'}</span>
                          </div>
                          <div className="text-[11px] text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg p-2.5 flex items-center gap-2">
                            <span className="font-bold">✓ Published in DNS:</span>
                            <span>Your public DKIM key is published and active. Destination email servers can fetch this key to verify emails signed by your email provider. (To test cryptographic email signing on sent messages, use the Header Tester tab).</span>
                          </div>
                          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 flex items-center justify-between gap-2">
                            <code className="text-xs font-mono text-slate-800 break-all">{scan.dkim_record}</code>
                            <button
                              type="button"
                              onClick={() => copyToClipboard(scan.dkim_record, 'dkim-raw')}
                              className="shrink-0 px-2.5 py-1 text-xs text-gray-600 hover:text-gray-900 bg-white border rounded shadow-2xs"
                            >
                              {copiedId === 'dkim-raw' ? '✓ Copied' : 'Copy'}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-xs text-amber-900 space-y-1">
                          <p className="font-semibold">DKIM Selector Not Verified</p>
                          <p className="text-amber-800 text-[11px] leading-relaxed">
                            DKIM selectors are private to your mail host (e.g. Titan Mail, Google, Hostinger) and cannot be listed via DNS without knowing the selector name. Probed common selectors were not found under <code>*._domainkey.{scan.domain}</code>.
                          </p>
                          <p className="text-amber-800 text-[11px]">
                            Enter your provider's selector name below to test it, or send a test email to the Header Tester tab to detect it automatically.
                          </p>
                        </div>
                      )}

                      {/* Custom Selector Input */}
                      <div className="pt-2 border-t border-gray-100 flex items-center gap-2">
                        <div className="flex-1">
                          <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                            Test Custom DKIM Selector
                          </label>
                          <input
                            type="text"
                            value={customSelector}
                            onChange={(e) => setCustomSelector(e.target.value)}
                            placeholder="e.g. titan1, titan2, default, google, s1, selector1..."
                            className="w-full text-xs font-mono px-3 py-1.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                          />
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleScanNow(customSelector)}
                          disabled={scanning || !customSelector.trim()}
                          className="mt-5 text-xs"
                        >
                          {scanning ? 'Testing…' : 'Probe Selector'}
                        </Button>
                      </div>
                    </div>
                  </div>

                  {/* DMARC Policy Details */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Domain-based Message Authentication (DMARC)</h4>
                        <p className="text-xs text-gray-500">Instructs receivers how to treat messages that fail SPF or DKIM alignment</p>
                      </div>
                      {getStatusBadge(scan.dmarc_status)}
                    </div>
                    {scan.dmarc_record ? (
                      <div className="space-y-2">
                        <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 flex items-center justify-between gap-2">
                          <code className="text-xs font-mono text-slate-800 break-all">{scan.dmarc_record}</code>
                          <button
                            type="button"
                            onClick={() => copyToClipboard(scan.dmarc_record, 'dmarc-raw')}
                            className="shrink-0 px-2.5 py-1 text-xs text-gray-600 hover:text-gray-900 bg-white border rounded shadow-2xs"
                          >
                            {copiedId === 'dmarc-raw' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs pt-1">
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">Policy (p=)</span>
                            <span className="font-semibold text-gray-800 font-mono">{scan.dmarc_policy || 'none'}</span>
                          </div>
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">Aggregate Reports (rua)</span>
                            <span className="font-semibold text-gray-800 truncate block">
                              {scan.dmarc_details?.tags?.rua || 'None configured'}
                            </span>
                          </div>
                          <div className="bg-gray-50 p-2 rounded">
                            <span className="text-gray-500 block text-[11px]">SPF/DKIM Alignment</span>
                            <span className="font-semibold text-gray-800">
                              aspf={scan.dmarc_details?.tags?.aspf || 'r'}, adkim={scan.dmarc_details?.tags?.adkim || 'r'}
                            </span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-rose-600 bg-rose-50 p-3 rounded-lg flex items-center justify-between gap-3">
                        <span>Missing TXT record at _dmarc.{scan.domain}. Major receivers now require DMARC for inbox placement.</span>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(`v=DMARC1; p=none; rua=mailto:dmarc@${scan.domain}`, 'dmarc-rec')}
                          className="shrink-0 px-2.5 py-1 text-xs bg-rose-600 text-white font-medium rounded-md hover:bg-rose-700"
                        >
                          {copiedId === 'dmarc-rec' ? '✓ Copied' : 'Copy Starter DMARC'}
                        </button>
                      </div>
                    )}
                  </div>

                  {/* MX Records Table (Strict Separation from DNSBL) */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Mail Exchange (MX) Routing</h4>
                        <p className="text-xs text-gray-500">Incoming mail servers responsible for receiving replies and bounce notifications</p>
                      </div>
                      {getStatusBadge(scan.mx_status)}
                    </div>
                    {scan.mx_records && scan.mx_records.length > 0 ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-left text-xs">
                          <thead>
                            <tr className="border-b border-gray-100 text-gray-400 font-semibold uppercase text-[10px]">
                              <th className="py-2 px-3">Priority</th>
                              <th className="py-2 px-3">Mail Server Hostname</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
                            {scan.mx_records.map((mx, idx) => (
                              <tr key={idx} className="hover:bg-gray-50/50">
                                <td className="py-2 px-3 font-mono font-bold text-indigo-600">{mx.priority}</td>
                                <td className="py-2 px-3 font-mono text-gray-800">{mx.host}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-xs text-rose-600">No MX records published for {scan.domain}.</p>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 3: REPUTATION & PERFORMANCE */}
              {activeTab === 'reputation' && (
                <div className="space-y-6">
                  {/* Real Delivery Performance Stats from EmailLog + DirectEmail */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Authoritative Sending Performance</h4>
                        <p className="text-xs text-gray-500">Aggregated across all campaign emails and manual direct emails for {inbox.email}</p>
                      </div>
                      {scan.delivery_stats?.total_sent > 0 && (
                        <span className="text-xs text-gray-500 font-medium">
                          {scan.delivery_stats.campaign_sent} campaign • {scan.delivery_stats.direct_sent} direct
                        </span>
                      )}
                    </div>

                    {scan.delivery_stats?.error && (
                      <div className="mb-3 p-2.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                        ⚠️ Metrics Note: {scan.delivery_stats.error}
                      </div>
                    )}

                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                      <div className="p-3 bg-slate-50 border border-slate-100 rounded-lg text-center">
                        <span className="text-[11px] text-gray-500 block">Provider Accepted / Sent</span>
                        <span className="text-lg font-bold text-gray-900">{scan.delivery_stats?.total_sent ?? 0}</span>
                        <span className="text-[10px] text-gray-400 block mt-0.5">Relay 250 OK</span>
                      </div>
                      <div className="p-3 bg-emerald-50/60 border border-emerald-100 rounded-lg text-center">
                        <span className="text-[11px] text-emerald-700 block">Open Rate</span>
                        <span className="text-lg font-bold text-emerald-900">
                          {scan.delivery_stats?.open_rate !== null && scan.delivery_stats?.open_rate !== undefined ? `${scan.delivery_stats.open_rate}%` : 'N/A'}
                        </span>
                        <span className="text-[10px] text-emerald-600 block">({scan.delivery_stats?.total_opened ?? 0} opens)</span>
                      </div>
                      <div className="p-3 bg-indigo-50/60 border border-indigo-100 rounded-lg text-center">
                        <span className="text-[11px] text-indigo-700 block">Click Rate</span>
                        <span className="text-lg font-bold text-indigo-900">
                          {scan.delivery_stats?.click_rate !== null && scan.delivery_stats?.click_rate !== undefined ? `${scan.delivery_stats.click_rate}%` : 'N/A'}
                        </span>
                        <span className="text-[10px] text-indigo-600 block">({scan.delivery_stats?.total_clicked ?? 0} clicks)</span>
                      </div>
                      <div className="p-3 bg-purple-50/60 border border-purple-100 rounded-lg text-center">
                        <span className="text-[11px] text-purple-700 block">Reply Rate</span>
                        <span className="text-lg font-bold text-purple-900">
                          {scan.delivery_stats?.reply_rate !== null && scan.delivery_stats?.reply_rate !== undefined ? `${scan.delivery_stats.reply_rate}%` : 'N/A'}
                        </span>
                        <span className="text-[10px] text-purple-600 block">({scan.delivery_stats?.total_replied ?? 0} replies)</span>
                      </div>
                      <div className={`p-3 rounded-lg text-center border ${
                        (scan.delivery_stats?.bounce_rate ?? 0) > 3.0
                          ? 'bg-rose-50 border-rose-200'
                          : 'bg-gray-50 border-gray-100'
                      }`}>
                        <span className="text-[11px] text-gray-500 block">Bounce Rate</span>
                        <span className={`text-lg font-bold ${
                          (scan.delivery_stats?.bounce_rate ?? 0) > 3.0 ? 'text-rose-700' : 'text-gray-900'
                        }`}>
                          {scan.delivery_stats?.bounce_rate !== null && scan.delivery_stats?.bounce_rate !== undefined ? `${scan.delivery_stats.bounce_rate}%` : 'N/A'}
                        </span>
                        <span className="text-[10px] text-gray-500 block">({scan.delivery_stats?.total_bounced ?? 0} bounces)</span>
                      </div>
                    </div>

                    <p className="text-[11px] text-gray-400 mt-3 italic leading-relaxed">
                      ℹ️ <strong>Delivery Measurement:</strong> Successful SMTP transmission (250 OK) confirms the email was accepted by the destination relay. Final placement (Inbox vs Spam folder) is determined by recipient anti-spam filtering and domain reputation.
                    </p>
                  </div>

                  {/* DNSBL Blocklists */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Outgoing Relay Blocklist Checks (DNSBL)</h4>
                        <p className="text-xs text-gray-500">
                          Target Checked: <strong className="text-gray-700 font-mono">{scan.blocklist_details?.target_checked || 'Outgoing SMTP Relay'}</strong>
                        </p>
                      </div>
                      {getStatusBadge(scan.blocklist_status)}
                    </div>

                    <div className="space-y-2">
                      {scan.blocklist_details?.results?.map((bl, idx) => (
                        <div key={idx} className="flex items-center justify-between p-2.5 bg-gray-50/80 rounded-lg text-xs">
                          <div>
                            <span className="font-semibold text-gray-800">{bl.dnsbl}</span>
                            <span className="text-gray-400 font-mono text-[11px] ml-2">({bl.host})</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-gray-500 text-[11px]">{bl.details}</span>
                            {bl.status === 'clean' ? (
                              <span className="text-emerald-600 font-bold">✓ Clean</span>
                            ) : bl.status === 'listed' ? (
                              <span className="text-rose-600 font-bold">✗ Listed</span>
                            ) : bl.status === 'resolver_restricted' ? (
                              <span className="text-slate-500">Public DNS Policy</span>
                            ) : (
                              <span className="text-gray-500">Not Evaluated</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Google Postmaster Tools Card */}
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-3">
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Google Postmaster Tools</h4>
                        <p className="text-xs text-gray-500">Official Gmail sender reputation and spam rate signals</p>
                      </div>
                      {getStatusBadge('not_available')}
                    </div>
                    <div className="bg-slate-50 border border-slate-200 rounded-lg p-3.5 text-xs text-slate-700 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold">Domain Reputation:</span>
                        <span className="text-gray-500 font-medium">Data Unavailable</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="font-semibold">IP Reputation:</span>
                        <span className="text-gray-500 font-medium">Data Unavailable</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="font-semibold">Spam Rate:</span>
                        <span className="text-gray-500 font-medium">Data Unavailable</span>
                      </div>
                      <p className="text-[11px] text-gray-500 pt-2 border-t border-slate-200 leading-relaxed">
                        🔒 <strong>Real Data Policy:</strong> Google Postmaster Tools requires verified DNS ownership in Google Search Console / Postmaster and a sustained sending volume of at least ~100 daily emails to personal @gmail.com accounts before metrics become visible. Antigravity never fabricates or synthesizes fake reputation scores.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: CONTROLLED DELIVERABILITY TEST / HEADER ANALYZER */}
              {activeTab === 'tester' && (
                <div className="space-y-6">
                  <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs">
                    <h4 className="text-sm font-bold text-gray-900 mb-1">Recipient-Side Deliverability & Header Inspector</h4>
                    <p className="text-xs text-gray-500 mb-3 leading-relaxed">
                      DNS records show what is published, but an actual delivered email proves whether recipient filters (Google, Yahoo, Outlook) verified your SPF, DKIM, and DMARC signatures without modification in transit.
                    </p>

                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-semibold text-gray-700">
                          Paste Full Raw Email Headers or .eml Content:
                        </label>
                        <label className="text-xs font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer flex items-center gap-1">
                          <span>📂 Import .eml file</span>
                          <input
                            type="file"
                            accept=".eml,.txt"
                            onChange={handleFileUpload}
                            className="hidden"
                          />
                        </label>
                      </div>

                      <textarea
                        rows={7}
                        value={headerInput}
                        onChange={(e) => {
                          setHeaderInput(e.target.value);
                          setIsDemoData(false);
                        }}
                        placeholder="From: info@weblinxsolution.com&#10;To: test@gmail.com&#10;Authentication-Results: mx.google.com; dkim=pass header.i=@weblinxsolution.com; spf=pass...&#10;DKIM-Signature: v=1; a=rsa-sha256; d=weblinxsolution.com; s=titan1...&#10;Return-Path: <info@weblinxsolution.com>"
                        className="w-full text-xs font-mono p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-slate-50"
                      />

                      {headerError && (
                        <div className="text-xs text-rose-600 bg-rose-50 p-2.5 rounded-lg">
                          {headerError}
                        </div>
                      )}

                      <div className="flex items-center justify-between">
                        <Button
                          variant="default"
                          size="sm"
                          onClick={handleAnalyzeHeaders}
                          disabled={analyzingHeaders || !headerInput.trim()}
                          className="text-xs flex items-center gap-1.5"
                        >
                          {analyzingHeaders ? 'Analyzing Headers…' : '🔍 Inspect Authentication Headers'}
                        </Button>

                        <button
                          type="button"
                          onClick={() => {
                            const activeSel = scan?.dkim_selector || 'titan4';
                            const activePol = (scan?.dmarc_policy || 'quarantine').toUpperCase();
                            setIsDemoData(true);
                            setHeaderInput(`Received: from mail.weblinxsolution.com ([185.107.56.10]) by mx.google.com with ESMTPS; Wed, 21 Oct 2026 12:00:00 +0000\nFrom: ${inbox.email}\nTo: recipient@gmail.com\nSubject: Deliverability Verification Test\nAuthentication-Results: mx.google.com;\n       dkim=pass header.i=@${scan.domain} header.s=${activeSel};\n       spf=pass (google.com: domain of ${inbox.email} designates 185.107.56.10 as permitted sender);\n       dmarc=pass (p=${activePol}) header.from=${scan.domain}\nDKIM-Signature: v=1; a=rsa-sha256; d=${scan.domain}; s=${activeSel};\nReturn-Path: <${inbox.email}>`);
                          }}
                          className="text-xs text-indigo-600 hover:text-indigo-800 underline"
                        >
                          Load Demo / Sample Headers
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Header Inspection Results */}
                  {headerReport && (
                    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs space-y-4">
                      {headerReport.is_demo_data && (
                        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 flex items-center gap-2">
                          <span className="text-base">⚠️</span>
                          <div>
                            <strong>DEMO SAMPLE DATA:</strong> These diagnostics are evaluated on synthetic demo text for testing purposes. They do not reflect an actual email sent by your domain.
                          </div>
                        </div>
                      )}

                      <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-bold text-gray-900">Header Inspection Diagnostics</h4>
                          {getStatusBadge(headerReport.overall_status)}
                        </div>
                        <span className="text-xs text-gray-500 font-mono">
                          From: {headerReport.from_domain || 'Unknown'}
                        </span>
                      </div>

                      {/* Verdict Cards */}
                      <div className="grid grid-cols-3 gap-3">
                        <div className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="font-bold text-gray-600">SPF Verdict</span>
                            <span className={`font-bold uppercase ${headerReport.spf?.verdict === 'pass' ? 'text-emerald-700' : 'text-rose-700'}`}>
                              {headerReport.spf?.verdict}
                            </span>
                          </div>
                          <span className="text-[11px] text-gray-500 block">
                            Alignment: {headerReport.spf?.aligned ? 'Aligned ✓' : 'Unaligned ✗'}
                          </span>
                        </div>

                        <div className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="font-bold text-gray-600">DKIM Signature</span>
                            <span className={`font-bold uppercase ${headerReport.dkim?.verdict === 'pass' ? 'text-emerald-700' : 'text-amber-700'}`}>
                              {headerReport.dkim?.verdict}
                            </span>
                          </div>
                          <span className="text-[11px] text-gray-500 block">
                            Alignment: {headerReport.dkim?.aligned ? 'Aligned ✓' : 'Unaligned ✗'}
                          </span>
                          {headerReport.dkim?.dns_key_matched && (
                            <span className="text-[10px] text-emerald-700 font-semibold block mt-0.5">
                              ✓ Matches Published DNS Key
                            </span>
                          )}
                        </div>

                        <div className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="font-bold text-gray-600">DMARC Verdict</span>
                            <span className={`font-bold uppercase ${headerReport.dmarc?.verdict === 'pass' ? 'text-emerald-700' : 'text-gray-600'}`}>
                              {headerReport.dmarc?.verdict}
                            </span>
                          </div>
                          <span className="text-[11px] text-gray-500 block">
                            Recipient evaluation
                          </span>
                        </div>
                      </div>

                      {/* Diagnostics list */}
                      <div className="space-y-1.5 pt-2">
                        {headerReport.diagnostics?.map((diag, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs p-2 bg-slate-50 rounded">
                            <span>{diag.status === 'pass' ? '✅' : diag.status === 'fail' ? '❌' : '⚠️'}</span>
                            <span className="font-semibold text-gray-700">[{diag.category}]</span>
                            <span className="text-gray-800">{diag.message}</span>
                          </div>
                        ))}
                      </div>

                      {/* Header details */}
                      <div className="pt-2 border-t border-gray-100 text-[11px] font-mono text-gray-500 space-y-1">
                        <div><strong>Sending Relay:</strong> {headerReport.sending_relay_host || 'Unknown'} {headerReport.sending_relay_ip ? `[${headerReport.sending_relay_ip}]` : ''}</div>
                        <div><strong>Message-ID:</strong> {headerReport.message_id || 'Not specified'}</div>
                        <div><strong>Return-Path:</strong> {headerReport.return_path || 'Not specified'}</div>
                        <div><strong>Subject:</strong> {headerReport.subject || 'Not specified'}</div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
          <span className="text-[11px] text-gray-500">
            Weblinx Deliverability Engine • Authoritative DNS + Live Header Inspection
          </span>
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

      </div>
    </div>
  );
}

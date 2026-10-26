import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';
import { useNotify } from '../context/NotificationContext';
import {
  RiCloseLine,
  RiSendPlaneFill,
  RiTimeLine,
  RiMailLine,
  RiUserLine,
  RiFileTextLine,
  RiEyeLine,
  RiEditLine,
  RiCheckLine,
  RiInformationLine,
  RiFlashlightLine,
  RiAttachment2,
} from 'react-icons/ri';

const QUICK_VARIABLES = [
  { key: '{{first_name}}', label: 'First Name' },
  { key: '{{last_name}}', label: 'Last Name' },
  { key: '{{company_name}}', label: 'Company' },
  { key: '{{industry}}', label: 'Industry' },
  { key: '{{website}}', label: 'Website' },
  { key: '{{city}}', label: 'City' },
];

export default function ComposeModal({
  isOpen,
  onClose,
  onSent,
  initialTo = '',
  initialRecipientName = '',
  initialLeadId = null,
  initialSubject = '',
  initialBody = '',
}) {
  const notify = useNotify();

  const [inboxes, setInboxes] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [loadingMeta, setLoadingMeta] = useState(false);

  const [selectedInboxId, setSelectedInboxId] = useState('');
  const [toEmail, setToEmail] = useState(initialTo);
  const [recipientName, setRecipientName] = useState(initialRecipientName);
  const [leadId, setLeadId] = useState(initialLeadId);
  const [subject, setSubject] = useState(initialSubject);
  const [body, setBody] = useState(initialBody);
  const [isHtml, setIsHtml] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');

  const [sendMode, setSendMode] = useState('immediate'); // 'immediate' | 'scheduled'
  const [scheduledAt, setScheduledAt] = useState('');
  const [openTracking, setOpenTracking] = useState(true);
  const [enableFollowUp, setEnableFollowUp] = useState(false);

  const [sending, setSending] = useState(false);
  const [previewTab, setPreviewTab] = useState(false); // false = edit, true = preview
  const [activeFocusField, setActiveFocusField] = useState('body'); // 'subject' or 'body'
  const [attachments, setAttachments] = useState([]);

  const bodyInputRef = useRef(null);
  const subjectInputRef = useRef(null);

  // Sync props when opening
  useEffect(() => {
    if (isOpen) {
      setToEmail(initialTo || '');
      setRecipientName(initialRecipientName || '');
      setLeadId(initialLeadId || null);
      if (initialSubject) setSubject(initialSubject);
      if (initialBody) setBody(initialBody);

      // Default scheduled time = +1 hour
      const nextHour = new Date(Date.now() + 60 * 60 * 1000);
      nextHour.setMinutes(0, 0, 0);
      const tzOffset = nextHour.getTimezoneOffset() * 60000;
      const localISOTime = new Date(nextHour.getTime() - tzOffset).toISOString().slice(0, 16);
      setScheduledAt(localISOTime);

      // Load inboxes and templates
      loadMetadata();
    }
  }, [isOpen, initialTo, initialRecipientName, initialLeadId, initialSubject, initialBody]);

  const loadMetadata = async () => {
    setLoadingMeta(true);
    try {
      const [inboxRes, tmplRes] = await Promise.all([
        api.get('/inboxes').catch(() => []),
        api.get('/templates').catch(() => []),
      ]);

      const inboxList = Array.isArray(inboxRes) ? inboxRes : (inboxRes?.items || []);
      setInboxes(inboxList);
      if (inboxList.length > 0 && !selectedInboxId) {
        // Auto select first active inbox
        const active = inboxList.find((i) => i.is_active !== false) || inboxList[0];
        setSelectedInboxId(String(active.id));
      }

      const tmplList = Array.isArray(tmplRes) ? tmplRes : (tmplRes?.items || []);
      setTemplates(tmplList);
    } catch {
      // silently handle
    } finally {
      setLoadingMeta(false);
    }
  };

  const handleTemplateSelect = (tmplId) => {
    setSelectedTemplateId(tmplId);
    if (!tmplId) return;

    const tmpl = templates.find((t) => String(t.id) === String(tmplId));
    if (tmpl) {
      setSubject(tmpl.subject || '');
      setBody(tmpl.body || '');
      setIsHtml(Boolean(tmpl.is_html));
      notify({ type: 'info', message: `Loaded template "${tmpl.name}"` });
    }
  };

  const insertVariable = (variableKey) => {
    if (activeFocusField === 'subject') {
      const el = subjectInputRef.current;
      if (!el) {
        setSubject((prev) => prev + variableKey);
        return;
      }
      const start = el.selectionStart || 0;
      const end = el.selectionEnd || 0;
      const next = subject.slice(0, start) + variableKey + subject.slice(end);
      setSubject(next);
      setTimeout(() => {
        el.focus();
        el.setSelectionRange(start + variableKey.length, start + variableKey.length);
      }, 0);
    } else {
      const el = bodyInputRef.current;
      if (!el) {
        setBody((prev) => prev + variableKey);
        return;
      }
      const start = el.selectionStart || 0;
      const end = el.selectionEnd || 0;
      const next = body.slice(0, start) + variableKey + body.slice(end);
      setBody(next);
      setTimeout(() => {
        el.focus();
        el.setSelectionRange(start + variableKey.length, start + variableKey.length);
      }, 0);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (sending) return;

    if (!selectedInboxId) {
      notify({ type: 'error', message: 'Please select a sending inbox account.' });
      return;
    }
    if (!toEmail || !toEmail.includes('@')) {
      notify({ type: 'error', message: 'Please enter a valid recipient email address.' });
      return;
    }
    if (!subject.trim()) {
      notify({ type: 'error', message: 'Subject line cannot be empty.' });
      return;
    }
    if (!body.trim()) {
      notify({ type: 'error', message: 'Email body cannot be empty.' });
      return;
    }

    let parsedScheduledAt = null;
    if (sendMode === 'scheduled') {
      if (!scheduledAt) {
        notify({ type: 'error', message: 'Please specify a scheduled delivery date and time.' });
        return;
      }
      const d = new Date(scheduledAt);
      if (isNaN(d.getTime())) {
        notify({ type: 'error', message: 'Invalid scheduled date/time.' });
        return;
      }
      parsedScheduledAt = d.toISOString();
    }

    setSending(true);
    try {
      const payload = {
        inbox_id: parseInt(selectedInboxId, 10),
        to_email: toEmail.trim(),
        recipient_name: recipientName.trim() || undefined,
        lead_id: leadId || undefined,
        template_id: selectedTemplateId ? parseInt(selectedTemplateId, 10) : undefined,
        subject: subject.trim(),
        body: body,
        is_html: isHtml,
        scheduled_at: parsedScheduledAt,
        open_tracking: openTracking,
        track_opens: openTracking,
        enable_follow_up: enableFollowUp,
      };

      const res = await api.post('/direct-emails', payload);

      if (sendMode === 'scheduled') {
        notify({ type: 'success', message: 'Email scheduled successfully!' });
      } else if (res?.error_message?.includes('tracking or saving failed') || res?.warning?.includes('tracking or saving failed')) {
        notify({ type: 'warning', message: 'Sent, but tracking or saving failed. Check sent history.' });
      } else if (res?.warning) {
        notify({ type: 'info', message: res.warning });
      } else {
        notify({ type: 'success', message: 'Direct email sent successfully!' });
      }

      if (onSent) {
        onSent(res);
      }
      onClose();
    } catch (err) {
      const errMsg = err.message || '';
      if (errMsg.toLowerCase().includes('already sent') || errMsg.toLowerCase().includes('duplicate')) {
        notify({ type: 'warning', message: 'Email already sent to this recipient. Duplicate send prevented.' });
        if (onSent) onSent();
        onClose();
      } else if (errMsg.includes('tracking or saving failed')) {
        notify({ type: 'warning', message: 'Sent, but tracking or saving failed. Check sent history.' });
        if (onSent) onSent();
        onClose();
      } else if (errMsg.includes('currently being delivered')) {
        notify({ type: 'warning', message: errMsg });
      } else {
        notify({ type: 'error', message: errMsg || 'Failed to send direct email.' });
      }
    } finally {
      setSending(false);
    }
  };

  if (!isOpen) return null;

  // Render dummy preview with variables substituted
  const renderPreview = (text) => {
    let out = text || '';
    const sample = {
      '{{first_name}}': recipientName ? recipientName.split(' ')[0] : 'Alex',
      '{{last_name}}': recipientName && recipientName.split(' ').length > 1 ? recipientName.split(' ').slice(1).join(' ') : 'Mercer',
      '{{name}}': recipientName || 'Alex Mercer',
      '{{company_name}}': 'Weblinx Solution',
      '{{industry}}': 'Software & AI Solutions',
      '{{website}}': 'https://weblinxsolution.com',
      '{{city}}': 'San Francisco',
    };
    for (const [k, v] of Object.entries(sample)) {
      out = out.split(k).join(v);
    }
    return out;
  };

  const previewSubject = renderPreview(subject);
  const previewBody = renderPreview(body);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-3xl rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden my-6 flex flex-col max-h-[92vh]">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-teal-50 dark:bg-teal-950/40 text-teal-600 dark:text-teal-400">
              <RiMailLine size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">Compose Direct Email</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Send a personalized one-off email directly through any connected inbox
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors"
          >
            <RiCloseLine size={22} />
          </button>
        </div>

        {/* Modal Body */}
        <form onSubmit={handleSend} className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Sending Inbox & Template Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                From Sending Account <span className="text-red-500">*</span>
              </label>
              <select
                value={selectedInboxId}
                onChange={(e) => setSelectedInboxId(e.target.value)}
                className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
                required
              >
                {inboxes.length === 0 ? (
                  <option value="">No inboxes connected</option>
                ) : (
                  inboxes.map((inbox) => (
                    <option key={inbox.id} value={inbox.id}>
                      {inbox.email} ({inbox.type ? inbox.type.toUpperCase() : 'INBOX'}{inbox.is_active === false ? ' - Inactive' : ''})
                    </option>
                  ))
                )}
              </select>
              {inboxes.length === 0 && !loadingMeta && (
                <p className="text-[11px] text-amber-600 mt-1">
                  Connect an inbox under Inboxes first before sending.
                </p>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Load Saved Template (Optional)
              </label>
              <select
                value={selectedTemplateId}
                onChange={(e) => handleTemplateSelect(e.target.value)}
                className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                <option value="">-- Custom Email (Write from scratch) --</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.category || 'General'})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Recipient Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Recipient Email <span className="text-red-500">*</span>
              </label>
              <input
                type="email"
                value={toEmail}
                onChange={(e) => setToEmail(e.target.value)}
                placeholder="prospect@company.com"
                className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Recipient Name (Optional)
              </label>
              <input
                type="text"
                value={recipientName}
                onChange={(e) => setRecipientName(e.target.value)}
                placeholder="e.g. John Doe"
                className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          {/* Variable Insertion Pills */}
          <div className="bg-slate-50 dark:bg-slate-800/40 p-2.5 rounded-lg border border-slate-200 dark:border-slate-700/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] font-semibold text-slate-600 dark:text-slate-300 flex items-center gap-1">
                <RiFlashlightLine size={13} className="text-amber-500" /> Insert Personalization Variable:
              </span>
              <span className="text-[10px] text-slate-400">
                Clicking inserts at cursor into {activeFocusField === 'subject' ? 'Subject' : 'Message'}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {QUICK_VARIABLES.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  onClick={() => insertVariable(v.key)}
                  className="px-2 py-0.5 text-[11px] font-mono bg-white dark:bg-slate-700 text-teal-700 dark:text-teal-300 rounded border border-slate-200 dark:border-slate-600 hover:border-teal-400 hover:bg-teal-50 dark:hover:bg-teal-900/40 transition-colors shadow-sm"
                  title={`Insert ${v.label}`}
                >
                  {v.key}
                </button>
              ))}
            </div>
          </div>

          {/* Subject Line */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Subject Line <span className="text-red-500">*</span>
            </label>
            <input
              ref={subjectInputRef}
              type="text"
              value={subject}
              onFocus={() => setActiveFocusField('subject')}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Quick question about {{company_name}}..."
              className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
              required
            />
          </div>

          {/* Body Editor with Edit / Preview Switch */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                Email Message <span className="text-red-500">*</span>
              </label>
              <div className="flex items-center gap-2">
                <label className="inline-flex items-center gap-1 text-[11px] text-slate-500 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isHtml}
                    onChange={(e) => setIsHtml(e.target.checked)}
                    className="rounded text-teal-600 focus:ring-teal-500 text-xs"
                  />
                  <span>Format as HTML</span>
                </label>
                <div className="flex border border-slate-200 dark:border-slate-700 rounded-md overflow-hidden text-xs">
                  <button
                    type="button"
                    onClick={() => setPreviewTab(false)}
                    className={`px-2.5 py-1 flex items-center gap-1 ${
                      !previewTab
                        ? 'bg-teal-600 text-white font-medium'
                        : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100'
                    }`}
                  >
                    <RiEditLine size={13} /> Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewTab(true)}
                    className={`px-2.5 py-1 flex items-center gap-1 ${
                      previewTab
                        ? 'bg-teal-600 text-white font-medium'
                        : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100'
                    }`}
                  >
                    <RiEyeLine size={13} /> Preview
                  </button>
                </div>
              </div>
            </div>

            {!previewTab ? (
              <textarea
                ref={bodyInputRef}
                rows={9}
                value={body}
                onFocus={() => setActiveFocusField('body')}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Hi {{first_name}},&#10;&#10;I noticed your work at {{company_name}} and wanted to reach out..."
                className="w-full text-xs font-sans rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500 resize-y"
                required
              />
            ) : (
              <div className="min-h-[220px] p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 space-y-2">
                <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 border-b border-slate-200 dark:border-slate-700 pb-2">
                  <span className="text-slate-400 font-normal">Subject: </span>
                  {previewSubject || '<Empty Subject>'}
                </div>
                {isHtml ? (
                  <div
                    className="text-xs text-slate-700 dark:text-slate-300 prose dark:prose-invert max-w-none pt-2"
                    dangerouslySetInnerHTML={{ __html: previewBody || '<em>No message entered</em>' }}
                  />
                ) : (
                  <div className="text-xs text-slate-700 dark:text-slate-300 whitespace-pre-wrap font-sans pt-2">
                    {previewBody || 'No message entered'}
                  </div>
                )}
                <div className="pt-3 border-t border-slate-200 dark:border-slate-700 text-[10px] text-slate-400 italic">
                  * Live preview rendered with simulated recipient variables.
                </div>
              </div>
            )}

            {/* File Attachments Selector */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <label className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer text-xs font-medium transition-colors shadow-2xs">
                <RiAttachment2 size={14} className="text-teal-600 dark:text-teal-400" />
                <span>Attach Files</span>
                <input
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files) {
                      setAttachments((prev) => [...prev, ...Array.from(e.target.files)]);
                    }
                  }}
                />
              </label>

              {attachments.map((file, idx) => (
                <div
                  key={idx}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg bg-teal-50 dark:bg-teal-950/40 text-teal-800 dark:text-teal-200 border border-teal-200 dark:border-teal-800"
                >
                  <span className="truncate max-w-[140px] font-medium">{file.name}</span>
                  <span className="text-[10px] text-teal-600 dark:text-teal-400 font-mono">
                    ({Math.max(1, Math.round(file.size / 1024))} KB)
                  </span>
                  <button
                    type="button"
                    onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-teal-600 hover:text-teal-800 dark:hover:text-teal-300 ml-1 font-bold p-0.5"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Delivery & Automation Controls */}
          <div className="bg-slate-50 dark:bg-slate-800/40 p-4 rounded-xl border border-slate-200 dark:border-slate-700/60 space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              {/* Send mode: Immediate vs Scheduled */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Delivery Timing
                </label>
                <div className="flex items-center gap-2">
                  <label className="inline-flex items-center gap-1.5 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
                    <input
                      type="radio"
                      name="sendMode"
                      value="immediate"
                      checked={sendMode === 'immediate'}
                      onChange={() => setSendMode('immediate')}
                      className="text-teal-600 focus:ring-teal-500"
                    />
                    <span>Send Immediately</span>
                  </label>
                  <label className="inline-flex items-center gap-1.5 text-xs text-slate-700 dark:text-slate-300 cursor-pointer ml-2">
                    <input
                      type="radio"
                      name="sendMode"
                      value="scheduled"
                      checked={sendMode === 'scheduled'}
                      onChange={() => setSendMode('scheduled')}
                      className="text-teal-600 focus:ring-teal-500"
                    />
                    <span>Schedule for Later</span>
                  </label>
                </div>
              </div>

              {sendMode === 'scheduled' && (
                <div className="sm:max-w-xs w-full">
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Scheduled Time
                  </label>
                  <input
                    type="datetime-local"
                    value={scheduledAt}
                    onChange={(e) => setScheduledAt(e.target.value)}
                    className="w-full text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
                    required={sendMode === 'scheduled'}
                  />
                </div>
              )}
            </div>

            {/* Tracking & Follow-up Options */}
            <div className="pt-2 border-t border-slate-200 dark:border-slate-700/60 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
              <label className="inline-flex items-center gap-2 text-slate-700 dark:text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={openTracking}
                  onChange={(e) => setOpenTracking(e.target.checked)}
                  className="rounded text-teal-600 focus:ring-teal-500"
                />
                <span>Track estimated email opens (tracking pixel)</span>
              </label>

              <label
                className="inline-flex items-center gap-2 text-slate-700 dark:text-slate-300 cursor-pointer"
                title="Manual direct emails will not trigger automated sequence follow-ups unless checked."
              >
                <input
                  type="checkbox"
                  checked={enableFollowUp}
                  onChange={(e) => setEnableFollowUp(e.target.checked)}
                  className="rounded text-teal-600 focus:ring-teal-500"
                />
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  Enable campaign follow-up sequence
                </span>
              </label>
            </div>
            {!enableFollowUp && (
              <p className="text-[11px] text-slate-400">
                <RiInformationLine size={12} className="inline mr-1" />
                Individual manual emails do not trigger follow-up sequences automatically.
              </p>
            )}
          </div>

          {/* Modal Footer */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-800">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={sending}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={sending || inboxes.length === 0}
              className="bg-teal-600 hover:bg-teal-700 text-white flex items-center gap-1.5 shadow-sm"
            >
              {sending ? (
                <>Sending...</>
              ) : sendMode === 'scheduled' ? (
                <>
                  <RiTimeLine size={16} /> Schedule Email
                </>
              ) : (
                <>
                  <RiSendPlaneFill size={16} /> Send Email Now
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

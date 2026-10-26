import { useState, useEffect } from 'react';
import { api } from '../api';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import {
  RiAddLine,
  RiFileCopyLine,
  RiDeleteBinLine,
  RiEditLine,
  RiEyeLine,
  RiSendPlaneLine,
  RiSearchLine,
  RiCloseLine,
  RiCheckLine,
  RiInformationLine,
  RiCodeSSlashLine,
  RiFileTextLine,
} from 'react-icons/ri';

const VARIABLES = [
  { key: '{{first_name}}', desc: 'First Name' },
  { key: '{{last_name}}', desc: 'Last Name' },
  { key: '{{company_name}}', desc: 'Company' },
  { key: '{{industry}}', desc: 'Industry' },
  { key: '{{city}}', desc: 'City' },
  { key: '{{website}}', desc: 'Website' },
  { key: '{{notes}}', desc: 'Prospect Notes' },
];

export default function Templates() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');

  // Edit/Create Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    subject: '',
    body: '',
    is_html: false,
    category: 'General',
  });
  const [activeFocusField, setActiveFocusField] = useState('body'); // 'subject' or 'body'
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // Preview Drawer/Modal state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Test send state
  const [testSendOpen, setTestSendOpen] = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [testSending, setTestSending] = useState(false);
  const [testStatus, setTestStatus] = useState(null);

  const fetchTemplates = async () => {
    try {
      setLoading(true);
      const data = await api.get('/templates');
      setTemplates(data || []);
    } catch (err) {
      console.error('Failed to load templates:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const openCreateModal = () => {
    setEditingTemplate(null);
    setFormData({
      name: '',
      subject: '',
      body: '',
      is_html: false,
      category: 'Cold Outreach',
    });
    setErrorMessage('');
    setModalOpen(true);
  };

  const openEditModal = (tmpl) => {
    setEditingTemplate(tmpl);
    setFormData({
      name: tmpl.name,
      subject: tmpl.subject,
      body: tmpl.body,
      is_html: tmpl.is_html,
      category: tmpl.category || 'General',
    });
    setErrorMessage('');
    setModalOpen(true);
  };

  const insertVariable = (varKey) => {
    if (activeFocusField === 'subject') {
      setFormData((prev) => ({ ...prev, subject: prev.subject + varKey }));
    } else {
      setFormData((prev) => ({ ...prev, body: prev.body + varKey }));
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!formData.name.trim() || !formData.subject.trim() || !formData.body.trim()) {
      setErrorMessage('Name, subject, and email body are required.');
      return;
    }

    try {
      setSaving(true);
      setErrorMessage('');
      if (editingTemplate) {
        await api.put(`/templates/${editingTemplate.id}`, formData);
      } else {
        await api.post('/templates', formData);
      }
      setModalOpen(false);
      await fetchTemplates();
    } catch (err) {
      setErrorMessage(err.message || 'Failed to save template.');
    } finally {
      setSaving(false);
    }
  };

  const handleDuplicate = async (tmpl) => {
    try {
      await api.post(`/templates/${tmpl.id}/duplicate`);
      await fetchTemplates();
    } catch (err) {
      alert('Failed to duplicate template: ' + (err.message || 'Unknown error'));
    }
  };

  const handleDelete = async (tmpl) => {
    if (!window.confirm(`Are you sure you want to delete template "${tmpl.name}"?`)) return;
    try {
      if (typeof api.delete === 'function') {
        await api.delete(`/templates/${tmpl.id}`);
      } else {
        await api.del(`/templates/${tmpl.id}`);
      }
      await fetchTemplates();
    } catch (err) {
      alert('Failed to delete template: ' + (err.message || 'Unknown error'));
    }
  };

  const openPreview = async (tmpl) => {
    try {
      setPreviewLoading(true);
      setPreviewOpen(true);
      const res = await api.post('/templates/preview', {
        subject: tmpl.subject,
        body: tmpl.body,
        sample_data: {
          first_name: 'Jordan',
          last_name: 'Belfort',
          company_name: 'Stratton Oakmont',
          industry: 'Financial Advisory',
          city: 'New York',
          website: 'https://weblinxsolution.com',
          notes: 'Key decision maker for sales tech',
        },
      });
      setPreviewData(res);
    } catch (err) {
      console.error(err);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleTestSend = async (e) => {
    e.preventDefault();
    if (!testEmail || !testEmail.includes('@')) {
      setTestStatus({ ok: false, msg: 'Please provide a valid recipient email.' });
      return;
    }
    try {
      setTestSending(true);
      setTestStatus(null);
      await api.post('/templates/test-send', {
        recipient_email: testEmail,
        subject: formData.subject,
        body: formData.body,
        is_html: formData.is_html,
      });
      setTestStatus({ ok: true, msg: `Test email successfully queued to ${testEmail}!` });
      setTimeout(() => {
        setTestSendOpen(false);
        setTestStatus(null);
      }, 2500);
    } catch (err) {
      setTestStatus({ ok: false, msg: err.message || 'Failed to send test email.' });
    } finally {
      setTestSending(false);
    }
  };

  const categories = ['all', ...Array.from(new Set(templates.map((t) => t.category || 'General')))];

  const filtered = templates.filter((t) => {
    const matchCat = categoryFilter === 'all' || (t.category || 'General') === categoryFilter;
    const matchSearch =
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.subject.toLowerCase().includes(search.toLowerCase());
    return matchCat && matchSearch;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
            Email Templates Library
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Build, test, and personalize high-converting reusable cold email copy with dynamic variables.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={openCreateModal} variant="primary" className="flex items-center gap-2">
            <RiAddLine size={18} />
            <span>Create Template</span>
          </Button>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="relative w-full sm:w-80">
          <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <input
            type="text"
            placeholder="Search templates or subjects..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 mr-1">Category:</span>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors whitespace-nowrap capitalize ${
                categoryFilter === cat
                  ? 'bg-primary-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Templates Grid */}
      {loading ? (
        <div className="flex items-center justify-center p-16 text-slate-400">Loading templates...</div>
      ) : filtered.length === 0 ? (
        <Card className="text-center py-16 px-4">
          <div className="w-12 h-12 mx-auto rounded-full bg-primary-50 dark:bg-primary-950/40 text-primary-600 flex items-center justify-center mb-3">
            <RiFileTextLine size={24} />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">No email templates found</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto mt-1 mb-4">
            {search ? 'Try adjusting your search criteria' : 'Create reusable cold email templates with personalized prospect placeholders.'}
          </p>
          <Button onClick={openCreateModal} variant="primary" className="mx-auto">
            Create First Template
          </Button>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((tmpl) => (
            <div
              key={tmpl.id}
              className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm hover:shadow-md transition-shadow flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                    {tmpl.category || 'General'}
                  </span>
                  <div className="flex items-center gap-1 text-slate-400">
                    {tmpl.is_html ? (
                      <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 px-1.5 py-0.5 rounded">
                        <RiCodeSSlashLine size={12} /> HTML
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] font-mono text-slate-500 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                        Plain Text
                      </span>
                    )}
                  </div>
                </div>

                <h3 className="font-semibold text-slate-900 dark:text-white text-base line-clamp-1">
                  {tmpl.name}
                </h3>
                <p className="text-xs font-medium text-primary-600 dark:text-primary-400 mt-1 line-clamp-1">
                  Subject: <span className="text-slate-700 dark:text-slate-300 font-normal">{tmpl.subject}</span>
                </p>

                <p className="text-xs text-slate-500 dark:text-slate-400 mt-3 line-clamp-4 whitespace-pre-line bg-slate-50 dark:bg-slate-800/50 p-2.5 rounded-lg border border-slate-100 dark:border-slate-800 font-sans">
                  {tmpl.body}
                </p>
              </div>

              <div className="flex items-center justify-between pt-4 mt-4 border-t border-slate-100 dark:border-slate-800">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => openPreview(tmpl)}
                    title="Live Preview"
                    className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
                  >
                    <RiEyeLine size={16} />
                  </button>
                  <button
                    onClick={() => handleDuplicate(tmpl)}
                    title="Duplicate"
                    className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
                  >
                    <RiFileCopyLine size={16} />
                  </button>
                  <button
                    onClick={() => openEditModal(tmpl)}
                    title="Edit"
                    className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-700 dark:hover:text-white transition-colors"
                  >
                    <RiEditLine size={16} />
                  </button>
                </div>

                <button
                  onClick={() => handleDelete(tmpl)}
                  title="Delete"
                  className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40 text-red-500 transition-colors"
                >
                  <RiDeleteBinLine size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create / Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
              <div>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  {editingTemplate ? 'Edit Email Template' : 'New Email Template'}
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Compose dynamic cold outreach emails with variable fallbacks.
                </p>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-white"
              >
                <RiCloseLine size={24} />
              </button>
            </div>

            <form onSubmit={handleSave} className="p-6 space-y-4 overflow-y-auto flex-1">
              {errorMessage && (
                <div className="p-3 text-xs bg-red-50 dark:bg-red-950/40 text-red-600 border border-red-200 dark:border-red-900 rounded-lg">
                  {errorMessage}
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Template Name
                  </label>
                  <Input
                    placeholder="e.g. Founder Cold Intro - SaaS"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Category
                  </label>
                  <Input
                    placeholder="e.g. Cold Outreach, Follow-up, Meeting"
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  />
                </div>
              </div>

              {/* Dynamic Variables Bar */}
              <div className="bg-slate-50 dark:bg-slate-800/60 p-3 rounded-xl border border-slate-200 dark:border-slate-700/60">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
                    <RiInformationLine size={14} className="text-primary-500" />
                    Insert Variable (into {activeFocusField === 'subject' ? 'Subject' : 'Email Body'}):
                  </span>
                  <div className="text-[11px] text-slate-400">
                    Supports fallback: <code className="bg-slate-200 dark:bg-slate-700 px-1 rounded">{'{{company_name | your team}}'}</code>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {VARIABLES.map((v) => (
                    <button
                      type="button"
                      key={v.key}
                      onClick={() => insertVariable(v.key)}
                      className="px-2 py-1 text-xs font-mono bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-md text-primary-600 dark:text-primary-400 hover:border-primary-500 transition-colors shadow-sm"
                    >
                      {v.key}
                    </button>
                  ))}
                </div>
              </div>

              {/* Subject Line */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Subject Line
                </label>
                <input
                  type="text"
                  placeholder="Quick question regarding {{company_name}}"
                  value={formData.subject}
                  onFocus={() => setActiveFocusField('subject')}
                  onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                />
              </div>

              {/* Body */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                    Email Body
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.is_html}
                      onChange={(e) => setFormData({ ...formData, is_html: e.target.checked })}
                      className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
                    />
                    <span>Rich HTML Format</span>
                  </label>
                </div>
                <textarea
                  rows={8}
                  placeholder={`Hi {{first_name}},\n\nI noticed {{company_name}} is expanding in {{city}}...\n\nBest,\nYour Name`}
                  value={formData.body}
                  onFocus={() => setActiveFocusField('body')}
                  onChange={(e) => setFormData({ ...formData, body: e.target.value })}
                  className="w-full px-3 py-2 text-sm font-sans rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                />
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-800">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setTestSendOpen(true);
                  }}
                  className="flex items-center gap-2"
                >
                  <RiSendPlaneLine size={16} />
                  <span>Send Test Email</span>
                </Button>

                <div className="flex items-center gap-3">
                  <Button type="button" variant="ghost" onClick={() => setModalOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" variant="primary" disabled={saving}>
                    {saving ? 'Saving...' : editingTemplate ? 'Update Template' : 'Create Template'}
                  </Button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Live Preview Modal */}
      {previewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl max-w-2xl w-full p-6">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-slate-800 mb-4">
              <div className="flex items-center gap-2">
                <RiEyeLine className="text-primary-500" size={20} />
                <h3 className="font-bold text-slate-900 dark:text-white">Rendered Prospect Preview</h3>
              </div>
              <button
                onClick={() => setPreviewOpen(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-white"
              >
                <RiCloseLine size={22} />
              </button>
            </div>

            {previewLoading ? (
              <div className="py-12 text-center text-slate-400 text-sm">Rendering preview with sample data...</div>
            ) : previewData ? (
              <div className="space-y-4">
                <div className="bg-slate-50 dark:bg-slate-800/60 p-3 rounded-lg border border-slate-200 dark:border-slate-700 text-xs">
                  <div className="font-semibold text-slate-700 dark:text-slate-300">
                    Subject: <span className="font-normal text-slate-900 dark:text-white">{previewData.rendered_subject}</span>
                  </div>
                  <div className="text-slate-400 mt-1">
                    Sample: Jordan Belfort (Stratton Oakmont, New York)
                  </div>
                </div>

                <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm font-sans whitespace-pre-wrap text-slate-800 dark:text-slate-200 min-h-[160px]">
                  {previewData.rendered_body}
                </div>

                <div className="flex justify-end pt-2">
                  <Button variant="secondary" onClick={() => setPreviewOpen(false)}>
                    Close Preview
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Test Send Modal */}
      {testSendOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-xl max-w-md w-full p-5">
            <h3 className="text-base font-bold text-slate-900 dark:text-white mb-2">Send Test Outreach Email</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
              Send a rendered test email with sample lead variables to verify formatting and deliverability.
            </p>

            {testStatus && (
              <div
                className={`p-3 text-xs rounded-lg mb-4 flex items-center gap-2 ${
                  testStatus.ok
                    ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                    : 'bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800'
                }`}
              >
                {testStatus.ok ? <RiCheckLine size={16} /> : <RiCloseLine size={16} />}
                <span>{testStatus.msg}</span>
              </div>
            )}

            <form onSubmit={handleTestSend} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Recipient Test Email Address
                </label>
                <Input
                  type="email"
                  placeholder="yourname@weblinxsolution.com"
                  value={testEmail}
                  onChange={(e) => setTestEmail(e.target.value)}
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <Button type="button" variant="ghost" onClick={() => setTestSendOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" disabled={testSending}>
                  {testSending ? 'Sending...' : 'Send Test'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

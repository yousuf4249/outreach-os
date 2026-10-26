import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api, apiCache } from '../api';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Input } from '../components/ui/Input';
import ErrorBoundary from '../components/ErrorBoundary';
import { useConfirm } from '../context/ConfirmContext';
import { useNotify } from '../context/NotificationContext';
import {
  RiDeleteBinLine,
  RiArchiveLine,
  RiInboxUnarchiveLine,
  RiPauseCircleLine,
  RiPlayCircleLine,
  RiSearchLine,
  RiCloseLine,
  RiAlertLine,
  RiCheckDoubleLine,
  RiFileCopyLine,
  RiFilterLine,
} from 'react-icons/ri';

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState(() => apiCache.get('/campaigns') || []);
  const [error, setError] = useState(null);

  // Scheduling strategy from server ("priority" or other)
  const [strategy, setStrategy] = useState('priority');
  const [orderChanged, setOrderChanged] = useState(false);
  const dragSrcIdx = useRef(null);
  const confirm = useConfirm();
  const notify = useNotify();

  // Search & Filter state
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all'); // 'all' | 'active' | 'paused' | 'completed' | 'archived'

  // Selection state
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selectAllFiltered, setSelectAllFiltered] = useState(false);

  // Bulk operation modals & loading
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [camp, strat] = await Promise.all([
        api.get('/campaigns'),
        api.get('/settings/scheduling-strategy').catch(() => ({ scheduling_strategy: 'priority' })),
      ]);
      setCampaigns(camp);
      setStrategy(strat.scheduling_strategy || 'priority');
      setOrderChanged(false);
    } catch (e) {
      setError('Failed to load campaigns');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Drag and drop helpers (only used when strategy === 'priority' and no filter/search active)
  const isPriority = strategy === 'priority';
  const canReorder = isPriority && !search.trim() && statusFilter === 'all';

  const onDragStart = (e, idx) => {
    dragSrcIdx.current = idx;
    e.currentTarget.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  };
  const onDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    e.currentTarget.classList.add('drag-over');
  };
  const onDragLeave = (e) => {
    e.currentTarget.classList.remove('drag-over');
  };
  const onDrop = (e, idx) => {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    const src = dragSrcIdx.current;
    if (src === null || src === idx) return;
    const newList = [...campaigns];
    const [moved] = newList.splice(src, 1);
    newList.splice(idx, 0, moved);
    setCampaigns(newList);
    setOrderChanged(true);
  };
  const onDragEnd = (e) => {
    e.currentTarget.classList.remove('dragging');
    dragSrcIdx.current = null;
  };

  const saveOrder = async () => {
    if (!orderChanged) return;
    try {
      await api.post('/campaigns/reorder', { campaign_ids: campaigns.map((c) => c.id) });
      setOrderChanged(false);
      notify({ type: 'success', message: 'Order saved' });
    } catch (e) {
      notify({ type: 'error', message: 'Error saving order' });
    }
  };

  // Filtered campaigns
  const filteredCampaigns = useMemo(() => {
    return campaigns.filter((c) => {
      // 1. Search query
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        if (!c.name.toLowerCase().includes(q)) return false;
      }

      const isArchived = Boolean(c.archived);

      // 2. Status filter
      if (statusFilter === 'archived') {
        return isArchived;
      }
      // If not viewing archived, exclude archived campaigns
      if (isArchived && statusFilter !== 'archived') {
        return false;
      }

      if (statusFilter === 'all') return true;

      const stats = c.stats || {};
      const scheduled = stats.scheduled || 0;
      const emailsSent = stats.emails_sent || 0;
      const isCompleted = !c.paused && scheduled === 0 && emailsSent > 0;

      if (statusFilter === 'paused') return Boolean(c.paused);
      if (statusFilter === 'completed') return isCompleted;
      if (statusFilter === 'active') return !c.paused && !isCompleted;

      return true;
    });
  }, [campaigns, search, statusFilter]);

  // Counts for filter tabs
  const filterCounts = useMemo(() => {
    let all = 0;
    let active = 0;
    let paused = 0;
    let completed = 0;
    let archived = 0;

    campaigns.forEach((c) => {
      if (c.archived) {
        archived++;
        return;
      }
      all++;
      const stats = c.stats || {};
      const scheduled = stats.scheduled || 0;
      const emailsSent = stats.emails_sent || 0;
      const isCompleted = !c.paused && scheduled === 0 && emailsSent > 0;

      if (c.paused) paused++;
      else if (isCompleted) completed++;
      else active++;
    });

    return { all, active, paused, completed, archived };
  }, [campaigns]);

  // Selection handlers
  const allVisibleSelected = useMemo(() => {
    if (!filteredCampaigns.length) return false;
    return filteredCampaigns.every((c) => selectedIds.has(c.id));
  }, [filteredCampaigns, selectedIds]);

  const toggleSelectOne = (id) => {
    setSelectAllFiltered(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    setSelectAllFiltered(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        filteredCampaigns.forEach((c) => next.delete(c.id));
      } else {
        filteredCampaigns.forEach((c) => next.add(c.id));
      }
      return next;
    });
  };

  const handleSelectAllMatching = () => {
    const allMatching = new Set(filteredCampaigns.map((c) => c.id));
    setSelectedIds(allMatching);
    setSelectAllFiltered(true);
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    setSelectAllFiltered(false);
  };

  // Selected campaigns objects
  const selectedCampaignsList = useMemo(() => {
    return campaigns.filter((c) => selectedIds.has(c.id));
  }, [campaigns, selectedIds]);

  const activeSelectedCount = useMemo(() => {
    return selectedCampaignsList.filter((c) => !c.paused).length;
  }, [selectedCampaignsList]);

  // Bulk Actions
  const handleOpenBulkDelete = () => {
    if (!selectedIds.size) return;
    setDeleteModalOpen(true);
  };

  const executeBulkDelete = async () => {
    setDeleteLoading(true);
    try {
      const ids = Array.from(selectedIds);
      const res = await api.post('/campaigns/bulk-delete', { campaign_ids: ids });

      if (res.deleted_count > 0 && res.failed_count === 0) {
        notify({ type: 'success', message: res.message });
      } else if (res.deleted_count > 0 && res.failed_count > 0) {
        notify({ type: 'warning', message: res.message });
      } else {
        notify({ type: 'error', message: res.message });
      }

      setDeleteModalOpen(false);
      clearSelection();
      load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to delete campaigns' });
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleBulkArchive = async (archive = true) => {
    if (!selectedIds.size) return;
    setBulkLoading(true);
    try {
      const ids = Array.from(selectedIds);
      const res = await api.post('/campaigns/bulk-archive', { campaign_ids: ids, archive });
      notify({ type: 'success', message: res.message });
      clearSelection();
      load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to update campaigns' });
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkPause = async (pause = true) => {
    if (!selectedIds.size) return;
    setBulkLoading(true);
    try {
      const ids = Array.from(selectedIds);
      await Promise.all(ids.map((id) => api.patch(`/campaigns/${id}`, { paused: pause })));
      notify({
        type: 'success',
        message: `Successfully ${pause ? 'paused' : 'resumed'} ${ids.length} campaign(s).`,
      });
      load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to update campaign status' });
    } finally {
      setBulkLoading(false);
    }
  };

  // Single campaign actions
  const togglePause = async (id, paused, name) => {
    const ok = await confirm(`${paused ? 'Resume' : 'Pause'} campaign "${name}"?`);
    if (!ok) return;
    await api.patch(`/campaigns/${id}`, { paused: !paused });
    load();
  };

  const deleteSingleCampaign = async (id, name, paused) => {
    if (!paused) {
      notify({
        type: 'error',
        message: `Cannot delete active campaign "${name}". Please pause it first.`,
      });
      return;
    }
    const ok = await confirm(
      `Delete campaign "${name}"?\n\nScheduled emails for this campaign will be canceled. Central prospects in your Prospects database will remain completely safe.`
    );
    if (!ok) return;
    try {
      await api.del(`/campaigns/${id}`);
      notify({ type: 'success', message: `Campaign "${name}" deleted.` });
      load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to delete campaign' });
    }
  };

  const toggleSingleArchive = async (id, name, isArchived) => {
    try {
      const res = await api.post(`/campaigns/${id}/archive`);
      notify({
        type: 'success',
        message: `Campaign "${name}" ${res.archived ? 'archived' : 'unarchived'}.`,
      });
      load();
    } catch (err) {
      notify({ type: 'error', message: err.message || 'Failed to archive campaign' });
    }
  };

  const duplicateCampaign = async (id, name) => {
    const ok = await confirm(`Duplicate campaign "${name}"?`);
    if (!ok) return;
    const c = await api.post(`/campaigns/${id}/duplicate`);
    notify({ type: 'success', message: 'Campaign duplicated: ' + c.name });
    load();
  };

  if (error) {
    return <div className="p-8 text-red-600">{error}</div>;
  }

  const banner =
    isPriority && canReorder ? (
      <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span className="font-semibold text-slate-700 dark:text-slate-300">Priority Scheduling</span>
        <span>·</span>
        <span>Drag rows to reorder priority</span>
        <span>·</span>
        <Link to="/settings#general" className="underline text-teal-600 dark:text-teal-400">
          Change strategy
        </Link>
      </div>
    ) : null;

  return (
    <ErrorBoundary title="Campaigns Error" description="An error occurred while loading campaigns.">
      <div className="min-h-0 flex-1 overflow-y-auto p-6 md:p-8 space-y-6">
        {/* Header Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Campaigns</h1>
            <p className="text-xs text-slate-500 mt-1">
              Create, organize, monitor, and manage your automated outreach sequences.
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <Button as={Link} to="/analytics" variant="outline" size="sm" className="text-xs">
              Analytics
            </Button>
            <Button
              as={Link}
              to="/campaigns/add"
              variant="default"
              size="sm"
              className="bg-teal-600 hover:bg-teal-700 text-white font-medium text-xs shadow-sm"
            >
              + Create Campaign
            </Button>
          </div>
        </div>

        {/* Search & Filter Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          {/* Status Filter Tabs */}
          <div className="flex flex-wrap items-center gap-1.5 p-1 bg-slate-100 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700/60 text-xs font-semibold">
            <button
              type="button"
              onClick={() => setStatusFilter('all')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === 'all'
                  ? 'bg-white dark:bg-slate-900 text-slate-900 dark:text-white shadow-2xs font-bold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              All ({filterCounts.all})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('active')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === 'active'
                  ? 'bg-white dark:bg-slate-900 text-emerald-600 dark:text-emerald-400 shadow-2xs font-bold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              Active ({filterCounts.active})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('paused')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === 'paused'
                  ? 'bg-white dark:bg-slate-900 text-amber-600 dark:text-amber-400 shadow-2xs font-bold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              Paused ({filterCounts.paused})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('completed')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === 'completed'
                  ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-2xs font-bold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              Completed ({filterCounts.completed})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('archived')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === 'archived'
                  ? 'bg-white dark:bg-slate-900 text-purple-600 dark:text-purple-400 shadow-2xs font-bold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              Archived ({filterCounts.archived})
            </button>
          </div>

          {/* Search Box */}
          <div className="relative w-full sm:w-64">
            <RiSearchLine className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search campaigns…"
              className="pl-9 pr-8 text-xs h-9 bg-white dark:bg-slate-900"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <RiCloseLine size={16} />
              </button>
            )}
          </div>
        </div>

        {/* Floating / Sticky Bulk Action Toolbar */}
        {selectedIds.size > 0 && (
          <div className="p-3 bg-teal-50/90 dark:bg-teal-950/50 border border-teal-200 dark:border-teal-800 rounded-xl shadow-md flex flex-wrap items-center justify-between gap-3 animate-fade-in text-xs">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-teal-600 text-white font-bold flex items-center justify-center text-[11px]">
                {selectedIds.size}
              </span>
              <span className="font-semibold text-teal-900 dark:text-teal-100">
                {selectedIds.size} campaign{selectedIds.size !== 1 ? 's' : ''} selected
              </span>
              {activeSelectedCount > 0 && (
                <span className="text-[10px] bg-amber-100 dark:bg-amber-950/70 text-amber-800 dark:text-amber-200 px-2 py-0.5 rounded-full font-medium">
                  {activeSelectedCount} active
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleBulkPause(true)}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 text-xs bg-white dark:bg-slate-900"
              >
                <RiPauseCircleLine size={15} className="text-amber-600" /> Pause
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleBulkPause(false)}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 text-xs bg-white dark:bg-slate-900"
              >
                <RiPlayCircleLine size={15} className="text-emerald-600" /> Resume
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleBulkArchive(statusFilter !== 'archived')}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 text-xs bg-white dark:bg-slate-900"
              >
                {statusFilter === 'archived' ? (
                  <>
                    <RiInboxUnarchiveLine size={15} className="text-purple-600" /> Unarchive
                  </>
                ) : (
                  <>
                    <RiArchiveLine size={15} className="text-purple-600" /> Archive
                  </>
                )}
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={handleOpenBulkDelete}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 text-xs shadow-2xs"
              >
                <RiDeleteBinLine size={15} /> Delete Selected
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={clearSelection}
                className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              >
                Clear
              </Button>
            </div>
          </div>
        )}

        {/* Select All Matching Filter Banner */}
        {selectedIds.size > 0 &&
          allVisibleSelected &&
          filteredCampaigns.length < campaigns.length &&
          !selectAllFiltered && (
            <div className="p-2.5 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-center text-slate-600 dark:text-slate-300">
              All {filteredCampaigns.length} visible campaigns on this page are selected.{' '}
              <button
                type="button"
                onClick={handleSelectAllMatching}
                className="text-teal-600 dark:text-teal-400 font-bold underline ml-1 hover:text-teal-700"
              >
                Select all {campaigns.length} campaigns across entire system
              </button>
            </div>
          )}

        {banner}

        {campaigns.length === 0 && (
          <Card className="p-8 text-center">
            <p className="text-slate-600 dark:text-slate-400 text-sm">
              No campaigns created yet.{' '}
              <Link className="text-teal-600 dark:text-teal-400 font-semibold underline" to="/campaigns/add">
                Create your first campaign
              </Link>
              .
            </p>
          </Card>
        )}

        {campaigns.length > 0 && filteredCampaigns.length === 0 && (
          <Card className="p-8 text-center space-y-2">
            <p className="text-slate-700 dark:text-slate-300 font-semibold text-sm">
              No campaigns match your search or filter.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch('');
                setStatusFilter('all');
              }}
              className="text-xs"
            >
              Reset Filters
            </Button>
          </Card>
        )}

        {filteredCampaigns.length > 0 && (
          <>
            <Card className="overflow-x-auto p-0 border border-slate-200 dark:border-slate-800 shadow-sm rounded-xl">
              <table className="w-full table-auto border-collapse text-left text-xs">
                <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-3 w-10 text-center">
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        onChange={toggleSelectAllVisible}
                        className="rounded text-teal-600 focus:ring-teal-500 cursor-pointer"
                        title="Select All Campaigns"
                      />
                    </th>
                    {canReorder && (
                      <>
                        <th className="w-8"></th>
                        <th className="w-10 text-slate-400 text-xs">#</th>
                      </>
                    )}
                    <th className="py-3 px-4">Campaign Name</th>
                    <th className="py-3 px-3">Status</th>
                    <th className="py-3 px-3 text-center">Progress</th>
                    <th className="py-3 px-3 text-center">Replies</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {filteredCampaigns.map((c, idx) => {
                    const stats = c.stats || {};
                    const totalLeads = stats.total_leads || 0;
                    const emailsSent = stats.emails_sent || 0;
                    const scheduled = stats.scheduled || 0;
                    const denom = emailsSent + scheduled;
                    const percent = denom > 0 ? Math.round((emailsSent / denom) * 100) : 0;
                    const replies = stats.replies || 0;
                    const replyRate = emailsSent > 0 ? Math.round((replies / emailsSent) * 100) : 0;

                    const isCompleted = !c.paused && scheduled === 0 && emailsSent > 0;
                    const isPaused = Boolean(c.paused);
                    const isArchived = Boolean(c.archived);

                    const pausedPercent =
                      isPaused && totalLeads > 0 ? Math.round((emailsSent / totalLeads) * 100) : 0;

                    const reasonParts = [];
                    if (replies > 0) reasonParts.push(`${replies} replied`);
                    const bounced = stats.bounced || 0;
                    if (bounced > 0) reasonParts.push(`${bounced} bounced`);
                    const unsubscribed = stats.unsubscribed || 0;
                    if (unsubscribed > 0) reasonParts.push(`${unsubscribed} unsub`);
                    const needsCustom = stats.needs_custom_email || 0;
                    if (needsCustom > 0) reasonParts.push(`${needsCustom} needs custom`);

                    let statusLabel, statusClass;
                    if (isArchived) {
                      statusLabel = 'Archived';
                      statusClass = 'text-purple-600 bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800';
                    } else if (isPaused) {
                      statusLabel = 'Paused';
                      statusClass = 'text-amber-700 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800';
                    } else if (isCompleted) {
                      statusLabel = 'Completed';
                      statusClass = 'text-blue-700 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800';
                    } else if (needsCustom > 0 && totalLeads === needsCustom) {
                      statusLabel = 'Needs Writing';
                      statusClass = 'text-indigo-700 bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-800';
                    } else if (totalLeads === 0) {
                      statusLabel = 'Draft';
                      statusClass = 'text-slate-600 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700';
                    } else {
                      statusLabel = 'Active';
                      statusClass = 'text-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800';
                    }

                    const barColor = isPaused ? 'bg-amber-400' : isCompleted ? 'bg-blue-500' : 'bg-teal-500';
                    const isSelected = selectedIds.has(c.id);

                    return (
                      <tr
                        key={c.id}
                        draggable={canReorder}
                        onDragStart={(e) => canReorder && onDragStart(e, idx)}
                        onDragOver={(e) => canReorder && onDragOver(e)}
                        onDragLeave={(e) => canReorder && onDragLeave(e)}
                        onDrop={(e) => canReorder && onDrop(e, idx)}
                        onDragEnd={(e) => canReorder && onDragEnd(e)}
                        className={`transition-colors ${
                          isSelected
                            ? 'bg-teal-50/50 dark:bg-teal-950/20'
                            : 'hover:bg-slate-50/80 dark:hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="py-3 px-3 text-center">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectOne(c.id)}
                            className="rounded text-teal-600 focus:ring-teal-500 cursor-pointer"
                          />
                        </td>
                        {canReorder && (
                          <>
                            <td className="py-3 px-1 text-center">
                              <span className="cursor-grab text-slate-400 hover:text-slate-600" title="Drag to reorder priority">
                                &#8942;&#8942;
                              </span>
                            </td>
                            <td className="py-3 px-1 text-slate-400 text-xs text-center">{idx + 1}</td>
                          </>
                        )}
                        <td className="py-3 px-4 font-medium">
                          <Link
                            to={`/campaigns/${c.id}`}
                            className="text-slate-900 dark:text-white font-semibold hover:text-teal-600 dark:hover:text-teal-400 text-sm"
                          >
                            {c.name}
                          </Link>
                          {isArchived && (
                            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 font-semibold">
                              ARCHIVED
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3">
                          <span className={`inline-block px-2 py-0.5 text-[11px] font-bold rounded-full ${statusClass}`}>
                            {statusLabel}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-center">
                          <div className="w-28 inline-block bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`${barColor} h-1.5`}
                              style={{ width: `${isPaused ? pausedPercent : percent}%` }}
                            />
                          </div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                            {isPaused ? (
                              <span>
                                {emailsSent} of {totalLeads} lead{totalLeads !== 1 ? 's' : ''}
                              </span>
                            ) : isCompleted ? (
                              <span className="text-blue-600 dark:text-blue-400 font-medium">
                                {emailsSent} sent — done
                              </span>
                            ) : (
                              <span>
                                {emailsSent} / {denom} ({percent}%)
                              </span>
                            )}
                          </div>
                          {reasonParts.length > 0 && (
                            <div className="text-[10px] text-slate-400 mt-0.5">{reasonParts.join(' · ')}</div>
                          )}
                        </td>
                        <td className="py-3 px-3 text-center font-semibold text-slate-700 dark:text-slate-300">
                          {replies} <span className="text-slate-400 text-[11px]">({replyRate}%)</span>
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <Button as={Link} to={`/campaigns/${c.id}`} variant="outline" size="sm" className="text-xs">
                              View
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => togglePause(c.id, c.paused, c.name)}
                              className="text-xs"
                            >
                              {c.paused ? 'Resume' : 'Pause'}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => toggleSingleArchive(c.id, c.name, isArchived)}
                              className="text-xs text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800"
                              title={isArchived ? 'Restore from Archive' : 'Archive Campaign'}
                            >
                              {isArchived ? 'Unarchive' : 'Archive'}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => duplicateCampaign(c.id, c.name)}
                              className="text-xs"
                            >
                              Duplicate
                            </Button>
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => deleteSingleCampaign(c.id, c.name, c.paused)}
                              className="text-xs px-2"
                              title={c.paused ? 'Delete Campaign' : 'Pause before deleting'}
                            >
                              Delete
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>

            {canReorder && orderChanged && (
              <div className="mt-4 flex items-center gap-4">
                <Button variant="default" size="sm" onClick={saveOrder} className="bg-teal-600 hover:bg-teal-700 text-white">
                  Save Priority Order
                </Button>
                <span className="text-emerald-600 text-xs font-semibold">Unsaved reordering changes</span>
              </div>
            )}
          </>
        )}

        {/* Confirmation Modal for Bulk Deletion */}
        {deleteModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 w-full max-w-lg flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-rose-50/50 dark:bg-rose-950/20">
                <h2 className="text-base font-bold text-rose-700 dark:text-rose-300 flex items-center gap-2">
                  <RiDeleteBinLine size={20} /> Confirm Bulk Campaign Deletion
                </h2>
                <button
                  type="button"
                  onClick={() => setDeleteModalOpen(false)}
                  className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <RiCloseLine size={20} />
                </button>
              </div>

              <div className="p-6 space-y-4 text-xs">
                <p className="text-slate-700 dark:text-slate-300 text-sm">
                  Are you sure you want to delete{' '}
                  <strong className="text-slate-900 dark:text-white">{selectedIds.size}</strong> selected campaign
                  {selectedIds.size !== 1 ? 's' : ''}?
                </p>

                {/* Active Campaign Warning (Requirement 8) */}
                {activeSelectedCount > 0 && (
                  <div className="p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl text-amber-900 dark:text-amber-200 flex items-start gap-2.5">
                    <RiAlertLine size={18} className="shrink-0 text-amber-600 mt-0.5" />
                    <div>
                      <strong className="block font-semibold">
                        {activeSelectedCount} Active Campaign{activeSelectedCount !== 1 ? 's' : ''} Detected
                      </strong>
                      <span>
                        Active campaigns cannot be deleted to prevent accidental disruption. They will be skipped unless
                        paused first.
                      </span>
                    </div>
                  </div>
                )}

                {/* Safe queue cancellation note */}
                <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1 text-slate-600 dark:text-slate-400">
                  <div className="font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                    <RiCheckDoubleLine className="text-teal-600" size={15} /> Safe Deletion Guarantees:
                  </div>
                  <ul className="list-disc pl-5 space-y-0.5 text-[11px]">
                    <li>Scheduled queue slots and pending emails will be cleanly canceled.</li>
                    <li>
                      <strong>Central Prospects remain completely safe</strong> in your central Prospects database.
                    </li>
                    <li>Unrelated direct communication history will not be touched.</li>
                  </ul>
                </div>

                {/* Scrollable list of campaigns to be deleted */}
                <div>
                  <span className="font-semibold text-slate-700 dark:text-slate-300 block mb-1.5">
                    Selected Campaigns ({selectedCampaignsList.length}):
                  </span>
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800 bg-slate-50/30 dark:bg-slate-950/30 p-1">
                    {selectedCampaignsList.map((c) => (
                      <div key={c.id} className="py-1.5 px-2.5 flex items-center justify-between">
                        <span className="font-medium text-slate-800 dark:text-slate-200 truncate max-w-xs">
                          {c.name}
                        </span>
                        <span
                          className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            c.paused
                              ? 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                              : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                          }`}
                        >
                          {c.paused ? 'Paused' : 'Active (Will be skipped)'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-200 dark:border-slate-800">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteModalOpen(false)}
                    disabled={deleteLoading}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    onClick={executeBulkDelete}
                    disabled={deleteLoading || selectedIds.size === activeSelectedCount}
                    className="flex items-center gap-1.5"
                  >
                    {deleteLoading ? (
                      'Deleting…'
                    ) : (
                      <>
                        <RiDeleteBinLine size={15} /> Confirm & Delete Selected
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}

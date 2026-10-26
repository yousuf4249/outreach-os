import React, { useState, useRef, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import logo from '../../assets/weblinx_logo.svg';
import {
  RiSendPlaneLine,
  RiLineChartLine,
  RiMailLine,
  RiInboxLine,
  RiCalendarScheduleLine,
  RiSettingsLine,
  RiSidebarFoldLine,
  RiInformationLine,
  RiHeartPulseLine,
  RiContactsLine,
  RiCompassDiscoverLine,
  RiNotification3Line,
  RiFileList3Line,
  RiExternalLinkLine,
} from 'react-icons/ri';
import { useUniboxNotifications } from '../../context/UniboxNotificationsContext';
import { useNotifications } from '../../context/NotificationsContext';
import { useOnboarding } from '../../context/OnboardingContext';
import { useSystemHealth } from '../../context/SystemHealthContext';

// links including icons
const links = [
  { to: '/analytics', label: 'Dashboard', icon: <RiLineChartLine size={20} /> },
  { to: '/campaigns', label: 'Campaigns', icon: <RiSendPlaneLine size={20} /> },
  { to: '/leads', label: 'Prospects', icon: <RiContactsLine size={20} /> },
  { to: '/prospect-research', label: 'Prospect Research', icon: <RiCompassDiscoverLine size={20} /> },
  { to: '/templates', label: 'Templates', icon: <RiFileList3Line size={20} /> },
  { to: '/inboxes', label: 'Inboxes', icon: <RiMailLine size={20} /> },
  { to: '/unibox', label: 'Unibox', icon: <RiInboxLine size={20} /> },
  { to: '/schedule', label: 'Schedule', icon: <RiCalendarScheduleLine size={20} /> },
  { to: '/notifications', label: 'Alerts', icon: <RiNotification3Line size={20} /> },
  { to: '/settings#general', label: 'Settings', icon: <RiSettingsLine size={20} /> },
];

const APP_VERSION = '1.0.0';

export default function Sidebar({ collapsed, onToggle }) {
  const location = useLocation();
  const { count: unreadCount } = useUniboxNotifications();
  const { count: notifUnreadCount } = useNotifications();
  const { startOnboarding } = useOnboarding();
  const { overallStatus } = useSystemHealth();
  const [helpOpen, setHelpOpen] = useState(false);
  const helpRef = useRef(null);

  const healthDotColor = {
    error:   'bg-red-500',
    warning: 'bg-yellow-400',
    ok:      'bg-green-500',
    unknown: 'bg-gray-400',
  }[overallStatus] || 'bg-gray-400';

  useEffect(() => {
    function handleClickOutside(e) {
      if (helpRef.current && !helpRef.current.contains(e.target)) {
        setHelpOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  const widthClass = collapsed ? 'w-16' : 'w-48';
  const justifyLogo = collapsed ? 'justify-center' : '';

  return (
    <nav
      className={`fixed top-0 left-0 z-40 h-full bg-slate-900 text-slate-300 flex flex-col p-3 border-r border-slate-800 transition-width duration-200 ${
        widthClass
      }`}
    >
      <NavLink
        to="/"
        className={`mb-6 flex items-center gap-2.5 no-underline hover:no-underline ${
          justifyLogo
        }`}
        title="Weblinx Outreach OS"
      >
        <img src={logo} alt="Weblinx Logo" className="h-8 w-8 shrink-0 rounded-lg shadow-sm" />
        {!collapsed && (
          <div className="flex flex-col overflow-hidden">
            <span className="text-white font-extrabold text-base tracking-tight leading-tight truncate">
              Weblinx OS
            </span>
            <span className="text-[10px] text-blue-400 font-semibold tracking-wider uppercase">
              Outreach
            </span>
          </div>
        )}
      </NavLink>

      <div className="flex flex-col gap-1.5 flex-1 overflow-y-auto pr-0.5 custom-scrollbar">
        {links.map(l => (
          <div key={l.to} className="relative group">
            <NavLink
              to={l.to}
              end={l.to === '/templates' || l.to === '/campaigns' || l.to === '/inboxes' || l.to === '/unibox'}
              className={({ isActive }) => {
                const active =
                  isActive ||
                  (l.to === '/analytics' && (location.pathname === '/' || location.pathname === '/analytics')) ||
                  (l.to.startsWith('/settings') && location.pathname.startsWith('/settings')) ||
                  (l.to === '/leads' && location.pathname.startsWith('/leads')) ||
                  (l.to === '/templates' && location.pathname.startsWith('/templates')) ||
                  (l.to === '/campaigns' && location.pathname.startsWith('/campaigns'));
                return `flex items-center py-2 rounded-lg px-2.5 text-xs font-medium transition-all duration-150 whitespace-nowrap !no-underline !hover:no-underline ${
                  active
                    ? 'text-white font-semibold bg-blue-600 shadow-sm'
                    : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
                }`;
              }}
            >
              <span className="flex-shrink-0 relative inline-flex">
                {l.icon}
                {l.to === '/unibox' && unreadCount > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white leading-none shadow">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
                {l.to === '/notifications' && notifUnreadCount > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-blue-400 text-[9px] font-bold text-white leading-none shadow">
                    {notifUnreadCount > 99 ? '99+' : notifUnreadCount}
                  </span>
                )}
              </span>
              {!collapsed && <span className="ml-2.5">{l.label}</span>}
            </NavLink>
            {collapsed && (
              <span className="absolute left-full top-1/2 transform -translate-y-1/2 ml-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-xs rounded-md px-2.5 py-1 whitespace-nowrap z-50 pointer-events-none shadow-lg border border-slate-700">
                {l.label}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Footer items */}
      <div className="mt-auto pt-3 border-t border-slate-800 flex flex-col gap-1.5">

        {/* System Health */}
        <div className="relative group">
          <NavLink
            to="/system-health"
            className={({ isActive }) =>
              `flex items-center py-1.5 rounded-lg px-2.5 text-xs font-medium transition-colors whitespace-nowrap !no-underline !hover:no-underline ${
                isActive ? 'text-white bg-slate-800' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
              }`
            }
          >
            <span className="flex-shrink-0 relative inline-flex">
              <RiHeartPulseLine size={18} />
              <span
                className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full border border-slate-900 ${healthDotColor}`}
              />
            </span>
            {!collapsed && <span className="ml-2.5">System Health</span>}
          </NavLink>
          {collapsed && (
            <span className="absolute left-full top-1/2 transform -translate-y-1/2 ml-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-xs rounded-md px-2.5 py-1 whitespace-nowrap z-50 pointer-events-none shadow-lg border border-slate-700">
              System Health
            </span>
          )}
        </div>

        {/* Help & Info */}
        <div className="relative group" ref={helpRef}>
          <button
            onClick={() => { setHelpOpen(prev => !prev); }}
            className={`w-full flex items-center py-1.5 rounded-lg px-2.5 text-xs font-medium transition-colors whitespace-nowrap ${
              helpOpen ? 'text-white bg-slate-800' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
            }`}
          >
            <span className="flex-shrink-0"><RiInformationLine size={18} /></span>
            {!collapsed && <span className="ml-2.5">About & Help</span>}
          </button>

          {collapsed && (
            <span className="absolute left-full top-1/2 transform -translate-y-1/2 ml-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-xs rounded-md px-2.5 py-1 whitespace-nowrap z-50 pointer-events-none shadow-lg border border-slate-700">
              About & Help
            </span>
          )}

          {helpOpen && (
            <div className="absolute bottom-0 left-full ml-2 w-64 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-[60] overflow-hidden p-2 text-xs">
              <div className="px-2 py-1.5 border-b border-slate-800 mb-1">
                <p className="font-semibold text-white">Weblinx Outreach OS</p>
                <p className="text-[10px] text-slate-400">v{APP_VERSION} • Weblinx Solution</p>
              </div>

              <a
                href="https://weblinxsolution.com"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between px-2 py-1.5 rounded text-slate-300 hover:text-white hover:bg-slate-800 !no-underline"
              >
                <span>Company Website</span>
                <RiExternalLinkLine size={14} />
              </a>

              <NavLink
                to="/deliverability-tips"
                onClick={() => setHelpOpen(false)}
                className="block px-2 py-1.5 rounded text-slate-300 hover:text-white hover:bg-slate-800 !no-underline"
              >
                Deliverability Best Practices
              </NavLink>

              <button
                onClick={() => { setHelpOpen(false); startOnboarding(); }}
                className="w-full text-left block px-2 py-1.5 rounded text-slate-300 hover:text-white hover:bg-slate-800"
              >
                Restart Onboarding Tour
              </button>

              <div className="border-t border-slate-800 my-1 pt-1 px-2 text-[10px] text-slate-500 leading-normal">
                Engine derived from Quickly. Released under the MIT License.
              </div>
            </div>
          )}
        </div>

        {/* Collapse toggle */}
        <div className="flex justify-end pt-1">
          <button
            onClick={onToggle}
            onMouseDown={e => e.preventDefault()}
            className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <RiSidebarFoldLine
              size={20}
              className={`transition-transform duration-300 ${
                collapsed ? 'rotate-180' : 'rotate-0'
              }`}
            />
          </button>
        </div>
      </div>
    </nav>
  );
}

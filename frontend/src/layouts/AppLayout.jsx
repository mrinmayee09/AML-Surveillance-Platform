/**
 * Application shell: fixed sidebar + sticky header.
 *
 * The sidebar is grouped by the platform's actual narrative - Surveillance,
 * Detection layers, Investigation, Configuration - rather than being a flat list,
 * so the three AML questions stay legible in the navigation itself.
 */
import clsx from 'clsx'
import {
  Activity,
  AlertTriangle,
  BellRing,
  Boxes,
  BrainCircuit,
  Building2,
  ChevronDown,
  FileSearch,
  Gauge,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  PlayCircle,
  ScrollText,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  Siren,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'

import { Chip, Spinner } from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { api } from '../services/api.js'
import { initials } from '../utils/format.js'

const NAV_GROUPS = [
  {
    label: 'Surveillance',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/transactions', label: 'Transactions', icon: Activity },
      { to: '/customers', label: 'Customers', icon: Users },
    ],
  },
  {
    label: 'Detection layers',
    items: [
      { to: '/gateway', label: 'Security Gateway', icon: ShieldCheck, hint: 'Pre-transaction integrity' },
      { to: '/proactive', label: 'Proactive Risk', icon: Gauge, hint: 'Before the transaction' },
      { to: '/reactive', label: 'Reactive AML', icon: Siren, hint: 'After settlement' },
      { to: '/network', label: 'GNN Network', icon: Network, hint: 'Graph intelligence' },
    ],
  },
  {
    label: 'Investigation',
    items: [
      { to: '/alerts', label: 'Alerts', icon: BellRing },
      { to: '/investigations', label: 'Investigations', icon: FileSearch },
      { to: '/demo', label: 'Run AML Demo', icon: PlayCircle },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { to: '/rules', label: 'Rules Engine', icon: Boxes },
      { to: '/models', label: 'Model Insights', icon: BrainCircuit },
      { to: '/audit-logs', label: 'Audit Logs', icon: ScrollText, permission: 'audit:read' },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
]

function Sidebar({ open, onClose }) {
  const { can } = useAuth()

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
        />
      )}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-ink-700/80 bg-ink-900',
          'transition-transform lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-ink-700/80 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-accent/15 ring-1 ring-accent/30">
            <Shield size={15} className="text-accent" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold tracking-tight text-white">
              Meridian AML
            </p>
            <p className="truncate text-2xs text-slateish-400">Financial Surveillance</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded p-1 text-slateish-400 hover:text-slateish-100 lg:hidden"
            aria-label="Close navigation"
          >
            <X size={15} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Main navigation">
          {NAV_GROUPS.map((group) => {
            const visible = group.items.filter(
              (item) => !item.permission || can(item.permission),
            )
            if (!visible.length) return null
            return (
              <div key={group.label} className="mb-4">
                <p className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400/70">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {visible.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.end}
                        onClick={onClose}
                        className={({ isActive }) =>
                          clsx(
                            'group flex items-start gap-2.5 rounded px-2.5 py-1.5 transition-colors',
                            isActive
                              ? 'bg-info-soft text-white ring-1 ring-info/25'
                              : 'text-slateish-300 hover:bg-ink-800 hover:text-slateish-100',
                          )
                        }
                      >
                        {({ isActive }) => (
                          <>
                            <item.icon
                              size={14}
                              className={clsx(
                                'mt-0.5 shrink-0',
                                isActive ? 'text-info' : 'text-slateish-400',
                              )}
                              aria-hidden="true"
                            />
                            <span className="min-w-0">
                              <span className="block truncate text-xs font-medium">
                                {item.label}
                              </span>
                              {item.hint && (
                                <span className="block truncate text-2xs text-slateish-400/80">
                                  {item.hint}
                                </span>
                              )}
                            </span>
                          </>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </nav>

        <div className="shrink-0 border-t border-ink-700/80 p-3">
          <p className="text-2xs leading-snug text-slateish-400/80">
            Risk scores are prioritisation signals for human review. They are not proof of
            criminal activity.
          </p>
        </div>
      </aside>
    </>
  )
}

function GlobalSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  function onSubmit(event) {
    event.preventDefault()
    const value = query.trim()
    if (!value) return
    // Route by reference prefix so one box reaches every entity type
    const upper = value.toUpperCase()
    if (upper.startsWith('CUST-')) navigate(`/customers/${upper}`)
    else if (upper.startsWith('TXN-')) navigate(`/transactions?search=${encodeURIComponent(value)}`)
    else if (upper.startsWith('ALERT-')) navigate(`/alerts/${upper}`)
    else if (upper.startsWith('CASE-')) navigate(`/investigations/${upper}`)
    else if (upper.startsWith('NET-')) navigate(`/network?network=${upper}`)
    else if (upper.startsWith('ACC-')) navigate(`/network?account=${upper}`)
    else navigate(`/transactions?search=${encodeURIComponent(value)}`)
    setQuery('')
  }

  return (
    <form onSubmit={onSubmit} className="relative hidden min-w-0 flex-1 max-w-md md:block">
      <Search
        size={13}
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slateish-400"
        aria-hidden="true"
      />
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search CUST-, TXN-, ALERT-, CASE-, NET-, ACC-…"
        aria-label="Global search"
        className="w-full rounded border border-ink-600 bg-ink-900 py-1.5 pl-7 pr-2.5 text-xs text-slateish-100 placeholder:text-slateish-400/70 focus:border-info/60 focus:outline-none focus:ring-1 focus:ring-info/40"
      />
    </form>
  )
}

function SystemStatus() {
  const [health, setHealth] = useState(null)
  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth({ status: 'degraded' }))
    return () => {
      cancelled = true
    }
  }, [])

  const ok = health?.status === 'ok'
  const engines = health?.engines
  const label = !health
    ? 'Checking…'
    : ok
      ? 'All engines operational'
      : 'Degraded'

  const detail = engines
    ? `Proactive model: ${engines.proactive_model?.trained ? 'trained' : 'UNTRAINED fallback'} · Graph engine: ${engines.graph_engine?.trained ? 'trained GNN' : 'UNTRAINED analytic'}`
    : undefined

  return (
    <span
      title={detail}
      className="hidden items-center gap-1.5 text-2xs text-slateish-400 xl:inline-flex"
    >
      <span
        className={clsx(
          'h-1.5 w-1.5 rounded-full',
          ok ? 'animate-pulse-soft bg-risk-low' : 'bg-risk-medium',
        )}
        aria-hidden="true"
      />
      {label}
    </span>
  )
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(id)
  }, [])
  return (
    <time
      dateTime={now.toISOString()}
      className="tnum hidden font-mono text-2xs text-slateish-400 lg:block"
    >
      {now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}{' '}
      {now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })} IST
    </time>
  )
}

function Notifications() {
  const [open, setOpen] = useState(false)
  const [stats, setStats] = useState(null)
  const ref = useRef(null)

  useEffect(() => {
    api.alertStats().then(setStats).catch(() => {})
  }, [])

  useEffect(() => {
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const open_count = stats?.open ?? 0

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative rounded p-1.5 text-slateish-400 transition-colors hover:bg-ink-800 hover:text-slateish-100"
        aria-label={`Notifications: ${open_count} open alerts`}
        aria-expanded={open}
      >
        <BellRing size={15} />
        {open_count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-risk-high px-1 text-[9px] font-bold text-white">
            {open_count > 99 ? '99+' : open_count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-50 w-72 rounded-card border border-ink-700 bg-ink-900 p-3 shadow-raised animate-slide-up">
          <p className="mb-2 text-xs font-semibold text-slateish-100">Alert queue</p>
          {stats ? (
            <ul className="space-y-1.5">
              {Object.entries(stats.by_status ?? {}).map(([status, count]) => (
                <li key={status} className="flex items-center justify-between text-2xs">
                  <span className="text-slateish-400">{status.replace(/_/g, ' ')}</span>
                  <span className="tnum font-mono text-slateish-100">{count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Spinner className="text-slateish-400" />
          )}
          <Link
            to="/alerts"
            onClick={() => setOpen(false)}
            className="mt-3 block rounded border border-ink-600 bg-ink-800 py-1.5 text-center text-2xs font-medium text-slateish-200 hover:bg-ink-750"
          >
            Open alert queue
          </Link>
        </div>
      )}
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  async function onLogout() {
    await logout()
    toast.info('Signed out.')
    navigate('/login')
  }

  if (!user) return null
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-ink-800"
        aria-expanded={open}
        aria-label="Account menu"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-info/20 text-2xs font-semibold text-info ring-1 ring-info/30">
          {initials(user.full_name)}
        </span>
        <span className="hidden min-w-0 sm:block">
          <span className="block truncate text-2xs font-medium text-slateish-100">
            {user.full_name}
          </span>
          <span className="block truncate text-2xs text-slateish-400">{user.role}</span>
        </span>
        <ChevronDown size={12} className="text-slateish-400" aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-50 w-56 rounded-card border border-ink-700 bg-ink-900 p-1 shadow-raised animate-slide-up">
          <div className="border-b border-ink-700 px-2.5 py-2">
            <p className="truncate text-xs font-medium text-slateish-100">{user.full_name}</p>
            <p className="truncate text-2xs text-slateish-400">{user.email}</p>
            <p className="mt-1 text-2xs text-slateish-400">
              {user.role} · {user.team}
            </p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="mt-1 flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-xs text-slateish-300 hover:bg-ink-800 hover:text-slateish-100"
          >
            <LogOut size={13} aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

export default function AppLayout({ children }) {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()

  // Close the mobile drawer whenever the route changes
  useEffect(() => setNavOpen(false), [location.pathname])

  return (
    <div className="min-h-screen bg-ink-950">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-ink-700/80 bg-ink-900/90 px-3 backdrop-blur sm:px-4">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="rounded p-1.5 text-slateish-400 hover:bg-ink-800 hover:text-slateish-100 lg:hidden"
            aria-label="Open navigation"
          >
            <Menu size={16} />
          </button>

          <GlobalSearch />

          <div className="ml-auto flex items-center gap-2.5 sm:gap-3.5">
            <Chip tone="medium" title="This deployment runs on synthetic data">
              <AlertTriangle size={9} aria-hidden="true" />
              Demo Environment
            </Chip>
            <SystemStatus />
            <Clock />
            <Notifications />
            <span className="h-6 w-px bg-ink-700" aria-hidden="true" />
            <UserMenu />
          </div>
        </header>

        <main className="px-3 py-4 sm:px-4 lg:px-6">{children}</main>

        <footer className="border-t border-ink-800 px-4 py-3 text-2xs text-slateish-400/70 lg:px-6">
          Meridian AML Surveillance · academic prototype on synthetic data · no payment provider
          is integrated and no real financial data is processed.
        </footer>
      </div>
    </div>
  )
}

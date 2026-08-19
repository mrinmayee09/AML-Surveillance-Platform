/**
 * Shared UI primitives for the investigator console.
 *
 * Design rules enforced here:
 *  - Colour never carries meaning alone: every risk/status colour ships with a
 *    text label, and severity badges include an icon.
 *  - Numbers use tabular figures so columns align while scanning.
 *  - Motion is short and orienting, never decorative.
 */
import clsx from 'clsx'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Eye,
  Info,
  Minus,
  Search,
  ShieldAlert,
  X,
} from 'lucide-react'
import { useEffect } from 'react'

import { RISK_META, riskMeta, statusMeta } from '../utils/format.js'

/* ------------------------------------------------------------------ layout */

export function Card({ children, className, padded = true, ...rest }) {
  return (
    <div
      className={clsx(
        'rounded-card border border-ink-700/70 bg-ink-850/80 shadow-card',
        padded && 'p-4',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({ title, subtitle, action, icon: Icon, className }) {
  return (
    <div className={clsx('mb-3 flex items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {Icon && <Icon size={14} className="shrink-0 text-slateish-400" aria-hidden="true" />}
          <h2 className="truncate text-sm font-semibold text-slateish-100">{title}</h2>
        </div>
        {subtitle && (
          <p className="mt-0.5 text-xs leading-snug text-slateish-400">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, children, icon: Icon }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="flex items-center gap-2">
          {Icon && <Icon size={17} className="text-accent" aria-hidden="true" />}
          <h1 className="text-lg font-semibold tracking-tight text-white">{title}</h1>
        </div>
        {subtitle && <p className="mt-1 max-w-3xl text-xs text-slateish-400">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Section({ title, children, className }) {
  return (
    <section className={className}>
      {title && (
        <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
          {title}
        </h3>
      )}
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------ badges */

/** Risk band badge - colour plus the band name, never colour alone. */
export function RiskBadge({ level, score, size = 'sm', showScore = false }) {
  const meta = riskMeta(level)
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded border font-semibold uppercase tracking-wide',
        size === 'xs' ? 'px-1.5 py-0.5 text-2xs' : 'px-2 py-0.5 text-2xs',
      )}
      style={{
        color: meta.color,
        backgroundColor: meta.bg,
        borderColor: `${meta.color}55`,
      }}
      title={meta.action}
    >
      <CircleDot size={9} aria-hidden="true" />
      {meta.label}
      {showScore && score !== undefined && score !== null && (
        <span className="tnum font-mono opacity-80">{Math.round(score)}</span>
      )}
    </span>
  )
}

export function StatusBadge({ status }) {
  const meta = statusMeta(status)
  return (
    <span
      className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-2xs font-medium"
      style={{ color: meta.color, backgroundColor: meta.bg, borderColor: `${meta.color}44` }}
    >
      {meta.label}
    </span>
  )
}

export function Chip({ children, tone = 'neutral', className, title }) {
  const tones = {
    neutral: 'border-ink-600 bg-ink-800 text-slateish-300',
    info: 'border-info/40 bg-info-soft text-info',
    accent: 'border-accent/40 bg-accent-soft text-accent',
    low: 'border-risk-low/40 bg-risk-lowBg text-risk-low',
    medium: 'border-risk-medium/40 bg-risk-mediumBg text-risk-medium',
    high: 'border-risk-high/40 bg-risk-highBg text-risk-high',
    critical: 'border-risk-critical/40 bg-risk-criticalBg text-risk-critical',
  }
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium',
        tones[tone] ?? tones.neutral,
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Small label proving where a number came from, and whether it is a real model. */
export function ProvenanceNote({ provenance, className }) {
  if (!provenance) return null
  const trained = provenance.trained
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded border px-2.5 py-2 text-2xs leading-snug',
        trained
          ? 'border-info/30 bg-info-soft/60 text-slateish-300'
          : 'border-risk-medium/40 bg-risk-mediumBg text-slateish-300',
        className,
      )}
    >
      {trained ? (
        <Info size={12} className="mt-0.5 shrink-0 text-info" aria-hidden="true" />
      ) : (
        <AlertTriangle
          size={12}
          className="mt-0.5 shrink-0 text-risk-medium"
          aria-hidden="true"
        />
      )}
      <span>
        <strong className="font-semibold text-slateish-200">
          {provenance.model_name} v{provenance.model_version}
        </strong>{' '}
        - {provenance.model_type}.{' '}
        {trained ? (
          <span className="text-risk-low">Trained artifact.</span>
        ) : (
          <span className="text-risk-medium">
            Not a trained model - untrained fallback in use.
          </span>
        )}{' '}
        {provenance.training_data}
      </span>
    </div>
  )
}

/** The standing AML advisory. Rendered wherever a score or finding is shown. */
export function Advisory({ children, tone = 'info', className, icon = true }) {
  const tones = {
    info: 'border-ink-600 bg-ink-800/70 text-slateish-400',
    warning: 'border-risk-medium/35 bg-risk-mediumBg text-slateish-300',
  }
  return (
    <p
      className={clsx(
        'flex items-start gap-2 rounded border px-3 py-2 text-2xs leading-relaxed',
        tones[tone],
        className,
      )}
    >
      {icon && (
        <ShieldAlert size={12} className="mt-0.5 shrink-0 text-slateish-400" aria-hidden="true" />
      )}
      <span>{children}</span>
    </p>
  )
}

/* ------------------------------------------------------------------ inputs */

export function Button({
  children,
  variant = 'secondary',
  size = 'sm',
  icon: Icon,
  loading = false,
  className,
  ...rest
}) {
  const variants = {
    primary: 'bg-info text-white hover:bg-info/85 border-info',
    secondary: 'bg-ink-800 text-slateish-200 hover:bg-ink-750 border-ink-600',
    ghost: 'bg-transparent text-slateish-300 hover:bg-ink-800 border-transparent',
    danger: 'bg-risk-high/15 text-risk-high hover:bg-risk-high/25 border-risk-high/40',
    success: 'bg-risk-low/15 text-risk-low hover:bg-risk-low/25 border-risk-low/40',
  }
  return (
    <button
      type="button"
      disabled={loading || rest.disabled}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded border font-medium transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-info/60',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'xs' ? 'px-2 py-1 text-2xs' : 'px-2.5 py-1.5 text-xs',
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
      ) : (
        Icon && <Icon size={13} aria-hidden="true" />
      )}
      {children}
    </button>
  )
}

export function TextInput({ icon: Icon, className, ...rest }) {
  return (
    <div className={clsx('relative', className)}>
      {Icon && (
        <Icon
          size={13}
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slateish-400"
          aria-hidden="true"
        />
      )}
      <input
        className={clsx(
          'w-full rounded border border-ink-600 bg-ink-900 py-1.5 text-xs text-slateish-100',
          'placeholder:text-slateish-400/70 focus:border-info/60 focus:outline-none focus:ring-1 focus:ring-info/40',
          Icon ? 'pl-7 pr-2.5' : 'px-2.5',
        )}
        {...rest}
      />
    </div>
  )
}

export function SearchInput(props) {
  return <TextInput icon={Search} type="search" {...props} />
}

export function Select({ options, className, ...rest }) {
  return (
    <select
      className={clsx(
        'rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-100',
        'focus:border-info/60 focus:outline-none focus:ring-1 focus:ring-info/40',
        className,
      )}
      {...rest}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

export function Textarea({ className, ...rest }) {
  return (
    <textarea
      className={clsx(
        'w-full rounded border border-ink-600 bg-ink-900 px-2.5 py-2 text-xs text-slateish-100',
        'placeholder:text-slateish-400/70 focus:border-info/60 focus:outline-none focus:ring-1 focus:ring-info/40',
        className,
      )}
      {...rest}
    />
  )
}

export function Toggle({ checked, onChange, label, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        'relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-info/60',
        checked ? 'bg-risk-low/70' : 'bg-ink-600',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span
        className={clsx(
          'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
          checked ? 'translate-x-3.5' : 'translate-x-0.5',
        )}
      />
    </button>
  )
}

export function SegmentedControl({ value, onChange, options, className }) {
  return (
    <div
      className={clsx('inline-flex rounded border border-ink-600 bg-ink-900 p-0.5', className)}
      role="group"
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-pressed={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={clsx(
            'rounded px-2 py-1 text-2xs font-medium transition-colors',
            value === opt.value
              ? 'bg-ink-700 text-slateish-100'
              : 'text-slateish-400 hover:text-slateish-200',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------- table */

export function Table({ children, className }) {
  return (
    <div className={clsx('overflow-x-auto', className)}>
      <table className="w-full min-w-full border-collapse text-xs">{children}</table>
    </div>
  )
}

export function Th({ children, align = 'left', sortable, active, direction, onClick, className }) {
  return (
    <th
      scope="col"
      className={clsx(
        'sticky top-0 z-10 whitespace-nowrap border-b border-ink-700 bg-ink-850/95 px-3 py-2',
        'text-2xs font-semibold uppercase tracking-wider text-slateish-400 backdrop-blur',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        sortable && 'cursor-pointer select-none hover:text-slateish-200',
        className,
      )}
      onClick={sortable ? onClick : undefined}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : undefined}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sortable && active && (
          <span aria-hidden="true" className="text-info">
            {direction === 'asc' ? '↑' : '↓'}
          </span>
        )}
      </span>
    </th>
  )
}

export function Td({ children, align = 'left', mono, className, ...rest }) {
  return (
    <td
      className={clsx(
        'whitespace-nowrap border-b border-ink-800/70 px-3 py-2 text-slateish-200',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        mono && 'tnum font-mono',
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  )
}

export function Tr({ children, onClick, selected, className }) {
  return (
    <tr
      onClick={onClick}
      className={clsx(
        'transition-colors',
        onClick && 'cursor-pointer hover:bg-ink-800/60',
        selected && 'bg-info-soft',
        className,
      )}
    >
      {children}
    </tr>
  )
}

export function Pagination({ page, pages, total, pageSize, onChange }) {
  if (!total) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-800 px-3 py-2 text-2xs text-slateish-400">
      <span className="tnum">
        Showing {from.toLocaleString()}-{to.toLocaleString()} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <Button
          size="xs"
          variant="ghost"
          icon={ChevronLeft}
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          Prev
        </Button>
        <span className="tnum px-1.5">
          {page} / {pages}
        </span>
        <Button
          size="xs"
          variant="ghost"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          Next <ChevronRight size={13} aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ states */

export function Skeleton({ className }) {
  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded bg-ink-800',
        className ?? 'h-4 w-full',
      )}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-ink-700/60 to-transparent" />
    </div>
  )
}

export function SkeletonTable({ rows = 8, cols = 6 }) {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton key={c} className={clsx('h-3.5', c === 0 ? 'w-32' : 'flex-1')} />
          ))}
        </div>
      ))}
    </div>
  )
}

export function EmptyState({ icon: Icon = Eye, title, message, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="rounded-full border border-ink-700 bg-ink-800 p-2.5">
        <Icon size={18} className="text-slateish-400" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium text-slateish-200">{title}</p>
      {message && <p className="max-w-md text-xs text-slateish-400">{message}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Could not load this view' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="rounded-full border border-risk-high/40 bg-risk-highBg p-2.5">
        <AlertTriangle size={18} className="text-risk-high" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium text-slateish-100">{title}</p>
      <p className="max-w-md break-words text-xs text-slateish-400">
        {error?.message ?? 'An unexpected error occurred.'}
      </p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} className="mt-1">
          Try again
        </Button>
      )}
    </div>
  )
}

export function Spinner({ size = 14, className }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={clsx(
        'inline-block animate-spin rounded-full border-2 border-current border-t-transparent',
        className,
      )}
      style={{ width: size, height: size }}
    />
  )
}

/* ------------------------------------------------------------------ drawer */

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 'max-w-2xl' }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close panel"
        onClick={onClose}
        className="absolute inset-0 bg-black/55 animate-fade-in"
      />
      <div
        className={clsx(
          'relative flex h-full w-full flex-col border-l border-ink-700 bg-ink-900 shadow-drawer',
          'animate-slide-in-right',
          width,
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-ink-700 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-white">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slateish-400">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-slateish-400 transition-colors hover:bg-ink-800 hover:text-slateish-100"
          >
            <X size={15} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && (
          <footer className="border-t border-ink-700 bg-ink-850 px-4 py-3">{footer}</footer>
        )}
      </div>
    </div>
  )
}

export function Modal({ open, onClose, title, children, footer, width = 'max-w-lg' }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 animate-fade-in"
      />
      <div
        className={clsx(
          'relative w-full rounded-card border border-ink-700 bg-ink-900 shadow-raised animate-slide-up',
          width,
        )}
      >
        <header className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-slateish-400 hover:bg-ink-800 hover:text-slateish-100"
          >
            <X size={15} />
          </button>
        </header>
        <div className="px-4 py-4">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-ink-700 bg-ink-850 px-4 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- data display */

export function DataList({ items, columns = 2, className }) {
  return (
    <dl
      className={clsx(
        'grid gap-x-6 gap-y-2.5',
        columns === 1 && 'grid-cols-1',
        columns === 2 && 'grid-cols-1 sm:grid-cols-2',
        columns === 3 && 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
        className,
      )}
    >
      {items
        .filter((item) => item && item.value !== undefined && item.value !== null)
        .map((item) => (
          <div key={item.label} className="min-w-0">
            <dt className="text-2xs uppercase tracking-wide text-slateish-400">{item.label}</dt>
            <dd
              className={clsx(
                'mt-0.5 break-words text-xs text-slateish-100',
                item.mono && 'tnum font-mono',
              )}
            >
              {item.value}
            </dd>
          </div>
        ))}
    </dl>
  )
}

/** Horizontal score meter. Always paired with the numeric score and band name. */
export function ScoreMeter({ score, level, label, className }) {
  const meta = riskMeta(level)
  const pct = Math.max(0, Math.min(100, score ?? 0))
  return (
    <div className={className}>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-2xs uppercase tracking-wide text-slateish-400">
          {label ?? 'Risk score'}
        </span>
        <span className="tnum font-mono text-xs font-semibold" style={{ color: meta.color }}>
          {Math.round(pct)}
          <span className="text-slateish-400">/100</span>
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label ?? 'Risk score'}: ${Math.round(pct)} of 100, band ${meta.label}`}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: meta.color }}
        />
      </div>
    </div>
  )
}

export function TrendIndicator({ trend, delta }) {
  const map = {
    INCREASING: { icon: ArrowUpRight, color: 'text-risk-high', label: 'Increasing' },
    DECREASING: { icon: ArrowDownRight, color: 'text-risk-low', label: 'Decreasing' },
    STABLE: { icon: Minus, color: 'text-slateish-400', label: 'Stable' },
  }
  const meta = map[trend] ?? map.STABLE
  const Icon = meta.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 text-2xs font-medium', meta.color)}>
      <Icon size={12} aria-hidden="true" />
      {meta.label}
      {delta !== undefined && delta !== null && delta !== 0 && (
        <span className="tnum font-mono opacity-80">
          {delta > 0 ? '+' : ''}
          {delta}
        </span>
      )}
    </span>
  )
}

/**
 * One explainable risk factor: points, label, and the reason behind it.
 * This is the component that makes a score defensible rather than opaque.
 */
export function FactorRow({ factor, maxContribution }) {
  const width = maxContribution ? (factor.contribution / maxContribution) * 100 : 0
  const categoryTone =
    {
      BEHAVIOURAL: '#3d8bfd',
      VELOCITY: '#d99524',
      NETWORK: '#4fd1c5',
      GEO: '#a78bfa',
      KYC: '#8b9ab5',
      INTEGRITY: '#e0533d',
      AMOUNT: '#3d8bfd',
    }[factor.category] ?? '#8b9ab5'

  return (
    <li className="py-2">
      <div className="flex items-baseline gap-2.5">
        <span className="tnum w-10 shrink-0 text-right font-mono text-xs font-semibold text-risk-high">
          +{factor.contribution}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-slateish-100">{factor.label}</span>
            <Chip tone="neutral" className="border-none bg-transparent px-0 text-slateish-400">
              <span
                className="mr-1 inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: categoryTone }}
                aria-hidden="true"
              />
              {factor.category?.toLowerCase()}
            </Chip>
          </div>
          <p className="mt-0.5 text-2xs leading-snug text-slateish-400">{factor.detail}</p>
          <div className="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-ink-800">
            <div
              className="h-full rounded-full bg-risk-high/60"
              style={{ width: `${width}%` }}
              aria-hidden="true"
            />
          </div>
        </div>
      </div>
    </li>
  )
}

export function FactorList({ factors, title = 'Risk factors', total }) {
  if (!factors?.length) {
    return (
      <EmptyState
        icon={Info}
        title="No aggravating factors recorded"
        message="No rule breached its threshold and the model found no material contributor."
      />
    )
  }
  const max = Math.max(...factors.map((f) => f.contribution))
  const sum = factors.reduce((acc, f) => acc + f.contribution, 0)
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-2xs font-semibold uppercase tracking-wider text-slateish-400">
          {title}
        </h3>
        <span className="tnum font-mono text-2xs text-slateish-400">
          contributions total {sum.toFixed(1)}
          {total !== undefined && ` of ${total}`}
        </span>
      </div>
      <ul className="divide-y divide-ink-800">
        {factors.map((factor) => (
          <FactorRow key={factor.code} factor={factor} maxContribution={max} />
        ))}
      </ul>
    </div>
  )
}

/** Pipeline step indicator used by the gateway and demo pages. */
export function PipelineStep({ step, last }) {
  const map = {
    PASS: { icon: CheckCircle2, color: '#22a06b', label: 'Pass' },
    WARN: { icon: AlertTriangle, color: '#d99524', label: 'Attention' },
    FAIL: { icon: Ban, color: '#e0533d', label: 'Fail' },
    SKIPPED: { icon: Minus, color: '#8b9ab5', label: 'Skipped' },
  }
  const meta = map[step.status] ?? map.SKIPPED
  const Icon = meta.icon
  return (
    <li className="relative flex gap-3 pb-3">
      {!last && (
        <span
          className="absolute left-[9px] top-5 h-full w-px bg-ink-700"
          aria-hidden="true"
        />
      )}
      <span
        className="relative z-10 mt-0.5 flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border"
        style={{ borderColor: `${meta.color}66`, backgroundColor: `${meta.color}1f` }}
      >
        <Icon size={11} style={{ color: meta.color }} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-xs font-medium text-slateish-100">{step.label}</span>
          <span className="text-2xs font-semibold uppercase" style={{ color: meta.color }}>
            {meta.label}
          </span>
          {step.value && (
            <span className="tnum font-mono text-2xs text-slateish-400">{step.value}</span>
          )}
          {step.duration_ms > 0 && (
            <span className="tnum ml-auto font-mono text-2xs text-slateish-400/70">
              {step.duration_ms}ms
            </span>
          )}
        </div>
        {step.detail && (
          <p className="mt-0.5 text-2xs leading-snug text-slateish-400">{step.detail}</p>
        )}
      </div>
    </li>
  )
}

export function KeyValue({ label, value, mono, tone }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-2xs text-slateish-400">{label}</span>
      <span
        className={clsx('text-xs font-medium', mono && 'tnum font-mono')}
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </span>
    </div>
  )
}
